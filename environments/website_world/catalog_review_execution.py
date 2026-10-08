"""Review-summary runtime and source-bound once-only post-policy grading."""
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from experiments.answer_grading import task_answer
from . import generation as shared, unified_generation as unified
from . import feature_offer_execution as feature, comparison_stock_execution as lifecycle
from .catalog_review_grading import ReviewSummaryGrader

VERSION = 'website-catalog-review-execution-v1'


class PublishedReviewSummaryGrader(ReviewSummaryGrader):
    """Project native derivations into the common trace-sidecar list shape."""
    def grade(self, claims, answer):
        result = super().grade(claims, answer)
        return {**result, 'derivations': [result['derivations']]}


class CatalogReviewEpisode(lifecycle.ComparisonStockEpisode):
    def __init__(self, output, *, lazy_publication=True):
        from .runtime import Runtime
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        from .comparison_sku_task import episode_task
        self.output = Path(output).resolve()
        self.manifest = shared.load(self.output)
        if self.manifest.get('recipe') != 'website-catalog-review-publication-v1':
            raise ValueError('Not a frozen catalog-review recipe')
        read = lambda name: json.loads((self.output/name).read_text())
        binding = read('catalog-review-binding.private.json')
        if binding.get('status') != 'bound':
            raise ValueError('A missing manufactured subject or review publication cannot launch')
        episode, native = read('episode.json'), read('catalog-review-task.private.json')
        # Public wording is editable presentation; identity and memories retain
        # the binding to the unchanged structured task/reference.
        public_task = episode['manual_task']
        if (episode['task_id'] != native['task_id']
                or public_task.get('memories') != native['memories']
                or type(public_task.get('user_message')) is not str
                or not public_task['user_message'].strip()):
            raise ValueError('Public episode/native review task binding changed')
        self.runtime = Runtime(self.output/'pin', presentation=read('presentation.json'),
            surrounding=read('surrounding.private.json'), basket_plan=read('basket-plan.private.json'),
            checkout_domain=read('checkout-domain.private.json'),
            delivery_plan=read('delivery-plan.private.json') if (self.output/'delivery-plan.private.json').exists() else None,
            discovery_mode='tool' if episode['start']['kind'] == 'tool_discovery' else 'index',
            readable_origins=episode.get('readable_origins', False), lazy_publication=lazy_publication)
        try:
            if read('compositions.private.json') != self.runtime.compositions:
                raise ValueError('Runtime composition differs from sampled pages')
            covered = [s['site_id'] for s in read('surrounding.private.json')['sites']
                if s['kind'] == 'product_reviews' and native['subject']['product_id'] in s['product_ids']]
            if binding != {'status': 'bound', 'publication_ids': covered, 'world_repaired': False}:
                raise ValueError('Review publication coverage binding changed')
            self.public = public_projection(unified.bind_task(self.runtime, episode))
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins, helpers=False)
            self.site_discovery = None
            if episode['start']['kind'] == 'tool_discovery':
                from intent_browser.harness import with_site_discovery
                self.profile = with_site_discovery(self.profile)
                self.site_discovery = self.runtime.site_discovery.search
            self.answer_grader = PublishedReviewSummaryGrader(self.runtime.world, native,
                read('catalog-review-reference.private.json'), self.runtime.site_registry,
                surrounding=read('surrounding.private.json'))
            files = {str(self.output/name): h for name, h in self.manifest['files'].items()}
            files.update({str(shared.ROOT/name): h for name, h in self.manifest['source_sha256'].items()})
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                attachments={name: str(self.output/name) for name in (
                    'catalog-review-task.private.json', 'catalog-review-reference.private.json',
                    'catalog-review-binding.private.json', 'review-topic-inventory.private.json')})
            self.task.site_discovery_callback = self.site_discovery
        except BaseException:
            self.runtime.close()
            raise

    export_private_runtime = _bind(lifecycle.ComparisonStockEpisode.export_private_runtime, VERSION=VERSION)


def run(output, run_directory, *, policy_session, metadata, runner_options,
        quota_guard=None, extraction_backend_factory=None, runner=None):
    """Use the actual returned main trace and runtime registry for native grading."""
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    output, destination = Path(output).resolve(), Path(run_directory).resolve()
    returned = []
    def actual_runner(*args, **kwargs):
        result = runner(*args, **kwargs)
        trace = Path(result[0]).resolve()
        if not trace.is_relative_to(destination/'runs'):
            raise ValueError('Returned review policy trace is outside this execution')
        returned.append(trace)
        return result
    def grade_review(**kwargs):
        if returned != [Path(kwargs['trace']).resolve()]:
            raise ValueError('Review grading requires the actual returned main trace')
        kwargs['inputs'].update(task=output/'catalog-review-task.private.json',
            reference=output/'catalog-review-reference.private.json',
            site_registry=destination/'runtime-binding/site-registry.private.json')
        kwargs['inputs'].pop('bindings', None)
        kwargs['grader_factory'] = PublishedReviewSummaryGrader
        return task_answer.grade_saved_once(**kwargs)
    consumer = _bind(feature.run, FeatureOfferEpisode=CatalogReviewEpisode,
        FeatureOfferGrader=ReviewSummaryGrader, VERSION=VERSION,
        task_answer=SimpleNamespace(grade_saved_once=grade_review,
            SubscriptionTaskExtractor=task_answer.SubscriptionTaskExtractor))
    return consumer(output, destination, policy_session=policy_session, metadata=metadata,
        runner_options=runner_options, quota_guard=quota_guard,
        extraction_backend_factory=extraction_backend_factory, runner=actual_runner)
