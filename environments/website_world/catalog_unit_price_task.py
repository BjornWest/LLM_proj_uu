"""Known whole-pack food mass and exact listed SEK/kg ranking."""
from copy import deepcopy, copy
from fractions import Fraction

from . import feature_offer_task as feature
from .adapter import digest
from experiments import source_binding

VERSION = 'website-catalog-unit-price-task-v2'
KIND = 'cheapest_matching_unit_price'
BASIS = 'net_food_mass_kg'
CONCEPTS = ('cat_food.dry_food', 'dog_food.dry_food')
FIELD = 'sku.net_mass_g'


def quantity_inventory(world, inventory):
    """Explicit closed capability for source-bound manufactured quantity members.

    Old pet-food samplers retain canonical required SKU quantities but omit their
    separate logical status. This adapter trusts only the exact retained native
    manufacture plus its declaration-source receipt. It never treats arbitrary
    numeric presence as knowledge or changes explicit unknown/NA statuses.
    """
    declaration_sources = {n:h for n,h in inventory.source_hashes.items()
        if n.startswith('environments/product_world/data/product_width/')}
    absent, proven, unresolved = [], [], []
    for item in world['products']:
        product = item['public']
        if product['concept_id'] != inventory.concept_id: continue
        if not any(FIELD not in item.get('sku_status',{}).get(s['sku_id'],{}) for s in product['skus']):continue
        absent.append(product['product_id'])
        private = item.get('private',{})
        sample = private.get('sample',{})
        gate = private.get('commerce_source_gate',{})
        original = sample.get('entities',{}).get('product',{})
        canonical = original.get('skus')
        bound = (sample.get('schema_version') == 'product-package-v1'
            and sample.get('concept_id') == inventory.concept_id
            and gate.get('capability') == 'accepted_package_sampler'
            and all(gate.get('source_hashes',{}).get(n) == h for n,h in declaration_sources.items())
            and original.get('product_id') == product['product_id']
            and type(canonical) is list and bool(canonical)
            and canonical == product['skus']
            and len({s.get('sku_id') for s in canonical}) == len(canonical)
            and all(s.get('product_id') == product['product_id'] and type(s.get('net_mass_g')) is int
                for s in canonical))
        if not bound:
            unresolved.append(product['product_id'])
            continue
        proven.append({'product_id':product['product_id'],
            'canonical_sku_menu_sha256':digest(canonical),'declaration_source_sha256':deepcopy(declaration_sources)})
    capability = bool(absent) and not unresolved
    derived = copy(inventory)
    if capability: derived.known_paths = (*inventory.known_paths, FIELD)
    return derived, {'version':'manufactured_net_food_quantity-capability-v1',
        'mode':'exact_source_bound_canonical_manufacture' if capability else 'explicit_status_only',
        'field':FIELD, 'source_bound_models':proven, 'unproven_model_ids':sorted(unresolved),
        'explicit_unknown_na_override_capability':True,
        'public_disclosure_or_exposure':'not_inferred'}


def _inner(spec):
    predicates = deepcopy(spec.get('predicates', []))
    if type(predicates) is not list:
        raise ValueError('Predicates must be a list')
    return {**{k: deepcopy(v) for k, v in spec.items() if k != 'unit_basis'},
            'kind': feature.KIND,
            'predicates': predicates + [{'field': FIELD, 'operator': 'gt', 'value': 0, 'unit': 'g'}]}


def resolve(spec, *, inventory, concept_ids):
    if (type(spec) is not dict or spec.get('kind') != KIND or spec.get('unit_basis') != BASIS
            or inventory.concept_id not in CONCEPTS):
        raise ValueError('Declare net_food_mass_kg for accepted dry cat/dog food')
    predicates = spec.get('predicates', [])
    if type(predicates) is not list:
        raise ValueError('Predicates must be a list')
    definition = inventory.fields.get(FIELD, {})
    if definition.get('type') != 'integer' or definition.get('unit') != 'g':
        raise ValueError('Unit-price capability requires declared integer net food grams')
    inner = feature.resolve(_inner(spec), inventory=inventory, concept_ids=concept_ids)
    return {**inner, 'kind': KIND, 'unit_basis': BASIS,
            'predicates': deepcopy(inner['predicates'][:-1])}


