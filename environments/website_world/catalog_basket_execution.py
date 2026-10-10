"""Mixed-basket episodes and actual-trace once-only combined-payable grading."""
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from experiments.answer_grading import task_answer
from . import generation as shared, unified_generation as unified
from . import feature_offer_execution as feature, comparison_stock_execution as lifecycle
from .catalog_basket_answer_grading import CatalogBasketAnswerGrader

VERSION = 'website-catalog-basket-execution-v1'


class CatalogBasketEpisode(lifecycle.ComparisonStockEpisode):
    def __init__(self, output, *, lazy_publication=True):
        from .runtime import Runtime
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        from .comparison_sku_task import episode_task
        self.output = Path(output).resolve()
        self.manifest = shared.load(self.output)
        if self.manifest.get('recipe') != 'website-catalog-basket-publication-v1':
            raise ValueError('Not a frozen catalog-basket recipe')
        read = lambda name: json.loads((self.output/name).read_text())
        episode, native = read('episode.json'), read('catalog-basket-task.private.json')
        reference = read('catalog-basket-reference.private.json')
        # A feasible incumbent under an incomplete search is not a graded optimum.
        if (read('catalog-basket-binding.private.json') != {
                'status': 'bound_exact_reference', 'world_repaired': False}
                or reference['result']['complete'] is not True):
            raise ValueError('An inconclusive basket reference cannot launch a graded episode')
        if episode['task_id'] != native['task_id'] or episode['manual_task'] != {
                'user_message': native['user_message'], 'memories': native['memories']}:
            raise ValueError('Public episode/native basket task binding changed')
        plan, domain = read('basket-plan.private.json'), read('checkout-domain.private.json')
        admission = read('delivery-plan.private.json') if (self.output/'delivery-plan.private.json').exists() else None
        self.runtime = Runtime(self.output/'pin', presentation=read('presentation.json'),
            surrounding=read('surrounding.private.json'), basket_plan=plan,
            checkout_domain=domain, delivery_plan=admission,
            discovery_mode='tool' if episode['start']['kind'] == 'tool_discovery' else 'index',
            readable_origins=episode.get('readable_origins', False), lazy_publication=lazy_publication)
        try:
            if read('compositions.private.json') != self.runtime.compositions:
                raise ValueError('Runtime composition differs from sampled pages')
            self.public = public_projection(unified.bind_task(self.runtime, episode))
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins, helpers=False)
            self.site_discovery = None
            if episode['start']['kind'] == 'tool_discovery':
                from intent_browser.harness import with_site_discovery
                self.profile = with_site_discovery(self.profile)
                self.site_discovery = self.runtime.site_discovery.search
            self.answer_grader = CatalogBasketAnswerGrader(self.runtime.world, native,
                reference, self.runtime.bindings, plan=plan, checkout_domain=domain,
                admission_plan=admission, surrounding=read('surrounding.private.json'))
            files = {str(self.output/name): h for name, h in self.manifest['files'].items()}
            files.update({str(shared.ROOT/name): h for name, h in self.manifest['source_sha256'].items()})
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                attachments={name: str(self.output/name) for name in (
                    'catalog-basket-task.private.json', 'catalog-basket-reference.private.json',
                    'catalog-basket-binding.private.json', 'basket-field-inventory.private.json')})
            self.task.site_discovery_callback = self.site_discovery
        except BaseException:
            self.runtime.close()
            raise

    export_private_runtime = _bind(lifecycle.ComparisonStockEpisode.export_private_runtime, VERSION=VERSION)


def run(output, run_directory, *, policy_session, metadata, runner_options,
        quota_guard=None, extraction_backend_factory=None, runner=None):
    """Pin full cart/quote inputs; format only the actual final answer after close."""
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    output, destination = Path(output).resolve(), Path(run_directory).resolve()
    returned = []
    def actual_runner(*args, **kwargs):
        result = runner(*args, **kwargs)
        trace = Path(result[0]).resolve()
        if not trace.is_relative_to(destination/'runs'):
            raise ValueError('Returned basket policy trace is outside this execution')
        returned.append(trace)
        return result
    def grade_basket(**kwargs):
        if returned != [Path(kwargs['trace']).resolve()]:
            raise ValueError('Basket grading requires the actual returned main trace')
        kwargs['inputs'].update(task=output/'catalog-basket-task.private.json',
            reference=output/'catalog-basket-reference.private.json',
            plan=output/'basket-plan.private.json', checkout_domain=output/'checkout-domain.private.json')
        if (output/'delivery-plan.private.json').exists():
            kwargs['inputs']['admission_plan'] = output/'delivery-plan.private.json'
        kwargs['inputs'].pop('site_registry', None)
        kwargs['grader_factory'] = CatalogBasketAnswerGrader
        return task_answer.grade_saved_once(**kwargs)
    consumer = _bind(feature.run, FeatureOfferEpisode=CatalogBasketEpisode,
        FeatureOfferGrader=CatalogBasketAnswerGrader, VERSION=VERSION,
        task_answer=SimpleNamespace(grade_saved_once=grade_basket,
            SubscriptionTaskExtractor=task_answer.SubscriptionTaskExtractor))
    return consumer(output, destination, policy_session=policy_session, metadata=metadata,
        runner_options=runner_options, quota_guard=quota_guard,
        extraction_backend_factory=extraction_backend_factory, runner=actual_runner)
