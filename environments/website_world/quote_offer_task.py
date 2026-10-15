"""Single-sale-unit delivered objectives over the unchanged prepared quote API.

This explicitly scoped task excludes extra purchases/new memberships/coupons.
Native matching/quote feasibility and public disclosure are separate contracts.
"""
from copy import deepcopy
from datetime import date
from hashlib import sha256
from pathlib import Path

from experiments.accepted_catalog_commerce import basket_quote
from . import basic_offer_task, feature_offer_task
from .adapter import browser_address, digest
from experiments import source_binding

VERSION = 'website-single-item-quote-task-v1'
KIND = 'matching_single_item_delivery'
TYPES = ('home', 'parcel_locker', 'staffed_counter')
TYPE_LABELS = {'home': 'home delivery', 'parcel_locker': 'pickup locker',
               'staffed_counter': 'staffed collection point'}
ROOT = Path(__file__).resolve().parents[2]


def feature_spec(spec):
    return {'kind': feature_offer_task.KIND, **{k: deepcopy(spec[k]) for k in
        ('concept_id', 'predicates', 'availability', 'comparison_site_id') if k in spec}}


def resolve(value, *, inventory, concept_ids):
    allowed = {'kind', 'concept_id', 'predicates', 'availability', 'comparison_site_id',
               'objective', 'destination', 'delivery_types', 'max_total_minor', 'arrival_deadline'}
    if type(value) is not dict or set(value)-allowed or value.get('kind') != KIND:
        raise ValueError('Declare a matching_single_item_delivery task')
    base = feature_offer_task.resolve(feature_spec(value), inventory=inventory, concept_ids=concept_ids)
    result = {**base, 'kind': KIND, 'objective': value.get('objective', 'cheapest_total'),
              'destination': value.get('destination', 'user_home'),
              'delivery_types': deepcopy(value.get('delivery_types', ['home']))}
    if result['objective'] not in ('cheapest_total', 'fastest_then_cheapest'):
        raise ValueError('Declare cheapest_total or fastest_then_cheapest')
    if result['destination'] != 'user_home':
        raise ValueError('V1 supports the generated user home destination only')
    types = result['delivery_types']
    if (type(types) is not list or not types or any(type(t) is not str or t not in TYPES for t in types)
            or len(set(types)) != len(types)):
        raise ValueError('Declare unique home/locker/staffed delivery types; branch pickup is separate')
    result['delivery_types'] = sorted(types)
    if 'max_total_minor' in value:
        cap = value['max_total_minor']
        if type(cap) is not int or cap < 0:
            raise ValueError('Delivered price threshold must be nonnegative integer ore')
        result['max_total_minor'] = cap
    if 'arrival_deadline' in value:
        token = value['arrival_deadline']
        if type(token) is not str:
            raise ValueError('Declare an ISO arrival deadline')
        try:
            parsed = date.fromisoformat(token)
        except ValueError as error:
            raise ValueError('Declare an ISO arrival deadline') from error
        if parsed.isoformat() != token:
            raise ValueError('Declare an ISO arrival deadline')
        result['arrival_deadline'] = token
    return result


