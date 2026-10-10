"""Opt-in materialized assortment via existing population factory hooks.

This is an authoring preview, not a connected-world generator or grader. It samples
presence and retailer allocation without fixing sparse draws or forcing matches.
"""
from copy import deepcopy
from collections import Counter
import hashlib
import json

from environments.product_world import footwear_context_pilot as legacy
from environments.product_world.product_package import ProductPackage
from environments.product_world.product_package_pilot import sample_ported_product
from environments.product_world.review_population import summarize_ratings
from experiments.world_sampling_defaults import model as population
from .coverage import PACKAGES, coverage

VERSION = 'product-width-assortment-preview-v2'
DESCRIPTION_PROJECTION = 'catalog-description-sku-scope-v1'
# Authoring-only adapter: this package declares a separate typed public view.
# Its canonical scalar/status rows remain unchanged, and selecting a description
# subject does not create a listing, review or task answer.
SKU_CONTEXT_PROJECTIONS = {
    'tablets.everyday_media_tablets': 'sku_projection',
    'tablets.pen_work_focused_tablets': 'sku_projection',
    'monitors.office_productivity_monitors': 'sku_projection',
    'monitors.high_refresh_gaming_monitors': 'sku_projection',
    'monitors.creative_image_work_monitors': 'sku_projection',
    'monitors.ultrawide_workspace_monitors': 'sku_projection',
}


def catalog_descriptions(package, entities, seed):
    """Render model facts once and candidate facts for every canonical SKU.

    A declared sku.* reference requires a real candidate, not a guessed default
    or a silent selection of the first size/bundle. This is private authoring
    presentation; it does not register a task or manufacture retailer stock.
    """
    output = []
    for pool in package.document['language']:
        if pool['meaning']['kind'] != 'catalog_fact':
            continue
        expressions = [*pool.get('slots', {}).values()]
        if 'when' in pool:
            expressions.append(pool['when'])
        references = set().union(*(package.expression(s).references for s in expressions))
        sku_scoped = any(path.startswith('sku.') for path in references)
        candidates = entities['product']['skus'] if sku_scoped else [None]
        for candidate in candidates:
            context = deepcopy(entities)
            if candidate is not None:
                projection = SKU_CONTEXT_PROJECTIONS.get(package.document['concept_id'])
                if projection is None:
                    context['sku'] = deepcopy(candidate)
                else:
                    projected = package.programs[projection].sample(seed, inputs={
                        'product': {'product_id': entities['product']['product_id'],
                                    'skus': deepcopy(entities['product']['skus'])},
                        'projection': {'subject': deepcopy(candidate)}})
                    context['sku'] = projected['entities']['sku']
            if 'when' in pool and not package._eval(pool['when'], context):
                continue
            output.append(package.formulate(pool['id'], context, seed=seed))
    return output


def seed_for(seed, key):
    return int.from_bytes(hashlib.sha256(f'{VERSION}/{seed}/{key}'.encode()).digest()[:4], 'big')


def sample_product(seed, concept_id, brand, product_id, review_count=16, *, accepted_contexts=False,
                   context_adapter_version='v5'):
    """Project public catalog data explicitly; latent profiles stay private."""
    package = ProductPackage.load(PACKAGES / (concept_id + '.json'))
    context_binding = None
    required = {'brand': {**deepcopy(brand), 'eligible_concepts': [concept_id]},
                'product': {'product_id': product_id}}
    preview_name = brand['name'] + ' ' + concept_id.split('.')[1].replace('_', ' ') + ' ' + product_id.split('/')[-1]
    # Names remain caller-owned identity in some neutral family bases. Supply
    # the existing inspector label only when the package declares it as input;
    # never overwrite a child's sampled or constant name.
    if package.fields.get('product.name', {}).get('input'):
        required['product']['name'] = preview_name
    # Explicit fixture-level profile weights for as-yet-unadopted brand dimensions.
    # Preserve real caller weights when supplied; never infer target from a name.
    for entity, defaults in package.document.get('metadata', {}).get('preview_input_defaults', {}).items():
        for key, value in defaults.items():
            required.setdefault(entity, {}).setdefault(key, deepcopy(value))
    if accepted_contexts:
        from .coverage import ACCEPTED
        acceptance = json.loads(ACCEPTED.read_text())[concept_id]
        if context_adapter_version == 'v5':
            from .context_adapter import bind
            context_binding = bind(package, acceptance)
        elif context_adapter_version == 'v6':
            from .context_adapter_v6 import bind
            context_binding = bind(package, acceptance, authoritative_inputs=required)
        else:
            raise ValueError('Unknown private context adapter version')
    result = package.sample(seed, inputs=required)
    entities = result['entities']
    catalog = deepcopy(entities['product'])
    family = package.document.get('metadata', {}).get('family_id', concept_id.split('.', 1)[0])
    if family != concept_id.split('.', 1)[0]:
        raise ValueError('Package family does not match the canonical concept')
    public = {'product_id': product_id, 'concept_id': concept_id, 'family_id': family,
              'brand_id': brand['brand_id'], 'name': catalog.get('name', preview_name),
              'model_name': concept_id.split('.')[1].replace('_', ' ') + ' ' + product_id.split('/')[-1],
              'facts': catalog['facts'], 'skus': catalog['skus'],
              'reference_price_sek': catalog['reference_price_sek']}
    descriptions = catalog_descriptions(package, entities, seed)
    reviews = []
    usage = Counter()
    previous_connector = None
    stage = package.programs['review']
    for index in range(review_count):
        rs = seed_for(seed, f'review/{index}')
        review = stage.sample(rs, inputs=entities)
        rentities = review['entities']
        statements = [stage.formulate(pool['id'], rentities, seed=rs, usage=usage)
                      for pool in stage.document['language'] if stage._eval(pool['when'], rentities)]
        # Reuse the accepted presentation compositor without rewriting atoms.
        presentation = legacy.compose_review(rs, product_id + f'/review-{index}',
                                              [dict(s, polarity=s['meaning']['polarity']) for s in statements],
                                              previous_connector=previous_connector)
        previous_connector = next((s['connector'] for s in presentation['segments']
                                   if s['connector'] != 'plain'), previous_connector)
        reviews.append({'review_id': product_id + f'/review-{index}',
                        'reviewer_id': product_id + f'/reviewer-{index}',
                        'sku_id': rentities['sku']['sku_id'], 'rating': rentities['review']['rating'],
                        'statements': statements, 'text': presentation['text'], 'presentation': presentation,
                        'private_trace': review['trace']})
    private = {'profiles': deepcopy(entities['profile']), 'sample': result}
    if context_binding is not None:
        private['context_binding'] = context_binding
    return {'public': public, 'private': private, 'descriptions': descriptions,
            'description_projection_version': (
                'catalog-description-explicit-typed-sku-v2'
                if concept_id in SKU_CONTEXT_PROJECTIONS else DESCRIPTION_PROJECTION),
            'reviews': reviews, 'rating_summary': summarize_ratings(reviews)}


