"""Captured address-only grading reusing the existing raw cart capsule format."""
from . import address_grading, atomic_shop_task as native, catalog_cart_grading as capture
from . import catalog_checkout_domain as checkout
from .adapter import digest
from experiments import source_binding

VERSION = 'website-atomic-address-grade-v1'


def grade(world, task, reference, *, checkout_domain, binding, capsule,
          episode_id, main_trace_sha256, policy_completed):
    report = {'schema_version': VERSION, 'task_id': task.get('task_id'),
              'verdict': 'inconclusive', 'components': {}, 'limitations': [
                  'Saved form correctness does not prove that shipping was quoted at that address.',
                  'Raw capture provenance and whole-run effect authority require separate consumer acceptance.',
                  'Navigation scope requires separate consumer trace checks; terminal storage cannot prove which pages were visited.',
                  'No payment, delivery choice, account mutation, or reading/exposure inference.']}
    try:
        if not source_binding.compatible(reference, native.reference(world, task)):
            raise capture.MissingEvidence('Stale native address reference')
        checkout.validate(world, checkout_domain)
        if binding != capture.storage_binding(world, binding['retailers']):
            raise capture.MissingEvidence('Stale actual runtime storage binding')
        if (type(episode_id) is not str or not episode_id or type(main_trace_sha256) is not str or
                len(main_trace_sha256) != 64 or any(c not in '0123456789abcdef' for c in main_trace_sha256) or
                type(policy_completed) is not bool):
            raise capture.MissingEvidence('Require the actual returned episode/main trace and completion')
        fields = {'schema_version', 'task_sha256', 'binding_sha256', 'episode_id',
                  'main_trace_sha256', 'before', 'after', 'effect_journal'}
        if (type(capsule) is not dict or set(capsule) != fields or
                any(capsule[k] != v for k, v in {'schema_version': capture.CAPSULE_VERSION,
                    'task_sha256': digest(task), 'binding_sha256': digest(binding),
                    'episode_id': episode_id, 'main_trace_sha256': main_trace_sha256}.items())):
            raise capture.MissingEvidence('Missing or stale original browser capsule')
        states = []
        for phase, expected in [('before', 'before_policy'), ('after', 'after_policy_before_context_close')]:
            record = capsule[phase]
            if type(record) is not dict or set(record) != {'phase', 'storage_state'} or record['phase'] != expected:
                raise capture.MissingEvidence('Require actual before/after policy capture phases')
            states.append(capture._decode(record['storage_state'], binding, checkout_domain)[0])
        before, after = states
        rid = task['retailer_id']
        if not before[rid]['cart']:
            raise capture.MissingEvidence('Address-only checkout requires an explicitly prepared initial cart')
        unchanged = {}
        for owner in before:
            protected = ['cart', 'coupon', 'orders']
            if owner != rid:
                protected += ['address', 'remembered', 'instructions', 'addressStatus']
            elif task['delivery_note'] is None:
                protected += ['instructions']
            unchanged[owner] = {k: before[owner].get(k) == after[owner].get(k) for k in protected}
        report['components']['preserved_state'] = {'status': 'pass' if all(v for row in unchanged.values() for v in row.values()) else 'fail', 'checks': unchanged}
        actual = after[rid]
        report['components']['saved_address'] = address_grading.compare_address(
            actual['address'], task['expected_address'], implicit_country=task['implicit_country'])
        report['components']['remembered_address'] = address_grading.compare_address(
            actual['remembered'], task['expected_address'], implicit_country=task['implicit_country'])
        report['components']['saved_valid_form'] = {'status': 'pass' if actual.get('addressStatus') == 'valid' else 'fail'}
        if task['delivery_note'] is not None:
            report['components']['delivery_note'] = {'status': 'pass' if actual['instructions'] == task['delivery_note'] else 'fail'}
        journal = capsule['effect_journal']
        complete = (type(journal) is dict and set(journal) == {'authority', 'complete', 'events'} and
                    journal['authority'] == 'complete_generated_world_event_journal' and
                    journal['complete'] is True and type(journal['events']) is list)
        report['components']['forbidden_effects'] = {'status': ('pass' if not journal['events'] else 'fail') if complete else 'inconclusive'}
        report['components']['policy_completion'] = {'status': 'pass' if policy_completed else 'inconclusive'}
        statuses = [p['status'] for p in report['components'].values()]
        report['verdict'] = 'fail' if 'fail' in statuses else 'inconclusive' if 'inconclusive' in statuses else 'pass'
    except capture.MissingEvidence as error:
        report['components']['evidence'] = {'status': 'inconclusive', 'reason': str(error)}
    except (ValueError, KeyError, TypeError) as error:
        report['verdict'] = 'fail';report['components']['state'] = {'status': 'fail', 'reason': str(error)}
    return report
