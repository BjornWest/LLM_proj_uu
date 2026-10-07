"""Authored audit controls: public text must establish the scoped native value."""
from copy import deepcopy
import json

import pytest

from training.browser_training.fact_exposure import digest, utf16_length
from training.browser_training.fact_public_readiness import audit_captures


def inputs():
    task = {'schema_version': 'website-catalog-compare-review-task-v1',
        'kind': 'compare_facts_and_reviews', 'task_id': 'authored-control',
        'comparison_task': {'models': [{'product_id': 'p'}, {'product_id': 'q'}],
                            'fields': ['product.facts.cushioning']},
        'required_obligations': [
            {'role_id': 'fact', 'product_id': 'p', 'source_family': 'retailer',
             'field': 'product.facts.cushioning', 'unit': None, 'basis': None},
            {'role_id': 'mean', 'product_id': 'q', 'source_family': 'product_reviews',
             'operation': 'rating_summary', 'field': 'summary.mean_rounded'},
            {'role_id': 'count', 'product_id': 'q', 'source_family': 'product_reviews',
             'operation': 'rating_summary', 'field': 'summary.rating_count'}]}
    reference = {'task_id': task['task_id'], 'comparison': {'models': [
        {'product_id': 'p', 'facts': {'product.facts.cushioning':
             {'status': 'known', 'value': 'moderate', 'unit': None, 'basis': None}}}]},
        'reviews': {'q': {'subject': {'product_id': 'q'}, 'summary': {
            'star_counts': {str(s): 1 for s in range(1, 6)}, 'mean_rounded': '3.00',
            'rating_count': 5, 'written_review_count': 3, 'rating_only_count': 2}}}}
    capture = {'schema': 'fact-render-normalized-v1', 'snapshot_id': 'snapshot',
               'document_id': 'doc', 'frame_id': 'frame', 'runs': [], 'ax_sources': [], 'occurrences': []}

    def add(binding, parts, state):
        number = len(capture['occurrences']); spans = []
        for name, text in parts.items():
            sid = f'source-{number}-{name}'
            capture['runs'].append({'id': sid, 'text': text, 'sha256': digest(text)})
            capture['ax_sources'].append({'id': sid, 'text': text, 'sha256': digest(text),
                'binding': {k: capture[k] for k in ('snapshot_id', 'document_id', 'frame_id')}})
            spans.append({'part': name, 'spans': [{'source_id': sid, 'start': 0, 'end': utf16_length(text)}]})
        capture['occurrences'].append({'id': f'o-{number}', 'binding': binding,
                                       'effective_state': state, 'parts': spans})

    add({'authority': 'native_public_field', 'source_family': 'retailer', 'product_id': 'p',
         'subject_type': 'product', 'subject_id': 'p', 'field': 'product.facts.cushioning',
         'displayed_value': 'moderate', 'unit': None, 'status': 'known'},
        {'label': 'Cushioning', 'value': 'moderate'}, {'product_id': 'p'})
    base = {'authority': 'renderer_native_review_aggregate', 'source_family': 'product_reviews',
            'product_id': 'q', 'grain': 'model', 'basis': 'all_recorded_ratings_all_options_including_silent'}
    state = {'product_id': 'q', 'rating_summary_sha256': 'same-corpus'}
    for stars in range(1, 6):
        add({**base, 'field': 'star_counts', 'stars': stars, 'displayed_value': 1},
            {'stars': f'{stars} stars', 'count': '1'}, deepcopy(state))
    add({**base, 'field': 'rating_count', 'displayed_value': 5},
        {'value': '5', 'label': ' ratings; '}, deepcopy(state))
    return task, reference, capture


def run(tmp_path, task, reference, capture):
    path = tmp_path/'capture.json'; path.write_text(json.dumps(capture))
    return audit_captures(task, reference, [path], runtime_binding_sha256='a'*64)


def test_complete_public_parts_and_exact_histogram_establish_all_roles(tmp_path):
    report = run(tmp_path, *inputs())
    assert report['status'] == 'sufficient'
    assert not report['delivery_evidence']
    assert len(report['roles'][1]['evidence']) == 5
    assert all(row['document'] in report['files'] for row in report['roles'])


@pytest.mark.parametrize('mutation', ['printed_value', 'missing_ax', 'foreign_frame',
                                      'missing_label', 'wrong_product', 'wrong_unit'])
def test_native_truth_alone_cannot_establish_a_missing_or_changed_public_fact(tmp_path, mutation):
    task, reference, capture = inputs()
    row = capture['occurrences'][0]
    if mutation == 'printed_value':
        # Truthful binding retained but both actual DOM and AX display another value.
        for source in capture['runs'] + capture['ax_sources']:
            if source['id'] == 'source-0-value':
                source.update(text='intense!', sha256=digest('intense!'))
    elif mutation == 'missing_ax':
        capture['ax_sources'] = [s for s in capture['ax_sources'] if s['id'] != 'source-0-value']
    elif mutation == 'foreign_frame':
        capture['ax_sources'][0]['binding']['frame_id'] = 'foreign'
    elif mutation == 'missing_label':
        row['parts'] = row['parts'][1:]
    elif mutation == 'wrong_product':
        row['binding']['product_id'] = 'q'
    else:
        row['binding']['unit'] = 'kg'
    report = run(tmp_path, task, reference, capture)
    assert report['status'] == 'unresolved' and report['roles'][0]['status'] == 'unresolved'


