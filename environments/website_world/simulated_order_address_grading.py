"""Score recorded address fields only; never certify ordering or effects."""
from copy import deepcopy
import json

from .adapter import digest
from .address_grading import compare_address

VERSION = 'website-simulated-order-address-grade-v1'
SCOPE = 'observed_checkout_or_submitted_address_only'
OBSERVATION_RULE = 'last_new_target_retailer_submission_else_terminal_checkout'


class MissingEvidence(ValueError):
    pass


def _json(text):
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise MissingEvidence('Duplicate recorded storage field')
            value[key] = item
        return value
    def nonfinite(value):
        raise MissingEvidence('Nonfinite recorded storage value')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)


def grade(task, reference, evidence, *, binding, storage_binding,
          episode_id, main_trace_sha256):
    """The trusted caller supplies actual capture/runtime and returned trace IDs.

    Evidence selection is fixed before dispatch: the last new recorded order at
    the target retailer, otherwise that retailer's terminal checkout address.
    All original records stay in the capture. Order count and delivery are not
    scored, and no complete-effect envelope is created.
    """
    report = {'schema_version': VERSION, 'task_id': task['task_id'],
        'scoring_scope': SCOPE, 'observation_rule': OBSERVATION_RULE,
        'verdict': 'inconclusive', 'address_correct': None, 'components': {},
        'full_effects': 'unknown', 'full_order_completion': 'not_assessed',
        'limitations': ['Only address fields are scored; this is not full ordering success.',
            'Order count, delivery choice, prices, items and other effects are ungraded.',
            'Recorded order history completeness is not certified.']}
    try:
        if (reference['task_id'] != task['task_id']
                or reference['task_sha256'] != digest(task)
                or reference['expected_address'] != task['delivery_address']
                or reference['retailer_id'] != task['retailer_id']
                or reference['scoring_scope'] != SCOPE
                or reference['implicit_country'] != storage_binding['implicit_country']):
            raise MissingEvidence('Address reference and actual Runtime binding differ')
        if (evidence['schema_version'] != 'website-simulated-order-address-capture-v1'
                or evidence['task_id'] != task['task_id']
                or evidence['task_sha256'] != digest(task)
                or evidence['binding'] != binding
                or evidence['episode_id'] != episode_id
                or evidence['main_trace_sha256'] != main_trace_sha256
                or binding['episode_binding']['episode_id'] != episode_id
                or binding['episode_binding']['task_sha256'] != digest(task)
                or evidence['complete_effect_envelope'] is not None
                or evidence['full_effects'] != 'unknown'
                or evidence['order_outcome_scored'] is not False):
            raise MissingEvidence('Missing bound actual address capture')
        ledger = evidence['ledger']
        if (ledger['episode_id'] != episode_id
                or ledger['task_sha256'] != digest(task)
                or ledger['main_trace_sha256'] != main_trace_sha256
                or ledger['effect_journal'] is not None):
            raise MissingEvidence('Ledger capture belongs to another episode')
        snapshots = []
        for phase, expected_phase in (('before', 'before_policy'),
                                      ('after', 'after_policy_before_context_close')):
            row = ledger[phase]
            snapshot = row['order_snapshot']
            if (row['phase'] != expected_phase
                    or snapshot['runtime_id'] != binding['runtime_id']
                    or snapshot['episode_binding'] != binding['episode_binding']
                    or type(snapshot['orders']) is not list):
                raise MissingEvidence('Missing actual bound order snapshots')
            snapshots.append(snapshot)
        before, after = snapshots
        if len(after['orders']) < len(before['orders']):
            raise MissingEvidence('Cannot identify newly recorded submissions')
        submitted = [row for row in after['orders'][len(before['orders']):]
                     if row['retailer_id'] == task['retailer_id']]
        if submitted:
            actual = submitted[-1]['address']
            selected = {'kind': 'submitted_order', 'order_id': submitted[-1]['order_id']}
        else:
            row = evidence['checkout_storage']['after']
            if (row['phase'] != 'after' or row['binding'] != binding
                    or row['episode_id'] != episode_id
                    or row['retailer_id'] != task['retailer_id']
                    or any(row[k] != storage_binding[k] for k in
                           ('origin', 'storage_key', 'implicit_country'))):
                raise MissingEvidence('Checkout capture and actual retailer differ')
            origins = [v for v in row['storage_state']['origins']
                       if v['origin'] == storage_binding['origin']]
            if len(origins) != 1:
                raise MissingEvidence('Missing or ambiguous actual retailer storage')
            entries = [v for v in origins[0]['localStorage']
                       if v['name'] == storage_binding['storage_key']]
            if len(entries) != 1:
                raise MissingEvidence('Missing or ambiguous actual checkout state')
            state = _json(entries[0]['value'])
            if type(state) is not dict or type(state.get('address')) is not dict:
                raise MissingEvidence('No usable actual checkout address')
            actual = state['address']
            selected = {'kind': 'terminal_checkout', 'origin': storage_binding['origin']}
        if (type(actual) is not dict
                or not {'name', 'street', 'postcode', 'city'} <= set(actual)):
            raise MissingEvidence('Actual address is unavailable')
        result = compare_address(actual, reference['expected_address'],
                                 implicit_country=storage_binding['implicit_country'])
        report.update(verdict=result['status'], address_correct={'pass': True,
            'fail': False, 'inconclusive': None}[result['status']],
            selected_evidence=selected, actual_address=deepcopy(actual))
        report['components']['address'] = result
    except (MissingEvidence, KeyError, TypeError, ValueError, IndexError) as error:
        report['components']['evidence'] = {'status': 'inconclusive', 'reason': str(error)}
    return report


def project_native(raw, binding):
    from intent_browser.evaluation import Evaluation
    report = raw['native_grade']
    if (raw['task_id'] != binding['task_id'] or report['task_id'] != binding['task_id']
            or report['scoring_scope'] != SCOPE or report['schema_version'] != VERSION):
        raise ValueError('Address-only grade belongs to another scoring contract')
    return Evaluation('simulated-order-address-only', VERSION, trust='native_reference',
        task_completed={'pass': True, 'fail': False, 'inconclusive': None}[report['verdict']],
        evidence=['automatic-grade.json', 'order-address-reference.private.json',
                  'manual-review-private/order-address-evidence.private.json'],
        limitations=report['limitations'])
