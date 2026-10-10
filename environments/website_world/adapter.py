"""Explicit public projection of the frozen native footwear world.

Private tasks, profiles, traces and references never enter these return values.
The producer remains authoritative for identities, prices, stock and quotes.
"""
from copy import deepcopy
from environments.product_world.public_field_rules import is_public_field
from hashlib import sha256
from pathlib import Path
import json
import re

from experiments.address_checkout_pilot.model import resolve
from experiments.address_checkout_pilot.model import autofill
from experiments.footwear_world_pilot import model

VERSION = 'footwear-pages-public-adapter-v1'
ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT / '.local/coordination/website-world-integration/first-journey-v1'


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_pin(path=PIN):
    path = Path(path)
    manifest = json.loads((path / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        if Path(name).name != name or sha256((path / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Pin artifact mismatch: {name}')
    # Quote behavior must remain the accepted producer behavior.
    for name in ('experiments/footwear_world_pilot/model.py',
                 'experiments/address_checkout_pilot/model.py',
                 'experiments/carrier_service_pilot/model.py',
                 'experiments/carrier_location_pilot/model.py'):
        if sha256((ROOT / name).read_bytes()).hexdigest() != manifest['current_source_sha256'][name]:
            raise ValueError(f'Pinned quote source mismatch: {name}')
    world = json.loads((path / 'world.json').read_text())
    if world['schema_version'] != 'footwear-world-pilot-v1' or world['world_id'] != manifest['world_id']:
        raise ValueError('Incompatible footwear world')
    return world, manifest


def browser_address(record):
    a = record['address']
    street = f"{a['street']} {a['house_number']}"
    if a['unit']:
        street += f", Lägenhetsnummer {a['unit']}"
    return {'name': a['recipient'], 'street': street, 'postcode': a['postcode'], 'city': a['city']}


def supported_destination(world, address):
    if set(address) not in ({'name', 'street', 'postcode', 'city'}, {'name', 'street', 'unit', 'postcode', 'city'}):
        raise ValueError('Supply recipient, street address, postcode and city')
    if any(not isinstance(v, str) or len(v) > 200 for v in address.values()):
        raise ValueError('Invalid address fields')
    match = re.fullmatch(r'\s*(.+?)\s+(\d+[A-Za-z]?)(?:\s*,?\s*(?:Lägenhetsnummer|Apartment|Apt)\s+(\w+))?\s*', address['street'], re.I)
    if not match:
        raise ValueError('Enter a supported street address, house number and apartment')
    street, number, unit = match.groups()
    if 'unit' in address:
        if unit and address['unit'] and unit.casefold() != address['unit'].casefold():
            raise ValueError('Apartment numbers disagree')
        unit = address['unit'] or unit
    result = resolve(world['address_context'], {
        'recipient': address['name'], 'street': street, 'house_number': number,
        'unit': unit or '', 'postcode': address['postcode'], 'city': address['city'], 'country': 'SE'})
    if result['status'] != 'supported' or result['precision'] != 'known_synthetic_building':
        raise ValueError('Delivery is unavailable for this address')
    # Do not publish resolver precision, hidden home distances or building keys.
    return result['location']


class PublicAdapter:
    def __init__(self, world, *, basket_plan=None,oracle=None):
        self.world = world
        self.products = {p['public']['product_id']: p for p in world['products']}
        self.retailers = {r['retailer_id']: r for r in world['retailers']}
        self.brands = {b['brand_id']: b['name'] for b in world['brands']}
        self.initial_address = browser_address(next(a for a in world['address_context']['addresses'] if a['address_id'] == 'user-home'))
        self.cache = {}
        self.fields = []  # Private explicit field/entity bindings, not prose annotations.
        self.basket_fulfilment_enabled=oracle is not None
        self.delivery_orders={}
        if oracle is not None:
            if basket_plan is None:raise ValueError('Item basket oracle requires its plan')
            oracle.validate_plan(world,basket_plan)
            self.oracle,self.plan=oracle,deepcopy(basket_plan)

    def fulfilment(self, retailer_id, address):
        if self.basket_fulfilment_enabled:
            from .basket_fulfilment import project
            return project(self,retailer_id,address)
        destination = supported_destination(self.world, address)
        key = (retailer_id, digest([destination, address]))
        if key in self.cache:
            return deepcopy(self.cache[key])
        r = self.retailers[retailer_id]
        points = {p['point_id']: p for p in self.world['address_context']['collection_points']}
        source_labels = {s['source_id']: s['location']['city'] + ' warehouse' for s in r['source_locations']}
        source_labels.update({b['branch_id']: b['name'] for b in r['geography']['branches']})
        options = {}
        for offer in r['offers']:
            rows = []
            for q in model.delivery_options(self.world, r, offer, destination=destination):
                point = points.get(q['point_id'])
                location = {'id': q['point_id'] or 'home',
                            'name': point['name'] if point else 'Your address',
                            'address': point.get('address', point['location']['city']) if point else
                                f"{address['street']}" + (f", Apartment {address['unit']}" if address.get('unit') else '') +
                                f", {address['postcode']} {address['city']}"}
                # A chosen home service survives an address edit when still
                # available; changed dates/fees are values, not service identity.
                identity = [offer['offer_id'], q['source_id'], q['carrier_id'], q['tier'], q['destination_type'], q['point_id']]
                rows.append({'id': 'delivery-' + digest(identity)[:24],
                    'offerId': offer['offer_id'], 'skuId': offer['sku_id'],
                    'sourceId': q['source_id'], 'carrierId': q['carrier_id'],
                    'company': q['carrier_name'], 'name': q['tier'].capitalize() + f" — dispatch from {source_labels[q['source_id']]}",
                    'tier': q['tier'], 'type': q['destination_type'], 'location': location,
                    'arrival': q['arrival_date'], 'readyDays': q['ready_days'],
                    'shippingMinor': q['shipping_minor'], 'totalMinor': q['total_minor'],
                    'fee': q['shipping_minor'] / 100, 'tariff': q['shipping_minor'] / 100,
                    'qualified': False, 'local': False, 'payment': 'online',
                    'supply': q['supply'], 'supplierWaitDays': q['supplier_wait_days'],
                    'scheduling': q['scheduling'], 'collectionHours': q['collection_hours']})
            options[offer['sku_id']] = rows
        result = {'address': deepcopy(address), 'optionsBySku': options}
        self.cache[key] = result
        return deepcopy(result)

    def catalog(self, retailer_id, configuration, *, presentation=None):
        r = self.retailers[retailer_id]
        offers = {o['sku_id']: o for o in r['offers']}
        seen = set()
        output = []
        fulfilment = self.fulfilment(retailer_id, self.initial_address)
        sources = {s['source_id']: s for s in r['source_locations']}
        for entry in r['catalog']:
            item = self.products[entry['product_id']]
            public = item['public']
            manufactured = {s['sku_id']: s for s in public['skus']}
            for page in entry['pages']:
                page_id = 'page-' + digest([public['product_id'], page['page_key']])[:24]
                options = [{'key': key, 'label': {'colour': 'Colour', 'width': 'Width', 'size_eu': 'Size (EU)'}[key],
                            'values': [str(v) for v in values]} for key, values in page['selectors'].items()]
                variants = []
                for listing in page['listings']:
                    sku_id = listing['sku_id']
                    if sku_id in seen or sku_id not in offers or sku_id not in manufactured:
                        raise ValueError('Page listing must resolve one unique carried manufactured SKU')
                    seen.add(sku_id)
                    sku, offer = manufactured[sku_id], offers[sku_id]
                    if offer['product_id'] != public['product_id'] or offer['currency'] != 'SEK':
                        raise ValueError('Invalid authoritative offer binding')
                    stock = [{'sourceId': sid, 'quantity': quantity, 'kind': sources[sid]['kind'],
                              'shippingEnabled': sources[sid]['shipping_enabled'],
                              'name': sources[sid]['location']['city']} for sid, quantity in offer['stock_by_source'].items()]
                    dispatch = [s for s in stock if s['shippingEnabled'] and s['quantity'] > 0]
                    state = 'in_stock' if dispatch else 'backorder' if offer['supplier_order']['enabled'] else 'in_stock' if any(s['quantity'] > 0 for s in stock) else 'unavailable'
                    groups = [{'role': 'configuration', 'heading': 'Selected configuration', 'facts': [
                        {'label': {'colour': 'Colour', 'width': 'Width', 'size_eu': 'Size (EU)'}[axis],
                         'value': str(sku[axis])} for axis in ('colour', 'width', 'size_eu')]}]
                    facts = []
                    for field in item['retail_content']['fields']:
                        if field['scope'] != 'product' or field['id'] not in public['facts']:
                            continue
                        if field.get('concepts') and public['concept'] not in field['concepts']:
                            continue
                        if (not is_public_field(field['path']) or
                                field.get('evidence_status') in ('unknown','not_applicable') or
                                public.get('fact_status',{}).get(field['id']) in ('unknown','not_applicable') or
                                public['facts'][field['id']] is None):
                            continue
                        value = deepcopy(public['facts'][field['id']])
                        if isinstance(value, dict):
                            value = [f'{k}: {v}' for k, v in value.items()]
                        if isinstance(value, bool):
                            value = 'Yes' if value else 'No'
                        fact = {'label': field['label'], 'value': value,
                                'status': field.get('evidence_status', 'known')}
                        if field.get('qualifiers'):
                            fact['qualifier'] = '; '.join(str(v) for v in field['qualifiers'].values())
                        facts.append(fact)
                        self.fields.append({'retailer_id': retailer_id, 'page_id': page_id,
                            'sku_id': sku_id, 'field': field['path'], 'label': field['label'],
                            'subject_id': public['product_id'], 'authority': 'catalog_facts'})
                    groups.append({'role': 'descriptive', 'heading': 'Product details', 'facts': facts})
                    pickup = model.pickup_options(self.world, r, offer, include_transfers=True)
                    variants.append({'key': sku_id, 'skuId': sku_id, 'offerId': offer['offer_id'],
                        'selection': {o['key']: str(sku[o['key']]) for o in options},
                        'price': offer['price_minor'] / 100, 'priceMinor': offer['price_minor'],
                        'currency': offer['currency'], 'state': state, 'sourceStock': stock,
                        'stock': max((s['quantity'] for s in dispatch), default=0),
                        'source': dispatch[0]['sourceId'] if dispatch else '',
                        'branchStock': max((s['quantity'] for s in stock if s['kind'] == 'branch'), default=0),
                        'bulky': False, 'days': None, 'details': groups,
                        'supplierOrder': deepcopy(offer['supplier_order']),
                        'pickup': [{k: q[k] for k in ('branch_id', 'branch_name', 'source_id', 'ready_days', 'requires_transfer', 'price_minor')} for q in pickup]})
                description = item['retail_content']['description']['text']
                blocks = [{'heading': 'About this product', 'text': description}]
                notice = page.get('retail_content', {}).get('fit_notice')
                if notice:
                    blocks.append({'heading': 'Fit guidance', 'text': notice['text']})
                suffix = ', '.join(str(v) for v in page['page_key'].values())
                output.append({'id': page_id, 'canonicalProductId': public['product_id'],
                    'pageKey': deepcopy(page['page_key']), 'name': public['name'] + (f' — {suffix}' if suffix else ''),
                    'category': 'Footwear', 'type': 'Walking sandals' if public['concept'] == 'walking_sandals' else 'Walking shoes',
                    'brand': self.brands[public['brand_id']],
                    'marketRange': {'status': public.get('fact_status', {}).get('market_range', 'unknown'),
                        'value': public.get('facts', {}).get('market_range')
                        if public.get('fact_status', {}).get('market_range') == 'known' else None},
                    'introduction': item['retail_content']['description']['sentences'][0]['text'],
                    'options': options, 'variants': variants, 'descriptions': blocks, 'guide': 'Sizing'})
        if seen != set(offers):
            raise ValueError('Every carried offer must have exactly one public page')
        branches = {b['branch_id']: {'name': b['name'],
            'address': f"{b['location']['city']}, {b['location']['country']}",
            'hours': 'Opening hours are not published'} for b in r['geography']['branches']}
        result = {'schema': VERSION, 'siteId': retailer_id, 'siteName': r['name'],
            'quoteAsOf': self.world['quote_as_of'],
            'configuration': configuration, 'products': output, 'branches': branches,
            'initialAddress': self.initial_address, 'fulfilment': fulfilment,
            'policy': {'freeThresholdMinor': r['free_shipping_threshold_minor'],
                'deliveryCountries': r['geography']['fulfilment_policy']['delivery_countries'],
                'transferEnabled': r['geography']['fulfilment_policy']['warehouse_transfer_enabled'],
                'contracts': deepcopy(r['contracts'])}}
        if 'return_policy' in r:
            result['policy']['returnTerms'] = deepcopy(r['return_policy'])
        if presentation:
            context = self.world['address_context']
            mode = presentation['initial_form']
            if mode == 'producer':
                form = deepcopy(r['initial_form'])
            elif mode == 'canonical':
                form = {'address': context['addresses'][0]['address'], 'instructions': ''}
            else:
                form = autofill(self.world['seed'], retailer_id, context['addresses'],
                                context['outside_postcode'], context['parameters'], force=mode)
            def fields(address):
                return {'name': address['recipient'],
                        'street': ' '.join(v for v in (address['street'], address['house_number']) if v),
                        'unit': address['unit'], 'postcode': address['postcode'], 'city': address['city']}
            remembered = fields(context['addresses'][0]['address'])
            initial = fields(form['address'])
            result.update(initialAddress=initial, rememberedAddress=remembered,
                          initialInstructions=form['instructions'],
                          checkoutCapabilities={'unitField': True, 'instructions': True})
            result['fulfilment'] = self.fulfilment(retailer_id, remembered)
            try:
                initial_quotes = self.fulfilment(retailer_id, initial)
            except ValueError:
                initial_quotes = None
            if mode in ('old', 'old_missing_unit') and (
                    initial_quotes is None or not any(o['type'] == 'home'
                    for rows in initial_quotes['optionsBySku'].values() for o in rows)):
                raise ValueError('Requested stale address has no native home-delivery coverage')
            result['initialFulfilment'] = initial_quotes
        return result
