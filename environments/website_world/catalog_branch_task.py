"""Named-city branch stock over retained feature/listed-price semantics."""
from copy import deepcopy
import unicodedata

from . import basic_offer_task, feature_offer_task
from .adapter import digest
from experiments import source_binding

VERSION = 'website-catalog-branch-stock-task-v1'
KIND = 'cheapest_matching_local_branch_stock'


def text(value):
    return ' '.join(unicodedata.normalize('NFC', value).split()).casefold()


def feature_spec(spec):
    return {'kind': feature_offer_task.KIND, 'availability': 'positive_stock',
            **{k: deepcopy(spec[k]) for k in
               ('concept_id', 'predicates', 'max_price_minor', 'comparison_site_id') if k in spec}}


def resolve(value, *, inventory, concept_ids):
    allowed = {'kind', 'concept_id', 'predicates', 'city', 'country',
               'max_price_minor', 'comparison_site_id'}
    if type(value) is not dict or set(value)-allowed or value.get('kind') != KIND:
        raise ValueError('Declare a named-city branch-stock task')
    city, country = value.get('city'), value.get('country', 'SE')
    if type(city) is not str or not city.strip() or len(city) > 80:
        raise ValueError('Declare a nonempty city name of at most80 characters')
    if (type(country) is not str or len(country) != 2 or
            not country.isascii() or not country.isalpha() or country != country.upper()):
        raise ValueError('Declare a two-letter uppercase country code')
    base = feature_offer_task.resolve(feature_spec(value), inventory=inventory, concept_ids=concept_ids)
    base.pop('availability')
    return {**base, 'kind': KIND, 'city': ' '.join(city.split()), 'country': country}


def selection(task):
    return {k: deepcopy(task[k]) for k in
            ('kind', 'concept_id', 'predicates', 'city', 'country',
             'max_price_minor', 'comparison_site_id') if k in task}


def branch_inventory(world):
    # All branches, including disabled/empty/remote branches, are retained for
    # identity resolution. Requirements and stock never disambiguate a name.
    return {r['retailer_id']: [
        {'retailer_id': r['retailer_id'], 'branch_id': b['branch_id'],
         'branch_name': b['name'], 'city': b['location']['city'],
         'country': b['location']['country'], 'pickup_enabled': b['pickup_enabled']}
        for b in r['geography']['branches']] for r in world['retailers']}


def make(world, spec, *, inventory, surrounding=None):
    selected = resolve(spec, inventory=inventory, concept_ids=world['config']['concept_ids'])
    base = feature_offer_task.make(world, feature_spec(selected), inventory=inventory,
                                   surrounding=surrounding)
    requirements = '; '.join(feature_offer_task._wording(p, inventory.fields[p['field']])
                             for p in selected['predicates'])
    scope = 'across the retailers in this world'
    if 'comparison_scope' in base:
        scope = 'among retailer listings shown on '+base['comparison_scope']['site_name']
    message = ('Find the cheapest listed price for one sale unit of '+
        basic_offer_task.LABELS[selected['concept_id']]+' '+scope+'. Requirements: '+
        requirements+'. Require positive physical stock of that exact variant at '
        'a pickup-enabled retailer branch in '+selected['city']+', '+selected['country']+'. '
        'Warehouse stock, transfers from another source and supplier orders do not qualify. '
        'Unknown or not-applicable specifications do not establish a match. Compare '
        'listed item prices only; shipping, transfer and collection fees are outside '
        'this price comparison. Opening hours, immediate readiness and travel time '
        'are not requirements. Tell me the product, exact variant, retailer, product '
        'link, listed price in SEK, and the branch name and city. ')
    if 'max_price_minor' in selected:
        cap = selected['max_price_minor']
        message += f'The listed price must be at most {cap//100}.{cap%100:02d} SEK. '
    message += 'If no option establishes all requirements, say so. Do not reserve or buy anything.'
    task = {**base, **selected, 'schema_version': VERSION, 'feature_task': base,
            'availability': 'positive_pickup_branch_stock', 'user_message': message,
            'collection_scope': 'one_sale_unit_physically_at_named_city_branch'}
    task.pop('task_id')
    task['task_id'] = 'catalog-branch-stock-'+digest(task)[:24]
    return task


def reference(world, task, *, inventory, surrounding=None):
    if not source_binding.compatible(task, make(world, selection(task), inventory=inventory, surrounding=surrounding)):
        raise ValueError('Branch task/world/declaration binding changed')
    features = feature_offer_task.reference(world, task['feature_task'], inventory=inventory,
                                            surrounding=surrounding)
    branches = branch_inventory(world)
    retailers = {r['retailer_id']: r for r in world['retailers']}
    candidates, branch_rows = [], []
    for offer in features['candidates']:
        retailer = retailers[offer['retailer_id']]
        raw = next(o for o in retailer['offers'] if o['offer_id'] == offer['offer_id'])
        sources = {s['source_id']: s for s in retailer['source_locations']}
        rows = []
        for branch in branches[retailer['retailer_id']]:
            bid = branch['branch_id']
            if (branch['pickup_enabled'] and text(branch['city']) == text(task['city'])
                    and branch['country'] == task['country'] and
                    sources[bid]['kind'] == 'branch' and raw['stock_by_source'][bid] > 0):
                rows.append({**deepcopy(offer), **deepcopy(branch),
                             'physical_stock': raw['stock_by_source'][bid]})
        if rows:
            candidates.append(deepcopy(offer))
            branch_rows.extend(rows)
    # The retained feature reference already orders offer rows by listed price.
    price = candidates[0]['price_minor'] if candidates else None
    return {**features, 'schema_version': VERSION, 'task_id': task['task_id'],
            'status': 'match' if candidates else 'no_match', 'minimum_price_minor': price,
            'candidates': candidates, 'winners': [r for r in candidates if r['price_minor'] == price],
            'feature_reference': features, 'branch_inventory': branches,
            'branch_candidates': branch_rows,
            'branch_winners': [r for r in branch_rows if r['price_minor'] == price],
            'collection_scope': task['collection_scope']}
