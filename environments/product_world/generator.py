"""Pure model/SKU catalog generation; no tasks, offers, inventory or layout inputs."""
import copy
import hashlib
import itertools
import json
import random
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

from environments.shopping_intent.catalog import FAMILIES, attribute_for
from environments.shopping_intent.semantics import RELATIONS
from environments.procedural_commerce.product_controls import VERSION as GROUP_VERSION
from .config import AXES, FAMILY_IDS, domains, resolve_config, token, wine_colours

VERSION = 'product-catalog-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def rng(seed, name):
    return random.Random(int.from_bytes(hashlib.sha256(f'{VERSION}:{seed}:{name}'.encode()).digest(), 'big'))


def weighted(stream, values, weights):
    scale = max(weights)
    normalized = [w / scale for w in weights]
    draw = stream.random() * sum(normalized)
    cumulative = 0
    for value, weight in zip(values, normalized):
        cumulative += weight
        if weight > 0 and draw < cumulative: return value
    return next(v for v, w in reversed(list(zip(values, weights))) if w > 0)


def choose(seed, namespace, values, weights, count=1):
    """Weighted sampling without replacement; zero-weight options cannot appear."""
    remaining = [(v, weights[token(v)]) for v in values if weights[token(v)] > 0]
    stream = rng(seed, namespace)
    selected = []
    for _ in range(min(count, len(remaining))):
        value = weighted(stream, [v for v, _ in remaining], [w for _, w in remaining])
        selected.append(value)
        remaining = [(v, w) for v, w in remaining if v != value]
    return selected


def price_minor(raw_sek, multiplier):
    # Reference prices are whole SEK; all commerce arithmetic uses integer öre.
    return max(100, int((Decimal(str(raw_sek)) * Decimal(str(multiplier))).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) * 100)


def axis(field, family, values):
    attr = attribute_for(family, field)
    return {'field': field, 'label': attr.label, 'value_type': attr.value_type, 'unit': attr.unit,
            'options': [{'id': 'v_' + digest(value)[:12],
                         'label': f'{value} {attr.unit}' if attr.unit else str(value), 'value': value} for value in values]}


