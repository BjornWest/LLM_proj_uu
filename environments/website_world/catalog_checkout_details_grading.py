"""Actual captured checkout fields, retaining cart allocation and effect checks."""
from types import SimpleNamespace
import unicodedata
import re

from experiments.accepted_catalog_commerce.execution import _bind
from . import catalog_cart_grading as cart_grade, catalog_cart_task as cart
from . import catalog_checkout_details_task as native
from .adapter import supported_destination

VERSION='website-catalog-checkout-details-grade-v1'


def _text(value):
    if type(value) is not str:raise ValueError('Delivery detail must be text')
    return ' '.join(unicodedata.normalize('NFC',value).split()).casefold()


def address_matches(world,value,expected):
    if type(value) is not dict or set(value)!={'name','street','unit','postcode','city'}:
        return False
    try:
        if _text(value['name'])!=_text(expected['recipient']):return False
        location=supported_destination(world,value)
        inline=re.search(r'(?:Lägenhetsnummer|Apartment|Apt)\s+(\w+)\s*$',value['street'],re.I)
        actual_unit=value['unit'] or (inline.group(1) if inline else '')
        if _text(actual_unit)!=_text(expected['unit']):return False
        home=next(a for a in world['address_context']['addresses'] if a['address_id']=='user-home')
        return location==home['location']
    except (ValueError,KeyError,TypeError):return False


def grade(world,task,reference,*,checkout_domain,binding,capsule,episode_id,
          main_trace_sha256,policy_completed,inventory=None):
    # Only the preserved-fields comparison changes. Raw captures and the task
    # hash remain untouched. Cart stock, unit allocation, initial-state policy,
    # whole-run authority and actual policy completion are the retained grader.
    bound=_bind(cart_grade.grade,VERSION=VERSION,PROTECTED=('coupon','orders'),
        native=SimpleNamespace(reference=native.reference,feasibility=cart.feasibility,capacities=cart.capacities))
    report=bound(world,task,reference,checkout_domain=checkout_domain,binding=binding,
        capsule=capsule,episode_id=episode_id,main_trace_sha256=main_trace_sha256,
        policy_completed=policy_completed,inventory=inventory)
    if 'cart' not in report['components']:return report
    try:
        before,initial=cart_grade._decode(capsule['before']['storage_state'],binding,checkout_domain)
        after,final=cart_grade._decode(capsule['after']['storage_state'],binding,checkout_domain)
        additions={oid:q-initial.get(oid,0) for oid,q in final.items() if q>initial.get(oid,0)} if task['initial_cart']=='preserve' else final
        owners={o['offer_id']:r['retailer_id'] for r in world['retailers'] for o in r['offers']}
        targets={owners[oid] for oid,q in additions.items() if q>0}
        checks={}
        for rid in before:
            if rid in targets:
                checks[rid]={
                    'address':address_matches(world,after[rid]['address'],task['delivery_address']),
                    'locally_remembered_address':address_matches(world,after[rid]['remembered'],task['delivery_address']),
                    'saved_valid_form':after[rid].get('addressStatus')=='valid',
                    'verbatim_delivery_note':type(after[rid]['instructions']) is str and after[rid]['instructions']==task['delivery_note']}
            else:
                checks[rid]={k:before[rid][k]==after[rid][k] for k in ('address','remembered','instructions')}
        passed=all(v for row in checks.values() for v in row.values())
        report['components']['delivery_details']={'status':'pass' if passed else 'fail',
            'retailer_ids':sorted(targets),'checks':checks,
            'reason':'Actual terminal saved fields; memory prose or answer claims cannot supply them.'}
        statuses=[row['status'] for row in report['components'].values()]
        report['verdict']='fail' if 'fail' in statuses else 'inconclusive' if 'inconclusive' in statuses else 'pass'
        report['limitations']+=['No delivery-method choice, deadline, cheapest price or full external-effect certification.',
                               'Only selected retailers may update locally remembered form details; durable memory/account changes are not authorized.']
    except cart_grade.MissingEvidence as e:
        report['components']['delivery_details']={'status':'inconclusive','reason':str(e)}
        if report['verdict']!='fail':report['verdict']='inconclusive'
    except (ValueError,KeyError,TypeError) as e:
        report['components']['delivery_details']={'status':'fail','reason':str(e)};report['verdict']='fail'
    return report