def _check_quote_binding(world, quote_context):
    binding = quote_context.binding
    if (binding.get('world_id') != world['world_id'] or
            binding.get('world_sha256') != basket_quote.model.digest(world)):
        # Native shipping uses its historical digest format; do not substitute
        # the compact website digest or silently repair either identity.
        raise ValueError('Prepared quote/world binding changed')
    for name, expected in binding['source_sha256'].items():
        if sha256((ROOT/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Prepared quote source changed: '+name)
    return binding


def home_record(world):
    records = [a for a in world['address_context']['addresses'] if a['address_id'] == 'user-home']
    if len(records) != 1:
        raise ValueError('Declare one generated user-home address')
    return records[0]


def make(world, selection, *, inventory, quote_context, surrounding=None):
    spec = resolve(selection, inventory=inventory, concept_ids=world['config']['concept_ids'])
    binding = _check_quote_binding(world, quote_context)
    base = feature_offer_task.make(world, feature_spec(spec), inventory=inventory, surrounding=surrounding)
    record = home_record(world)
    address = browser_address(record)
    requirements = '; '.join(feature_offer_task._wording(p, inventory.fields[p['field']])
                             for p in spec['predicates'])
    scope = 'across the shops in this world'
    if 'comparison_scope' in base:
        scope = 'among products and retailer listings shown on '+base['comparison_scope']['site_name']
    ranking = ('Find the cheapest complete delivered total' if spec['objective'] == 'cheapest_total'
               else 'Find the option with the earliest latest estimated arrival date, breaking ties by complete delivered total')
    message = (f'{ranking} for one sale unit of {basic_offer_task.LABELS[spec["concept_id"]]} {scope}. '
        'Requirements: '+requirements+'. Use known, applicable specifications; unknown or '
        'not-applicable values do not establish a match. Order exactly one sale unit (the whole '
        'pack if sold as a pack), with no extra items, coupons or newly purchased memberships. '
        'Include shipping and any already-active shipping benefit in the payable total; do not '
        'compare normalized per-unit prices. Deliver to '+', '.join(address.values())+'. '
        'Allowed delivery methods: '+', '.join(TYPE_LABELS[t] for t in spec['delivery_types'])+'. ')
    if spec['availability'] == 'positive_stock':
        message += 'Require positive physical stock; supplier-only orders do not count. '
    else:
        message += 'Supplier orders count only if the complete delivery option is available. '
    if 'max_total_minor' in spec:
        cap = spec['max_total_minor']
        message += f'The complete payable total must be at most {cap//100}.{cap%100:02d} SEK. '
    if 'arrival_deadline' in spec:
        message += 'Require the latest estimated arrival date to be on or before '+spec['arrival_deadline']+'. '
    if spec['objective'] == 'cheapest_total':
        message += 'Arrival speed is not a preference beyond any stated deadline. '
    message += ('Tell me the product, exact variant, retailer, product link, complete payable total '
        'in SEK, carrier and service tier, delivery method, and collection point if used. '
        'When a date is needed for a deadline or fastest ranking, state the latest estimated '
        'arrival date in YYYY-MM-DD form; estimates are not guarantees. If no option establishes '
        'all requirements, say so. Do not place an order.')
    task = {**base, **deepcopy(spec), 'schema_version': VERSION, 'price_basis': 'complete_single_item_payable',
        'user_message': message, 'destination_address': address, 'quote_binding': binding,
        'destination_sha256': digest(record['location']),
        'quote_as_of': world['quote_as_of'], 'feature_task': base,
        'order_domain': {'quantity': 1, 'extra_items': False, 'new_memberships': False, 'coupons': False}}
    task.pop('task_id')
    task['task_id'] = 'quote-offer-'+digest(task)[:24]
    return task


def score(task, option):
    if task['objective'] == 'cheapest_total':
        return [option['total_minor']]
    return [option['arrival']['latest_date'], option['total_minor']]


def reference(world, task, *, inventory, quote_context, surrounding=None):
    spec = {k: task[k] for k in ('kind', 'concept_id', 'predicates', 'availability',
        'comparison_site_id', 'objective', 'destination', 'delivery_types', 'max_total_minor',
        'arrival_deadline') if k in task}
    rebuilt = make(world, spec, inventory=inventory, quote_context=quote_context, surrounding=surrounding)
    if task != rebuilt:
        changes = source_binding.substantive_changes(task, rebuilt)
        if source_binding.mode() == 'pinned' or changes:
            raise ValueError('Quote task/world/declaration/plan binding changed' + (': ' + ', '.join(changes[:8]) if changes else ''))
    features = feature_offer_task.reference(world, task['feature_task'], inventory=inventory, surrounding=surrounding)
    carriers = {c['carrier_id']: c['name'] for c in world['address_context']['carriers']}
    points = {p['point_id']: p['name'] for p in world['address_context']['collection_points']}
    rows, candidates, quote_inventory = [], [], []
    for offer in features['candidates']:
        oid = offer['offer_id']
        quote = quote_context.quote(offer['retailer_id'], [{'line_id': oid, 'offer_id': oid, 'quantity': 1}],
                                    destination=home_record(world)['location'], split=False)
        quote_inventory.append({'offer_id': oid, 'quote_id': quote['quote_id'], 'status': quote['status'],
                                'option_ids': [o['option_id'] for o in quote['options']]})
        for option in quote['options']:
            if len(option['shipments']) != 1 or set(option['selection']) != {oid}:
                raise ValueError('Single-item native quote produced a different order shape')
            delivery = option['shipments'][0]['delivery']
            row = {**deepcopy(offer), 'quote_id': quote['quote_id'], 'option': deepcopy(option),
                'choice_id': option['selection'][oid], 'delivery': deepcopy(delivery),
                'carrier_name': carriers.get(delivery.get('carrier_id')),
                'point_name': points.get(delivery.get('point_id'))}
            # Retain every option for independent service identity resolution.
            # Do not use task eligibility, cost or timing to repair its identity.
            rows.append(row)
            arrival = option['arrival']
            if delivery['destination_type'] not in task['delivery_types']:
                continue
            if task['availability'] == 'positive_stock' and any(
                    item['supply'] != 'on_hand' for shipment in option['shipments'] for item in shipment['items']):
                # Stock at a nonshipping branch does not turn a home-delivery
                # supplier order into physical-stock fulfilment.
                continue
            if 'max_total_minor' in task and option['total_minor'] > task['max_total_minor']:
                continue
            if task['objective'] == 'fastest_then_cheapest' or 'arrival_deadline' in task:
                if arrival['status'] != 'estimated' or arrival['latest_date'] is None:
                    continue
                if 'arrival_deadline' in task and arrival['latest_date'] > task['arrival_deadline']:
                    continue
            candidates.append(row)
    candidates.sort(key=lambda r: (score(task, r['option']), r['offer_id'], r['choice_id']))
    optimum = score(task, candidates[0]['option']) if candidates else None
    return {'schema_version': VERSION, 'task_id': task['task_id'], 'world_id': world['world_id'],
        'world_sha256': task['world_sha256'], 'quote_binding': task['quote_binding'],
        'status': 'match' if candidates else 'no_match', 'currency': 'SEK', 'objective': task['objective'],
        'optimal_score': optimum, 'feature_reference': features, 'quote_inventory': quote_inventory,
        'all_options': rows, 'candidates': candidates,
        'winners': [r for r in candidates if score(task, r['option']) == optimum],
        'evidence_coverage': 'native_truth_does_not_establish_public_disclosure_or_visits'}
