"""Saved-review direct start; dispatch/automatic lifecycle is Evaluation-owned."""
from copy import deepcopy
from hashlib import sha256
import json
from urllib.parse import quote, urlencode

from .catalog_review_execution import CatalogReviewEpisode
from .review_saved_inputs import target_setup

VERSION = 'website-saved-review-execution-v1'


def review_start(runtime, setup, native, surrounding, binding):
    start = setup.get('start', {})
    if type(start) is not dict or set(start) not in ({'kind', 'site_id', 'product_id'}, {'kind', 'site_id', 'product_id', 'query'}):
        raise ValueError('Require the exact saved review-product setup')
    expected = target_setup(runtime.world, native, surrounding, binding,
                            review_site_id=start.get('site_id'), start_query=start.get('query'))
    if setup != expected or start['kind'] != 'review_product':
        raise ValueError('Saved review-product setup changed')
    matches = [site for site in runtime.site_registry if site['site_id'] == start['site_id']]
    if (len(matches) != 1 or matches[0]['kind'] != 'product_reviews'
            or matches[0]['name'] != expected['site_name'] or runtime.origin_map is None):
        raise ValueError('Require the actual readable-origin review site identity')
    url = matches[0]['origin']+'/reviews/'+quote(start['product_id'], safe='')
    if url not in runtime.bindings['surrounding']['review_products'].get(start['product_id'], []):
        raise ValueError('Review start URL is missing from actual runtime route bindings')
    query = start.get('query', {})
    return url + ('?' + urlencode(sorted(query.items())) if query else '')


class SavedReviewEpisode(CatalogReviewEpisode):
    """Native validation first, then browser-only profile and actual review start.

    Product owns prose relaxation in the parent consumer. Native ID, memories,
    task/reference and topic semantics remain unchanged. No runner is provided:
    callers must attach the automatic native grader before provider dispatch.
    """
    def __init__(self, output, *, lazy_publication=True):
        super().__init__(output, lazy_publication=lazy_publication)
        try:
            from intent_browser.standard_profile import standard_profile
            from intent_browser.connected_world_task import public_projection
            from .comparison_sku_task import episode_task
            if self.manifest.get('saved_review_recipe') != 'website-saved-review-publication-v1':
                raise ValueError('Not an exact saved-review publication')
            read = lambda name: json.loads((self.output/name).read_bytes())
            native = self.answer_grader.task
            setup_bytes = (self.output/'saved-review-setup.private.json').read_bytes()
            if sha256(setup_bytes).hexdigest() != self.manifest['files']['saved-review-setup.private.json']:
                raise ValueError('Saved review setup changed after native validation')
            self.setup = json.loads(setup_bytes)
            self.public = public_projection({**self.public, 'start_url': review_start(
                self.runtime, self.setup, native, read('surrounding.private.json'),
                read('catalog-review-binding.private.json'))})
            # This finite counts task uses the browser/AX only; no Docker tool
            # is advertised. All surrounding sites remain navigable.
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins,
                                            helpers=False, data_tools=False)
            self.site_discovery = None
            files = deepcopy(self.task.files)
            attachments = deepcopy(self.task.attachments)
            attachments['saved-review-setup.private.json'] = str(self.output/'saved-review-setup.private.json')
            self.task = episode_task(self.runtime, self.public, self.profile,
                                     files=files, attachments=attachments)
            self.task.site_discovery_callback = None
        except BaseException:
            self.runtime.close()
            raise
