"""Opt-in exact-SKU episode and one task-specific extraction after policy close."""
from hashlib import sha256
import json
from pathlib import Path

from . import generation as shared, comparison_sku_task
from .comparison_stock_grading import ComparisonStockGrader
from .generation_configs import execution_options, provenance
from experiments.answer_grading import task_answer
from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
from intent_browser.connected_world_task import checked_files, TERMINAL_INSTRUCTION
from .generation_configs import observation_runner_options

VERSION = 'website-comparison-stock-execution-v1'


class ComparisonStockEpisode:
    def __init__(self, output, *, lazy_publication=True):
        from .runtime import Runtime
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        self.output = Path(output).resolve()
        self.manifest = shared.load(self.output)
        read = lambda name: json.loads((self.output/name).read_text())
        if self.manifest.get('recipe') != 'website-comparison-stock-generation-v1':
            raise ValueError('Not a frozen comparison-stock recipe')
        if read('comparison-stock-binding.private.json')['status'] != 'bound':
            raise ValueError('An empty, ambiguous or unpublished target cannot launch')
        episode = read('episode.json')
        native = read('comparison-stock-task.private.json')
        if episode['start'] != {'kind': 'comparison_home', 'comparison_site_id': native['comparison_site_id']}:
            raise ValueError('Comparison-home start changed')
        self.runtime = Runtime(self.output/'pin', presentation=read('presentation.json'),
            surrounding=read('surrounding.private.json'), basket_plan=read('basket-plan.private.json'),
            checkout_domain=read('checkout-domain.private.json'),
            delivery_plan=read('delivery-plan.private.json') if (self.output/'delivery-plan.private.json').exists() else None,
            readable_origins=episode.get('readable_origins', False), lazy_publication=lazy_publication)
        try:
            if read('compositions.private.json') != self.runtime.compositions:
                raise ValueError('Runtime composition differs from sampled pages')
            self.public = public_projection(comparison_sku_task.bind_public(self.runtime, native))
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins, helpers=False)
            self.site_discovery = None
            self.answer_grader = ComparisonStockGrader(self.runtime.world, native,
                read('comparison-stock-reference.private.json'), self.runtime.bindings,
                surrounding=read('surrounding.private.json'), site_registry=self.runtime.site_registry)
            files = {str(self.output/name): h for name, h in self.manifest['files'].items()}
            files.update({str(shared.ROOT/name): h for name, h in self.manifest['source_sha256'].items()})
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            self.task = comparison_sku_task.episode_task(self.runtime, self.public, self.profile,
                files=files, attachments={name: str(self.output/name) for name in (
                    'comparison-stock-task.private.json', 'comparison-stock-reference.private.json')})
        except BaseException:
            self.runtime.close()
            raise

    def export_private_runtime(self, output):
        output = Path(output).resolve()
        output.mkdir(parents=True, exist_ok=False)
        for name, value in (('runtime.private.json', self.runtime.manifest),
                            ('bindings.private.json', self.runtime.bindings),
                            ('site-registry.private.json', self.runtime.site_registry),
                            ('task.public.json', self.public),
                            ('answer-contract.private.json', self.answer_grader.contract)):
            shared.save(output/name, value)
        manifest = {'schema': VERSION, 'world_id': self.runtime.world['world_id'],
            'generation_manifest_sha256': sha256((self.output/'manifest.json').read_bytes()).hexdigest(),
            'files': {p.name: sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()},
            'model_runs': 0, 'purchases': 0}
        shared.save(output/'manifest.json', manifest)
        return manifest

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.runtime.close()


def run(output, run_directory, *, policy_session, metadata, runner_options,
        quota_guard=None, extraction_backend_factory=None, runner=None):
    """One authorized episode; policy_session must apply before_dispatch per call.

    The caller owns subscription-only transport and finite-run authorization.
    Closing the policy context releases its lease before extraction can open.
    No retries or fallback transport are introduced by this consumer.
    """
    runner_options = observation_runner_options(runner_options)
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    if quota_guard is not None and not callable(quota_guard):
        raise ValueError('A subscription dispatch guard is required')
    if type(runner_options) is not dict or any(type(runner_options.get(k)) is not int
            or runner_options[k] <= 0 for k in ('max_steps', 'max_input_tokens')):
        raise ValueError('Declare finite positive request and context limits')
    if set(runner_options) & {'env_factory', 'backend', 'metadata', 'output',
                             'episode_task', 'harness_profile', 'site_discovery'}:
        raise ValueError('Runner options cannot replace episode bindings')
    output, destination = Path(output).resolve(), Path(run_directory).resolve()
    manifest = shared.load(output)
    record = json.loads((output/'execution.private.json').read_text())
    options = execution_options({'validation': record['validation'],
        'answer_grading': record.get('answer_grading'), **record.get('runtime_options', {})})
    grading = options['answer_grading']
    if grading['mode'] == 'off' and extraction_backend_factory is not None:
        raise ValueError('Extraction backend configured with grading disabled')
    destination.mkdir(parents=True, exist_ok=False)
    if quota_guard is None:
        quota_guard = SubscriptionQuotaGuard(destination/'subscription-quota', remaining_floor=1)
    shared.save(destination/'execution-plan.private.json', {'schema': VERSION,
        'generation': provenance(output), 'execution': options, 'runner_options': runner_options,
        'source_sha256': manifest['source_sha256'], 'automatic_grading_retries': 0,
        'extraction_requests_max': int(grading['mode'] != 'off')})
    with ComparisonStockEpisode(output, lazy_publication=options['lazy_publication']) as episode:
        episode.export_private_runtime(destination/'runtime-binding')
        checked_files(episode.task.files)
        quota_guard()
        with policy_session(before_dispatch=quota_guard) as backend:
            trace, summary = runner(episode.task.make_env, backend, metadata,
                output=destination/'runs', episode_task=episode.task, harness_profile=episode.profile,
                terminal_response_instruction=TERMINAL_INSTRUCTION,
                **runner_options)
        shared.save(destination/'policy-result.json', {'trace': str(trace), 'summary': summary})
        checked_files(episode.task.files)
        stage = {'mode': grading['mode'], 'status': 'disabled', 'task_completed': None}
        if grading['mode'] != 'off':
            try:
                if summary.get('error') or summary.get('cleanup_errors'):
                    stage.update(status='skipped', reason='Policy execution or cleanup failed')
                else:
                    factory = extraction_backend_factory or task_answer.SubscriptionTaskExtractor(
                        quota_guard=quota_guard, model=grading['model'],
                        reasoning_effort=grading['reasoning_effort']).backend
                    grade = task_answer.grade_saved_once(trace=trace,
                        inputs={'world': output/'pin/world.private.json',
                                'task': output/'comparison-stock-task.private.json',
                                'reference': output/'comparison-stock-reference.private.json',
                                'surrounding': output/'surrounding.private.json',
                                'bindings': destination/'runtime-binding/bindings.private.json',
                                'site_registry': destination/'runtime-binding/site-registry.private.json'},
                        output=destination/'answer-grading', grader_factory=ComparisonStockGrader,
                        backend_factory=factory, source_paths=list(episode.task.files),
                        before_model_dispatch=quota_guard)
                    stage.update(status='graded' if grade is not None else 'skipped',
                        task_completed=grade['structured_claims_correct'] if grade is not None else None)
            except Exception as error:
                stage.update(status='failed', error_type=type(error).__name__,
                             reason=str(error), automatic_retries=0)
        result = {'schema': VERSION, 'trace': str(trace),
                  'policy_summary': summary, 'answer_grading': stage}
        shared.save(destination/'execution-result.json', result)
        return result
