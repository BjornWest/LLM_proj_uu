"""Reusable prospective saved-answer lifecycle, derived from the reviewed review flow.

Adapters supply native constructors, immutable inputs and an episode factory.
Cleanup precedes one extraction and final canonical publication.
"""
from copy import deepcopy
from hashlib import sha256
import importlib
import inspect
import json
from pathlib import Path

from intent_browser.connected_world_task import checked_files, policy_goal, TERMINAL_INSTRUCTION
from .catalog_cart_execution import save_new
from .catalog_compare_review_execution import (check_policy_outcome,
    check_saved_public_task, extract_saved_deferred, publish_finalized_answer)
from .generation_configs import observation_runner_options

VERSION = 'website-saved-answer-lifecycle-v1'


class PresentedGrader:
    """Present actual prose to extraction; native grading retains its own task."""
    def __init__(self, native, public):
        if (native.task['task_id'] != public['task_id']
                or native.task['memories'] != public['memories']):
            raise ValueError('Native/public task identity or memories changed')
        self.native = native
        self.task = deepcopy(native.task)
        self.task['user_message'] = public['user_message']

    def __getattr__(self, name):
        return getattr(self.native, name)


def native_input_snapshot(inputs, bound_files):
    """Consume already-bound native buffers without replacing their fixed hashes."""
    references, task = {}, None
    for name, path in inputs.items():
        payload = path.read_bytes()
        digest = sha256(payload).hexdigest()
        if bound_files.get(str(path)) != digest:
            raise ValueError('Native input differs from the frozen recipe/runtime export: '+name)
        references[str(path)] = digest
        if name == 'task':
            task = json.loads(payload)
    return task, references


