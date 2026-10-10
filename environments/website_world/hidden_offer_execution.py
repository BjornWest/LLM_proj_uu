"""Hidden task runtime and task-neutral post-policy grading; no page changes."""
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from experiments.answer_grading import task_answer
from . import generation as shared, unified_generation as unified
from . import feature_offer_execution as feature
from . import comparison_stock_execution as lifecycle
from .hidden_offer_grading import HiddenOfferGrader
from . import catalog_clarification

VERSION = 'website-hidden-offer-execution-v1'


class HiddenOfferEpisode(lifecycle.ComparisonStockEpisode):
    def __init__(self, output, *, lazy_publication=True):
        from .runtime import Runtime
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        from .comparison_sku_task import episode_task
        self.output = Path(output).resolve()
        self.manifest = shared.load(self.output)
        if self.manifest.get('recipe') != 'website-hidden-offer-publication-v1':
            raise ValueError('Not a frozen hidden-offer recipe')
        read = lambda name: json.loads((self.output/name).read_text())
        episode, native = read('episode.json'), read('hidden-offer-task.private.json')
        reference = read('hidden-offer-reference.private.json')
        binding = read('hidden-offer-binding.private.json')
        expected = {'status': 'bound' if reference['clarification_affects_eligibility'] else
                    'unsupported_no_effectful_clarification', 'world_repaired': False, 'task_id': native['task_id']}
        if binding != expected:
            raise ValueError('Hidden clarification binding changed')
        if binding['status'] != 'bound':
            raise ValueError('Cannot launch a no-effect hidden clarification binding')
        self.clarification_callback = catalog_clarification.Responder(native)
        self.clarification_audit_id = self.clarification_callback.audit_id
        if read('hidden-reply-binding.private.json') != {
                'schema': catalog_clarification.VERSION, 'task_id': native['task_id'],
                'audit_id': self.clarification_audit_id, 'hidden_requirement': native['hidden_requirement']}:
            raise ValueError('Hidden reply contract binding changed')
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
            from intent_browser.harness import with_clarification
            self.profile = with_clarification(self.profile)
            self.answer_grader = HiddenOfferGrader(self.runtime.world, native,
                read('hidden-offer-reference.private.json'), self.runtime.bindings,
                surrounding=read('surrounding.private.json'))
            files = {str(self.output/name): h for name, h in self.manifest['files'].items()}
            files.update({str(shared.ROOT/name): h for name, h in self.manifest['source_sha256'].items()})
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                attachments={name: str(self.output/name) for name in (
                    'hidden-offer-task.private.json', 'hidden-offer-reference.private.json',
                    'hidden-offer-binding.private.json', 'hidden-reply-binding.private.json')})
            self.task.site_discovery_callback = self.site_discovery
            self.task.clarification_callback = self.clarification_callback
            self.task.clarification_audit_id = self.clarification_audit_id
        except BaseException:
            self.runtime.close()
            raise

    export_private_runtime = _bind(lifecycle.ComparisonStockEpisode.export_private_runtime, VERSION=VERSION)




def interaction_sources(trace):
    """Pin actual retained interaction artifacts, including referenced content files."""
    trace = Path(trace).resolve()
    names = {'steps.jsonl', 'natural-answer.json', 'policy-delivery.jsonl'}
    paths = [trace/name for name in names if (trace/name).exists()]
    for pattern in ('clarification-*.json', 'policy-content-*.json'):
        paths.extend(trace.glob(pattern))
    # Native evidence also checks references and their hashes/spans. Here all
    # retained callback/content files, including unmatched ones, are pinned.
    resolved = sorted({p.resolve() for p in paths})
    if any(not p.is_relative_to(trace) for p in resolved):
        raise ValueError('Hidden interaction source escapes its main trace')
    return resolved


def run(output, run_directory, *, policy_session, metadata, runner_options,
        quota_guard=None, extraction_backend_factory=None, runner=None):
    """Bind actual callbacks and the returned main trace before once-only grading."""
    if type(runner_options) is not dict or set(runner_options) & {
            'clarification_callback', 'clarification_audit_id'}:
        raise ValueError('Runner options cannot replace the hidden reply binding')
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    output, destination = Path(output).resolve(), Path(run_directory).resolve()
    returned = []
    def actual_runner(*args, episode_task, **kwargs):
        result = runner(*args, episode_task=episode_task,
            clarification_callback=episode_task.clarification_callback,
            clarification_audit_id=episode_task.clarification_audit_id, **kwargs)
        path = Path(result[0]).resolve()
        if not path.is_relative_to(destination/'runs'):
            raise ValueError('Returned hidden policy trace is outside this execution')
        returned.append(path)
        return result
    def grade_hidden(**kwargs):
        trace = Path(kwargs['trace']).resolve()
        if returned != [trace]:
            raise ValueError('Hidden grading requires the actual returned main trace')
        kwargs['inputs'].update(task=output/'hidden-offer-task.private.json',
                                reference=output/'hidden-offer-reference.private.json')
        kwargs['source_paths'] = [*kwargs['source_paths'], *interaction_sources(trace)]
        def grader_factory(**records):
            return HiddenOfferGrader(**records, interaction_trace=trace)
        kwargs['grader_factory'] = grader_factory
        return task_answer.grade_saved_once(**kwargs)
    consumer = _bind(feature.run, FeatureOfferEpisode=HiddenOfferEpisode,
        FeatureOfferGrader=HiddenOfferGrader, VERSION=VERSION,
        task_answer=SimpleNamespace(grade_saved_once=grade_hidden,
            SubscriptionTaskExtractor=task_answer.SubscriptionTaskExtractor))
    return consumer(output, destination, policy_session=policy_session, metadata=metadata,
        runner_options=runner_options, quota_guard=quota_guard,
        extraction_backend_factory=extraction_backend_factory, runner=actual_runner)
