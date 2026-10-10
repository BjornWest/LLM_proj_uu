"""Delivered quote task runtime and task-neutral post-policy grading; no page changes."""
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from experiments.answer_grading import task_answer
from . import generation as shared, unified_generation as unified
from . import comparison_stock_execution as lifecycle
from .quote_offer_grading import QuoteOfferGrader

VERSION = 'website-quote-offer-execution-v1'


class QuoteOfferEpisode(lifecycle.ComparisonStockEpisode):
    def __init__(self, output, *, lazy_publication=True):
        from .runtime import Runtime
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        from .comparison_sku_task import episode_task
        self.output = Path(output).resolve()
        self.manifest = shared.load(self.output)
        if self.manifest.get('recipe') != 'website-quote-offer-publication-v1':
            raise ValueError('Not a frozen quote-offer recipe')
        read = lambda name: json.loads((self.output/name).read_text())
        episode, native = read('episode.json'), read('quote-offer-task.private.json')
        if episode['task_id'] != native['task_id'] or episode['manual_task'] != {
                'user_message': native['user_message'], 'memories': native['memories']}:
            raise ValueError('Public episode/native task binding changed')
        self.runtime = Runtime(self.output/'pin', presentation=read('presentation.json'),
            surrounding=read('surrounding.private.json'), basket_plan=read('basket-plan.private.json'),
            checkout_domain=read('checkout-domain.private.json'),
            delivery_plan=read('delivery-plan.private.json') if (self.output/'delivery-plan.private.json').exists() else None,
            discovery_mode='tool' if episode['start']['kind'] == 'tool_discovery' else 'index',
            readable_origins=episode.get('readable_origins', False), lazy_publication=lazy_publication)
        try:
            if read('compositions.private.json') != self.runtime.compositions:
                raise ValueError('Runtime composition differs from sampled pages')
            start = episode['start']
            if start['kind'] == 'comparison_home':
                if start != {'kind': 'comparison_home', 'comparison_site_id': native.get('comparison_site_id')}:
                    raise ValueError('Comparison-home task scope changed')
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
            from experiments.accepted_catalog_commerce.prepared_quote import prepare
            self.quote_context = self.runtime.prepared or prepare(self.runtime.world,
                plan=read('basket-plan.private.json'), admission_plan=
                read('delivery-plan.private.json') if (self.output/'delivery-plan.private.json').exists() else None)
            self.answer_grader = QuoteOfferGrader(self.runtime.world, native,
                read('quote-offer-reference.private.json'), self.runtime.bindings,
                quote_context=self.quote_context, surrounding=read('surrounding.private.json'))
            files = {str(self.output/name): h for name, h in self.manifest['files'].items()}
            files.update({str(shared.ROOT/name): h for name, h in self.manifest['source_sha256'].items()})
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                attachments={name: str(self.output/name) for name in (
                    'quote-offer-task.private.json', 'quote-offer-reference.private.json')})
            self.task.site_discovery_callback = self.site_discovery
        except BaseException:
            self.runtime.close()
            raise

    export_private_runtime = _bind(lifecycle.ComparisonStockEpisode.export_private_runtime, VERSION=VERSION)


def grader_from_records(*, world, task, reference, bindings, surrounding, basket_plan, delivery_plan=None):
    """Rebuild the typed central context from verified frozen inputs, never JSON guesses."""
    from experiments.accepted_catalog_commerce.prepared_quote import prepare
    return QuoteOfferGrader(world, task, reference, bindings, surrounding=surrounding,
        quote_context=prepare(world, plan=basket_plan, admission_plan=delivery_plan))


def run(output, run_directory, *, policy_session, metadata, runner_options,
        quota_guard=None, extraction_backend_factory=None, runner=None):
    """Reuse the accepted close/once/quota lifecycle with private task bindings.

    Quote-only inputs and formatter instructions are supplied to the native
    quote grader. Neither the exact-SKU recipe nor lifecycle module is edited.
    """
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    output = Path(output).resolve()
    def grade_quote(**kwargs):
        kwargs['inputs'] = {**kwargs['inputs'], 'task': output/'quote-offer-task.private.json',
                            'reference': output/'quote-offer-reference.private.json'}
        kwargs['inputs'].pop('site_registry', None)
        kwargs['inputs']['basket_plan'] = output/'basket-plan.private.json'
        if (output/'delivery-plan.private.json').exists():
            kwargs['inputs']['delivery_plan'] = output/'delivery-plan.private.json'
        kwargs['grader_factory'] = grader_from_records
        return task_answer.grade_saved_once(**kwargs)
    def run_with_discovery(*args, episode_task, **kwargs):
        return runner(*args, episode_task=episode_task,
                      site_discovery=episode_task.site_discovery_callback, **kwargs)
    consumer = _bind(lifecycle.run, ComparisonStockEpisode=QuoteOfferEpisode,
        ComparisonStockGrader=QuoteOfferGrader, VERSION=VERSION,
        task_answer=SimpleNamespace(grade_saved_once=grade_quote,
                                  SubscriptionTaskExtractor=task_answer.SubscriptionTaskExtractor))
    return consumer(output, run_directory, policy_session=policy_session, metadata=metadata,
        runner_options=runner_options, quota_guard=quota_guard,
        extraction_backend_factory=extraction_backend_factory, runner=run_with_discovery)
