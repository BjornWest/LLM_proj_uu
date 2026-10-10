"""Native priority tasks with actual runtime bindings and post-policy grading."""
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from experiments.answer_grading import task_answer
from . import generation as shared, unified_generation as unified
from . import feature_offer_execution as feature, comparison_stock_execution as lifecycle
from .catalog_priority_grading import CatalogPriorityGrader

VERSION = 'website-catalog-priority-execution-v1'


class CatalogPriorityEpisode(lifecycle.ComparisonStockEpisode):
    def __init__(self, output, *, lazy_publication=True):
        from .runtime import Runtime
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        from .comparison_sku_task import episode_task
        self.output = Path(output).resolve()
        self.manifest = shared.load(self.output)
        if self.manifest.get('recipe') != 'website-catalog-priority-publication-v1':
            raise ValueError('Not a frozen catalog-priority recipe')
        read = lambda name: json.loads((self.output/name).read_text())
        episode, native = read('episode.json'), read('catalog-priority-task.private.json')
        if read('catalog-priority-binding.private.json') != {'status': 'bound', 'world_repaired': False}:
            raise ValueError('Priority binding changed')
        if episode['task_id'] != native['task_id'] or episode['manual_task'] != {
                'user_message': native['user_message'], 'memories': native['memories']}:
            raise ValueError('Public episode/native priority task binding changed')
        start = episode['start']
        if start['kind'] == 'comparison_home' and start != {
                'kind': 'comparison_home', 'comparison_site_id': native.get('comparison_site_id')}:
            raise ValueError('Comparison-home priority scope changed')
        self.runtime = Runtime(self.output/'pin', presentation=read('presentation.json'),
            surrounding=read('surrounding.private.json'), basket_plan=read('basket-plan.private.json'),
            checkout_domain=read('checkout-domain.private.json'),
            delivery_plan=read('delivery-plan.private.json') if (self.output/'delivery-plan.private.json').exists() else None,
            discovery_mode='tool' if start['kind'] == 'tool_discovery' else 'index',
            readable_origins=episode.get('readable_origins', False), lazy_publication=lazy_publication)
        try:
            if read('compositions.private.json') != self.runtime.compositions:
                raise ValueError('Runtime composition differs from sampled pages')
            if start['kind'] == 'comparison_home':
                site = next(s for s in self.runtime.site_registry if s['site_id'] == start['comparison_site_id'])
                public = unified.bind_task(self.runtime, {**episode, 'start': {'kind': 'directory'}})
                public['start_url'] = site['origin']+'/'
            else:
                public = unified.bind_task(self.runtime, episode)
            self.public = public_projection(public)
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins, helpers=False)
            self.site_discovery = None
            if start['kind'] == 'tool_discovery':
                from intent_browser.harness import with_site_discovery
                self.profile = with_site_discovery(self.profile)
                self.site_discovery = self.runtime.site_discovery.search
            self.answer_grader = CatalogPriorityGrader(self.runtime.world, native,
                read('catalog-priority-reference.private.json'), self.runtime.bindings,
                surrounding=read('surrounding.private.json'))
            files = {str(self.output/name): h for name, h in self.manifest['files'].items()}
            files.update({str(shared.ROOT/name): h for name, h in self.manifest['source_sha256'].items()})
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                attachments={name: str(self.output/name) for name in (
                    'catalog-priority-task.private.json', 'catalog-priority-reference.private.json',
                    'catalog-priority-binding.private.json', 'priority-field-inventory.private.json')})
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
            raise ValueError('Returned priority policy trace is outside this execution')
        returned.append(trace)
        return result
    def grade_priority(**kwargs):
        if returned != [Path(kwargs['trace']).resolve()]:
            raise ValueError('Priority grading requires the actual returned main trace')
        kwargs['inputs'].update(task=output/'catalog-priority-task.private.json',
            reference=output/'catalog-priority-reference.private.json')
        kwargs['inputs'].pop('site_registry', None)
        kwargs['grader_factory'] = CatalogPriorityGrader
        return task_answer.grade_saved_once(**kwargs)
    consumer = _bind(feature.run, FeatureOfferEpisode=CatalogPriorityEpisode,
        FeatureOfferGrader=CatalogPriorityGrader, VERSION=VERSION,
        task_answer=SimpleNamespace(grade_saved_once=grade_priority,
            SubscriptionTaskExtractor=task_answer.SubscriptionTaskExtractor))
    return consumer(output, destination, policy_session=policy_session, metadata=metadata,
        runner_options=runner_options, quota_guard=quota_guard,
        extraction_backend_factory=extraction_backend_factory, runner=actual_runner)
