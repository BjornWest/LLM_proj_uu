"""Exact link episodes with a pinned browser capability and once-only grading."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.answer_grading import task_answer
from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
from intent_browser.connected_world_task import checked_files, TERMINAL_INSTRUCTION
from . import generation as shared, variant_link_publication as publication
from . import variant_link_task as native
from .variant_link_answer_grading import VariantLinkGrader

VERSION = 'website-variant-link-execution-v1'


class VariantLinkEpisode:
    def __init__(self, output):
        from .runtime import Runtime
        from .comparison_sku_task import episode_task
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        self.output = Path(output).resolve()
        self.manifest = shared.load(self.output)
        if self.manifest.get('recipe') != publication.VERSION:
            raise ValueError('Not a frozen variant-link recipe')
        read = lambda name: json.loads((self.output / name).read_bytes())
        task = read('variant-link-task.private.json')
        accepted = read('variant-link-acceptance.private.json')
        # Acceptance is checked before any host publication as well as against
        # the actual new Runtime. A source-only capability cannot launch.
        publication.compile_packet(world=read('pin/world.private.json'),
            spec={k: task[k] for k in ('kind', 'retailer_id', 'offer_id')},
            catalog=read('variant-link-catalog.private.json'),
            bindings=read('variant-link-bindings.private.json'),
            asset_sha256=read('variant-link-assets.private.json'), acceptance=accepted)
        episode = read('episode.json')
        options = read('variant-link-runtime-options.private.json')
        if set(options) - {'review_presentation', 'page_option_order'}:
            raise ValueError('Unsupported variant-link Runtime override')
        if episode != {'task_id': task['task_id'], 'readable_origins': True,
                       'start': task['start'],
                       'manual_task': {k: task[k] for k in ('user_message', 'memories')}}:
            raise ValueError('Frozen public request/memories/product start changed')
        self.runtime = Runtime(self.output / 'pin', presentation=read('presentation.json'),
            surrounding=read('surrounding.private.json'), basket_plan=read('basket-plan.private.json'),
            checkout_domain=read('checkout-domain.private.json'),
            delivery_plan=read('delivery-plan.private.json') if (self.output / 'delivery-plan.private.json').exists() else None,
            readable_origins=True, lazy_publication=True, partial_url_navigation=True, **options)
        try:
            if self.runtime.compositions != read('compositions.private.json'):
                raise ValueError('Page composition changed')
            catalog = self.runtime.public_catalogs[task['retailer_id']]
            packet = publication.compile_packet(world=self.runtime.world,
                spec={k: task[k] for k in ('kind', 'retailer_id', 'offer_id')},
                catalog=catalog, bindings=self.runtime.bindings,
                asset_sha256=self.runtime.asset_hashes, acceptance=accepted)
            if (packet['task'] != task or packet['reference'] != read('variant-link-reference.private.json')
                    or packet['navigation_capability'] != read('variant-link-capability.private.json')):
                raise ValueError('Actual native task/reference/navigation capability differs')
            self.native_task, self.reference = task, packet['reference']
            self.catalog, self.capability = catalog, packet['navigation_capability']
            self.answer_grader = VariantLinkGrader(self.runtime.world, task, self.reference,
                catalog, self.runtime.bindings, self.capability)
            retailer = next(r for r in self.runtime.world['retailers'] if r['retailer_id'] == task['retailer_id'])
            self.public = public_projection({'schema_version': 'connected-world-manual-v1',
                'task_id': task['task_id'], 'user_message': task['user_message'],
                'memories': deepcopy(task['memories']), 'start_url': task['start']['url'],
                'environment_context': {'currency': 'SEK', 'scenario_date': self.runtime.world['quote_as_of'],
                                        'shopping_scope': retailer['name']}})
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins, helpers=False)
            files = {str(self.output / name): expected for name, expected in self.manifest['files'].items()}
            files.update({str(shared.ROOT / name): expected for name, expected in self.manifest['source_sha256'].items()})
            files[str(self.output / 'manifest.json')] = sha256((self.output / 'manifest.json').read_bytes()).hexdigest()
            files[accepted['path']] = accepted['sha256']
            self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                attachments={name: str(self.output / name) for name in (
                    'variant-link-task.private.json', 'variant-link-reference.private.json',
                    'variant-link-capability.private.json', 'variant-link-acceptance.private.json')})
        except BaseException:
            self.runtime.close()
            raise

    def export_private_runtime(self, output):
        output = Path(output).resolve()
        output.mkdir(parents=True, exist_ok=False)
        for name, value in {'runtime.private.json': self.runtime.manifest,
                            'bindings.private.json': self.runtime.bindings,
                            'catalog.private.json': self.catalog,
                            'navigation-capability.private.json': self.capability,
                            'task.public.json': self.public}.items(): shared.save(output / name, value)
        return output

    def __enter__(self): return self
    def __exit__(self, *args): self.runtime.close()


def run(output, run_directory, *, policy_session, metadata, runner_options,
        viewer_projection, quota_guard=None, extraction_backend_factory=None, runner=None):
    """Bind grading prospectively, finalize after both cleanups, then publish once.

    This is consumer source preparation. Actual recipient capability, native
    public-instance acceptance and a reviewed frozen dependency union still gate
    every episode; this function grants neither a model run nor effect authority.
    """
    import importlib
    from intent_browser.automatic_grading import AutomaticGrading, canonical_viewer_check, finalize_external
    from intent_browser.connected_world_task import policy_goal
    from intent_browser.evaluation import Evaluation
    from . import catalog_compare_review_execution as finalization
    if not callable(policy_session) or not callable(viewer_projection):
        raise ValueError('Policy session and automatic viewer projection are required')
    if type(runner_options) is not dict or any(type(runner_options.get(k)) is not int
            or runner_options[k] <= 0 for k in ('max_steps', 'max_input_tokens')):
        raise ValueError('Declare finite positive policy turn and input limits')
    reserved = {'env_factory', 'backend', 'metadata', 'output', 'episode_task',
        'harness_profile', 'site_discovery', 'observation_pipeline', 'terminal_response_instruction',
        'automatic_grading', 'allow_ungraded', 'ungraded_reason', 'agent_runtime', 'agent_actor'}
    if set(runner_options) & reserved:
        raise ValueError('Runner options cannot replace native task or prospective grading bindings')
    if extraction_backend_factory is not None and not callable(extraction_backend_factory):
        raise ValueError('Configured answer extractor must be callable')
    output, destination = Path(output).resolve(), Path(run_directory).resolve()
    shared.load(output)
    record = json.loads((output/'execution.private.json').read_bytes())
    grading = record['answer_grading']
    if grading['mode'] != 'subscription-post-run':
        raise ValueError('Automatic variant-link grading must be attached before dispatch')
    destination.mkdir(parents=True, exist_ok=False)
    if quota_guard is None:
        quota_guard = SubscriptionQuotaGuard(destination/'subscription-quota', remaining_floor=1)
    if not callable(quota_guard):raise ValueError('Quota guard must be callable')
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    runner_options = deepcopy(runner_options)
    state = {'policy_closed':False,'runtime_closed':False,'grade':None,'deferred':None}
    trace = None; summary = None
    shared.save(destination/'execution-plan.private.json', {'schema':VERSION,
        'grading':grading,'runner_options':runner_options,'automatic_retries':0,
        'extractor_requests_max':1,'prospective_external_grading':True,'viewer_projection_required':True})
    try:
        with VariantLinkEpisode(output) as episode:
            binding = episode.export_private_runtime(destination/'runtime-binding')
            expected_public = deepcopy(episode.public)
            inputs = {'world':output/'pin/world.private.json',
                'task':output/'variant-link-task.private.json',
                'reference':output/'variant-link-reference.private.json',
                'catalog':binding/'catalog.private.json','bindings':binding/'bindings.private.json',
                'navigation_capability':binding/'navigation-capability.private.json'}
            reference_files = {str(path.resolve()):sha256(path.read_bytes()).hexdigest()
                               for path in inputs.values()}
            episode.task.files.update(reference_files)
            for name in ('intent_browser.automatic_grading','intent_browser.evaluation',
                         'agent_trace.adapters.browsergym','environments.website_world.catalog_compare_review_execution'):
                path = Path(importlib.import_module(name).__file__).resolve()
                expected = sha256(path.read_bytes()).hexdigest()
                if str(path) in episode.task.files and episode.task.files[str(path)] != expected:
                    raise ValueError('Grading implementation differs from frozen variant binding')
                episode.task.files[str(path)] = expected
            def bind(env, actual_trace, observation):
                if observation['goal'] != policy_goal(expected_public):
                    raise ValueError('Displayed variant-link task differs from the bound public task')
                return {'task_id':expected_public['task_id'],
                    'goal_sha256':sha256(observation['goal'].encode()).hexdigest(),
                    'reference_files':deepcopy(reference_files),'source_files':deepcopy(episode.task.files)}
            def native_grade(env, actual_trace, outcome):
                if not state['policy_closed'] or not state['runtime_closed']:
                    raise ValueError('Variant-link grading requires policy and Runtime cleanup first')
                if outcome.get('error') or outcome.get('execution_error') or outcome.get('cleanup_errors'):
                    raise ValueError('Policy/setup/cleanup failed; no complete variant answer')
                checked_files(episode.task.files)
                public = json.loads((actual_trace.directory/'policy-task.json').read_bytes())
                if any(public.get(key) != expected_public[key] for key in
                       ('task_id','user_message','memories','environment_context','start_url')):
                    raise ValueError('Saved public variant task or context changed')
                factory = extraction_backend_factory or task_answer.SubscriptionTaskExtractor(
                    quota_guard=quota_guard,model=grading['model'],reasoning_effort=grading['reasoning_effort']).backend
                deferred = finalization.extract_saved_deferred(trace=actual_trace.directory, inputs=inputs,
                    output=destination/'answer-grading',grader_factory=VariantLinkGrader,
                    backend_factory=factory,source_paths=list(episode.task.files),before_model_dispatch=quota_guard)
                state['deferred'],state['grade'] = deferred,deferred['grade']
                return {'task_id':expected_public['task_id'],'native_grade':state['grade']}
            def project(raw, captured_binding):
                if raw['task_id'] != captured_binding['task_id']:
                    raise ValueError('Automatic variant grade belongs to another task')
                grade = raw['native_grade']
                return Evaluation('variant-link-native',VERSION,trust='native_reference',
                    task_completed=grade['structured_claims_correct'],
                    evidence=[str(destination/'answer-grading/completed.json')],
                    limitations=[*grade.get('limitations',[]),
                        'Answer grading does not establish visits, exposure or whole-run effect authorization'])
            contract = AutomaticGrading(VERSION,bind,native_grade,project,phase='external',viewer_check=canonical_viewer_check)
            contract.validate()
            if not contract.callable_sources() <= episode.task.files.keys():
                raise ValueError('Prospective variant callbacks are absent from the source union')
            def before_policy():
                checked_files(episode.task.files);quota_guard()
            before_policy()
            with policy_session(before_dispatch=before_policy) as backend:
                trace,summary = runner(episode.task.make_env,backend,metadata,output=destination/'runs',
                    episode_task=episode.task,harness_profile=episode.profile,observation_pipeline='native',
                    terminal_response_instruction=TERMINAL_INSTRUCTION,automatic_grading=contract,**runner_options)
            state['policy_closed'] = True
            trace = Path(trace).resolve()
            if trace == destination/'runs' or not trace.is_relative_to(destination/'runs'):
                raise ValueError('Returned variant trace escaped its declared run directory')
            shared.save(destination/'policy-result.json',{'trace':str(trace),'summary':summary})
            checked_files(episode.task.files)  # No post-policy quota check suppresses native grading.
        state['runtime_closed'] = True
        saved_summary = json.loads((trace/'episode.json').read_bytes())
        if any(saved_summary.get(key) != summary.get(key) for key in
               ('stop_reason','error','execution_error','cleanup_errors','trace_complete')):
            raise ValueError('Returned policy outcome differs from its saved variant trace')
        summary = finalize_external(trace,contract)
        if summary.get('grading_error') or not summary.get('infrastructure_completed'):
            raise ValueError('External automatic variant grading failed: '+str(summary.get('grading_error')))
        finalization.publish_finalized_answer(state['deferred'],contract_id=contract.contract_id)
        projected = viewer_projection(trace=trace,grade=state['grade'])
        if type(projected) is not dict or projected.get('status') != 'verified':
            raise ValueError('Final automatic variant viewer projection is missing/unverified')
        result = {'schema':VERSION,'status':'graded_and_projected','trace':str(trace),
            'task_completed':state['grade']['structured_claims_correct'],'answer_grading':state['grade'],
            'viewer_projection':projected,'policy_summary':summary,'automatic_retries':0}
    except Exception as error:
        result = {'schema':VERSION,'status':'system_failure','trace':str(trace) if trace else None,
            'task_completed':None,'policy_summary':summary,'error_type':type(error).__name__,
            'reason':str(error),'policy_closed':state['policy_closed'],
            'runtime_closed':state['runtime_closed'],'automatic_retries':0}
    shared.save(destination/'execution-result.json',result)
    return result
