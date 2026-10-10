"""Native carrier reviews with actual runtime bindings and post-policy grading."""
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from experiments.answer_grading import task_answer
from . import generation as shared, unified_generation as unified
from . import feature_offer_execution as feature, comparison_stock_execution as lifecycle
from .carrier_review_grading import CarrierReviewGrader
from .carrier_review_runtime import CarrierReviewRuntime as Runtime

VERSION = 'website-carrier-review-execution-v1'


class CarrierReviewEpisode(lifecycle.ComparisonStockEpisode):
    def __init__(self, output, *, lazy_publication=True):
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        from .comparison_sku_task import episode_task
        self.output = Path(output).resolve()
        self.manifest = shared.load(self.output)
        if self.manifest.get('recipe') != 'website-carrier-review-publication-v1':
            raise ValueError('Not a frozen carrier-review recipe')
        read = lambda name: json.loads((self.output/name).read_text())
        episode, native = read('episode.json'), read('carrier-review-task.private.json')
        if read('carrier-review-binding.private.json') != {'status': 'requires_carrier_publication_adoption', 'world_repaired': False}:
            raise ValueError('Carrier review binding changed')
        if episode['task_id'] != native['task_id'] or episode['manual_task'] != {
                'user_message': native['user_message'], 'memories': native['memories']}:
            raise ValueError('Public episode/native carrier review task binding changed')
        start = episode['start']
        self.runtime = Runtime(self.output/'pin', publication=read('carrier-publication.private.json'), presentation=read('presentation.json'),
            surrounding=read('surrounding.private.json'), basket_plan=read('basket-plan.private.json'),
            checkout_domain=read('checkout-domain.private.json'),
            delivery_plan=read('delivery-plan.private.json') if (self.output/'delivery-plan.private.json').exists() else None,
            discovery_mode='tool' if start['kind'] == 'tool_discovery' else 'index',
            readable_origins=episode.get('readable_origins', False), lazy_publication=lazy_publication)
        try:
            if read('compositions.private.json') != self.runtime.compositions:
                raise ValueError('Runtime composition differs from sampled pages')
            public = unified.bind_task(self.runtime, episode)
            self.public = public_projection(public)
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins, helpers=False)
            self.site_discovery = None
            if start['kind'] == 'tool_discovery':
                from intent_browser.harness import with_site_discovery
                self.profile = with_site_discovery(self.profile)
                self.site_discovery = self.runtime.site_discovery.search
            self.answer_grader = CarrierReviewGrader(self.runtime.world, native,
                read('carrier-review-reference.private.json'), self.runtime.site_registry, publication=read('carrier-publication.private.json'))
            files = {str(self.output/name): h for name, h in self.manifest['files'].items()}
            files.update({str(shared.ROOT/name): h for name, h in self.manifest['source_sha256'].items()})
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                attachments={name: str(self.output/name) for name in (
                    'carrier-review-task.private.json', 'carrier-review-reference.private.json',
                    'carrier-review-binding.private.json', 'carrier-review-inventory.private.json', 'carrier-publication.private.json')})
            self.task.site_discovery_callback = self.site_discovery
        except BaseException:
            self.runtime.close()
            raise

    export_private_runtime = _bind(lifecycle.ComparisonStockEpisode.export_private_runtime, VERSION=VERSION)


def run(output, run_directory, *, policy_session, metadata, runner_options,
        quota_guard=None, extraction_backend_factory=None, runner=None):
    """Extract stated claims once after policy close against the actual returned trace."""
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    output, destination = Path(output).resolve(), Path(run_directory).resolve()
    returned = []
    def actual_runner(*args, **kwargs):
        result = runner(*args, **kwargs)
        trace = Path(result[0]).resolve()
        if not trace.is_relative_to(destination/'runs'):
            raise ValueError('Returned carrier review policy trace is outside this execution')
        returned.append(trace)
        return result
    def grade_carrier(**kwargs):
        if returned != [Path(kwargs['trace']).resolve()]:
            raise ValueError('Carrier review grading requires the actual returned main trace')
        kwargs['inputs'].update(task=output/'carrier-review-task.private.json',
            reference=output/'carrier-review-reference.private.json',
            publication=output/'carrier-publication.private.json',
            site_registry=destination/'runtime-binding/site-registry.private.json')
        kwargs['inputs'].pop('bindings', None)
        kwargs['inputs'].pop('surrounding', None)
        kwargs['grader_factory'] = CarrierReviewGrader
        return task_answer.grade_saved_once(**kwargs)
    consumer = _bind(feature.run, FeatureOfferEpisode=CarrierReviewEpisode,
        FeatureOfferGrader=CarrierReviewGrader, VERSION=VERSION,
        task_answer=SimpleNamespace(grade_saved_once=grade_carrier,
            SubscriptionTaskExtractor=task_answer.SubscriptionTaskExtractor))
    return consumer(output, destination, policy_session=policy_session, metadata=metadata,
        runner_options=runner_options, quota_guard=quota_guard,
        extraction_backend_factory=extraction_backend_factory, runner=actual_runner)
