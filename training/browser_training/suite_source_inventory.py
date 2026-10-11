"""Common captured-scope task inventory for any compiled suite task.

A compiled/pinned program supplies requirements. Exact registrations supply
public spans. Private truth cannot fill a missing public span; unvisited-world
completeness and native terminal action outcomes are not inferred here.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from .fact_exposure import object_digest, require
from .fact_role_joins import (selected_configurations, resolved_parts, quote_roles,
                              typed_slot_assertions, page_title_axes, public_part_texts)


def pin(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def checked(record):
    require(pin(record['path']) == record, 'Changed inventory input: ' + record['path'])
    return json.loads(Path(record['path']).read_bytes())


def same_typed_assertion(actual, declared):
    """Keep Boolean/string domains distinct from native JSON Number values."""
    if type(actual) in (int, float) and type(declared) in (int, float):
        return actual == declared
    if type(actual) is not type(declared):
        return False
    if isinstance(actual, dict):
        return (actual.keys() == declared.keys() and
                all(same_typed_assertion(v, declared[k]) for k, v in actual.items()))
    if isinstance(actual, list):
        return len(actual) == len(declared) and all(
            same_typed_assertion(a, d) for a, d in zip(actual, declared))
    return actual == declared


def build_inventory(trace, *, task, compiled, inputs=(), source_inputs=()):
    """Task/program arguments are exact {path, sha256} pins, not prose guesses.

    This returns a reader-compatible partial inventory and preserves all
    information-need templates. Missing source mappings retain explicit reasons.
    It does not compute reward, optimality, oracle relevance or action success.
    """
    trace = Path(trace).resolve()
    native, program = checked(task), checked(compiled)
    require(program.get('schema') == 'compiled-task-requirements-v1' and
            program.get('task_sha256') == object_digest(native) and
            program.get('task_id') == native['task_id'] and
            program.get('source_schema') == native['schema_version'],
            'Compiled task identity differs from original native task')
    metadata = pin(trace/'metadata.json')
    require(checked(metadata).get('native_task_id') == native['task_id'],
            'Task/trace identity mismatch')
    require(checked(metadata).get('fact_recording', {}).get('enabled') is True,
            'Trace has no enabled fact recording')
    for record in [*inputs, *source_inputs]:
        require(pin(record['path']) == record, 'Changed inventory dependency')
    targets, captures, mapped, unresolved = {}, {}, set(), []
    # These are explicit producer field aliases, not text/semantic similarity.
    aliases = {'listed_price_minor': 'listing_price',
               'listed_sku_price_minor': 'listing_price'}
    needs = program['information_needs']
    identity_keys = ('site_id','retailer_id','product_id','page_id','sku_id','offer_id','review_id','quote_id')
    # These three keys describe producer display labels, not task-role membership.
    supported_qualifiers = set(identity_keys) | {'selection','axis_labels','heading','row'}
    unresolved_needs = {}
    for need in needs:
        qualifiers = need.get('qualifiers', {})
        unsupported = sorted(set(qualifiers) - supported_qualifiers)
        if unsupported or not any(qualifiers.get(k) is not None for k in identity_keys):
            unresolved_needs[need['id']] = dict(reason='unresolved_task_role_or_subject',
                unresolved_qualifiers=unsupported, qualifiers=deepcopy(qualifiers))
    for path in sorted(trace.glob('fact-capture-*.json')):
        capture_pin = pin(path)
        cap = checked(capture_pin)
        require(isinstance(cap.get('sources'),list) and
                all(isinstance(s,dict) and isinstance(s.get('id'),str) for s in cap['sources']),
                'Malformed capture source collection')
        require(isinstance(cap.get('private_context',{}),dict), 'Malformed capture private context')
        captures[capture_pin['sha256']] = {'pin': capture_pin}
        sources = {s.get('export_id', s['id']):s for s in cap['sources']}
        # Span export IDs refer to original normalized registrations; native
        # capture sources retain those IDs as export_id when the harness renames.
        normalized = deepcopy(cap.get('private_context', {}))
        rows = normalized.setdefault('occurrences', [])
        rows += typed_slot_assertions(normalized, sources)
        rows += page_title_axes(normalized, sources)
        rows += selected_configurations(normalized, sources)
        semantics = program.get('semantics', {})
        modes = semantics.get('domain', {}).get('allowed_destination_types', [])
        if semantics.get('delivery_selection_scope') == 'valid_home_service':modes = ['home']
        rows += quote_roles(normalized, modes)
        for need in needs:
            if need['id'] in unresolved_needs:
                continue
            for row in rows:
                b, state = row['binding'], row['effective_state']
                if b.get('field') != aliases.get(need['field_role'], need['field_role']):continue
                # Atomic/link scopes carry exact producer identities. Never
                # replace these with another product or selected configuration.
                q = need.get('qualifiers', {})
                assertion = b.get('typed_assertion')
                if assertion is not None:
                    if assertion.get('unit') != need.get('unit'):
                        continue
                    declaration = q.get('row')
                    if declaration is None:
                        if need.get('producer_assertion_id') != assertion['semantic_id']:
                            continue
                    else:
                        texts = public_part_texts(row, sources)
                        if (not isinstance(declaration, dict)
                                or declaration.get('slotId') != b.get('slot_id')
                                or texts.get('label') != declaration.get('label')
                                or not any(same_typed_assertion(assertion, a)
                                           for a in declaration.get('assertions', []))):
                            continue
                scope = {k:b.get(k, state.get(k)) for k in identity_keys}
                scope['site_id'] = scope['site_id'] or state.get('site')
                scope['retailer_id'] = scope['retailer_id'] or scope['site_id']
                if any(q.get(k) is not None and q[k] != scope[k] for k in scope):continue
                if q.get('selection') is not None and need['field_role'] != 'selected_configuration':
                    selection = {**state.get('page_configuration',{}),**state.get('selection',{})}
                    if not all(type(selection.get(k)) is type(v) and selection[k]==v
                               for k,v in q['selection'].items()):continue
                if need['field_role']=='selected_configuration' and q.get('selection') is not None:
                    if b.get('displayed_value') != q['selection']:continue
                scope['effective_state_sha256'] = object_digest(state)
                identifier = need['id'] + '/' + object_digest(scope)
                target = targets.setdefault(identifier, dict(id=identifier, need_id=need['id'],
                    field=need['field_role'], subject=scope, witnesses=[]))
                if assertion is not None:
                    target.setdefault('assertion_bindings', [])
                    if assertion not in target['assertion_bindings']:
                        target['assertion_bindings'].append(deepcopy(assertion))
                parts, missing = resolved_parts(row, sources)
                if not parts:
                    reason = ('configuration_axes_have_no_resolved_public_spans'
                        if row.get('unresolved_axes') else 'DOM_registration_has_no_exact_AX_source_binding')
                    if not target['witnesses']:
                        target['reason'] = reason
                        if row.get('unresolved_axes'):
                            target['unresolved_configuration_axes'] = row['unresolved_axes']
                            target['resolved_configuration_parts'] = resolved_parts(
                                {'parts': row.get('resolved_axis_parts', [])}, sources)[0]
                    unresolved.append(dict(capture=capture_pin,need_id=need['id'],
                        subject=scope,reason=reason,missing_source_ids=missing,
                        unresolved_axes=row.get('unresolved_axes',[])))
                    continue
                witness = {'capture_sha256':capture_pin['sha256'], 'parts':parts}
                if witness not in target['witnesses']:target['witnesses'].append(witness)
                target.pop('reason',None)
                target.pop('unresolved_configuration_axes',None)
                target.pop('resolved_configuration_parts',None)
                mapped.add(need['id'])
    for need in needs:
        if need['id'] not in mapped and not any(t['need_id']==need['id'] for t in targets.values()):
            targets[need['id']] = dict(id=need['id'],need_id=need['id'],field=need['field_role'],
                witnesses=[],**unresolved_needs.get(need['id'],
                    {'reason':'no_resolved_public_source_in_captured_scope'}))
    dependencies = [task, compiled, metadata, *inputs, *source_inputs]
    dependencies += [c['pin'] for c in captures.values()]
    for record in dependencies:
        require(pin(record['path']) == record, 'Inventory inputs changed while projecting')
    return dict(schema='task-model-source-inventory-v1',task=task,
        task_sha256=program['task_sha256'],trace_binding={'metadata':metadata,'task_id':native['task_id']},
        captures=captures,targets=list(targets.values()),inputs=[compiled,*inputs],
        source_inputs=list(source_inputs),field_templates=len(needs),mapped_field_templates=len(mapped),
        unmapped_field_templates=[n['field_role'] for n in needs if n['id'] not in mapped],
        unresolved_occurrence_parts=unresolved,
        qualification='Captured public scopes only; complete unvisited-world coverage, oracle relevance and native action outcomes remain separate')
