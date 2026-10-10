"""Versioned latent product tendencies for existing, exact-SKU review assessments.

Quality within a profile and between-reviewer noise are separate controls. The
oracle reads the realized public corpus, never these private model tendencies.
Price position is relative to the authored family reference-price range, not a
real market percentile or an assertion about value at a live retailer's price.
"""
from copy import deepcopy
import math
from .generate import digest, stream

VERSION = 'product-opinion-profiles-v1'
# Offsets affect favourability, so + on noise/rubbing means fewer complaints.
ARCHETYPES = {
    'budget_basic': {'families': ['footwear', 'laptops', 'dog_food', 'cat_food', 'beer', 'wine'], 'offsets': {}},
    'balanced_generalist': {'families': ['footwear', 'laptops', 'dog_food', 'cat_food', 'beer', 'wine'], 'offsets': {}},
    'premium_positioned': {'families': ['footwear', 'laptops', 'dog_food', 'cat_food', 'beer', 'wine'], 'offsets': {}},
    'cushioned_walker': {'families': ['footwear'], 'offsets': {'comfort': .16, 'heel_rubbing': .04}},
    'rugged_hiker': {'families': ['footwear'], 'offsets': {'comfort': -.06, 'heel_rubbing': -.14}},
    'light_trail': {'families': ['footwear'], 'offsets': {'comfort': .10, 'heel_rubbing': .04}},
    'occasion_first': {'families': ['footwear'], 'offsets': {'comfort': -.16, 'heel_rubbing': -.08}},
    'beach_basic': {'families': ['footwear'], 'offsets': {'comfort': -.20}},
    'quiet_writer': {'families': ['laptops'], 'offsets': {'keyboard_comfort': .12, 'fan_noise': .18}},
    'performance_focused': {'families': ['laptops'], 'offsets': {'keyboard_comfort': .04, 'fan_noise': -.22}},
    'office_workhorse': {'families': ['laptops'], 'offsets': {'keyboard_comfort': .05, 'fan_noise': .03}},
    'feeding_staple': {'families': ['dog_food', 'cat_food'], 'offsets': {'pet_acceptance': .06}},
    'acceptance_first': {'families': ['dog_food', 'cat_food'], 'offsets': {'pet_acceptance': .18, 'pack_handling': -.06}},
    'convenient_pack': {'families': ['dog_food', 'cat_food'], 'offsets': {'pet_acceptance': -.03, 'pack_handling': .18}},
    'approachable_drink': {'families': ['beer', 'wine'], 'offsets': {'taste_enjoyment': .08}},
    'characterful_drink': {'families': ['beer', 'wine'], 'offsets': {'taste_enjoyment': -.03}},
}
COST_RANGES = {'footwear': (600, 1400), 'laptops': (5500, 9500), 'dog_food': (45, 90),
               'cat_food': (55, 110), 'beer': (15, 35), 'wine': (70, 220)}
COMPLAINTS = {'heel_rubbing', 'fan_noise'}
DESCRIPTIVE = {'bitterness', 'dryness'}


def _number(value, key):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(key + ' must be a finite number in [0,1]')


def resolve_options(options):
    defaults = {'execution_mean': None, 'execution_mean_range': [0.0, 1.0],
                'reviewer_spread': None, 'reviewer_spread_range': [.05, .35], 'model_overrides': {}}
    if not isinstance(options, dict) or set(options) - set(defaults): raise ValueError('Unknown profile options')
    result = {**defaults, **deepcopy(options)}
    for key in ('execution_mean', 'reviewer_spread'):
        if result[key] is not None: _number(result[key], key)
        bounds = result[key + '_range']
        if not isinstance(bounds, list) or len(bounds) != 2: raise ValueError('Invalid ' + key + '_range')
        for value in bounds: _number(value, key + '_range')
        if bounds[0] > bounds[1]: raise ValueError('Reversed ' + key + '_range')
    if not isinstance(result['model_overrides'], dict): raise ValueError('Expected model overrides object')
    for mid, patch in result['model_overrides'].items():
        if not isinstance(mid, str) or not isinstance(patch, dict) or set(patch) - {'archetype', 'execution_mean', 'reviewer_spread'}:
            raise ValueError('Invalid model override')
        for key, value in patch.items():
            if key == 'archetype':
                if not isinstance(value, str) or value not in ARCHETYPES: raise ValueError('Unknown archetype')
            else: _number(value, key)
    return result