def generate_catalog(seed=0, model_count=12, config=None, *, model_families=None, model_identities=None, model_blueprints=None):
    if type(seed) is not int: raise ValueError('seed must be an integer')
    if type(model_count) is not int or not 1 <= model_count <= 500: raise ValueError('model_count must be 1..500')
    settings = resolve_config(config)
    if model_families is not None:
        if not isinstance(model_families, list) or len(model_families) != model_count or any(
                f not in FAMILY_IDS or settings['family_weights'][f] <= 0 for f in model_families):
            raise ValueError('model_families must supply one enabled family per model')
    identities = [None] * model_count if model_identities is None else model_identities
    if not isinstance(identities, list) or len(identities) != model_count:
        raise ValueError('model_identities must supply one optional identity per model')
    for identity in identities:
        if identity is not None and (not isinstance(identity, dict) or set(identity) != {'id', 'name'} or
                any(not isinstance(v, str) or not v.strip() for v in identity.values())):
            raise ValueError('A model identity must contain nonempty id and name strings')
    field_domains = domains()
    blueprints = [None] * model_count if model_blueprints is None else model_blueprints
    if not isinstance(blueprints, list) or len(blueprints) != model_count:
        raise ValueError('model_blueprints must supply one optional blueprint per model')
    products, groups, provenance = [], [], []
    for i in range(model_count):
        family = model_families[i] if model_families is not None else weighted(rng(seed, f'model/{i}/family'), list(FAMILY_IDS), [settings['family_weights'][f] for f in FAMILY_IDS])
        blueprint = blueprints[i]
        if blueprint is not None:
            from .footwear_depth import validate_blueprint
            validate_blueprint(family, blueprint)
        model_id = f'{family}-model-{i + 1:04d}'
        root = 'model/' + str(i) + '/' + family
        brand = rng(seed, root + '/name').choice(('Aster', 'Boreal', 'Cedar', 'Solvik'))
        title = {'footwear': 'Stride', 'laptops': 'Notebook', 'dog_food': 'Canine Recipe', 'cat_food': 'Feline Recipe',
                 'beer': 'Brew', 'wine': 'Vineyard'}[family]
        name = f'{brand} {title} {i + 1:04d}'
        if identities[i] is not None:
            model_id, name = identities[i]['id'], identities[i]['name']
        axes, shared = [], {}
        for attr in FAMILIES[family].attributes:
            if attr.key == 'ingredients' or (family == 'beer' and attr.key == 'production_region'): continue
            key = family + '.' + attr.key
            count = settings['axis_option_counts'].get(key, 1)
            domain = field_domains[key]
            if family == 'wine' and attr.key == 'wine_colour':
                domain = [colour for colour in domain if any(settings['field_weights']['wine.grapes'][grape] > 0
                          and colour in wine_colours([grape]) for grape in field_domains['wine.grapes'])]
            if family == 'wine' and attr.key == 'grapes':
                domain = [grape for grape in domain if shared['wine_colour'] in wine_colours([grape])]
            if family == 'beer' and attr.key == 'origin_country':
                domain = [c for c in domain if any(country == c and settings['field_weights']['beer.production_region'][region] > 0
                          for country, region in RELATIONS['beer'][0]['rows'])]
            values = choose(seed, root + '/field/' + attr.key, domain, settings['field_weights'][key], count)
            if blueprint is not None and attr.key in blueprint['axis_values']:
                values = blueprint['axis_values'][attr.key]
            if attr.key in AXES[family]:
                axes.append(axis(attr.key, family, sorted(values)))
            else:
                shared[attr.key] = [values[0]] if attr.value_type == 'string_set' else values[0]
        if blueprint is not None:
            shared.update(copy.deepcopy(blueprint['shared_attributes']))
        if family == 'beer':
            regions = [r for c, r in RELATIONS['beer'][0]['rows'] if c == shared['origin_country']]
            shared['production_region'] = choose(seed, root + '/field/production_region', regions,
                                                 settings['field_weights']['beer.production_region'])[0]
        group = {'schema_version': GROUP_VERSION, 'group_id': model_id, 'family': family,
                 'name': name, 'axes': axes, 'variants': []}
        candidates = list(itertools.product(*(a['options'] for a in axes)))
        anchor = rng(seed, root + '/anchor').randrange(len(candidates))
        if blueprint is not None:
            anchor = next(j for j, values in enumerate(candidates)
                if all(next(o['value'] for a,o in zip(axes, values) if a['field']==k)==v
                       for k,v in blueprint['anchor_attributes'].items()))
        base = rng(seed, root + '/reference').randint(*{'footwear': (600, 1400), 'laptops': (5500, 9500),
                                                     'dog_food': (45, 90), 'cat_food': (55, 110),
                                                     'beer': (15, 35), 'wine': (70, 220)}[family])
        if blueprint is not None:
            base = rng(seed, root + '/reference').randint(*blueprint['reference_range_sek'])
        omitted, recipes = [], {}
        # Recipe ingredients and per-kg price are shared across pack-size siblings.
        if family in ('dog_food', 'cat_food'):
            for recipe in next(a for a in axes if a['field'] == 'recipe')['options']:
                protein = recipe['value']
                ingredients = [protein, 'rice', 'sunflower oil', 'minerals']
                if rng(seed, root + '/recipe/' + protein + '/wheat').random() < settings['wheat_probability']:
                    ingredients.append('wheat')
                if rng(seed, root + '/recipe/' + protein + '/extra').random() < settings['extra_protein_probability']:
                    ingredients.append(rng(seed, root + '/recipe/' + protein + '/extra-value').choice([x for x in ('chicken', 'beef', 'salmon') if x != protein]))
                recipes[protein] = sorted(set(ingredients))
        for j, options in enumerate(candidates):
            selection = {a['field']: o['id'] for a, o in zip(axes, options)}
            variant_key = digest(selection)
            if j != anchor and rng(seed, root + '/omit/' + variant_key).random() < settings['variant_omission_probability']:
                omitted.append(selection); continue
            facts = {**copy.deepcopy(shared), **{a['field']: o['value'] for a, o in zip(axes, options)}}
            if family == 'footwear':
                # Ordinary fit/cosmetic options share a commercial model price.
                # Retailer-specific size surcharges are sampled separately.
                reference = base + (150 if facts['waterproof'] else 0)
            elif family == 'laptops':
                reference = base + (facts['ram_gb'] - 16) * 75 + (facts['storage_gb'] - 256) * 3
            elif family in ('dog_food', 'cat_food'):
                facts['ingredients'] = recipes[facts['recipe']].copy()
                rate = base * (1.8 if facts['food_type'] == 'wet' else 1) + {'chicken': 0, 'salmon': 15, 'lamb': 10, 'turkey': 8}[facts['recipe']]
                weight = facts['net_weight_kg']
                # Linear weight term plus fixed packaging: larger packs cost more,
                # while price per kg falls, holding recipe/model fixed.
                reference = 25 + weight * rate
            else:
                volume_unit = 330 if family == 'beer' else 750
                count = facts['pack_count']
                discount = min(.2, .01 * (count - 1))
                reference = base * facts['volume_ml'] / volume_unit * count * (1 - discount)
            sku = model_id + '-sku-' + variant_key[:12]
            products.append({'product_id': sku, 'name': name + ' — ' + ' / '.join(o['label'] for o in options),
                'category': family, 'reference_price_minor': price_minor(reference, settings['reference_price_multiplier']),
                'attributes': facts, 'traits': []})
            group['variants'].append({'product_id': sku, 'selection': selection})
        groups.append(group)
        provenance.append({'model_id': model_id, 'family': family, 'base_reference_sek': base,
            'candidate_combinations': len(candidates), 'anchor_selection': {a['field']: o['id'] for a, o in zip(axes, candidates[anchor])},
            'omitted_combinations': omitted, 'namespace': root})
    public = {'products': products, 'product_groups': groups}
    bundle = {'schema_version': VERSION, 'seed': seed, 'model_count': model_count, 'config': settings,
              'public': public, 'catalog_sha256': digest(public),
              'private_provenance': {'models': provenance, 'priors': 'authored_not_empirically_calibrated',
                  'family_plan': copy.deepcopy(model_families),
                  'identity_plan': copy.deepcopy(model_identities),
                  'structural_rule': 'one seed-selected anchor tuple per model is always retained; omission applies to other tuples'}}
    if model_blueprints is not None:bundle['private_provenance']['model_blueprints']=copy.deepcopy(model_blueprints)
    from .validation import validate_catalog
    validate_catalog(bundle)
    return bundle


def summarize(bundle):
    models = Counter(g['family'] for g in bundle['public']['product_groups'])
    skus = Counter(p['category'] for p in bundle['public']['products'])
    rows = bundle['private_provenance']['models']
    candidates = sum(r['candidate_combinations'] for r in rows)
    omitted = sum(len(r['omitted_combinations']) for r in rows)
    trials = candidates - len(rows)
    return {'models_by_family': dict(models), 'skus_by_family': dict(skus),
            'models': sum(models.values()), 'skus': sum(skus.values()),
            'candidate_combinations': candidates, 'omitted_combinations': omitted,
            'omission_eligible_combinations': trials,
            'realized_nonanchor_omission_fraction': omitted / trials if trials else None,
            'catalog_sha256': bundle['catalog_sha256']}