def make(world, spec, *, inventory, surrounding=None):
    selection = resolve(spec, inventory=inventory, concept_ids=world['config']['concept_ids'])
    derived, provenance = quantity_inventory(world, inventory)
    inner = feature.make(world, _inner(selection), inventory=derived, surrounding=surrounding)
    message = inner['user_message'].replace('Find the cheapest available',
        'Find the available option with the lowest listed SEK price per kilogram of net food', 1)
    message += (' Compare listed whole-pack price divided by the manufactured net food mass, '
                'excluding packaging, animal weight and daily feeding portions. '
                'Use the exact ratios to rank; do not rank by rounded displayed unit prices. '
                'A cheaper pack price alone does not determine the answer. '
                'Require known, applicable positive net food mass. Report the model, retailer, '
                'explicit pack/variant, retailer product link, listed whole-pack SEK price, '
                'net food mass as an integer number of g, and SEK per kg rounded to two decimals '
                'with half-up rounding. Shipping, coupons, cart extras and purchase effects are excluded.')
    task = {'schema_version': VERSION, **selection, 'world_id': world['world_id'],
            'world_sha256': digest(world), 'feature_task': inner, 'quantity_field': FIELD,
            'quantity_unit': 'g', 'unit_price_unit': 'kg', 'normalization_factor': 1000,
            'quantity_basis': 'manufactured whole-bag net food mass, excluding packaging',
            'quantity_provenance': provenance,
            'ranking': 'exact_integer_ratio_then_all_ties', 'display_rounding': 'SEK_2dp_half_up',
            'user_message': message, 'memories': []}
    task['task_id'] = 'catalog-unit-price-'+digest(task)[:24]
    return task


def ratio(price_minor, mass_g):
    if type(price_minor) is not int or price_minor < 0 or type(mass_g) is not int or mass_g <= 0:
        raise ValueError('Unit price requires nonnegative integer ore and positive integer net grams')
    return Fraction(price_minor * 1000, mass_g)


def serialize_ratio(value):
    return {'numerator': value.numerator, 'denominator': value.denominator}


def rounded_minor(value):
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def reference(world, task, *, inventory, surrounding=None):
    spec = {k: deepcopy(task[k]) for k in ('kind','concept_id','predicates','availability',
            'max_price_minor','comparison_site_id','unit_basis') if k in task}
    if not source_binding.compatible(task, make(world, spec, inventory=inventory, surrounding=surrounding)):
        raise ValueError('Unit-price task/world/quantity declaration binding changed')
    derived, _ = quantity_inventory(world, inventory)
    inner = feature.reference(world, task['feature_task'], inventory=derived, surrounding=surrounding)
    skus = {s['sku_id']: s for p in world['products'] for s in p['public']['skus']}
    candidates = []
    for row in inner['candidates']:
        mass = skus[row['sku_id']]['net_mass_g']
        cost = ratio(row['price_minor'], mass)
        candidates.append({**deepcopy(row), 'quantity_g': mass,
            'unit_price_exact': serialize_ratio(cost), 'unit_price_minor': rounded_minor(cost)})
    candidates.sort(key=lambda r: (Fraction(r['unit_price_exact']['numerator'],
        r['unit_price_exact']['denominator']), r['offer_id']))
    minimum = candidates[0]['unit_price_exact'] if candidates else None
    return {'schema_version': VERSION, 'task_id': task['task_id'], 'world_id': world['world_id'],
            'status': 'match' if candidates else 'no_match', 'unit_basis': BASIS,
            'minimum_unit_price_exact': deepcopy(minimum),
            'minimum_unit_price_minor': candidates[0]['unit_price_minor'] if candidates else None,
            'candidates': candidates, 'winners': [r for r in candidates if r['unit_price_exact'] == minimum],
            'feature_reference': inner, 'ranking': task['ranking'],
            'evidence_coverage': 'not_inferred_from_native_truth'}
