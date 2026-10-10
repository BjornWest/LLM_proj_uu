"""Bind approved coverage and syndicated reviews to isolated public hosts."""
from copy import deepcopy

from .discovery import Index, retailer_records
from .ecosystem import public_products
from .surrounding_config import validate
from . import rich_ecosystem
from . import native_review_ecosystem
from .native_review_pages import NativeReviewPage
from .comparison_pages import ComparisonPage as RichComparisonPage
from .surrounding_pages import ComparisonPage, ReviewPage, path
from .site_discovery import DiscoverSites, scope_description


def mount(runtime, sidecar, host_class):
    validate(runtime.world, sidecar)
    products = runtime.review_products
    rich = sidecar['schema_version'] in (rich_ecosystem.VERSION, native_review_ecosystem.VERSION)
    families = {p['public']['product_id']: p['public']['family_id'] for p in runtime.world['products']}
    types = {p['public']['product_id']: p['public']['concept'].replace('_', ' ')
             for p in runtime.world['products']}
    names = {sid: r['name'] for sid, r in runtime.adapter.retailers.items()}
    bindings = deepcopy(runtime.bindings['retailer_offers'])
    for sid, catalog in runtime.public_catalogs.items():
        for product in catalog['products']:
            for variant in product['variants']:
                bindings[variant['offerId']]['model_url'] = runtime.bindings['retailer_pages'][sid][product['id']]
    sites, documents = retailer_records(runtime.public_catalogs, runtime.origins)
    index_origin = runtime.index_origin if runtime.discovery_mode == 'index' else None
    origins, views, review_links = {}, {}, {}
    review_bindings = {pid: [] for pid in products}
    comparison_bindings = {pid: [] for pid in products}
    for site in sidecar['sites']:
        if site['kind'] != 'product_reviews':
            continue
        review_class = NativeReviewPage if sidecar['schema_version'] == native_review_ecosystem.VERSION else ReviewPage
        view = review_class(site, {pid: products[pid] for pid in site['product_ids']},
                          bindings, names, index_origin)
        host = runtime._stack.enter_context(host_class(view.page))
        sid = site['site_id']
        runtime.sites[sid] = host
        origins[sid], views[sid] = host.origin, view
        for pid in site['product_ids']:
            url = host.origin + path('reviews', pid)
            review_links.setdefault(pid, url)
            review_bindings[pid].append(url)
    for site in sidecar['sites']:
        if site['kind'] != 'aggregator':
            continue
        tracked = {}
        for pid in site['product_ids']:
            p = products[pid]
            tracked[pid] = {'name': p['name'], 'family_id': families[pid], 'facts': p['facts'], 'fact_status': p.get('fact_status', {}), 'listings': [
                {**listing, 'advertised_price_minor': listing['price_minor']}
                for listing in site['listings'] if listing['product_id'] == pid]}
        page_class = RichComparisonPage if rich else ComparisonPage
        view = page_class(site, tracked, bindings, names, index_origin, review_links)
        host = runtime._stack.enter_context(host_class(view.page, max_query_fields=256) if rich else host_class(view.page))
        sid = site['site_id']
        runtime.sites[sid] = host
        origins[sid], views[sid] = host.origin, view
        for pid in tracked:
            comparison_bindings[pid].append(host.origin + path('models', pid))
    for site in sidecar['sites']:
        sid = site['site_id']
        covered_types = sorted({types[pid] for pid in site['product_ids']})
        sites.append({'site_id': sid, 'kind': site['kind'], 'name': site['name'],
            'origin': origins[sid], 'families': site.get('families', ['footwear']), 'types': covered_types,
            'description': scope_description(covered_types, kind=site['kind'])})
        for doc in [{'path': '/', 'title': site['name'], 'description': sites[-1]['description'], 'keywords': ' '.join(site.get('families', ['footwear']))},
                    {'path': '/about', 'title': 'Sources and scope', 'description': sites[-1]['description'], 'keywords': 'methodology coverage'},
                    *views[sid].documents()]:
            documents.append({'site_id': sid, **doc})
    runtime.discovery = Index(sites, documents)
    runtime.surrounding_origins = origins
    runtime.surrounding_views = views
    runtime.site_registry = sites
    runtime.site_discovery = DiscoverSites(sites)
    runtime.bindings['surrounding'] = {'origins': origins, 'comparison_products': comparison_bindings,
                                     'review_products': review_bindings}
    runtime.navigation_origins = [runtime.index_origin if runtime.discovery_mode == 'index' else runtime.research_origin,
                                  *runtime.origins.values(), *origins.values()]
