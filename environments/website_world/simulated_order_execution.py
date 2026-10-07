"""Prepared ordering episodes with private ledger capture and automatic grading.

The current capture deliberately retains null whole-run effect authority. These
consumers are source preparation until exact Git/runtime/authority acceptance.
"""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path

from intent_browser.connected_world_task import checked_files, policy_goal
from . import generation as shared, short_task_setup as setup
from . import simulated_order_task as native, simulated_order_grading as grading
from . import simulated_order_capture as capture_api
from .adapter import ROOT, digest
from .catalog_cart_execution import save_new

VERSION = 'website-simulated-order-execution-v1'
RECIPE = 'website-simulated-order-publication-v1'
QUOTA_DEPENDENCIES = {
    'experiments/external_agent/subscription_quota.py':
        '5db315f4ad2ae620565be783ee6ba162990e1dca38a8d62ce75218e9a4bd7d8d',
    'scripts/product_width_watch.py':
        'b5a730622da60e94bc0c17bfab54d21699bf68613a3d89a928e32d8e3148e0c1',
}
TERMINAL_INSTRUCTION = (
    'When finished, use send_msg_to_user to give a self-contained answer with '
    'the requested result and relevant source links. Explain missing information '
    'honestly. Only perform shopping actions authorized by the user request.'
)


def quota_sources():
    """Retain the exact released guard dependencies, without quota RPC reads."""
    checked_files({str((ROOT/name).resolve()): expected
                   for name, expected in QUOTA_DEPENDENCIES.items()})
    return deepcopy(QUOTA_DEPENDENCIES)


def checked_union(manifest, additions=None):
    """Retain complete declared source pins, rejecting conflicting dependencies."""
    sources = {}
    for name, expected in manifest['source_sha256'].items():
        path = (ROOT/name).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('Ordering source escaped the release root')
        sources[str(path)] = expected
    for path, expected in (additions or {}).items():
        absolute = str(Path(path).resolve())
        if absolute in sources and sources[absolute] != expected:
            raise ValueError('Ordering dependency conflicts with frozen source')
        sources[absolute] = expected
    checked_files(sources)
    return sources


class SimulatedOrderEpisode(shared.GeneratedEpisode):
    def __init__(self, output, *, lazy_publication=None, additional_source_files=None):
        # Validate the recipe before starting any server.
        manifest = shared.load(output)
        if manifest.get('simulated_order_recipe') != RECIPE:
            raise ValueError('Not a frozen native ordering recipe')
        if lazy_publication is None:
            lazy_publication = manifest['execution_policy']['runtime_options']['lazy_publication']
        sources = checked_union(manifest, additional_source_files)
        super().__init__(output, lazy_publication=lazy_publication)
        try:
            read = lambda name: json.loads((self.output/name).read_bytes())
            self.native_task = read('simulated-order-task.private.json')
            self.reference = read('simulated-order-reference.private.json')
            if (self.native_task != native.make(self.runtime.baskets, self.native_task['spec'])
                    or self.reference != native.reference(self.runtime.baskets, self.native_task)):
                raise ValueError('Native ordering task, address, quote context or reference changed')
            episode = read('episode.json')
            expected = {'user_message': self.native_task['user_message'],
                        'memories': self.native_task['memories']}
            if episode['task_id'] != self.native_task['task_id'] or episode['manual_task'] != expected:
                raise ValueError('Original authored ordering request or memories changed')
            rid = self.native_task['retailer_id']
            if episode['start'] != {'kind': 'retailer_home', 'retailer_id': rid}:
                raise ValueError('The internal constructor start must identify the ordering retailer')
            if (self.native_task['coupon_code'] is not None
                    or read('simulated-order-setup.private.json') != {
                        'start': {'kind': 'cart'}, 'prepared_cart': [{
                            'offer_id': self.native_task['spec']['offer_id'],
                            'quantity': self.native_task['spec']['quantity']}]}):
                raise ValueError('This initial consumer supports an explicit preloaded cart without a setup coupon')
            declaration = read('simulated-order-setup.private.json')
            self.setup_plan = setup.make_plan(self.runtime, retailer_id=rid, **declaration)
            if not self.runtime.public_catalogs[rid].get('simulatedOrders'):
                raise ValueError('This Runtime has no default simulated-order capability')
            self.public = {**self.public, **deepcopy(expected), 'task_id': self.native_task['task_id'],
                           'start_url': self.setup_plan['start_url']}
            files = deepcopy(self.task.files)
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            files.update(sources)
            self.task = type(self.task)(self.public, origins=self.runtime.navigation_origins,
                files=files, attachments=self.task.attachments, headless=self.task.headless,
                profile_name=self.profile.name)
            self.capture = capture_api.OrderCapture(self.runtime, self.native_task, source_files=sources)
            self.task = capture_api.prepared_task(self.task, self.capture, self.setup_plan, self.runtime)
            self.source_union = sources
        except BaseException:
            self.runtime.close()
            raise

    def export_private_runtime(self, output):
        manifest = super().export_private_runtime(output)
        output = Path(output).resolve()
        for name, value in (
            ('simulated-order-task.private.json', self.native_task),
            ('simulated-order-reference.private.json', self.reference),
            ('simulated-order-setup.private.json', self.setup_plan),
            ('order-source-union.private.json', self.source_union),
            ('order-ledger-before-setup.private.json', self.runtime.orders.snapshot())):
            save_new(output/name, value)
            manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
        (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False,
                                                     allow_nan=False)+'\n')
        return manifest


