"""Exact link episodes with a pinned browser capability and once-only grading."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
from . import generation as shared, variant_link_publication as publication
from .variant_link_answer_grading import VariantLinkGrader

VERSION = 'website-variant-link-execution-v1'


class VariantLinkEpisode:
    def __init__(self, output):
        from .runtime import Runtime
        from .comparison_sku_task import episode_task
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        self.site_discovery = None
        self.output = Path(output).resolve()
        self.manifest = shared.load(self.output)
        if self.manifest.get('recipe') != publication.VERSION:
            raise ValueError('Not a frozen variant-link recipe')
        def read(name):
            payload = (self.output / name).read_bytes()
            if self.manifest['files'].get(name) != sha256(payload).hexdigest():
                raise ValueError('Variant-link input differs from its frozen manifest: ' + name)
            return json.loads(payload)
        if read('execution.private.json')['answer_grading']['mode'] != 'subscription-post-run':
            raise ValueError('Automatic variant-link grading must be attached before dispatch')
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
        manifest = {"files": {str(path.relative_to(output)): sha256(path.read_bytes()).hexdigest()
                               for path in output.rglob("*") if path.is_file()}}
        shared.save(output / "manifest.json", manifest)
        return manifest

    def __enter__(self): return self
    def __exit__(self, *args): self.runtime.close()

def inputs_factory(output, runtime_directory):
    """Read exact task inputs plus authenticated actual Runtime exports."""
    return {'world': output / 'pin/world.private.json',
            'task': output / 'variant-link-task.private.json',
            'reference': output / 'variant-link-reference.private.json',
            'catalog': runtime_directory / 'catalog.private.json',
            'bindings': runtime_directory / 'bindings.private.json',
            'navigation_capability': runtime_directory / 'navigation-capability.private.json'}


def grader_factory(*, world, task, reference, catalog, bindings, navigation_capability):
    return VariantLinkGrader(world, task, reference, catalog, bindings, navigation_capability)


def run(output, run_directory, *, policy_session, metadata, runner_options,
        viewer_projection, quota_guard=None, extraction_backend_factory=None, runner=None):
    """Reuse the reviewed external lifecycle; actual recipient acceptance gates setup.

    Read correctness never implies browser visits or complete effect authority.
    No source-only capability can release a task through VariantLinkEpisode.
    """
    from . import saved_answer_lifecycle as lifecycle
    if quota_guard is None:
        quota_guard = SubscriptionQuotaGuard(Path(run_directory).resolve() / 'subscription-quota',
                                             remaining_floor=1)
    return lifecycle.run(output, run_directory, episode_factory=VariantLinkEpisode,
        inputs_factory=inputs_factory, grader_factory=grader_factory,
        contract_id=VERSION, verifier='variant-link-native',
        policy_session=policy_session, metadata=metadata, runner_options=runner_options,
        viewer_projection=viewer_projection, quota_guard=quota_guard,
        extraction_backend_factory=extraction_backend_factory, runner=runner)