def run(output, run_directory, *, episode_factory, inputs_factory, grader_factory,
        contract_id, verifier, policy_session, metadata, runner_options,
        viewer_projection, quota_guard, extraction_backend_factory=None, runner=None,
        evidence_sources=None):
    """One finite policy lease, at most one ordinary answer formatter, no retries.

    Grading and publication follow policy/Runtime cleanup. All native input and
    actual public request bytes are pinned before policy dispatch.
    """
    runner_options = observation_runner_options(runner_options)
    from intent_browser.automatic_grading import AutomaticGrading, canonical_viewer_check, finalize_external
    from intent_browser.evaluation import Evaluation
    if (not all(callable(f) for f in (episode_factory, inputs_factory, grader_factory,
                                    policy_session, viewer_projection, quota_guard))
            or not all(type(v) is str and v.strip() for v in (contract_id, verifier))):
        raise ValueError('Require policy, quota and actual HTTP projection callables')
    if evidence_sources is not None and not callable(evidence_sources):
        raise ValueError('Interaction evidence sources must be callable')
    if extraction_backend_factory is not None and not callable(extraction_backend_factory):
        raise ValueError('Extraction backend must be callable')
    if (type(runner_options) is not dict
            or type(runner_options.get('max_input_tokens')) is not int
            or runner_options['max_input_tokens'] <= 0
            or 'max_steps' not in runner_options
            or (runner_options['max_steps'] is not None and
                (type(runner_options['max_steps']) is not int or runner_options['max_steps'] <= 0))):
        raise ValueError('Declare positive input-context bound and positive turns or explicit None')
    reserved = {'env_factory', 'backend', 'metadata', 'output', 'episode_task', 'harness_profile',
        'site_discovery', 'terminal_response_instruction',
        'automatic_grading', 'allow_ungraded', 'ungraded_reason', 'agent_runtime', 'agent_actor'}
    if set(runner_options) & reserved:
        raise ValueError('Runner options cannot replace task or automatic-grade bindings')
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    output, destination = Path(output).resolve(), Path(run_directory).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    state = {'policy_closed': False, 'runtime_closed': False, 'grade': None, 'deferred': None, 'evidence_hashes': {}}
    trace, summary = None, None
    try:
        with episode_factory(output) as episode:
            expected_public = deepcopy(episode.public)
            runtime_directory = destination/'runtime-binding'
            inputs = inputs_factory(output, runtime_directory)
            if type(inputs) is not dict or not {'world', 'task', 'reference'} <= inputs.keys():
                raise ValueError('Require declared native world/task/reference inputs')
            inputs = {key: Path(path).resolve() for key, path in inputs.items()}
            if any(not (path.is_relative_to(output) or path.is_relative_to(runtime_directory))
                   for path in inputs.values()):
                raise ValueError('Native inputs escaped the recipe/runtime export')
            exported = episode.export_private_runtime(runtime_directory)
            for name, expected in exported['files'].items():
                path = (runtime_directory/name).resolve()
                if not path.is_relative_to(runtime_directory):
                    raise ValueError('Saved-answer export escaped the runtime directory')
                episode.task.files[str(path)] = expected
            runtime_manifest = runtime_directory/'manifest.json'
            episode.task.files[str(runtime_manifest)] = sha256(runtime_manifest.read_bytes()).hexdigest()
            native, references = native_input_snapshot(inputs, episode.task.files)
            if (expected_public['task_id'] != native['task_id']
                    or expected_public['memories'] != native['memories']
                    or type(expected_public['user_message']) is not str
                    or not expected_public['user_message'].strip()):
                raise ValueError('Native saved-answer identity/memories or public request is malformed')
            callbacks = (episode_factory, inputs_factory, grader_factory)
            if evidence_sources is not None:
                callbacks += (evidence_sources,)
            for callback in callbacks:
                source = inspect.getsourcefile(callback)
                if source is None:
                    raise ValueError('Task adapter has no source-file binding')
                source = Path(source).resolve()
                if episode.task.files.get(str(source)) != sha256(source.read_bytes()).hexdigest():
                    raise ValueError('Task adapter differs from the frozen source union')
            for name in ('intent_browser.automatic_grading', 'intent_browser.evaluation',
                         'agent_trace.adapters.browsergym', __name__):
                module = importlib.import_module(name)
                path = Path(module.__file__).resolve()
                expected = sha256(path.read_bytes()).hexdigest()
                if str(path) in episode.task.files and episode.task.files[str(path)] != expected:
                    raise ValueError('Automatic saved-answer source differs from the frozen union')
                episode.task.files[str(path)] = expected

            def bind(env, actual_trace, observation):
                if observation['goal'] != policy_goal(expected_public):
                    raise ValueError('Rendered saved-answer goal differs from its ordinary public request')
                return {'task_id': native['task_id'],
                    'goal_sha256': sha256(observation['goal'].encode()).hexdigest(),
                    'public_task_sha256': sha256(json.dumps(expected_public,
                        sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
                    'reference_files': deepcopy(references), 'source_files': deepcopy(episode.task.files)}

            def presented_grader_factory(**values):
                return PresentedGrader(grader_factory(**values), expected_public)

            def native_grade(env, actual_trace, outcome):
                if not state['policy_closed'] or not state['runtime_closed']:
                    raise ValueError('Saved-answer grading requires policy and Runtime cleanup first')
                if outcome.get('error') or outcome.get('execution_error') or outcome.get('cleanup_errors'):
                    raise ValueError('Policy/setup/cleanup failed; saved-answer grade unavailable')
                checked_files(episode.task.files)
                checked_files(references)
                check_saved_public_task(actual_trace.directory, expected_public)
                extra_paths = ([] if evidence_sources is None else evidence_sources(actual_trace.directory))
                if type(extra_paths) not in (list, tuple):
                    raise ValueError('Interaction evidence must list retained source files')
                extra_paths = [Path(p).resolve() for p in extra_paths]
                if any(not p.is_relative_to(actual_trace.directory.resolve()) for p in extra_paths):
                    raise ValueError('Interaction evidence escaped its actual main trace')
                state['evidence_hashes'] = {str(p): sha256(p.read_bytes()).hexdigest() for p in extra_paths}
                natural = json.loads((actual_trace.directory/'natural-answer.json').read_bytes())
                from .compound_answer_delivery_v1 import select_answer_path
                terminal = json.loads((actual_trace.directory/'episode.json').read_bytes())
                answer_path = select_answer_path(natural, terminal)
                if answer_path == 'missing_answer':
                    # The requested output was not delivered. This is a task failure,
                    # not an invented successful answer or a formatter request.
                    grade = {'grading_version': contract_id, 'task_id': native['task_id'],
                        'outcome_kind': 'required_answer_not_delivered',
                        'structured_claims_correct': False, 'extraction_requests': 0,
                        'limitations': ['No complete final answer; answer claims were not extracted.',
                            'Whole-run effects and public attention are not established.']}
                    save_new(destination/'missing-answer-native-grade.json', grade)
                    state['grade'] = grade
                    return {'task_id': native['task_id'], 'native_grade': grade}
                from experiments.answer_grading.task_answer import SubscriptionTaskExtractor
                factory = extraction_backend_factory or SubscriptionTaskExtractor(
                    quota_guard=quota_guard, model='gpt-6.1-sol', reasoning_effort='low').backend
                deferred = extract_saved_deferred(trace=actual_trace.directory, inputs=inputs,
                    output=destination/'answer-grading', grader_factory=presented_grader_factory,
                    backend_factory=factory, source_paths=[*episode.task.files, *extra_paths],
                    before_model_dispatch=quota_guard)
                state['deferred'] = deferred
                state['grade'] = deferred['grade']
                return {'task_id': native['task_id'], 'native_grade': deferred['grade']}

            def project(raw, binding):
                grade = raw['native_grade']
                if raw['task_id'] != binding['task_id']:
                    raise ValueError('Saved-answer grade belongs to another bound task')
                evidence = destination/('missing-answer-native-grade.json' if
                    grade.get('outcome_kind') == 'required_answer_not_delivered' else
                    'answer-grading/completed.json')
                return Evaluation(verifier, contract_id, trust='native_reference',
                    task_completed=grade['structured_claims_correct'], evidence=[str(evidence)],
                    limitations=[*grade.get('limitations', []),
                        'Answer correctness does not establish whole-run effect authorization.'])

            contract = AutomaticGrading(contract_id, bind, native_grade, project,
                                       phase='external', viewer_check=canonical_viewer_check)
            contract.validate()
            if not contract.callable_sources() <= episode.task.files.keys():
                raise ValueError('Automatic saved-answer callbacks absent from the frozen source union')
            def before_dispatch():
                checked_files(episode.task.files)
                checked_files(references)
                quota_guard()
            before_dispatch()
            with policy_session(before_dispatch=before_dispatch) as backend:
                trace, summary = runner(episode.task.make_env, backend, metadata,
                    output=destination/'runs', episode_task=episode.task, harness_profile=episode.profile,
                    site_discovery=episode.site_discovery,
                    terminal_response_instruction=TERMINAL_INSTRUCTION,
                    automatic_grading=contract, **runner_options)
            state['policy_closed'] = True
            trace = Path(trace).resolve()
            if trace == destination/'runs' or not trace.is_relative_to(destination/'runs'):
                raise ValueError('Returned saved-answer trace escaped its declared run directory')
            save_new(destination/'policy-result.json', {'trace': str(trace), 'summary': summary})
            checked_files(episode.task.files)
        state['runtime_closed'] = True
        check_policy_outcome(summary, json.loads((trace/'episode.json').read_bytes()))
        summary = finalize_external(trace, contract)
        if summary.get('grading_error') or not summary.get('infrastructure_completed'):
            raise ValueError('Automatic saved-answer grading failed: '+str(summary.get('grading_error')))
        checked_files(state['evidence_hashes'])
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
                    or canonical['verifier'] != verifier
                    or canonical['verifier_version'] != contract_id
                    or canonical['trust'] != 'native_reference'
                    or canonical['task_completed'] is not False or canonical['technical_error'] is not None
                    or canonical['authorization_satisfied'] is not None
                    or canonical['unauthorized_effects'] is not None):
                raise ValueError('Missing-output display differs from actual automatic native failure')
            publication = destination/'missing-answer-publication'
            publication.mkdir(exist_ok=False)
            save_new(publication/'usage.json', {'model':'not used', 'provider':'not used',
                'reported_cost_usd':0, 'requests':0})
            source_hashes = {**episode.task.files, **references, **state['evidence_hashes']}
            artifacts = [trace/name for name in BOUND_FILES]
            artifacts += [trace/name for name in ('automatic-grading.json', 'automatic-grade.json',
                'automatic-grade-projection.json')]
            artifacts += [destination/'missing-answer-native-grade.json', publication/'usage.json']
            source_hashes.update({str(path):listed_offer.sha(path) for path in artifacts})
            listed_offer.publish(trace, publication, {
                'grading_version':contract_id, 'structured_claims_correct':False,
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
            raise ValueError('Actual HTTP saved-answer grade projection is missing')
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