def project_native(raw, binding):
    """State correctness is distinct from unaccepted whole-run effect coverage."""
    from intent_browser.evaluation import Evaluation
    grade = raw['native_grade']
    if raw['task_id'] != binding['task_id'] or grade['task_id'] != binding['task_id']:
        raise ValueError('Native ordering grade belongs to another task')
    completed = {'pass': True, 'fail': False, 'inconclusive': None}[grade['verdict']]
    return Evaluation('simulated-order-native', VERSION, trust='native_reference',
        task_completed=completed,
        evidence=['automatic-grade.json', 'order-capsule.private.json',
                  'order-capture-provenance.private.json'],
        limitations=[*grade.get('limitations', []),
            'Whole-run effect authority remains unaccepted; candidate capsules retain null journals.'])


def run(output, run_directory, *, policy_session, metadata, runner_options,
        viewer_projection, quota_guard=None, runner=None):
    """One finite policy lease, one native state grade, no answer extraction.

    This source candidate has no accepted effect-envelope constructor. Exact
    runtime/authority/instance acceptance and spending authorization stay separate.
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
                 'agent_trace.adapters.browsergym'):
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
        with SimulatedOrderEpisode(output, additional_source_files=additions) as episode:
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
                for name in ('simulated-order-task.private.json', 'simulated-order-reference.private.json',
                             'simulated-order-setup.private.json')}

            def bind(env, actual_trace, observation):
                if observation['goal'] != policy_goal(expected_public):
                    raise ValueError('Displayed ordering goal differs from its authored request')
                return {'task_id': expected_public['task_id'],
                    'goal_sha256': sha256(observation['goal'].encode()).hexdigest(),
                    'reference_files': deepcopy(references), 'source_files': deepcopy(episode.task.files)}

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
                capsule, completed = episode.capture.seal(actual_trace.directory, outcome)
                result = grading.grade(episode.runtime.baskets, episode.native_task, episode.reference,
                    binding=episode.capture.binding, capsule=capsule,
                    episode_id=actual_trace.episode_id, main_trace_sha256=capsule['main_trace_sha256'],
                    policy_completed=completed)
                state['grade'] = result
                return {'task_id': expected_public['task_id'], 'native_grade': result}

            def viewer_check(actual_trace, evaluation):
                return canonical_viewer_check(actual_trace, evaluation)

            contract = AutomaticGrading(VERSION, bind, native_grade, project_native,
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
            'answer_extraction_requests': 0, 'automatic_retries': 0}
    except Exception as error:
        result = {'schema': VERSION, 'status': 'system_failure', 'trace': str(trace) if trace else None,
            'state_grading': state['grade'], 'policy_summary': summary, 'reason': str(error),
            'error_type': type(error).__name__, 'policy_closed': state['policy_closed'],
            'runtime_closed': state['runtime_closed'], 'answer_extraction_requests': 0, 'automatic_retries': 0}
    save_new(destination/'execution-result.json', result)
    return result