def eligible_archetypes(family, attributes, price_position):
    base = {'low': 'budget_basic', 'middle': 'balanced_generalist', 'high': 'premium_positioned'}[price_position]
    if family == 'footwear':
        specific = {'walking': ['cushioned_walker'], 'running': ['cushioned_walker'],
                    'hiking': ['rugged_hiker', 'light_trail'], 'formal': ['occasion_first'], 'beach': ['beach_basic']}[attributes['activity']]
    elif family == 'laptops': specific = ['quiet_writer', 'performance_focused', 'office_workhorse']
    elif family in ('dog_food', 'cat_food'): specific = ['feeding_staple', 'acceptance_first', 'convenient_pack']
    else: specific = ['approachable_drink', 'characterful_drink']
    return [base, *specific]


def sample_profiles(world, *, seed=0, options=None):
    from .evidence import catalog_hash, ASPECTS
    if type(seed) is not int: raise ValueError('Integer profile seed required')
    cfg = resolve_options({} if options is None else options)
    groups = sorted(world['public']['product_groups'], key=lambda g: g['group_id'])
    if set(cfg['model_overrides']) - {g['group_id'] for g in groups}: raise ValueError('Unknown model override identity')
    products = {p['product_id']: p for p in world['public']['products']}
    catalog = world.get('catalog', world)
    base_prices = {r['model_id']: r['base_reference_sek'] for r in catalog['private_provenance']['models']}
    rows = []
    for group in groups:
        mid = group['group_id']; family = group['family']
        attrs = products[sorted(v['product_id'] for v in group['variants'])[0]]['attributes']
        lo, hi = COST_RANGES[family]; base = base_prices[mid]
        cost = (base - lo) / (hi - lo)
        tier = 'low' if cost < 1/3 else 'high' if cost > 2/3 else 'middle'
        allowed = eligible_archetypes(family, attrs, tier)
        patch = cfg['model_overrides'].get(mid, {})
        archetype = patch.get('archetype', stream(seed, VERSION + '/' + mid + '/archetype').choice(allowed))
        if archetype not in allowed: raise ValueError('Archetype contradicts family, activity or price position')
        values = {}
        for key in ('execution_mean', 'reviewer_spread'):
            values[key] = patch.get(key, cfg[key])
            if values[key] is None:
                values[key] = round(stream(seed, VERSION + '/' + mid + '/' + key).uniform(*cfg[key + '_range']), 8)
        mean = values['execution_mean']
        # The effect of context vanishes at the endpoints: both all-praise and
        # all-criticism are representable for every archetype with zero noise.
        centers = {aspect: max(0., min(1., mean + ARCHETYPES[archetype]['offsets'].get(aspect, 0) * 4 * mean * (1 - mean)))
                   for aspect, spec in ASPECTS.items() if family in spec['families'] and aspect not in DESCRIPTIVE}
        rows.append({'model_id': mid, 'family': family, 'archetype': archetype,
                     'reference_base_sek': base, 'price_position': tier, **values,
                     'aspect_favourability_centers': centers})
    result = {'schema_version': VERSION, 'seed': seed, 'config': cfg, 'source_catalog_sha256': catalog_hash(world),
              'price_basis': 'authored_normalized_model_base_sek_before_retailer_offers', 'models': rows}
    return {**result, 'profiles_sha256': digest(result)}


def expected_stance(profile, aspect, *, seed, legacy_id):
    if aspect in DESCRIPTIVE: raise ValueError('Sensory presence is not quality')
    mean = profile['aspect_favourability_centers'][aspect]; spread = profile['reviewer_spread']
    shared = stream(seed, VERSION + '/review/' + legacy_id).uniform(-1, 1)
    specific = stream(seed, VERSION + '/review/' + legacy_id + '/' + aspect).uniform(-1, 1)
    score = max(0., min(1., mean + spread * (.75 * shared + .25 * specific)))
    if score >= .65: return 'negative' if aspect in COMPLAINTS else 'positive'
    if score <= .35: return 'positive' if aspect in COMPLAINTS else 'negative'
    return 'neutral' if .45 <= score <= .55 else 'mixed'


def identity(legacy_id, profile):
    return 'review-' + digest([VERSION, legacy_id, profile])[:20]


