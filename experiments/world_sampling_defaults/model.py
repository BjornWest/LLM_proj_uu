"""Metadata-only sampling reference; never publishes product facts or live worlds.

Purpose-keyed random streams keep stock/price outcomes out of population and
assortment decisions. Finite slots bound support; they are not population quotas.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random

from environments.product_world.concept_registry import ConceptRegistry

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / 'docs/agents/world-sampling-defaults.json'


def stream(seed, key):
    return random.Random(int.from_bytes(hashlib.sha256(f'{seed}/{key}'.encode()).digest(), 'big'))


def load():
    config = json.loads(DEFAULT_PATH.read_text())
    registry = ConceptRegistry.load()
    validate(config, registry)
    return config, registry


def validate(config, registry):
    if config['schema_version'] != 'world-sampling-defaults-v1':
        raise ValueError('Unknown defaults schema')
    concepts = {c['id']: c for c in registry.concepts()}
    families = {c['family_id'] for c in concepts.values()}
    if set(config['population']['base_expected_products_per_concept']) != families:
        raise ValueError('Population defaults must cover every registered family')
    scopes = [f for s in config['population']['brand_scopes'].values() for f in s['family_ids']]
    if set(scopes) != families or len(scopes) != len(families):
        raise ValueError('Each family needs exactly one brand scope')
    seen = set()
    covered = set()
    for template in config['retailer_templates']:
        if template['id'] in seen:
            raise ValueError('Duplicate retailer template')
        seen.add(template['id'])
        own = set()
        for dept in template['departments']:
            ids = set(dept['concept_ids'])
            if ids - concepts.keys() or ids & own or dept['weight'] <= 0:
                raise ValueError('Invalid or overlapping department scope')
            if set(dept['requires_declared_theme']) - ids:
                raise ValueError('Conditional membership outside department')
            own.update(ids)
        if set(template['direct_task_concept_ids']) - own:
            raise ValueError('Direct relevance outside hard scope')
        if not math.isclose(sum(d['weight'] for d in template['departments']), 1):
            raise ValueError('Department weights must sum to one')
        covered.update(own)
    if covered != concepts.keys():
        raise ValueError('Store templates must cover the concept registry')
    for values in config['themes'].values():
        if set(values) - concepts.keys():
            raise ValueError('Unknown concept in shared theme')
    for name in ('scale_probabilities', 'emphasis_specificity_probabilities',
                 'price_preference_probabilities_balanced', 'price_preference_probabilities_focused'):
        probs = config['retailer_population'][name]
        if min(probs.values()) < 0 or not math.isclose(sum(probs.values()), 1):
            raise ValueError('Invalid retailer prior')


def weighted(rng, weights):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def theme_ids(config, cid):
    return {t for t, ids in config['themes'].items() if cid in ids}


def affinity(config, cid, tasks):
    values = config['population']['task_affinity']
    best = 0
    for other in tasks:
        level = ('exact_concept' if cid == other else 'shared_theme'
                 if theme_ids(config, cid) & theme_ids(config, other) else 'same_family'
                 if cid.split('.')[0] == other.split('.')[0] else 'unrelated')
        best = max(best, values[level])
    return best


def relevance(template, tasks):
    if not tasks:
        return 'unrelated'
    direct = sum(cid in template['direct_task_concept_ids'] for cid in tasks) / len(tasks)
    if direct >= .75:
        return 'direct'
    scope = {cid for d in template['departments'] for cid in d['concept_ids']}
    return 'partial' if scope.intersection(tasks) else 'unrelated'


def eligible(product, department):
    cid = product['concept_id']
    required = department['requires_declared_theme'].get(cid)
    return cid in department['concept_ids'] and (not required or required in product['theme_ids'])


def inclusion_probabilities(weights, expected):
    """Solve a monotone bounded expectation, rather than selecting an exact count."""
    if not weights:
        return [], bool(expected)
    if expected == 0:
        return [0.] * len(weights), False
    target = min(expected, .95 * len(weights))
    capped = expected > target + 1e-9
    lo, hi = 0., 1.
    while sum(min(.95, hi * w) for w in weights) < target - 1e-12:
        hi *= 2
    for _ in range(60):
        mid = (lo + hi) / 2
        if sum(min(.95, mid * w) for w in weights) < target:
            lo = mid
        else:
            hi = mid
    return [min(.95, hi * w) for w in weights], capped


def department_budgets(weights, counts, expected):
    """Redistribute saturated department shares within existing hard scope."""
    if not counts:
        return []
    capacities = [.95 * n for n in counts]
    target = min(expected, sum(capacities))
    if target == 0:
        return [0.] * len(counts)
    lo, hi = 0., 1.
    while sum(min(cap, hi * w) for cap, w in zip(capacities, weights)) < target - 1e-12:
        hi *= 2
    for _ in range(60):
        mid = (lo + hi) / 2
        if sum(min(cap, mid * w) for cap, w in zip(capacities, weights)) < target:
            lo = mid
        else:
            hi = mid
    return [min(cap, hi * w) for cap, w in zip(capacities, weights)]


def sample(seed=0, tasks=('footwear.walking_shoes',), controls=None, *, concept_ids=None,
           brand_factory=None, product_factory=None):
    """Draw metadata, optionally materializing a bounded authored concept slice.

    Factories execute before allocation so stores consume the actual positioning
    and brand metadata, rather than a separately drawn surrogate. They must retain
    identities/scope. No stock or price result is inspected by population logic.
    Default calls preserve the original metadata-only draw.
    """
    config, registry = load()
    knobs = {**config['controls'], **(controls or {})}
    if set(knobs) != set(config['controls']):
        raise ValueError('Unknown population control')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in knobs.values()):
        raise ValueError('Controls must be finite nonnegative numbers')
    if knobs['product_concentration'] == 0 or knobs['within_store_task_concentration'] == 0:
        raise ValueError('Product/allocation concentration must remain positive')
    concepts = registry.concepts()
    if concept_ids is not None:
        selected = set(concept_ids)
        if not selected or selected - {c['id'] for c in concepts}:
            raise ValueError('Unknown or empty concept slice')
        concepts = [c for c in concepts if c['id'] in selected]
    tasks = sorted(set(tasks))
    if set(tasks) - {c['id'] for c in concepts}:
        raise ValueError('Unknown task concept')
    pop = config['population']
    expectations = {c['id']: knobs['world_size'] * pop['base_expected_products_per_concept'][c['family_id']] *
                    (1 + (knobs['product_concentration'] - 1) * affinity(config, c['id'], tasks)) for c in concepts}
    brands, products, diagnostics = [], [], []
    for sid, scope in pop['brand_scopes'].items():
        own = [c for c in concepts if c['family_id'] in scope['family_ids']]
        if not own:
            continue
        expected = sum(expectations[c['id']] for c in own)
        desired = scope['diversity_multiplier'] * knobs['brand_diversity'] * math.sqrt(expected)
        cap = scope['candidate_brand_capacity']
        if desired > cap:
            diagnostics.append({'kind': 'brand_capacity', 'scope': sid, 'desired': desired, 'capacity': cap})
        sampled = []
        positions = Counter()
        for i in range(cap):
            bid = f'{sid}-brand-{i:02d}'
            if stream(seed, bid+'/exists').random() >= min(1, desired / cap):
                continue
            weights = {p: 1 / (1 + .5 * positions[p]) for p in ('budget', 'mainstream', 'premium')}
            position = weighted(stream(seed, bid+'/positioning'), weights)
            positions[position] += 1
            scope_themes = sorted({t for c in own for t in theme_ids(config, c['id'])})
            focus = stream(seed, bid+'/theme').choice([None, None, *scope_themes]) if scope_themes else None
            brand = {'brand_id': bid, 'scope_id': sid, 'positioning': position, 'focus_theme': focus}
            if brand_factory is not None:
                actual = brand_factory(dict(brand), brands)
                if any(actual[k] != brand[k] for k in ('brand_id', 'scope_id')):
                    raise ValueError('Brand factory changed identity or scope')
                brand = actual
            sampled.append(brand)
            brands.append(brand)
        if not sampled:
            diagnostics.append({'kind': 'empty_brand_scope', 'scope': sid, 'expected_products': expected})
            continue
        slots = pop['brand_product_slots_per_concept']
        for c in own:
            brand_weights = {b['brand_id']: 1.5 if b['focus_theme'] in theme_ids(config, c['id']) else 1 for b in sampled}
            for brand in sampled:
                desired_p = expectations[c['id']] * brand_weights[brand['brand_id']] / (sum(brand_weights.values()) * slots)
                if desired_p > .95:
                    diagnostics.append({'kind': 'product_slot_capacity', 'concept': c['id'], 'brand': brand['brand_id'], 'desired_probability': desired_p})
                for i in range(slots):
                    pid = f"{brand['brand_id']}/{c['id']}/{i:02d}"
                    if stream(seed, pid+'/exists').random() >= min(.95, desired_p):
                        continue
                    profiles = {'budget': {'budget':7,'mainstream':3,'premium':1},
                                'mainstream': {'budget':2,'mainstream':7,'premium':2},
                                'premium': {'budget':1,'mainstream':3,'premium':7}}
                    product = {'product_id': pid, 'brand_id': brand['brand_id'], 'concept_id': c['id'],
                               'family_id': c['family_id'], 'theme_ids': sorted(theme_ids(config, c['id'])),
                               'positioning': weighted(stream(seed, pid+'/position'), profiles[brand['positioning']])}
                    if product_factory is not None:
                        actual = product_factory(dict(product), brand, products)
                        if any(actual[k] != product[k] for k in ('product_id', 'brand_id', 'concept_id', 'family_id')):
                            raise ValueError('Product factory changed identity or concept')
                        product = actual
                    products.append(product)
    retailer_config = config['retailer_population']
    allocation = config['allocation']
    retailers = []
    brands_by_id = {b['brand_id']: b for b in brands}
    for template in config['retailer_templates']:
        departments = [(d, [p for p in products if eligible(p, d)]) for d in template['departments']]
        missing = sum(p['concept_id'] in d['concept_ids'] and not eligible(p, d) for d in template['departments'] for p in products)
        if missing:
            diagnostics.append({'kind': 'conditional_theme_missing', 'template': template['id'], 'excluded_products': missing})
        own = [p for _, xs in departments for p in xs]
        cls = relevance(template, tasks)
        mean = retailer_config['base_mean_per_template'] * knobs['world_size'] ** retailer_config['world_size_exponent'] * \
               (len(own) / retailer_config['scope_population_reference']) ** retailer_config['scope_population_exponent'] * \
               retailer_config['generation_weights'][cls] ** knobs['retailer_concentration']
        slots = retailer_config['candidate_slots_per_template']
        if mean / slots > .95:
            diagnostics.append({'kind': 'retailer_slot_capacity', 'template': template['id'], 'desired_mean': mean})
        for i in range(slots):
            rid = f"{template['id']}-{i:02d}"
            if stream(seed, rid+'/exists').random() >= min(.95, mean / slots):
                continue
            scale = weighted(stream(seed, rid+'/scale'), retailer_config['scale_probabilities'])
            specificity = weighted(stream(seed, rid+'/specificity'), retailer_config['emphasis_specificity_probabilities'])
            focus_options = sorted({t for p in own for t in p['theme_ids']})
            focus = (template['focus_theme'] or (stream(seed, rid+'/focus').choice(focus_options) if focus_options else None)) if specificity == 'focused' else None
            price = weighted(stream(seed, rid+'/price_preference'), retailer_config['price_preference_probabilities_'+specificity])
            aligned_fraction = sum(focus in p['theme_ids'] for p in own) / len(own) if focus and own else 1
            depth = (.35 + .65 * aligned_fraction) if focus else 1
            budget = len(own) * allocation['coverage_fraction_by_scale'][scale] * depth
            if tasks and cls == 'unrelated':
                budget *= knobs['unrelated_store_assortment_weight']
            preferred = []
            if stream(seed, rid+'/prefers_brand').random() < allocation['preferred_brand_probabilities'][scale]:
                count = int(weighted(stream(seed, rid+'/brand_count'), allocation['preferred_brand_count_probabilities']))
                options = {p['brand_id'] for p in own}
                for j in range(min(count, len(options))):
                    bw = {}
                    for bid in options:
                        branded = [p for p in own if p['brand_id'] == bid]
                        match = sum(focus in p['theme_ids'] for p in branded) / len(branded) if focus else 0
                        bw[bid] = (1 + .5 * match) * (1.2 if brands_by_id[bid]['positioning'] == price else 1)
                    bid = weighted(stream(seed, rid+f'/preferred/{j}'), dict(sorted(bw.items())))
                    preferred.append(bid)
                    options.remove(bid)
            listings, traces = [], []
            budgets = department_budgets([d['weight'] for d, _ in departments], [len(xs) for _, xs in departments], budget)
            for (dept, xs), desired in zip(departments, budgets):
                if not xs:
                    continue
                weights = []
                for p in xs:
                    w = allocation['inside_focus_product_weight'] if focus in p['theme_ids'] else 1
                    w *= allocation['price_match_weight'] if p['positioning'] == price else 1
                    w *= allocation['brand_alignment_match_weight'] if focus and brands_by_id[p['brand_id']]['focus_theme'] == focus else 1
                    w *= allocation['preferred_brand_product_weight'] if p['brand_id'] in preferred else 1
                    w *= 1 + (knobs['within_store_task_concentration'] - 1) * affinity(config, p['concept_id'], tasks)
                    weights.append(w)
                # A zero task weight deliberately removes that product's support.
                active = [(p, w) for p, w in zip(xs, weights) if w > 0]
                probs, capped = inclusion_probabilities([w for _, w in active], desired)
                if capped:
                    diagnostics.append({'kind': 'department_budget_capacity', 'retailer': rid, 'department': dept['id'], 'desired': desired})
                chosen = [p['product_id'] for (p, _), prob in zip(active, probs) if stream(seed, rid+'/'+p['product_id']+'/listed').random() < prob]
                listings.extend(chosen)
                traces.append({'department_id': dept['id'], 'eligible_products': len(xs), 'expected_products': sum(probs), 'listed_products': len(chosen)})
            if not listings:
                diagnostics.append({'kind': 'empty_retailer', 'retailer': rid})
            ship = config['shipping_selection']
            count = stream(seed, rid+'/carrier_count').randint(*ship['carrier_count_ranges_by_scale'][scale])
            carriers = stream(seed, rid+'/carriers').sample([f'carrier-{j}' for j in range(ship['world_carrier_count'])], count)
            services = []
            for cid in carriers:
                tiers = ['standard'] + [tier for tier in ('economy', 'express') if stream(seed, rid+'/'+cid+'/'+tier).random() < ship[tier+'_service_probability']]
                services.append({'carrier_id': cid, 'tiers': tiers, 'bulky_supported': stream(seed, cid+'/bulky').random() < ship['world_carrier_bulky_home_probability']})
            retailers.append({'retailer_id': rid, 'template_id': template['id'], 'relevance': cls, 'scale': scale,
                              'specificity': specificity, 'focus_theme': focus, 'price_preference': price,
                              'preferred_brands': preferred, 'product_ids': listings, 'eligible_product_count': len(own),
                              'departments': traces, 'shipping_options': services})
    return {'schema_version': config['schema_version'], 'seed': seed, 'task_concepts': tasks, 'controls': knobs,
            'scope': ('Authored concept slice with factories; materialized data is caller-owned.' if brand_factory or product_factory
                      else 'Metadata-only reference draw; no SKU facts, prices, stock, reviews or task oracle.'),
            'brands': brands, 'products': products, 'retailers': retailers, 'diagnostics': diagnostics}


def list_skus(seed, key, skus, axes, config=None):
    """Subset manufactured SKUs without inventing combinations or reading stock."""
    config = (config or load()[0])['sku_listing']
    if not skus or len({s['sku_id'] for s in skus}) != len(skus):
        raise ValueError('Expected nonempty unique manufactured SKU identities')
    roles = config['role_default_probabilities']
    selected = {}
    commonness = {}
    sizes = []
    for axis, definition in axes.items():
        if definition['kind'] not in {'size', 'colour', 'configuration'}:
            raise ValueError('Unknown variant axis kind')
        values = sorted({s[axis] for s in skus})
        if definition['kind'] == 'size':
            sizes.append(axis)
            continue
        supplied = definition['roles']
        if set(values) != set(supplied) or set(supplied.values()) - roles.keys():
            raise ValueError('Variant role annotations must match manufactured values')
        if definition['kind'] == 'colour' and ('extension' in supplied.values() or list(supplied.values()).count('base') > 1):
            raise ValueError('Colour supports at most one base and otherwise alternatives')
        alternatives = sum(role != 'base' for role in supplied.values())
        probabilities = {v: (config['standard_colour_probability'] if supplied[v] == 'base' else .75 / math.sqrt(max(1, alternatives)))
                         if definition['kind'] == 'colour' else roles[supplied[v]] for v in values}
        commonness[axis] = probabilities
        selected[axis] = {v for v in values if len(values) == 1 or stream(seed, key+f'/{axis}/{v}/carry').random() < probabilities[v]}
    candidates = [s for s in skus if all(s[axis] in values for axis, values in selected.items())]
    groups = {}
    for s in candidates:
        group = tuple((axis, s[axis]) for axis in sorted(selected))
        groups.setdefault(group, []).append(s)
    listed = []
    for group, rows in groups.items():
        coverage = {}
        for axis in sizes:
            values = sorted({s[axis] for s in rows})
            rng = stream(seed, key+'/'+repr(group)+'/'+axis)
            mode = weighted(rng, config['size_coverage_mode_probabilities'])
            coverage[axis] = set(values if mode == 'all_manufactured_sizes' else values[rng.randrange(min(2, len(values)))::2])
        listed.extend(s for s in rows if all(s[a] in values for a, values in coverage.items()))
    fallback = not listed
    if fallback:
        weights = [math.prod(commonness[a][s[a]] for a in commonness) for s in skus]
        listed = [stream(seed, key+'/fallback').choices(skus, weights=weights)[0]]
    return {'sku_ids': [s['sku_id'] for s in listed], 'used_nonempty_fallback': fallback}


def grouping_policy(seed, retailer_id, allowed):
    """Retailer-level policy key, reused across concepts sharing allowed roles."""
    result = {}
    for axis, modes in allowed.items():
        if not modes or set(modes) - {'selector', 'page_partition'}:
            raise ValueError('Invalid grouping roles')
        result[axis] = stream(seed, retailer_id+'/'+axis+'/'+','.join(sorted(modes))).choice(sorted(modes))
    return result


def foreign_placement_multiplier(user_city_id, candidate_city_id, method='delivery', international=False):
    """Candidate-city placement weight; independent of inventory and winners."""
    from environments.product_world.geography import cities, route
    if method not in {'delivery', 'pickup', 'inspection'}:
        raise ValueError('Unknown fulfilment method')
    config, _ = load()
    rule = config['shipping_selection']['nearby_foreign_pickup']
    known = cities()
    if user_city_id not in known or candidate_city_id not in known:
        raise ValueError('Unknown city')
    if international or known[user_city_id]['country'] == known[candidate_city_id]['country']:
        return 1
    if method == 'delivery':
        return rule['ordinary_multiplier']
    def anchor(cid):
        city = known[cid]
        return {'location_id':'anchor/'+cid, 'city_id':cid, 'latitude':city['latitude'],
                'longitude':city['longitude'], 'local_east_km':0, 'local_north_km':0}
    estimate = route(anchor(candidate_city_id), anchor(user_city_id), 'driving')
    if estimate['status'] == 'estimated' and estimate['duration_minutes'] <= rule['maximum_driving_minutes']:
        return rule['relaxed_domestic_only_foreign_multiplier']
    return rule['ordinary_multiplier']