@pytest.mark.parametrize('mutation', ['wrong_histogram', 'mixed_corpus', 'wrong_basis', 'wrong_label'])
def test_review_mean_requires_actual_labelled_all_rating_cells_in_one_corpus(tmp_path, mutation):
    task, reference, capture = inputs()
    if mutation == 'wrong_histogram':
        for source in capture['runs'] + capture['ax_sources']:
            if source['id'] == 'source-5-count':
                source.update(text='9', sha256=digest('9'))
    elif mutation == 'mixed_corpus':
        capture['occurrences'][5]['effective_state']['rating_summary_sha256'] = 'other-corpus'
    elif mutation == 'wrong_basis':
        capture['occurrences'][5]['binding']['basis'] = 'written_only'
    else:
        for source in capture['runs'] + capture['ax_sources']:
            if source['id'] == 'source-5-stars':
                source.update(text='4 stars', sha256=digest('4 stars'))
    report = run(tmp_path, task, reference, capture)
    assert report['status'] == 'unresolved' and report['roles'][1]['status'] == 'unresolved'


def test_absent_fact_does_not_become_an_unknown_or_na_public_declaration(tmp_path):
    task, reference, capture = inputs()
    reference['comparison']['models'][0]['facts']['product.facts.cushioning']['status'] = 'unknown'
    report = run(tmp_path, task, reference, capture)
    assert report['roles'][0]['status'] == 'unresolved'


def test_stale_capture_hash_and_duplicate_identity_fail_closed(tmp_path):
    task, reference, capture = inputs()
    capture['runs'][0]['sha256'] = 'invalid'
    assert run(tmp_path, task, reference, capture)['status'] == 'unresolved'
    capture['occurrences'].append(capture['occurrences'][0])
    with pytest.raises(ValueError, match='Duplicate occurrence'):
        run(tmp_path, task, reference, capture)


@pytest.mark.parametrize('mutation', [None, 'wrong_value', 'wrong_basis', 'partial_slot'])
def test_whole_selected_slot_uses_its_explicit_scoped_assertion_contract(tmp_path, mutation):
    task, reference, capture = inputs()
    role = task['required_obligations'][0]
    role.update(unit='g', basis='reference configuration')
    expected = reference['comparison']['models'][0]['facts'][role['field']]
    expected.update(value=300, unit='g', basis='reference configuration')
    binding = capture['occurrences'][0]['binding']
    binding.update(authority='selected_slot', field=None, unit=None,
                   displayed_value='300 g for reference configuration', assertions=[{
        'field': role['field'], 'subject': {'kind': 'product', 'id': 'p'},
        'status': 'known', 'value': 300, 'unit': 'g',
        'qualifiers': {'basis': 'reference configuration'},
        'mapping_status': 'authored_scalar_assertion'}])
    text = binding['displayed_value']
    for source in capture['runs'] + capture['ax_sources']:
        if source['id'] == 'source-0-value':
            source.update(text=text, sha256=digest(text))
    span = capture['occurrences'][0]['parts'][1]['spans'][0]
    span['end'] = utf16_length(text)
    if mutation == 'wrong_value':
        binding['assertions'][0]['value'] = 301
    elif mutation == 'wrong_basis':
        binding['assertions'][0]['qualifiers']['basis'] = 'another option'
    elif mutation == 'partial_slot':
        span['end'] -= 5
    report = run(tmp_path, task, reference, capture)
    assert report['roles'][0]['status'] == ('known' if mutation is None else 'unresolved')


@pytest.mark.parametrize('value,displayed,text', [
    (True, 'Yes', 'Yes'), (False, 'No', 'No'), (1.0, 1, '1'),
    (1e-6, 1e-6, '0.000001'), (1e-7, 1e-7, '1e-7'),
    (1e20, 100000000000000000000, '100000000000000000000'), (1e21, 1e21, '1e+21'),
    (-0.0, 0, '0')])
def test_exact_producer_boolean_and_javascript_numeric_displays(tmp_path, value, displayed, text):
    task, reference, capture = inputs()
    reference['comparison']['models'][0]['facts']['product.facts.cushioning']['value'] = value
    capture['occurrences'][0]['binding']['displayed_value'] = displayed
    for source in capture['runs'] + capture['ax_sources']:
        if source['id'] == 'source-0-value':
            source.update(text=text, sha256=digest(text))
    span = capture['occurrences'][0]['parts'][1]['spans'][0]
    span['end'] = utf16_length(text)
    assert run(tmp_path, task, reference, capture)['roles'][0]['status'] == 'known'
    # Matching native metadata cannot excuse a different rendered value.
    for source in capture['runs'] + capture['ax_sources']:
        if source['id'] == 'source-0-value':
            source.update(text='wrong', sha256=digest('wrong'))
    span['end'] = 5
    assert run(tmp_path, task, reference, capture)['roles'][0]['status'] == 'unresolved'


def test_numeric_native_value_cannot_be_satisfied_by_string_or_boolean_metadata(tmp_path):
    task, reference, capture = inputs()
    reference['comparison']['models'][0]['facts']['product.facts.cushioning']['value'] = 1
    capture['occurrences'][0]['binding']['displayed_value'] = '1'
    for source in capture['runs'] + capture['ax_sources']:
        if source['id'] == 'source-0-value':
            source.update(text='1', sha256=digest('1'))
    capture['occurrences'][0]['parts'][1]['spans'][0]['end'] = 1
    assert run(tmp_path, task, reference, capture)['roles'][0]['status'] == 'unresolved'


def test_slot_numeric_transport_preserves_scalar_domain_without_bool_coercion():
    from training.browser_training.fact_public_readiness import _same_native_scalar
    assert _same_native_scalar(1, 1.0)
    assert not _same_native_scalar(True, 1)
    assert not _same_native_scalar('1', 1.0)
