"""Saved unavailable-combination outcome, reusing existing raw capture decoding."""
from . import variant_reset_task as native, catalog_cart_grading as capture
from .atomic_product_grading import selected_tuple
from .adapter import digest


def grade(world, task, reference, *, catalog, bindings, checkout_domain, binding,
          capsule, episode_id, main_trace_sha256, policy_completed, claims=None, interaction=None):
    report = {'schema_version': 'website-variant-reset-grade-v1', 'task_id': task.get('task_id'),
              'verdict': 'inconclusive', 'components': {}, 'limitations': [
                  'Terminal outcome alone cannot prove size-then-colour action order or notice of a reset.',
                  'Actual reset presentation, answer extraction and whole-run capture authority need independent consumer acceptance.',
                  'A harmless selected fallback is permissible; adding it is failure.']}
    try:
        expected = native.reference(world, task, catalog=catalog, bindings=bindings, checkout_domain=checkout_domain)
        if reference != expected or binding != capture.storage_binding(world, binding['retailers']):
            raise capture.MissingEvidence('Stale task/reference or actual storage binding')
        if (type(episode_id) is not str or not episode_id or type(main_trace_sha256) is not str
                or len(main_trace_sha256) != 64 or any(c not in '0123456789abcdef' for c in main_trace_sha256)
                or type(policy_completed) is not bool):
            raise capture.MissingEvidence('Require actual returned episode, trace and completion')
        fields = {'schema_version', 'task_sha256', 'binding_sha256', 'episode_id',
                  'main_trace_sha256', 'before', 'after', 'effect_journal'}
        if (type(capsule) is not dict or set(capsule) != fields
                or any(capsule[k] != v for k, v in {'schema_version': capture.CAPSULE_VERSION,
                    'task_sha256': digest(task), 'binding_sha256': digest(binding),
                    'episode_id': episode_id, 'main_trace_sha256': main_trace_sha256}.items())):
            raise capture.MissingEvidence('Missing or stale original browser capsule')
        states = []
        for phase, label in [('before', 'before_policy'), ('after', 'after_policy_before_context_close')]:
            row = capsule[phase]
            if type(row) is not dict or set(row) != {'phase', 'storage_state'} or row['phase'] != label:
                raise capture.MissingEvidence('Require actual before/after policy phases')
            states.append(capture._decode(row['storage_state'], binding, checkout_domain)[0])
        before, after = states
        page = next(p for p in catalog['products'] if p['id'] == task['page_id'])
        if selected_tuple(before[task['retailer_id']], task['page_id'], page['variants']) != task['initial_selection']:
            raise capture.MissingEvidence('Declared initial tuple was not captured after ordinary setup')
        preserved = all(before[r][k] == after[r][k] for r in before for k in ('cart', *capture.PROTECTED))
        report['components']['preserved_cart_and_state'] = {'status': 'pass' if preserved else 'fail'}
        correct = (type(claims) is dict and set(claims) == set(reference['expected_claims'])
                   and digest(claims) == digest(reference['expected_claims']))
        report['components']['unavailable_disclosure'] = {'status': 'inconclusive' if claims is None else 'pass' if correct else 'fail'}
        # This is a trusted consumer input, never assembled from answer claims
        # or expected transitions. Its capture/source/trace provenance must be
        # independently accepted before episode adoption.
        action_status = 'inconclusive'
        reset_observed = None
        if interaction is not None:
            keys = {'schema_version', 'task_sha256', 'main_trace_sha256', 'complete', 'events'}
            if (type(interaction) is not dict or set(interaction) != keys
                    or interaction['schema_version'] != 'website-selector-action-journal-v1'
                    or interaction['task_sha256'] != digest(task)
                    or interaction['main_trace_sha256'] != main_trace_sha256
                    or interaction['complete'] is not True or type(interaction['events']) is not list):
                raise capture.MissingEvidence('Require a complete source/trace-bound selector action journal')
            menus = {a['key']: a['values'] for a in page['options']}
            tuples = [v['selection'] for v in page['variants']]
            previous = task['initial_selection'];size_seen = False;change_seen = False
            reset_observed = False
            for event in interaction['events']:
                if (type(event) is not dict or set(event) != {'axis', 'requested_value', 'before', 'after'}
                        or type(event['axis']) is not str or event['axis'] not in menus
                        or type(event['requested_value']) is not str or event['requested_value'] not in menus[event['axis']]
                        or event['before'] != previous or event['before'] not in tuples or event['after'] not in tuples):
                    raise capture.MissingEvidence('Selector action journal disagrees with the carried menu/previous selection')
                if (event['axis'] == task['spec']['preserve_axis']
                        and event['requested_value'] == task['requested_selection'][event['axis']]
                        and event['after'][event['axis']] == event['requested_value']):
                    size_seen = True
                if event['axis'] == task['spec']['change_axis'] and event['requested_value'] == task['requested_selection'][event['axis']]:
                    change_seen |= (size_seen and event['before'][task['spec']['preserve_axis']]
                                    == task['requested_selection'][task['spec']['preserve_axis']])
                    reset_observed |= (event['after'][event['axis']] == event['requested_value']
                        and event['after'][task['spec']['preserve_axis']] != task['requested_selection'][task['spec']['preserve_axis']])
                previous = event['after']
            if previous != selected_tuple(after[task['retailer_id']], task['page_id'], page['variants']):
                raise capture.MissingEvidence('Complete selector journal does not reach the captured terminal selection')
            action_status = 'pass' if change_seen else 'fail'
        report['components']['ordered_selector_actions'] = {'status': action_status, 'reset_observed': reset_observed}
        journal = capsule['effect_journal']
        complete = (type(journal) is dict and set(journal) == {'authority', 'complete', 'events'}
                    and journal['authority'] == 'complete_generated_world_event_journal'
                    and journal['complete'] is True and type(journal['events']) is list)
        report['components']['forbidden_effects'] = {'status': ('pass' if not journal['events'] else 'fail') if complete else 'inconclusive'}
        report['components']['policy_completion'] = {'status': 'pass' if policy_completed else 'inconclusive'}
        statuses = [r['status'] for r in report['components'].values()]
        report['verdict'] = 'fail' if 'fail' in statuses else 'inconclusive' if 'inconclusive' in statuses else 'pass'
    except capture.MissingEvidence as error:
        report['components']['evidence'] = {'status': 'inconclusive', 'reason': str(error)}
        # An incomplete journal cannot erase an independently observed failure.
        report['verdict'] = 'fail' if any(c['status'] == 'fail' for c in report['components'].values()) else 'inconclusive'
    except (ValueError, KeyError, TypeError) as error:
        report['verdict'] = 'fail';report['components']['state'] = {'status': 'fail', 'reason': str(error)}
    return report
