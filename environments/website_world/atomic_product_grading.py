"""Captured outcome grading for short product tasks, using existing cart truth.

Read-task claims come from a separately adopted extractor; expected values must
never be inserted to repair missing claims. Provenance is consumer-owned.
"""
from . import atomic_product_task as native, catalog_cart_grading as capture
from . import catalog_cart_task as carts
from .adapter import digest

VERSION = 'website-atomic-product-grade-v1'


def selected_tuple(state, page_id, variants):
    """Malformed captured selectors are missing evidence, never an exception."""
    selection = state.get('selection')
    if type(selection) is not dict:
        raise capture.MissingEvidence('Missing captured page selection mapping')
    selected = selection.get(page_id)
    if (type(selected) is not dict or any(type(k) is not str or type(v) is not str for k, v in selected.items())
            or selected not in [v['selection'] for v in variants]):
        raise capture.MissingEvidence('Captured page selection is not one complete carried tuple')
    return selected


def grade(world, task, reference, *, catalog, bindings, checkout_domain,
          binding, capsule, episode_id, main_trace_sha256, policy_completed, claims=None):
    report = {'schema_version': VERSION, 'task_id': task.get('task_id'), 'verdict': 'inconclusive',
              'components': {}, 'limitations': [
                  'Terminal selection does not prove action order, navigation scope or reading/exposure.',
                  'Read claims need independently accepted extraction from the actual answer.',
                  'Browser provenance and whole-run effects require the exact consumer authority.',
                  'Public fact correctness here means faithful reporting of the retailer declaration.']}
    try:
        expected = native.reference(world, task, catalog=catalog, bindings=bindings, checkout_domain=checkout_domain)
        if reference != expected or binding != capture.storage_binding(world, binding['retailers']):
            raise capture.MissingEvidence('Stale task/reference or actual storage binding')
        if (type(episode_id) is not str or not episode_id or type(main_trace_sha256) is not str
                or len(main_trace_sha256) != 64 or any(c not in '0123456789abcdef' for c in main_trace_sha256)
                or type(policy_completed) is not bool):
            raise capture.MissingEvidence('Bind the actual returned episode, trace and completion')
        fields = {'schema_version', 'task_sha256', 'binding_sha256', 'episode_id',
                  'main_trace_sha256', 'before', 'after', 'effect_journal'}
        if (type(capsule) is not dict or set(capsule) != fields or
                any(capsule[k] != v for k, v in {'schema_version': capture.CAPSULE_VERSION,
                    'task_sha256': digest(task), 'binding_sha256': digest(binding),
                    'episode_id': episode_id, 'main_trace_sha256': main_trace_sha256}.items())):
            raise capture.MissingEvidence('Missing or stale original browser capsule')
        decoded = []
        for phase, label in [('before', 'before_policy'), ('after', 'after_policy_before_context_close')]:
            record = capsule[phase]
            if type(record) is not dict or set(record) != {'phase', 'storage_state'} or record['phase'] != label:
                raise capture.MissingEvidence('Require actual before/after policy phases')
            decoded.append(capture._decode(record['storage_state'], binding, checkout_domain))
        (before, initial), (after, final) = decoded
        preserved = {rid: {k: before[rid][k] == after[rid][k] for k in capture.PROTECTED} for rid in before}
        report['components']['protected_state'] = {'status': 'pass' if all(v for row in preserved.values() for v in row.values()) else 'fail', 'checks': preserved}
        kind, rid, oid = task['kind'], task['retailer_id'], task['offer_id']
        variants = next(p for p in catalog['products'] if p['id'] == task['page_id'])['variants']
        if task['initial_selection'] is not None:
            if selected_tuple(before[rid], task['page_id'], variants) != task['initial_selection']:
                raise capture.MissingEvidence('Declared ordinary-UI initial selection was not captured')
        if kind == 'add_exact_quantity':
            q = reference['quantity']
            wanted = {**initial, oid: initial.get(oid, 0) + q}
            available = carts.capacities(world, checkout_domain, initial)
            correct = final == wanted and available[oid] >= q
            report['components']['cart'] = {'status': 'pass' if correct else 'fail',
                'initial_quantities': initial, 'final_quantities': final, 'required_addition': q}
        else:
            # Preserve physical cart rows, not merely aggregated quantities.
            correct = all(before[r]['cart'] == after[r]['cart'] for r in before)
            report['components']['cart'] = {'status': 'pass' if correct else 'fail'}
        if kind == 'select_exact_variant':
            selected = selected_tuple(after[rid], task['page_id'], variants)
            report['components']['selected_variant'] = {'status': 'pass' if selected == task['selection'] else 'fail', 'actual': selected}
        elif kind.startswith('read_'):
            correct = (type(claims) is dict and set(claims) == set(reference['expected_claims'])
                       and digest(claims) == digest(reference['expected_claims']))
            report['components']['answer'] = {'status': 'inconclusive' if claims is None else 'pass' if correct else 'fail'}
        journal = capsule['effect_journal']
        complete = (type(journal) is dict and set(journal) == {'authority', 'complete', 'events'}
                    and journal['authority'] == 'complete_generated_world_event_journal'
                    and journal['complete'] is True and type(journal['events']) is list)
        report['components']['forbidden_effects'] = {'status': ('pass' if not journal['events'] else 'fail') if complete else 'inconclusive'}
        report['components']['policy_completion'] = {'status': 'pass' if policy_completed else 'inconclusive'}
        statuses = [c['status'] for c in report['components'].values()]
        report['verdict'] = 'fail' if 'fail' in statuses else 'inconclusive' if 'inconclusive' in statuses else 'pass'
    except capture.MissingEvidence as error:
        report['components']['evidence'] = {'status': 'inconclusive', 'reason': str(error)}
    except (ValueError, KeyError, TypeError) as error:
        report['verdict'] = 'fail'
        report['components']['state'] = {'status': 'fail', 'reason': str(error)}
    return report