def generate(seed=0, *, controls=None, task_concept='footwear.casual_trainers', review_count=16,
             accepted_contexts=False):
    accepted = [r['concept_id'] for r in coverage()['concepts'] if r['status'] == 'domain_accepted']
    slice_ids = ['footwear.walking_shoes', 'footwear.walking_sandals', *accepted]
    if task_concept not in slice_ids:
        raise ValueError('Task concentration concept must have accepted executable coverage')
    rich = []

    def brand_factory(base, prior):
        if base['scope_id'] != 'footwear':
            # A scoped authoring fixture, not an adopted production brand model.
            # Keep sampled identity/theme/positioning rather than shoe-specific facts.
            weights = {'budget': {'budget': 7, 'mainstream': 3, 'premium': 1},
                       'mainstream': {'budget': 2, 'mainstream': 7, 'premium': 2},
                       'premium': {'budget': 1, 'mainstream': 3, 'premium': 7}}
            return {**base, 'name': 'Author brand ' + base['brand_id'],
                    'positioning_weights': weights[base['positioning']]}
        brand = legacy.sample_brand(seed_for(seed, 'brands'), len(prior), legacy.load_spec(), existing=prior)
        return {**base, **brand, 'brand_id': base['brand_id'], 'scope_id': base['scope_id']}

    def product_factory(base, brand, prior):
        product_seed = seed_for(seed, base['product_id'])
        if base['concept_id'] in accepted:
            item = sample_product(product_seed, base['concept_id'], brand, base['product_id'], review_count,
                                  accepted_contexts=accepted_contexts)
            positioning = item['private']['profiles']['positioning']
        else:
            item = sample_ported_product(product_seed, base['concept_id'].split('.')[1], brand,
                                         product_id=base['product_id'], existing_products=[r['public'] for r in rich])
            positioning = item['private']['positioning']
            from environments.product_world.footwear_retail_content import render_retail_content
            item['descriptions'] = [render_retail_content(item['public'], seed=product_seed)['description']]
            item['reviews'] = legacy.sample_reviews(product_seed, item, count=review_count)
            item['rating_summary'] = summarize_ratings(item['reviews'])
        rich.append(item)
        return {**base, 'positioning': positioning, 'name': item['public']['name']}

    plan = population.sample(seed, tasks=[task_concept], controls=controls,
                             concept_ids=slice_ids, brand_factory=brand_factory,
                             product_factory=product_factory)
    listed = {pid for r in plan['retailers'] for pid in r['product_ids']}
    summary = {'brands': len(plan['brands']), 'world_products': len(rich),
               'listed_distinct_products': len(listed),
               'unlisted_products': len(rich) - len(listed),
               'distinct_concepts': len({r['public']['concept_id'] for r in rich}),
               'manufactured_skus': sum(len(r['public']['skus']) for r in rich),
               'retailers': len(plan['retailers']),
               'empty_retailers': sum(not r['product_ids'] for r in plan['retailers']),
               'product_listing_counts': {r['public']['product_id']: sum(r['public']['product_id'] in s['product_ids'] for s in plan['retailers']) for r in rich}}
    return {'schema_version': VERSION, 'seed': seed, 'population': plan,
            'products': rich, 'summary': summary,
            'limitations': ['Private authoring preview; not an agent-facing website.',
                           'Brand eligibility is an explicit current-concept authoring fixture override; this is not full brand-breadth consumer adoption.',
                           'New profile weights use declared fixture defaults unless supplied by the caller.',
                           'Manufacturer facts/reviews and population allocation only; no new stock, offers, shipping or task grader.',
                           'Retailer templates contain only the current accepted concept slice; other departments remain unsampled.',
                           'Non-footwear brands are explicit scoped authoring fixtures, not production brand-breadth validation.',
                           'Sparse/empty draws retained; no success-conditioned sampling.']}
