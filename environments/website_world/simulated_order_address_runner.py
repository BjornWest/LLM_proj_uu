"""Limited address-only automatic grading on ordinary order-capable episodes.

Preparation only until exact source and scripted browser/HTTP acceptance pass.
Every raw order remains recorded; full order outcome and effects are unassessed.
"""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path

from intent_browser.connected_world_task import checked_files, policy_goal
from .adapter import ROOT
from .catalog_cart_execution import save_new
from .simulated_order_execution import quota_sources
from .simulated_order_address_execution import AddressOnlyOrderEpisode
from . import simulated_order_address_grading as grading

VERSION = 'website-simulated-order-address-runner-v1'
TERMINAL_INSTRUCTION = (
    'When finished, use send_msg_to_user to give a self-contained answer with '
    'the requested result and relevant source links. Explain missing information honestly.'
)

def run(output, run_directory, *, policy_session, metadata, runner_options,
        viewer_projection, quota_guard=None, runner=None):
    """One finite policy lease, one native state grade, no answer extraction.

    This scores address fields only and never requires a complete effect envelope.
    Exact source/instance/scripted-grade/viewer acceptance and finite resources remain required.
    """
    from intent_browser.automatic_grading import AutomaticGrading, canonical_viewer_check, finalize_external
    if type(runner_options) is not dict or any(type(runner_options.get(key)) is not int
            or runner_options[key] <= 0 for key in ('max_steps', 'max_input_tokens')):
        raise ValueError('Declare finite positive turn and context bounds')
    reserved = {'env_factory', 'backend', 'metadata', 'output', 'episode_task', 'harness_profile',
        'site_discovery', 'observation_pipeline', 'terminal_response_instruction',
        'automatic_grading', 'allow_ungraded', 'ungraded_reason', 'agent_runtime', 'agent_actor'}
    if set(runner_options) & reserved:
        raise ValueError('Runner options cannot replace ordering, grading or capture bindings')
    if not callable(policy_session) or not callable(viewer_projection):
        raise ValueError('Require a policy lease and final HTTP viewer projection')
    if quota_guard is not None and not callable(quota_guard):
        raise ValueError('Quota guard must be callable')
    additions = {}
    for name in ('intent_browser.automatic_grading', 'intent_browser.evaluation',
                 'agent_trace.adapters.browsergym', __name__, grading.__name__):
        path = Path(importlib.import_module(name).__file__).resolve()
        additions[str(path)] = sha256(path.read_bytes()).hexdigest()
    destination = Path(run_directory).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    if quota_guard is None:
        additions.update({str((ROOT/name).resolve()): expected
                          for name, expected in quota_sources().items()})
        from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
        quota_guard = SubscriptionQuotaGuard(destination/'subscription-quota', remaining_floor=1)
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    state = {'policy_closed': False, 'runtime_closed': False, 'grade': None}
    trace = None
    summary = None
    try:
        with AddressOnlyOrderEpisode(output, additional_source_files=additions) as episode:
            from intent_browser.standard_profile import standard_profile
            # This finite GUI address probe never depends on an unavailable Python sandbox.
            episode.profile = standard_profile(navigation_origins=episode.runtime.navigation_origins,
                                               helpers=False, data_tools=False)
            runtime_directory = destination/'runtime-binding'
            exported = episode.export_private_runtime(runtime_directory)
            for name, expected in exported['files'].items():
                path = (runtime_directory/name).resolve()
                if not path.is_relative_to(runtime_directory):
                    raise ValueError('Ordering runtime export escaped its binding directory')
                episode.task.files[str(path)] = expected
            episode.task.files[str(runtime_directory/'manifest.json')] = sha256(
                (runtime_directory/'manifest.json').read_bytes()).hexdigest()
            expected_public = deepcopy(episode.public)
            references = {str(episode.output/name): sha256((episode.output/name).read_bytes()).hexdigest()
                for name in ('simulated-order-task.private.json', 'order-address-reference.private.json',
                             'simulated-order-setup.private.json')}

            def bind(env, actual_trace, observation):
                if observation['goal'] != policy_goal(expected_public):
                    raise ValueError('Displayed ordering goal differs from its authored request')
                return {'task_id': expected_public['task_id'],
                    'goal_sha256': sha256(observation['goal'].encode()).hexdigest(),
                    'public_task_sha256': sha256(json.dumps(expected_public,
                        sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
                    'reference_files': deepcopy(references), 'source_files': deepcopy(episode.task.files),
                    'scoring_scope': grading.SCOPE, 'observation_rule': grading.OBSERVATION_RULE}

            def native_grade(env, actual_trace, outcome):
                if not state['policy_closed'] or not state['runtime_closed']:
                    raise ValueError('Ordering grading requires policy and Runtime cleanup first')
                if outcome.get('error') or outcome.get('execution_error') or outcome.get('cleanup_errors'):
                    raise ValueError('Policy/setup/cleanup failed; native ordering grade unavailable')
                checked_files(episode.task.files)
                public = json.loads((actual_trace.directory/'policy-task.json').read_bytes())
                if any(public.get(key) != expected_public[key] for key in
                        ('task_id', 'user_message', 'memories', 'environment_context', 'start_url')):
                    raise ValueError('Saved ordering request, identity or context changed')
                evidence, completed = episode.capture.seal(actual_trace.directory, outcome)
                rid = episode.native_task['retailer_id']
                result = grading.grade(episode.native_task, episode.reference, evidence,
                    binding=episode.capture.binding,
                    storage_binding={'origin': episode.runtime.origins[rid],
                        'storage_key': 'website-drafts.state.' + rid,
                        'implicit_country': episode.reference['implicit_country']},
                    episode_id=actual_trace.episode_id,
                    main_trace_sha256=evidence['main_trace_sha256'])
                result['policy_completed_observed'] = completed
                state['grade'] = result
                return {'task_id': expected_public['task_id'], 'native_grade': result}

            def viewer_check(actual_trace, evaluation):
                return canonical_viewer_check(actual_trace, evaluation)

            contract = AutomaticGrading(VERSION, bind, native_grade, grading.project_native,
                                       phase='external', viewer_check=viewer_check)
            contract.validate()
            if not contract.callable_sources() <= episode.task.files.keys():
                raise ValueError('Automatic ordering callbacks absent from the frozen source union')

            def before_dispatch():
                checked_files(episode.task.files)
                quota_guard()

            before_dispatch()
            with policy_session(before_dispatch=before_dispatch) as backend:
                trace, summary = runner(episode.task.make_env, backend, metadata,
                    output=destination/'runs', episode_task=episode.task, harness_profile=episode.profile,
                    site_discovery=episode.site_discovery, observation_pipeline='native',
                    terminal_response_instruction=TERMINAL_INSTRUCTION, automatic_grading=contract,
                    **runner_options)
            state['policy_closed'] = True
            trace = Path(trace).resolve()
            if trace == destination/'runs' or not trace.is_relative_to(destination/'runs'):
                raise ValueError('Returned ordering trace escaped the declared run directory')
            save_new(destination/'policy-result.json', {'trace': str(trace), 'summary': summary})
            checked_files(episode.task.files)  # No post-policy quota check suppresses native grading.
        state['runtime_closed'] = True
        saved = json.loads((trace/'episode.json').read_bytes())
        if any(saved.get(key) != summary.get(key) for key in
                ('stop_reason', 'error', 'execution_error', 'cleanup_errors', 'trace_complete')):
            raise ValueError('Returned ordering outcome differs from the saved browser trace')
        summary = finalize_external(trace, contract)
        if summary.get('grading_error') or not summary.get('infrastructure_completed'):
            raise ValueError('Automatic ordering grade failed: '+str(summary.get('grading_error')))
        projection = viewer_projection(trace=trace, grade=state['grade'])
        if type(projection) is not dict or projection.get('status') != 'verified':
            raise ValueError('Final native ordering grade HTTP viewer projection is missing')
        result = {'schema': VERSION, 'status': 'graded_and_projected', 'trace': str(trace),
            'state_grading': state['grade'], 'policy_summary': summary, 'viewer_projection': projection,
            'scoring_scope': grading.SCOPE, 'full_effects': 'unknown', 'full_order_completion': 'not_assessed',
            'answer_extraction_requests': 0, 'automatic_retries': 0}
    except Exception as error:
        result = {'schema': VERSION, 'status': 'system_failure', 'trace': str(trace) if trace else None,
            'state_grading': state['grade'], 'policy_summary': summary, 'reason': str(error),
            'error_type': type(error).__name__, 'policy_closed': state['policy_closed'],
            'runtime_closed': state['runtime_closed'], 'answer_extraction_requests': 0, 'automatic_retries': 0}
    save_new(destination/'execution-result.json', result)
    return result
