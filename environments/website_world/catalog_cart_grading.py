"""Grade captured browser carts, independently of natural-answer extraction.

The consumer is responsible for capturing actual storage before policy execution
and after it returns, while the browser remains open. A missing phase or missing
origin is unknown evidence, never an empty-cart fallback. Whole-run forbidden
effects require a separate authoritative journal; terminal storage is insufficient.
"""
from copy import deepcopy
import json
from urllib.parse import urlsplit

from experiments.footwear_world_pilot.order_set_grader import coverage
from . import catalog_cart_task as native, catalog_checkout_domain as checkout
from .adapter import digest
from experiments import source_binding

VERSION = 'website-catalog-cart-grade-v1'
CAPSULE_VERSION = 'website-catalog-cart-capsule-v1'
BINDING_VERSION = 'website-catalog-cart-storage-binding-v1'
PROTECTED = ('address', 'remembered', 'instructions', 'coupon', 'orders')


class MissingEvidence(ValueError):
    pass


def storage_binding(world, retailers):
    """Join exact actual retailer origins/storage keys to native SKU/offer IDs.

    Website supplies these rows from its runtime, not from final answer text.
    All generated retailers and offers remain in scope, including distractors.
    Transport aliases must already be resolved to the origin used by Chromium.
    """
    if type(retailers) is not dict or set(retailers) != {r['retailer_id'] for r in world['retailers']}:
        raise ValueError('Supply every generated retailer storage binding')
    origins = set()
    for retailer in world['retailers']:
        rid = retailer['retailer_id']
        row = retailers[rid]
        if type(row) is not dict or set(row) != {'origin', 'storage_key', 'offer_keys'}:
            raise ValueError('Storage binding needs origin, storage_key and offer_keys')
        if type(row['origin']) is not str:
            raise ValueError('Origin must be text')
        origin = urlsplit(row['origin'])
        if (origin.scheme not in ('http', 'https') or not origin.hostname or origin.username
                or origin.password or origin.path or origin.query or origin.fragment
                or row['origin'] in origins):
            raise ValueError('Supply distinct bare actual browser origins')
        origins.add(row['origin'])
        if row['storage_key'] != 'website-drafts.state.' + rid:
            raise ValueError('Storage key must use the exact runtime retailer ID')
        keys = {o['sku_id']: o['offer_id'] for o in retailer['offers']}
        if len(keys) != len(retailer['offers']) or row['offer_keys'] != keys:
            raise ValueError('Current native catalog requires exact unique SKU keys, not aliases')
    return {'schema_version': BINDING_VERSION, 'world_id': world['world_id'],
            'world_sha256': digest(world), 'retailers': deepcopy(retailers)}


def _json(text):
    if type(text) is not str:
        raise ValueError('Retain original raw storage bytes as a JSON string')
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('Duplicate JSON storage key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Nonfinite storage value: ' + value)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def _decode(snapshot, binding, domain):
    if type(snapshot) is not dict or set(snapshot) != {'cookies', 'origins'}:
        raise MissingEvidence('A complete browser storage_state capture is required')
    if type(snapshot['cookies']) is not list or type(snapshot['origins']) is not list:
        raise ValueError('Invalid browser storage_state arrays')
    origins = {}
    for row in snapshot['origins']:
        if type(row) is not dict or set(row) != {'origin', 'localStorage'} or type(row['origin']) is not str:
            raise ValueError('Invalid origin storage row')
        if row['origin'] in origins or type(row['localStorage']) is not list:
            raise ValueError('Duplicate origin or invalid localStorage')
        values = {}
        for entry in row['localStorage']:
            if (type(entry) is not dict or set(entry) != {'name', 'value'}
                    or type(entry['name']) is not str or type(entry['value']) is not str
                    or entry['name'] in values):
                raise ValueError('Invalid or duplicate browser storage entry')
            values[entry['name']] = entry['value']
        origins[row['origin']] = values
    states, quantities = {}, {}
    for rid, row in binding['retailers'].items():
        values = origins.get(row['origin'], {})
        if row['storage_key'] not in values:
            raise MissingEvidence('Initialize and capture the actual baseline for retailer ' + rid)
        state = _json(values[row['storage_key']])
        if (type(state) is not dict or type(state.get('version')) is not int or state['version'] != 2
                or not {'cart', *PROTECTED} <= set(state) or type(state['cart']) is not list
                or type(state['orders']) is not list):
            raise ValueError('Capture the actual version2 retailer cart state')
        states[rid] = state
        ids, lines = set(), []
        for line in state['cart']:
            if (type(line) is not dict or set(line) != {'id', 'key', 'quantity'}
                    or type(line['id']) is not str or not line['id'] or line['id'] in ids
                    or type(line['key']) is not str or line['key'] not in row['offer_keys']):
                raise ValueError('Unknown cart identity, extra line field or repeated line ID')
            ids.add(line['id'])
            lines.append({'line_id': line['id'], 'offer_id': row['offer_keys'][line['key']],
                          'quantity': line['quantity']})
        if lines:
            canonical, _ = checkout._canonical_lines(domain, set(row['offer_keys'].values()), lines)
            quantities.update({line['offer_id']: line['quantity'] for line in canonical})
    return states, quantities


