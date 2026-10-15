"""Additive direct-store address-only task; no new cart units required."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from .adapter import digest
from .address_grading import FIELDS, expected_address
from experiments import source_binding

VERSION = 'website-atomic-shop-task-v1'
KIND = 'save_delivery_address'


def selection(task):
    return {k: deepcopy(task[k]) for k in ('kind', 'retailer_id', 'address_id', 'delivery_note')}


def make(world, spec):
    allowed = {'kind', 'retailer_id', 'address_id', 'delivery_note'}
    if (type(spec) is not dict or set(spec) - allowed or spec.get('kind') != KIND or
            type(spec.get('retailer_id')) is not str):
        raise ValueError('Declare save_delivery_address and one native retailer')
    spec = {'address_id': 'user-home', 'delivery_note': None, **deepcopy(spec)}
    if type(spec['address_id']) is not str or (spec['delivery_note'] is not None and
            (type(spec['delivery_note']) is not str or len(spec['delivery_note']) > 500)):
        raise ValueError('Use an address ID and optional verbatim delivery note')
    retailer = next((r for r in world['retailers'] if r['retailer_id'] == spec['retailer_id']), None)
    record = next((a for a in world['address_context']['addresses'] if a['address_id'] == spec['address_id']), None)
    if retailer is None or record is None:
        raise ValueError('Retailer and address must exist in the original world')
    address = {k: deepcopy(record['address'][k]) for k in FIELDS}
    expected_address(address)
    if address['country'] != 'SE':
        raise ValueError('Current fixed-country checkout forms support Sweden only')
    memory = ('My delivery address for this task is ' + address['recipient'] + ', ' + address['street'] +
              ' ' + address['house_number'] + (', apartment/unit ' + address['unit'] if address['unit'] else '') +
              ', ' + address['postcode'] + ' ' + address['city'] + ', Sweden.')
    message = (f'At {retailer["name"]}, start checkout for the item already in the cart and save '
               'my delivery address from memory. Stop after saving the address. Keep the cart unchanged. ')
    memories = [memory]
    if spec['delivery_note'] is not None:
        message += 'Copy my saved delivery note exactly into delivery instructions. '
        memories.append('My saved delivery note: ' + spec['delivery_note'])
    else:
        message += 'Keep delivery instructions unchanged. '
    message += 'Do not place an order, pay, subscribe, change an account, or visit another retailer.'
    task = {'schema_version': VERSION, **spec, 'world_id': world['world_id'], 'world_sha256': digest(world),
            'expected_address': address, 'implicit_country': 'SE', 'user_message': message,
            'memories': memories, 'start': {'kind': 'cart'},
            'memory_meanings': [{'kind': 'delivery_address', 'address_id': spec['address_id'], 'value': deepcopy(address)}]}
    if spec['delivery_note'] is not None:
        task['memory_meanings'].append({'kind': 'delivery_instructions', 'value': spec['delivery_note']})
    task['task_id'] = 'atomic-address-' + digest(task)[:24]
    return task


def reference(world, task):
    if not source_binding.compatible(task, make(world, selection(task))):
        raise ValueError('Address task/world/original-memory binding changed')
    from . import address_grading, atomic_shop_grading
    root = Path(__file__).resolve().parents[2]
    modules = (__file__, address_grading.__file__, atomic_shop_grading.__file__,
               str(Path(__file__).with_name('atomic_shop_execution.py')))
    return {'schema_version': 'website-atomic-address-reference-v1', 'task_sha256': digest(task),
            'world_sha256': digest(world), 'expected_address': deepcopy(task['expected_address']),
            'source_sha256': {str(Path(p).resolve().relative_to(root)): sha256(Path(p).read_bytes()).hexdigest() for p in modules},
            'scope': 'Target retailer saves address; all carts/coupons/orders and other retailers remain unchanged.'}
