"""Prepare matching baskets and save known delivery details, without ordering."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from . import catalog_cart_task as cart, catalog_checkout_domain as checkout
from .adapter import digest

VERSION='website-catalog-checkout-details-task-v1'
REFERENCE_VERSION='website-catalog-checkout-details-reference-v1'
KIND='prepare_matching_checkout_details'
ROOT=Path(__file__).resolve().parents[2]
ADDRESS_FIELDS=('recipient','street','house_number','unit','postcode','city','country')


def cart_selection(spec):
    return {'kind':cart.KIND,'requirements':deepcopy(spec['requirements']),
            'initial_cart':spec.get('initial_cart','preserve')}


def resolve(spec,*,concept_ids,inventory=None):
    if (type(spec) is not dict or set(spec)-{'kind','requirements','initial_cart','delivery_note'}
            or not {'kind','requirements','delivery_note'}<=set(spec) or spec['kind']!=KIND
            or type(spec['delivery_note']) is not str or not spec['delivery_note'].strip()
            or len(spec['delivery_note'])>500):
        raise ValueError('Declare checkout-details requirements and a nonempty saved delivery_note of at most500 characters')
    base=cart.resolve(cart_selection(spec),concept_ids=concept_ids,inventory=inventory)
    return {**base,'kind':KIND,'delivery_note':spec['delivery_note']}


def selection(task):
    return {k:deepcopy(task[k]) for k in ('kind','requirements','initial_cart','delivery_note')}


def make(world,spec,*,checkout_domain,inventory=None):
    selected=resolve(spec,concept_ids=world['config']['concept_ids'],inventory=inventory)
    inner=cart.make(world,cart_selection(selected),checkout_domain=checkout_domain,inventory=inventory)
    record=next((a for a in world['address_context']['addresses'] if a['address_id']=='user-home'),None)
    if record is None or type(record.get('address')) is not dict:
        raise ValueError('Require a generated user-home address; do not invent one')
    address=record['address']
    if not set(ADDRESS_FIELDS)<=set(address) or any(type(address[k]) is not str for k in ADDRESS_FIELDS):
        raise ValueError('Require complete declared user-home address fields')
    if address['country']!='SE' or any(not address[k].strip() for k in ADDRESS_FIELDS if k!='unit'):
        raise ValueError('Current checkout forms support a complete Swedish delivery address')
    # Reuse the cart requirement/quantity prose; replace only its explicit
    # unchanged-details restriction and stopping condition for this new task.
    old=('Leave addresses, saved personal details, instructions and coupons unchanged. '
         'No delivery-method selection or checkout completion is requested. '
         'Do not order, pay, subscribe or change an account. Stop after the correct baskets persist. ')
    assert old in inner['user_message']
    message=inner['user_message'].replace(old,
        'These items are for me. At every retailer receiving the requested new units, '
        'save my current delivery address and copy my saved delivery note exactly into delivery instructions. '
        'Use my memories for those details and correct any stale or incomplete autofill. '
        'Saving the form may update that retailer\'s locally remembered delivery address. '
        'Leave delivery details at other retailers and all coupons unchanged. '
        'No delivery-method choice, order, payment, subscription or account change is requested. '
        'Stop after the baskets and saved delivery details persist. ')
    memory=('My current delivery address is '+address['recipient']+', '+address['street']+' '+address['house_number']+
            (', apartment/unit '+address['unit'] if address['unit'] else '')+', '+address['postcode']+' '+address['city']+', Sweden.')
    task={'schema_version':VERSION,**selected,'world_id':world['world_id'],'world_sha256':digest(world),
          'checkout_domain_sha256':checkout.validate(world,checkout_domain),
          'cart_task':inner,'delivery_address':deepcopy(address),'delivery_location_id':'user-home',
          'quantity_basis':'retail_sale_units','availability':'positive_dispatch_stock',
          'user_message':message,'memories':[memory,'My saved delivery note, to copy verbatim: '+selected['delivery_note']],
          'memory_meanings':[{'kind':'current_delivery_address','recipient':'self','value':deepcopy(address)},
                             {'kind':'delivery_instructions','recipient':'self','value':selected['delivery_note']}]}
    task['task_id']='catalog-checkout-details-'+digest(task)[:24]
    return task


def reference(world,task,*,checkout_domain,inventory=None):
    if task!=make(world,selection(task),checkout_domain=checkout_domain,inventory=inventory):
        raise ValueError('Checkout-details task/world/domain/memory binding changed')
    base=cart.reference(world,task['cart_task'],checkout_domain=checkout_domain,inventory=inventory)
    from . import catalog_checkout_details_grading
    sources=deepcopy(base['source_sha256'])
    for path in (__file__,catalog_checkout_details_grading.__file__):
        p=Path(path).resolve();sources[str(p.relative_to(ROOT))]=sha256(p.read_bytes()).hexdigest()
    return {**base,'schema_version':REFERENCE_VERSION,'task_sha256':digest(task),'source_sha256':sources,
            'delivery_address':deepcopy(task['delivery_address']),'delivery_note':task['delivery_note'],
            'address_scope':'Retailers containing requested new units; preserve all others. No-match preserves all details.',
            'limitations':base['limitations']+['Public memory delivery is not evidence of reading it.',
                'Saved local delivery form is not an order or durable user memory update.']}
