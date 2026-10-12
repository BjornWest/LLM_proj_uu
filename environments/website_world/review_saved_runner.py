"""Review answer run with grading attached before dispatch.

English presentation remains editable; native task/reference/ID/memories do not.
This is prospective source only until the frozen setup and HTTP gates pass.
"""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path

from intent_browser.connected_world_task import checked_files, policy_goal, TERMINAL_INSTRUCTION
from .catalog_cart_execution import save_new
from .review_saved_execution import SavedReviewEpisode
from .catalog_review_execution import PublishedReviewSummaryGrader
from .catalog_compare_review_execution import (check_policy_outcome,
    check_saved_public_task, extract_saved_deferred, publish_finalized_answer)

VERSION = 'website-saved-review-automatic-runner-v1'


def run(output, run_directory, *, policy_session, metadata, runner_options,
        viewer_projection, quota_guard, extraction_backend_factory=None, runner=None):
    """One policy lease, at most one ordinary answer formatter, no retries.

    Grading and publication follow policy/Runtime cleanup. All native input and
    actual public request bytes are pinned before policy dispatch.
    """
    from intent_browser.automatic_grading import AutomaticGrading, canonical_viewer_check, finalize_external
    from intent_browser.evaluation import Evaluation
    if not all(callable(f) for f in (policy_session, viewer_projection, quota_guard)):
        raise ValueError('Require policy, quota and actual HTTP projection callables')
    if extraction_backend_factory is not None and not callable(extraction_backend_factory):
        raise ValueError('Extraction backend must be callable')
    if (type(runner_options) is not dict
            or type(runner_options.get('max_input_tokens')) is not int
            or runner_options['max_input_tokens'] <= 0
            or 'max_steps' not in runner_options
            or (runner_options['max_steps'] is not None and
                (type(runner_options['max_steps']) is not int or runner_options['max_steps'] <= 0))):
        raise ValueError('Declare max_steps as None or a positive integer and a positive input token limit')
    reserved = {'env_factory', 'backend', 'metadata', 'output', 'episode_task', 'harness_profile',
        'site_discovery', 'observation_pipeline', 'terminal_response_instruction',
        'automatic_grading', 'allow_ungraded', 'ungraded_reason', 'agent_runtime', 'agent_actor'}
    if set(runner_options) & reserved:
        raise ValueError('Runner options cannot replace task or automatic-grade bindings')
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    output, destination = Path(output).resolve(), Path(run_directory).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    state = {'policy_closed': False, 'runtime_closed': False, 'grade': None, 'deferred': None}
    trace, summary = None, None
    try:
        with SavedReviewEpisode(output) as episode:
            expected_public = deepcopy(episode.public)
            native = json.loads((output/'catalog-review-task.private.json').read_bytes())
            if (expected_public['task_id'] != native['task_id']
                    or expected_public['memories'] != native['memories']
                    or type(expected_public['user_message']) is not str
                    or not expected_public['user_message'].strip()):
                raise ValueError('Native review identity/memories or public request is malformed')
            runtime_directory = destination/'runtime-binding'
            exported = episode.export_private_runtime(runtime_directory)
            for name, expected in exported['files'].items():
                path = (runtime_directory/name).resolve()
                if not path.is_relative_to(runtime_directory):
                    raise ValueError('Review export escaped the runtime directory')
                episode.task.files[str(path)] = expected
            runtime_manifest = runtime_directory/'manifest.json'
            episode.task.files[str(runtime_manifest)] = sha256(runtime_manifest.read_bytes()).hexdigest()
            inputs = {'world': output/'pin/world.private.json',
                'task': output/'catalog-review-task.private.json',
                'reference': output/'catalog-review-reference.private.json',
                'site_registry': runtime_directory/'site-registry.private.json',
                'surrounding': output/'surrounding.private.json'}
            references = {str(path): sha256(path.read_bytes()).hexdigest() for path in inputs.values()}
            for name in ('intent_browser.automatic_grading', 'intent_browser.evaluation',
                         'agent_trace.adapters.browsergym', __name__):
                module = importlib.import_module(name)
                path = Path(module.__file__).resolve()
                expected = sha256(path.read_bytes()).hexdigest()
                if str(path) in episode.task.files and episode.task.files[str(path)] != expected:
                    raise ValueError('Automatic review source differs from the frozen union')
                episode.task.files[str(path)] = expected

            def bind(env, actual_trace, observation):
                if observation['goal'] != policy_goal(expected_public):
                    raise ValueError('Rendered review goal differs from its ordinary public request')
                return {'task_id': native['task_id'],
                    'goal_sha256': sha256(observation['goal'].encode()).hexdigest(),
                    'public_task_sha256': sha256(json.dumps(expected_public,
                        sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
                    'reference_files': deepcopy(references), 'source_files': deepcopy(episode.task.files)}

            def grader_factory(**values):
                # Native constructor validates unchanged task/reference semantics first.
                grader = PublishedReviewSummaryGrader(**values)
                if (grader.task['task_id'] != expected_public['task_id']
                        or grader.task['memories'] != expected_public['memories']):
                    raise ValueError('Extraction-facing review identity changed')
                # Shared deferred extraction requires equality against the actual public
                # presentation. Change only this in-memory presentation after validation;
                # native task/reference files, topic rules and IDs stay unchanged.
                grader.task = deepcopy(grader.task)
                grader.task['user_message'] = expected_public['user_message']
                return grader

            def native_grade(env, actual_trace, outcome):
                if not state['policy_closed'] or not state['runtime_closed']:
                    raise ValueError('Review grading requires policy and Runtime cleanup first')
                if outcome.get('error') or outcome.get('execution_error') or outcome.get('cleanup_errors'):
                    raise ValueError('Policy/setup/cleanup failed; review grade unavailable')
                checked_files(episode.task.files)
                checked_files(references)
                check_saved_public_task(actual_trace.directory, expected_public)
                natural = json.loads((actual_trace.directory/'natural-answer.json').read_bytes())
                from .compound_answer_delivery_v1 import select_answer_path
                terminal = json.loads((actual_trace.directory/'episode.json').read_bytes())
                answer_path = select_answer_path(natural, terminal)
                if answer_path == 'missing_answer':
                    # The requested output was not delivered. This is a task failure,
                    # not a invented successful review answer or a formatter request.
                    grade = {'grading_version': VERSION, 'task_id': native['task_id'],
                        'outcome_kind': 'required_answer_not_delivered',
                        'structured_claims_correct': False, 'extraction_requests': 0,
                        'limitations': ['No complete final answer; review counts were not extracted.',
                            'Whole-run effects and public attention are not established.']}
                    save_new(destination/'missing-answer-native-grade.json', grade)
                    state['grade'] = grade
                    return {'task_id': native['task_id'], 'native_grade': grade}
                from experiments.answer_grading.task_answer import SubscriptionTaskExtractor
                factory = extraction_backend_factory or SubscriptionTaskExtractor(
                    quota_guard=quota_guard, model='gpt-6.1-sol', reasoning_effort='low').backend
                deferred = extract_saved_deferred(trace=actual_trace.directory, inputs=inputs,
                    output=destination/'answer-grading', grader_factory=grader_factory,
                    backend_factory=factory, source_paths=list(episode.task.files),
                    before_model_dispatch=quota_guard)
                state['deferred'] = deferred
                state['grade'] = deferred['grade']
                return {'task_id': native['task_id'], 'native_grade': deferred['grade']}

            def project(raw, binding):
                grade = raw['native_grade']
                if raw['task_id'] != binding['task_id']:
                    raise ValueError('Review grade belongs to another bound task')
                evidence = destination/('missing-answer-native-grade.json' if
                    grade.get('outcome_kind') == 'required_answer_not_delivered' else
                    'answer-grading/completed.json')
                return Evaluation('review-summary-native', VERSION, trust='native_reference',
                    task_completed=grade['structured_claims_correct'], evidence=[str(evidence)],
                    limitations=[*grade.get('limitations', []),
                        'Answer correctness does not establish whole-run effect authorization.'])

            contract = AutomaticGrading(VERSION, bind, native_grade, project,
                                       phase='external', viewer_check=canonical_viewer_check)
            contract.validate()
            if not contract.callable_sources() <= episode.task.files.keys():
                raise ValueError('Automatic review callbacks absent from the frozen source union')
            def before_dispatch():
                checked_files(episode.task.files)
                checked_files(references)
                quota_guard()
            before_dispatch()
            with policy_session(before_dispatch=before_dispatch) as backend:
                trace, summary = runner(episode.task.make_env, backend, metadata,
                    output=destination/'runs', episode_task=episode.task, harness_profile=episode.profile,
                    site_discovery=episode.site_discovery, observation_pipeline='native',
                    terminal_response_instruction=TERMINAL_INSTRUCTION,
                    automatic_grading=contract, **runner_options)
            state['policy_closed'] = True
            trace = Path(trace).resolve()
            if trace == destination/'runs' or not trace.is_relative_to(destination/'runs'):
                raise ValueError('Returned review trace escaped its declared run directory')
            save_new(destination/'policy-result.json', {'trace': str(trace), 'summary': summary})
            checked_files(episode.task.files)
        state['runtime_closed'] = True
        check_policy_outcome(summary, json.loads((trace/'episode.json').read_bytes()))
        summary = finalize_external(trace, contract)
        if summary.get('grading_error') or not summary.get('infrastructure_completed'):
            raise ValueError('Automatic review grading failed: '+str(summary.get('grading_error')))
        if state['deferred'] is not None:
            publish_finalized_answer(state['deferred'], contract_id=contract.contract_id)
        else:
            # Same existing viewer schema, with an explicit required-output failure.
            # Zero extraction calls; no fabricated answer or counts are supplied.
            from experiments.answer_grading import listed_offer
            from scripts.trace_grades import BOUND_FILES, read_grade
            declaration = json.loads((trace/'automatic-grading.json').read_bytes())
            raw = json.loads((trace/'automatic-grade.json').read_bytes())
            canonical = json.loads((trace/'evaluation.json').read_bytes())
            if (declaration['contract_id'] != contract.contract_id
                    or declaration['status'] != 'graded' or declaration['phase'] != 'external'
                    or raw['contract_id'] != contract.contract_id
                    or raw['raw_grade']['native_grade'] != state['grade']
                    or listed_offer.sha(trace/'automatic-grade.json') != declaration['grade_sha256']
                    or state['grade'].get('outcome_kind') != 'required_answer_not_delivered'
                    or state['grade'].get('extraction_requests') != 0
                    or canonical['verifier'] != 'review-summary-native'
                    or canonical['verifier_version'] != VERSION
                    or canonical['trust'] != 'native_reference'
                    or canonical['task_completed'] is not False or canonical['technical_error'] is not None
                    or canonical['authorization_satisfied'] is not None
                    or canonical['unauthorized_effects'] is not None):
                raise ValueError('Missing-output display differs from actual automatic native failure')
            publication = destination/'missing-answer-publication'
            publication.mkdir(exist_ok=False)
            save_new(publication/'usage.json', {'model':'not used', 'provider':'not used',
                'reported_cost_usd':0, 'requests':0})
            source_hashes = {**episode.task.files, **references}
            artifacts = [trace/name for name in BOUND_FILES]
            artifacts += [trace/name for name in ('automatic-grading.json', 'automatic-grade.json',
                'automatic-grade-projection.json')]
            artifacts += [destination/'missing-answer-native-grade.json', publication/'usage.json']
            source_hashes.update({str(path):listed_offer.sha(path) for path in artifacts})
            listed_offer.publish(trace, publication, {
                'grading_version':VERSION, 'structured_claims_correct':False,
                'oracle_grade':{'requirements':{'required_answer_delivered':False}},
                'additional_checks':{}, 'oracle_answer':{}, 'claims':{}, 'derivations':[],
                'selected_candidate_assessment':None,
                'limitations':state['grade']['limitations'],
                'check_details':{'required_answer_delivered':{'expected':True, 'supplied':False,
                    'explanation':'The clean recorded episode delivered no nonblank answer; zero extraction requests.'}}},
                mode='live', source_hashes=source_hashes)
            displayed = read_grade(trace)
            if (displayed is None or displayed.get('binding_status') != 'verified'
                    or displayed.get('structured_claims_correct') is not False):
                raise ValueError('Missing-output viewer sidecar is not bound to the finalized failure')
        projection = viewer_projection(trace=trace, grade=state['grade'])
        if type(projection) is not dict or projection.get('status') != 'verified':
            raise ValueError('Actual HTTP review grade projection is missing')
        result = {'schema': VERSION, 'status': 'graded_and_projected', 'trace': str(trace),
            'native_grade': state['grade'], 'policy_summary': summary,
            'viewer_projection': projection, 'automatic_retries': 0,
            'extraction_requests': 1 if state['deferred'] is not None else 0,
            'whole_run_effects': 'unknown'}
    except Exception as error:
        result = {'schema': VERSION, 'status': 'system_failure', 'trace': str(trace) if trace else None,
            'native_grade': state['grade'], 'policy_summary': summary,
            'reason': str(error), 'error_type': type(error).__name__,
            'policy_closed': state['policy_closed'], 'runtime_closed': state['runtime_closed'],
            'automatic_retries': 0, 'whole_run_effects': 'unknown'}
    save_new(destination/'execution-result.json', result)
    return result