def star_choices(report, family):
    from .evidence import PRIMARY
    primary = next((a['stance'] for a in report['assessments'] if a['aspect_id'] == PRIMARY[family]), None)
    if primary is not None:
        return {'positive': (4, 5), 'negative': (1, 2), 'neutral': (3,), 'mixed': (2, 3, 4)}[primary]
    values = []
    for a in report['assessments']:
        if a['aspect_id'] in DESCRIPTIVE: continue
        positive = a['stance'] == ('negative' if a['aspect_id'] in COMPLAINTS else 'positive')
        negative = a['stance'] == ('positive' if a['aspect_id'] in COMPLAINTS else 'negative')
        values.append(1 if positive else -1 if negative else 0)
    if values and all(v == 1 for v in values): return (4, 5)
    if values and all(v == -1 for v in values): return (1, 2)
    return (2, 3, 4)


def generate_profiled_evidence(world, *, seed, as_of, reviews_per_sku, reviewed_variants_per_model, profile_options):
    from .evidence import generate_evidence, validate_evidence
    from .evidence_prose import render_natural
    from .evidence_drinks import render_drink
    profiles = sample_profiles(world, seed=seed, options=profile_options)
    by_model = {p['model_id']: p for p in profiles['models']}
    result = generate_evidence(world, seed=seed, as_of=as_of, reviews_per_sku=reviews_per_sku,
                               reviewed_variants_per_model=reviewed_variants_per_model)
    products = {p['product_id']: p for p in world['public']['products']}
    for row in result['public']['reviews']:
        profile = by_model[row['article_id']]; old_id = row['review_id']; p = products[row['subject']['id']]
        for a in row['assessments']:
            if a['aspect_id'] not in DESCRIPTIVE:
                a['stance'] = expected_stance(profile, a['aspect_id'], seed=seed, legacy_id=old_id)
        if row['stars'] is not None:
            row['stars'] = stream(seed, VERSION + '/stars/' + old_id).choice(star_choices(row, p['category']))
        row['review_id'] = identity(old_id, profile)
        row['reviewer_id'] = 'reviewer-' + digest([VERSION, row['reviewer_id'], profile])[:20]
        row['source_locator']['fragment'] = row['review_id']
        if row['template_version'] == 4:
            # Keep the same sensory observations: quality shifts enjoyment, not
            # whether a beer is bitter or a wine is perceived as dry.
            row['body'], row['mentioned_attributes'] = render_drink(row, p)
        else: row['body'], row['mentioned_attributes'] = render_natural(row, p)
    provenance = result['private_provenance']
    provenance.update(profile_sampling=profiles, public_sha256=digest(result['public']),
        sampling='Model-shared archetype/execution center and separate reviewer noise; exact-SKU public claims. Descriptive sensory presence unchanged. No task, stock, offer-price or layout input.')
    validate_evidence(world, result)
    return result


def validate_profile_binding(world, export):
    from .evidence import PUBLISHER
    provenance = export['private_provenance']; profiles = provenance['profile_sampling']
    if not isinstance(profiles, dict) or profiles.get('schema_version') != VERSION: raise ValueError('Unknown profile sampler')
    expected = sample_profiles(world, seed=provenance['seed'], options=profiles.get('config'))
    if profiles != expected: raise ValueError('Profile provenance differs from catalog/seed/config')
    by_model = {p['model_id']: p for p in profiles['models']}
    # Recover deterministic source identities; no per-review latent labels enter public data.
    reports = {}
    for row in export['public']['reviews']: reports.setdefault(row['subject']['id'], []).append(row)
    for sku, rows in reports.items():
        profile = by_model[rows[0]['article_id']]; template = rows[0]['template_version']
        ids = {}
        for i in range(provenance['reviews_per_sku']):
            old_id = 'review-' + digest([PUBLISHER, template, provenance['seed'], sku, i])[:20]
            ids[identity(old_id, profile)] = old_id
        for row in rows:
            if row['review_id'] not in ids: raise ValueError('Profile review identity mismatch')
            old_id = ids[row['review_id']]
            for a in row['assessments']:
                if a['aspect_id'] not in DESCRIPTIVE and a['stance'] != expected_stance(profile, a['aspect_id'], seed=provenance['seed'], legacy_id=old_id):
                    raise ValueError('Profile assessment differs from its draw')
            if row['stars'] is not None and row['stars'] != stream(provenance['seed'], VERSION + '/stars/' + old_id).choice(star_choices(row, profile['family'])):
                raise ValueError('Profile rating differs from its assessments')
