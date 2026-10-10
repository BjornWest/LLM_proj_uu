"""Exact shipping-audit runtime and once-only extraction after policy close."""
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from experiments.answer_grading import task_answer
from . import generation as shared, unified_generation as unified
from . import comparison_stock_execution as lifecycle
from .catalog_shipping_claim_grading import ShippingClaimGrader

VERSION = 'website-shipping-claim-execution-v1'


class ShippingClaimEpisode(lifecycle.ComparisonStockEpisode):
    def __init__(self, output, *, lazy_publication=True):
        from .runtime import Runtime
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        from .comparison_sku_task import episode_task
        self.output = Path(output).resolve()
        self.manifest = shared.load(self.output)
        if self.manifest.get('recipe') != 'website-shipping-claim-publication-v1':
            raise ValueError('Not a frozen shipping-claim recipe')
        read = lambda name: json.loads((self.output/name).read_text())
        episode, native = read('episode.json'), read('shipping-claim-task.private.json')
        binding = read('shipping-claim-binding.private.json')
        if native is None or binding != {'status': 'requires_public_quote_and_policy_adoption', 'world_repaired': False}:
            raise ValueError('Missing or changed native shipping-audit binding')
        if episode['task_id'] != native['task_id'] or episode['manual_task'] != {
                'user_message': native['user_message'], 'memories': native['memories']}:
            raise ValueError('Public episode/native shipping task binding changed')
        start = episode['start']
        self.runtime = Runtime(self.output/'pin', presentation=read('presentation.json'),
            surrounding=read('surrounding.private.json'), basket_plan=read('basket-plan.private.json'),
            checkout_domain=read('checkout-domain.private.json'),
            delivery_plan=read('delivery-plan.private.json') if (self.output/'delivery-plan.private.json').exists() else None,
            discovery_mode='tool' if start['kind'] == 'tool_discovery' else 'index',
            readable_origins=episode.get('readable_origins', False), lazy_publication=lazy_publication)
        try:
            if read('compositions.private.json') != self.runtime.compositions:
                raise ValueError('Runtime composition differs from sampled pages')
            self.public = public_projection(unified.bind_task(self.runtime, episode))
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins, helpers=False)
            self.site_discovery = None
            if start['kind'] == 'tool_discovery':
                from intent_browser.harness import with_site_discovery
                self.profile = with_site_discovery(self.profile)
                self.site_discovery = self.runtime.site_discovery.search
            from experiments.accepted_catalog_commerce.prepared_quote import prepare
            self.quote_context = self.runtime.prepared or prepare(self.runtime.world,
                plan=read('basket-plan.private.json'), admission_plan=
                read('delivery-plan.private.json') if (self.output/'delivery-plan.private.json').exists() else None)
            self.answer_grader = ShippingClaimGrader(self.runtime.world, native,
                read('shipping-claim-reference.private.json'), self.runtime.bindings,
                quote_context=self.quote_context, checkout_domain=read('checkout-domain.private.json'))
            files = {str(self.output/name): h for name, h in self.manifest['files'].items()}
            files.update({str(shared.ROOT/name): h for name, h in self.manifest['source_sha256'].items()})
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                attachments={name: str(self.output/name) for name in (
                    'shipping-claim-task.private.json', 'shipping-claim-reference.private.json',
                    'shipping-claim-binding.private.json', 'shipping-claim-inventory.private.json')})
            self.task.site_discovery_callback = self.site_discovery
        except BaseException:
            self.runtime.close()
            raise

    export_private_runtime = _bind(lifecycle.ComparisonStockEpisode.export_private_runtime, VERSION=VERSION)


def grader_from_records(*, world, task, reference, bindings, basket_plan, checkout_domain, delivery_plan=None):
    from experiments.accepted_catalog_commerce.prepared_quote import prepare
    return ShippingClaimGrader(world, task, reference, bindings, checkout_domain=checkout_domain,
        quote_context=prepare(world, plan=basket_plan, admission_plan=delivery_plan))


def run(output, run_directory, *, policy_session, metadata, runner_options,
        quota_guard=None, extraction_backend_factory=None, runner=None):
    """Bind the actual returned trace; only public answer/schema reach extraction."""
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    output, destination = Path(output).resolve(), Path(run_directory).resolve()
    returned = []
    def actual_runner(*args, episode_task, **kwargs):
        result = runner(*args, episode_task=episode_task,
            site_discovery=episode_task.site_discovery_callback, **kwargs)
        trace = Path(result[0]).resolve()
        if not trace.is_relative_to(destination/'runs'):
            raise ValueError('Returned shipping policy trace is outside this execution')
        returned.append(trace)
        return result
    def grade_shipping(**kwargs):
        if returned != [Path(kwargs['trace']).resolve()]:
            raise ValueError('Shipping grading requires the actual returned main trace')
        inputs = kwargs['inputs']
        inputs.update(task=output/'shipping-claim-task.private.json',
            reference=output/'shipping-claim-reference.private.json',
            basket_plan=output/'basket-plan.private.json',
            checkout_domain=output/'checkout-domain.private.json')
        inputs.pop('site_registry', None)
        inputs.pop('surrounding', None)
        if (output/'delivery-plan.private.json').exists():
            inputs['delivery_plan'] = output/'delivery-plan.private.json'
        kwargs['grader_factory'] = grader_from_records
        return task_answer.grade_saved_once(**kwargs)
    consumer = _bind(lifecycle.run, ComparisonStockEpisode=ShippingClaimEpisode,
        ComparisonStockGrader=ShippingClaimGrader, VERSION=VERSION,
        task_answer=SimpleNamespace(grade_saved_once=grade_shipping,
            SubscriptionTaskExtractor=task_answer.SubscriptionTaskExtractor))
    return consumer(output, destination, policy_session=policy_session, metadata=metadata,
        runner_options=runner_options, quota_guard=quota_guard,
        extraction_backend_factory=extraction_backend_factory, runner=actual_runner)
