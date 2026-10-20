"""Grade private committed receipts, with separately accepted capture authority.

Self-hashed snapshots are bindings, not proof of origin. Website must obtain
independent acceptance of the exact store/capture/source union before supplying a
complete effect envelope. Missing authority never becomes an empty-event pass.
"""
from copy import deepcopy

from .adapter import digest
from .address_grading import compare_address
from . import simulated_order_task as native, simulated_order_record as records

VERSION = 'website-simulated-order-grade-v1'
CAPSULE_VERSION = 'website-simulated-order-capsule-v1'
SNAPSHOT_VERSION = 'website-simulated-order-store-v1'
AUTHORITY = 'complete_generated_world_order_event_journal'


class MissingEvidence(ValueError):
    pass


def _sha(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _snapshot(baskets, value, binding):
    fields = {'schema', 'runtime_id', 'world_id', 'world_sha256', 'plan_id',
              'domain_id', 'episode_binding', 'orders', 'events', 'snapshot_sha256'}
    if (type(value) is not dict or set(value) != fields
            or value['schema'] != SNAPSHOT_VERSION or value['runtime_id'] != binding['runtime_id']
            or value['episode_binding'] != binding['episode_binding']
            or type(value['orders']) is not list or type(value['events']) is not list
            or value['snapshot_sha256'] != digest({k: v for k, v in value.items() if k != 'snapshot_sha256'})):
        raise MissingEvidence('Supply the exact private Runtime snapshot with episode/source binding')
    ctx = native.context(baskets)
    if any(value[k] != ctx[k] for k in ('world_id', 'world_sha256', 'plan_id', 'domain_id')):
        raise MissingEvidence('Order store and current native quote context differ')
    if len(value['orders']) != len(value['events']):
        raise ValueError('Private order/event counts differ')
    ids = set()
    for index, (order, event) in enumerate(zip(value['orders'], value['events']), 1):
        records.validate(baskets, order['retailer_id'], order)
        if order['order_id'] in ids:
            raise ValueError('Duplicate committed order identity')
        ids.add(order['order_id'])
        expected = {'sequence': index, 'order_id': order['order_id'], 'retailer_id': order['retailer_id'],
                    'submission_sha256': order['submission_sha256'], 'record_sha256': digest(order)}
        if digest(event) != digest(expected):
            raise ValueError('Private event does not bind the actual committed native receipt')
    return deepcopy(value)


def grade(baskets, task, reference, *, binding, capsule, episode_id,
          main_trace_sha256, policy_completed):
    """State-only report, suitable for the existing trace grade projection.

    `binding` comes from the accepted trusted runner, not the model. It contains
    runtime_id and exact episode_binding {episode_id, task_sha256,
    source_union_sha256, capture_implementation_sha256}. The complete journal is
    accepted only under the new order-capable union, never old Address approval.
    """
    report = {'schema_version': VERSION, 'task_id': task.get('task_id'),
              'verdict': 'inconclusive', 'order_outcome_correct': None, 'components': {},
              'limitations': ['Native receipt validation is not capture-origin certification.',
                  'No payment, stock decrement, fulfillment or durable account/memory outcome is implemented.']}
    try:
        # Trusted setup/reference validation is separate from actual committed
        # receipt validation below. A stale task/context is not a model outcome.
        try:
            expected_reference = native.reference(baskets, task)
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise MissingEvidence('Invalid task/native quote binding: ' + str(error)) from error
        if digest(reference) != digest(expected_reference):
            raise MissingEvidence('Stale task/reference or native quote context')
        if (type(binding) is not dict or set(binding) != {'runtime_id', 'episode_binding'}
                or type(binding['runtime_id']) is not str or not binding['runtime_id']
                or type(binding['episode_binding']) is not dict
                or set(binding['episode_binding']) != {'episode_id', 'task_sha256', 'source_union_sha256', 'capture_implementation_sha256'}
                or binding['episode_binding']['episode_id'] != episode_id
                or binding['episode_binding']['task_sha256'] != digest(task)
                or not all(_sha(binding['episode_binding'][k]) for k in ('task_sha256', 'source_union_sha256', 'capture_implementation_sha256'))
                or type(episode_id) is not str or not episode_id or not _sha(main_trace_sha256)
                or type(policy_completed) is not bool):
            raise MissingEvidence('Require the actual runtime, task, source union, capture and returned trace')
        fields = {'schema_version', 'task_sha256', 'episode_id', 'main_trace_sha256', 'before', 'after', 'effect_journal'}
        if (type(capsule) is not dict or set(capsule) != fields
                or capsule['schema_version'] != CAPSULE_VERSION or capsule['task_sha256'] != digest(task)
                or capsule['episode_id'] != episode_id or capsule['main_trace_sha256'] != main_trace_sha256):
            raise MissingEvidence('Missing actual before/after order capsule')
        snapshots = []
        for phase, expected in [('before', 'before_policy'), ('after', 'after_policy_before_context_close')]:
            row = capsule[phase]
            if type(row) is not dict or set(row) != {'phase', 'order_snapshot'} or row['phase'] != expected:
                raise MissingEvidence('Capture private orders around the actual policy')
            snapshots.append(_snapshot(baskets, row['order_snapshot'], binding))
        before, after = snapshots
        size = len(before['orders'])
        if (digest(after['orders'][:size]) != digest(before['orders'])
                or digest(after['events'][:size]) != digest(before['events'])):
            raise ValueError('Historical private order ledger was removed or changed')
        added = after['orders'][size:]
        checks = {'one_new_order': len(added) == 1, 'native_feasible': reference['status'] == 'ready'}
        if len(added) == 1:
            order = added[0]
            address = {**order['address'], 'unit': order['address'].get('unit', '')}
            checks.update(retailer=order['retailer_id'] == task['retailer_id'],
                exact_items=digest(order['items']) == digest(task['items']),
                address=compare_address(address, task['delivery_address'], implicit_country='SE')['status'] == 'pass',
                coupon_context=order['submission']['quote_request']['coupon_code'] == task['coupon_code'],
                delivery_types=task['delivery_types'] is None or
                    {s['delivery']['type'] for s in order['shipments']} <= set(task['delivery_types']))
            if task['spec'].get('require_cheapest_delivery', True):
                checks['cheapest_delivery'] = order['shipping_minor'] == reference['minimum_shipping_minor']
        correct = all(checks.values())
        report['order_outcome_correct'] = correct
        report['components']['order'] = {'status': 'pass' if correct else 'fail', 'checks': checks,
                                        'new_order_ids': [o['order_id'] for o in added]}
        journal = capsule['effect_journal']
        complete = (type(journal) is dict and set(journal) == {'authority', 'complete', 'events'}
                    and journal['authority'] == AUTHORITY and journal['complete'] is True
                    and type(journal['events']) is list)
        expected_events = [{'kind': 'order_committed', **event} for event in after['events'][size:]]
        report['components']['effects'] = {'status': ('pass' if digest(journal['events']) == digest(expected_events)
            else 'fail') if complete else 'inconclusive',
            'reason': 'Only the captured native order commits are allowed; complete external-effect coverage requires new-union acceptance.'}
        report['components']['policy_completion'] = {'status': 'pass' if policy_completed else 'inconclusive'}
        statuses = [c['status'] for c in report['components'].values()]
        report['verdict'] = 'fail' if 'fail' in statuses else 'inconclusive' if 'inconclusive' in statuses else 'pass'
    except MissingEvidence as error:
        report['components']['evidence'] = {'status': 'inconclusive', 'reason': str(error)}
    except (ValueError, KeyError, TypeError, IndexError) as error:
        report['components']['record'] = {'status': 'fail', 'reason': str(error)}
        report['verdict'] = 'fail'
    return report
