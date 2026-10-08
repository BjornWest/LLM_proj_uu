"""Real delivery ledger → strict scoped rows → approved two-row conjunction.

Synthetic transport controls only; actual saved capture acceptance is separate.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from intent_browser.policy_delivery import PolicyDelivery
from training.browser_training.fact_delivery_features import extract
from training.browser_training.fact_exposure import digest, object_digest
from training.browser_training.fact_native_mass_join import BASIS, MASS, LITERAL, join_role, audit_captures

PID = 'footwear-brand-11/footwear.walking_shoes/01'
ROLE = {'role_id': f'model_1.fact.{MASS}', 'product_id': PID}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))


def capture(path, *, index=0, step=0, revision=3, fields=(MASS, BASIS), size='42'):
    sid = f'fact-capture-{index:04d}'
    state = {'site': 'store1', 'page_id': 'page1', 'product_id': PID, 'sku_id': 'sku-'+size,
             'selection': {'size_eu': size}, 'offer_id': 'offer-'+size, 'variant_key': 'sku-'+size}
    sources, occurrences = [], []
    for n, field in enumerate(fields):
        label = 'Reference mass g' if field == MASS else 'Mass basis'
        value = 250 if field == MASS else LITERAL
        text = label + ': ' + str(value)
        oid = f'{sid}/o{n}'; eid = f'run{n}'; source_id = f'{sid}-source-{n:04d}'
        spans = [{'part': 'label', 'spans': [{'source_id': eid, 'start': 0, 'end': len(label)}]},
                 {'part': 'value', 'spans': [{'source_id': eid, 'start': len(label)+2, 'end': len(text)}]}]
        sources.append({'id': source_id, 'export_id': eid, 'text': text, 'sha256': digest(text),
            'captured_step': step, 'binding': {'snapshot_id': sid, 'document_id': 'd1', 'frame_id': 'f1',
                                             'node_id': str(n), 'field': 'name'},
            'opaque_binding': {'render_revision': revision, 'parts': [
                {'occurrence_id': oid, 'state_id': object_digest(state), 'part': part['part'],
                 'start': part['spans'][0]['start'], 'end': part['spans'][0]['end']} for part in spans]}})
        occurrences.append({'id': oid, 'binding': {'source_family': 'retailer', 'authority': 'native_public_field',
            'site_id': 'store1', 'page_id': 'page1', 'product_id': PID, 'subject_type': 'product',
            'subject_id': PID, 'field': field, 'status': None, 'unit': None, 'displayed_value': value},
            'effective_state': deepcopy(state), 'parts': spans})
    save(path/(sid+'.json'), {'schema': 'ax-fact-provenance-v1', 'offset_unit': 'utf16_code_units',
        'id': sid, 'step': step, 'snapshot_id': sid, 'sources': sources,
        'private_context': {'schema': 'fact-render-occurrence-joins-v1', 'occurrences': occurrences}})
    return sources


def deliver(path, fragments, *, step=0, previous=None, ack=True, recipient='main'):
    ledger, rows = previous or (PolicyDelivery(SimpleNamespace(directory=path, event=lambda *a, **k: None)), [])
    messages, bindings = [], []
    for source, start, end in fragments:
        text = source['text'][start:end]
        cid = ledger.register('ax_result', text, step=step)
        artifact = f'projection-{cid}.json'
        save(path/artifact, {'schema': 'ax-fact-provenance-v1', 'offset_unit': 'utf16_code_units',
            'content_id': cid, 'text_sha256': digest(text), 'projections': [{
                'source_id': source['id'], 'source_sha256': source['sha256'],
                'binding_sha256': object_digest(source['binding']), 'source_start': start,
                'source_end': end, 'output_path': [], 'output_start': 0, 'output_end': end-start,
                'encoding': 'identity'}]})
        ledger.sources[cid]['provenance'] = {'fact_projection_artifact': artifact}
        save(path/ledger.sources[cid]['artifact'], ledger.sources[cid])
        bindings.append({'content_id': cid, 'message_index': len(messages), 'start': 0, 'end': len(text)})
        messages.append({'role': 'tool', 'content': text})
    event = {'step': step, 'messages': messages, 'model_request': {'messages': messages}}
    ledger.record(event, bindings, acknowledged=ack, recipient=recipient)
    rows.append(event)
    (path/'steps.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    return ledger, rows


def records(path, step=0):
    return extract(path, step=step, strict_render=True)['records']


def full(source):
    return source, 0, len(source['text'])


def test_actual_ledger_requires_both_rows_and_complete_parts(tmp_path):
    mass, basis = capture(tmp_path)
    previous = deliver(tmp_path, [full(mass)])
    assert join_role(ROLE, records(tmp_path))['observation_status'] == 'partial'
    previous = deliver(tmp_path, [(basis, 0, 10)], step=1, previous=previous)
    assert join_role(ROLE, records(tmp_path, 1))['observation_status'] == 'partial'
    deliver(tmp_path, [(basis, 10, len(basis['text']))], step=2, previous=previous)
    joined = join_role(ROLE, records(tmp_path, 2))
    assert joined['observation_status'] == 'complete'
    assert joined['evidence'][0]['observed_value'] == 250
    assert len(joined['evidence'][0]['records']) == 2
    # EU40 is a reference basis, not a requirement on the selected size42.
    assert joined['evidence'][0]['effective_state']['selection']['size_eu'] == '42'
    assert join_role(ROLE, records(tmp_path, 0))['observation_status'] == 'partial'


@pytest.mark.parametrize('control', ['no_delivery', 'unacknowledged', 'other_recipient', 'value_only'])
def test_source_presence_or_unconfirmed_output_never_establishes_join(tmp_path, control):
    sources = capture(tmp_path)
    if control != 'no_delivery':
        fragments = [full(s) for s in sources]
        if control == 'value_only':
            fragments = [(s, s['text'].index(': ')+2, len(s['text'])) for s in sources]
        deliver(tmp_path, fragments, ack=control != 'unacknowledged',
                recipient='worker' if control == 'other_recipient' else 'main')
    assert join_role(ROLE, records(tmp_path))['observation_status'] != 'complete'


@pytest.mark.parametrize('control', ['document', 'frame', 'revision', 'variant', 'page', 'site', 'subject'])
def test_cross_scope_rows_cannot_be_joined(tmp_path, control):
    sources = capture(tmp_path); deliver(tmp_path, [full(s) for s in sources])
    rows = records(tmp_path)
    basis = next(r for r in rows if r['binding']['field'] == BASIS)
    if control in ('document', 'frame'):
        basis['render_scope'][control+'_id'] = 'different'
    elif control == 'revision':
        basis['render_scope']['render_revision'] += 1
    elif control == 'variant':
        basis['effective_state']['selection']['size_eu'] = '43'
    elif control in ('page', 'site'):
        basis['binding'][control+'_id'] = 'different'
        basis['effective_state']['page_id' if control == 'page' else 'site'] = 'different'
    else:
        basis['binding']['subject_id'] = 'other'
    assert join_role(ROLE, rows)['observation_status'] != 'complete'


@pytest.mark.parametrize('control', ['bool', 'float', 'NA', 'unknown', 'unit', 'basis', 'label', 'conflict'])
def test_malformed_or_conflicting_values_are_not_selected_by_expected_answer(tmp_path, control):
    sources = capture(tmp_path); deliver(tmp_path, [full(s) for s in sources])
    rows = records(tmp_path)
    mass = next(r for r in rows if r['binding']['field'] == MASS)
    basis = next(r for r in rows if r['binding']['field'] == BASIS)
    if control in ('bool', 'float'):
        mass['binding']['displayed_value'] = True if control == 'bool' else 250.0
    elif control in ('NA', 'unknown'):
        mass['binding']['status'] = 'not_applicable' if control == 'NA' else 'unknown'
    elif control == 'unit':
        mass['binding']['unit'] = 'kg'
    elif control == 'basis':
        basis['binding']['displayed_value'] = basis['parts']['value']['observed_text'] = 'pair'
    elif control == 'label':
        mass['parts']['label']['observed_text'] = 'Weight'
    else:
        other = deepcopy(mass); other['id'] = 'contradiction'
        other['binding']['displayed_value'] = 251; other['parts']['value']['observed_text'] = '251'
        rows.append(other)
    assert join_role(ROLE, rows)['observation_status'] == 'unknown'


def test_strict_extraction_does_not_union_changed_render_snapshots(tmp_path):
    first = capture(tmp_path, fields=(MASS,))[0]
    second = capture(tmp_path, index=1, step=1, revision=4, fields=(MASS,))[0]
    previous = deliver(tmp_path, [(first, 0, 10)])
    deliver(tmp_path, [(second, 10, len(second['text']))], step=1, previous=previous)
    strict = records(tmp_path, 1)
    assert len(strict) == 2 and all(r['status'] != 'complete' for r in strict)
    assert extract(tmp_path, step=1)['records'][0]['status'] == 'complete'


def test_strict_extraction_can_union_same_document_revision_across_snapshots(tmp_path):
    first = capture(tmp_path, fields=(MASS,))[0]
    second = capture(tmp_path, index=1, step=1, fields=(MASS,))[0]
    previous = deliver(tmp_path, [(first, 0, 10)])
    deliver(tmp_path, [(second, 10, len(second['text']))], step=1, previous=previous)
    strict = records(tmp_path, 1)
    assert len(strict) == 1 and strict[0]['status'] == 'complete'
    assert len(strict[0]['source_spans']) == 4


def test_exact_request_inventory_prevents_future_same_step_credit(tmp_path):
    mass = capture(tmp_path, fields=(MASS,))[0]
    basis = capture(tmp_path, index=1, fields=(BASIS,))[0]
    deliver(tmp_path, [full(mass), full(basis)])
    bounded = extract(tmp_path, step=0, strict_render=True,
                      capture_artifacts={'fact-capture-0000.json'})
    assert join_role(ROLE, bounded['records'])['observation_status'] == 'partial'


def test_missing_revision_fails_closed(tmp_path):
    sources = capture(tmp_path)
    saved = json.loads((tmp_path/'fact-capture-0000.json').read_text())
    for source in saved['sources']:
        del source['opaque_binding']['render_revision']
    save(tmp_path/'fact-capture-0000.json', saved)
    deliver(tmp_path, [full(s) for s in sources])
    result = extract(tmp_path, step=0, strict_render=True)
    assert result['records'] == [] and result['diagnostics']['invalid_occurrence'] == 2


def test_transient_capture_replacement_cannot_supply_evidence_under_old_hash(tmp_path, monkeypatch):
    capture(tmp_path)
    transport = json.loads((tmp_path/'fact-capture-0000.json').read_text())
    normalized = {'schema': 'fact-render-normalized-v1', 'snapshot_id': transport['snapshot_id'],
        'document_id': 'd1', 'frame_id': 'f1', 'render_revision': 3,
        'occurrences': transport['private_context']['occurrences'], 'runs': [], 'ax_sources': []}
    for source in transport['sources']:
        normalized['runs'].append({'id': source['export_id'], 'text': source['text'], 'sha256': source['sha256']})
        normalized['ax_sources'].append({'id': source['export_id'], 'text': source['text'],
                                         'sha256': source['sha256'], 'binding': source['binding']})
    path = tmp_path/'public.json'; save(path, normalized)
    original = path.read_bytes()
    task = {'schema_version': 'website-catalog-compare-review-task-v1', 'kind': 'compare_facts_and_reviews',
        'task_id': 'synthetic', 'comparison_task': {'models': [{'product_id': PID}, {'product_id': 'other'}],
            'fields': [MASS]}, 'required_obligations': [{**ROLE, 'field': MASS, 'source_family': 'retailer',
                                                      'unit': 'g', 'basis': LITERAL}]}
    reference = {'task_id': 'synthetic', 'comparison': {'models': [{'product_id': PID, 'facts': {
        MASS: {'value': 250, 'status': 'known', 'unit': 'g', 'basis': LITERAL}}}]}, 'reviews': {}}
    transient = deepcopy(normalized)
    transient['occurrences'][0]['id'] = 'not-present-in-pinned-bytes'
    changed = json.dumps(transient).encode()
    reader = Path.read_bytes; calls = []
    def replace_second_read(p):
        if p == path:
            calls.append(p)
            return changed if len(calls) == 2 else original
        return reader(p)
    monkeypatch.setattr(Path, 'read_bytes', replace_second_read)
    with pytest.raises(ValueError, match='Capture changed between public-audit passes'):
        audit_captures(task, reference, [path], runtime_binding_sha256='a'*64,
                       contract={'task_sha256': object_digest(task), 'roles': [ROLE['role_id']]})
    assert len(calls) == 2 and sha256(reader(path)).digest() == sha256(original).digest()