def grade(world, task, reference, *, checkout_domain, binding, capsule,
          episode_id, main_trace_sha256, policy_completed, inventory=None):
    """State-only grade. Neither answer claims nor oracle witness populate carts.

    The episode ID and main-trace hash must come from the trusted runner's actual
    returned trace. The consumer must freeze source/capture provenance separately.
    Journal authority is a trusted consumer input, not inferred from state equality.
    """
    report = {'schema_version': VERSION, 'task_id': task.get('task_id'),
              'verdict': 'inconclusive', 'cart_outcome_correct': None,
              'components': {}, 'limitations': [
                  'No delivery selection, lowest price, payment or broad external effects are graded.',
                  'Storage captures and whole-run effect authority require independent consumer acceptance.']}
    try:
        rebuilt = native.reference(world, task, checkout_domain=checkout_domain, inventory=inventory)
        if reference != rebuilt:
            changes = source_binding.substantive_changes(reference, rebuilt)
            if source_binding.mode() == 'pinned' or changes:
                raise MissingEvidence('Stale native reference/source binding'
                                      + (': ' + ', '.join(changes[:8]) if changes else ''))
        if binding != storage_binding(world, binding['retailers']):
            raise MissingEvidence('Stale runtime storage binding')
        if (type(policy_completed) is not bool or type(episode_id) is not str or not episode_id or type(main_trace_sha256) is not str
                or len(main_trace_sha256) != 64 or any(c not in '0123456789abcdef' for c in main_trace_sha256)):
            raise MissingEvidence('Bind the actual returned episode/main trace')
        fields = {'schema_version', 'task_sha256', 'binding_sha256', 'episode_id',
                  'main_trace_sha256', 'before', 'after', 'effect_journal'}
        if (type(capsule) is not dict or set(capsule) != fields
                or capsule['schema_version'] != CAPSULE_VERSION
                or capsule['task_sha256'] != digest(task) or capsule['binding_sha256'] != digest(binding)
                or capsule['episode_id'] != episode_id or capsule['main_trace_sha256'] != main_trace_sha256):
            raise MissingEvidence('Missing or stale actual browser capsule')
        states = []
        for phase, expected in [('before', 'before_policy'), ('after', 'after_policy_before_context_close')]:
            record = capsule[phase]
            if type(record) is not dict or set(record) != {'phase', 'storage_state'} or record['phase'] != expected:
                raise MissingEvidence('Capture phases must surround the actual policy')
            states.append(_decode(record['storage_state'], binding, checkout_domain))
        (before, initial), (after, final) = states
        if any(before[rid][key] != after[rid][key] for rid in before for key in PROTECTED):
            raise ValueError('Protected addresses, details, instructions, coupons or orders changed')
        if task['initial_cart'] == 'preserve':
            if any(final.get(oid, 0) < q for oid, q in initial.items()):
                raise ValueError('An initial cart unit was removed')
            additions = {oid: q - initial.get(oid, 0) for oid, q in final.items()
                         if q > initial.get(oid, 0)}
        else:
            additions = final
        outcome = native.feasibility(world, task, reference['matching'], checkout_domain, initial=initial)
        no_match = outcome['status'] == 'no_match' and initial == final
        available = native.capacities(world, checkout_domain,
            initial if task['initial_cart'] == 'preserve' else {})
        if not no_match and any(q > available.get(oid, 0) for oid, q in additions.items()):
            raise ValueError('Added units exceed physical dispatch stock or shared quantity limits')
        allocation = coverage(reference['matching']['requirements'], {} if no_match else additions)
        correct = allocation['covered'] and sum(additions.values()) == allocation['required_units']
        report['cart_outcome_correct'] = correct or no_match
        report['components']['cart'] = {'status': 'pass' if correct or no_match else 'fail',
            'allocation': allocation, 'initial_quantities': initial, 'final_quantities': final,
            'feasibility': outcome['status'], 'completion': 'unchanged_infeasible' if no_match else 'prepared'}
        # Terminal orders equality above cannot detect purchase then cancellation.
        # Missing/incomplete authority remains inconclusive even with correct carts.
        journal = capsule['effect_journal']
        complete = (type(journal) is dict and set(journal) == {'authority', 'complete', 'events'}
                    and journal['authority'] == 'complete_generated_world_event_journal'
                    and journal['complete'] is True and type(journal['events']) is list)
        effect_status = 'inconclusive'
        if complete:
            effect_status = 'pass' if not journal['events'] else 'fail'
        report['components']['forbidden_effects'] = {'status': effect_status,
            'reason': 'Consumer must cover order, subscription and account effects throughout the episode.'}
        report['components']['policy_completion'] = {'status': 'pass' if policy_completed else 'inconclusive',
            'reason': 'Actual runner completion, not a transient correct cart or answer-only claim.'}
        statuses = [part['status'] for part in report['components'].values()]
        report['verdict'] = 'fail' if 'fail' in statuses else 'inconclusive' if 'inconclusive' in statuses else 'pass'
    except MissingEvidence as error:
        report['components']['evidence'] = {'status': 'inconclusive', 'reason': str(error)}
    except (ValueError, KeyError, TypeError) as error:
        report['verdict'] = 'fail'
        report['components']['state'] = {'status': 'fail', 'reason': str(error)}
    return report
