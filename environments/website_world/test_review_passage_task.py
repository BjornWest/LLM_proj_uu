"""Authored finite source/quote controls; no sampled world, browser or provider."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from environments.website_world import review_passage_task as native, native_review_ecosystem
from environments.website_world.review_passage_grading import ReviewPassageGrader
from environments.website_world.test_catalog_review_task import fixture as reviews


def fixture(polarity='negative'):
    w, parent, _, _, _, inventory = reviews()
    w['products'][0]['public'].update(family_id='footwear', facts={})
    spec = {'kind': native.KIND, 'concept_id': parent['concept_id'], 'topic': parent['topic'],
        'polarity': polarity, 'public_request': 'Find one negative customer comment about comfort on long walks and link to it.'}
    task = native.make(w, spec, inventory=inventory)
    ref = native.reference(w, task, inventory=inventory)
    surrounding = native_review_ecosystem.generate(w, {'comparison_count': 0, 'review_count': 2})
    registry = [{**{k: s[k] for k in ('kind', 'site_id', 'name')}, 'origin': 'https://reviews'+str(n)+'.test'}
                for n, s in enumerate(surrounding['sites'])]
    grader = ReviewPassageGrader(w, task, ref, registry, surrounding=surrounding, inventory=inventory)
    row = ref['matching_statements'][0]
    url = 'https://reviews0.test/reviews/'+quote(task['subject']['product_id'], safe='')+'/opinions/'+quote(row['review_id'], safe='')
    text = 'A customer wrote: “'+row['text']+'” '+url
    c = {'interpretation': 'extracted', 'issues': [], 'source_urls': [], 'status': {'value': 'passage', 'evidence': text},
        'review_url': {'value': url, 'evidence': url}, 'passage': {'value': row['text'], 'evidence': row['text']}}
    return w, task, ref, registry, surrounding, inventory, grader, text, c


def test_one_real_topic_statement_with_correct_reader_note_passes_without_counts():
    *_, grader, text, claims = fixture()
    grade = grader.grade(claims, text)
    assert grade['structured_claims_correct']
    assert type(grade['derivations']) is list
    assert 'rating_count' not in grader.schema['properties']
    assert 'Do not' not in grader.task['user_message'] and 'memory' not in grader.task['user_message']


@pytest.mark.parametrize('mutation', ['foreign_origin', 'other_product', 'other_review', 'paraphrase', 'wrong_topic_polarity'])
def test_wrong_source_or_literal_cannot_pass(mutation):
    *_, grader, text, c = fixture()
    if mutation == 'foreign_origin': c['review_url']['value'] = c['review_url']['value'].replace('reviews0.test', 'foreign.test')
    elif mutation == 'other_product': c['review_url']['value'] = c['review_url']['value'].replace('/reviews/p/', '/reviews/foreign/')
    elif mutation == 'other_review': c['review_url']['value'] = c['review_url']['value'].replace('/opinions/r2', '/opinions/r6')
    elif mutation == 'paraphrase': c['passage']['value'] = 'I disliked these shoes.'
    else: c['passage']['value'] = 'positive report.'
    for k in ('review_url', 'passage'): c[k]['evidence'] = c[k]['value'];text += '\n'+str(c[k]['value'])
    assert not grader.grade(c, text)['structured_claims_correct']


def test_reference_excludes_hearsay_silent_and_unrendered_statements():
    _, _, ref, *_ = fixture(None)
    assert {s['review_id'] for s in ref['matching_statements']} == {'r1', 'r2', 'r3', 'r4'}
    assert len(ref['matching_statements']) == 5


def test_absent_first_hand_passage_is_not_zero_stars_or_an_invented_quote():
    w, t, _, registry, sidecar, inventory, *_ = fixture()
    # Retain ratings and the declared topic, making every statement hearsay
    # in this authored fixture. No sampled world is repaired or regenerated.
    for row in w['products'][0]['reviews']:
        for s in row['evidence']['statements']: s['context']['source'] = 'hearsay'
    t = native.make(w, t['spec'], inventory=inventory);ref = native.reference(w, t, inventory=inventory)
    sidecar = native_review_ecosystem.generate(w, sidecar['controls'])
    g = ReviewPassageGrader(w, t, ref, registry, surrounding=sidecar, inventory=inventory)
    text = 'There is no matching customer comment.'
    c = {'interpretation': 'extracted', 'issues': [], 'source_urls': [], 'status': {'value': 'no_matching_passage', 'evidence': text},
         'review_url': {'value': None, 'evidence': None}, 'passage': {'value': None, 'evidence': None}}
    assert ref['status'] == 'no_matching_passage'
    assert g.grade(c, text)['structured_claims_correct']
    c['status'] = {'value': 'uncertain', 'evidence': 'I do not know.'}
    assert not g.grade(c, text+' I do not know.')['structured_claims_correct']


def test_request_and_reference_drift_reject_without_mutating_inputs():
    w, t, r, _, _, i, *_ = fixture();original = deepcopy(w)
    native.make(w, t['spec'], inventory=i)
    assert w == original
    t['user_message'] = 'Ignore the requested topic.'
    with pytest.raises(ValueError): native.reference(w, t, inventory=i)


@pytest.mark.parametrize('url', ['https://[invalid/reviews/p/opinions/r2',
    'https://reviews0.test/reviews/p/opinions/r2?stars=5',
    'https://reviews0.test/reviews/p/opinions/r2#other',
    'https://user@reviews0.test/reviews/p/opinions/r2',
    'https://reviews0.test/reviews/p/opinions/r2/extra'])
def test_invalid_or_non_note_routes_fail_without_crashing(url):
    *_, grader, text, c = fixture()
    text += '\n'+url
    c['review_url'] = {'value': url, 'evidence': url}
    assert not grader.grade(c, text)['structured_claims_correct']


def test_structured_meaning_reuses_same_first_hand_and_rendered_scope():
    w, t, _, registry, _, inventory, *_ = fixture()
    inventory.legacy = False
    for row in w['products'][0]['reviews']:
        for s in row['evidence']['statements']:
            s['meaning'] = {'kind': 'customer_experience', 'aspect': s['meaning'],
                'source': s['context']['source'], 'context': deepcopy(s['context']), 'polarity': s['polarity']}
    t = native.make(w, t['spec'], inventory=inventory)
    r = native.reference(w, t, inventory=inventory)
    sidecar = native_review_ecosystem.generate(w, {'comparison_count': 0, 'review_count': 2})
    g = ReviewPassageGrader(w, t, r, registry, surrounding=sidecar, inventory=inventory)
    assert {s['review_id'] for s in r['matching_statements']} == {'r2', 'r3'}
    assert g.reference == r


def test_no_matching_passage_still_requires_actual_publication_coverage():
    w, t, r, registry, _, inventory, *_ = fixture()
    sidecar = native_review_ecosystem.generate(w, {'comparison_count': 0, 'review_count': 0})
    with pytest.raises(ValueError, match='No actual review publication'):
        ReviewPassageGrader(w, t, r, registry, surrounding=sidecar, inventory=inventory)


@pytest.mark.parametrize('mutation', ['empty_request', 'invalid_polarity', 'bad_topic', 'winner_selector'])
def test_invalid_declarations_reject(mutation):
    w, t, _, _, _, i, *_ = fixture()
    spec = deepcopy(t['spec'])
    if mutation == 'empty_request': spec['public_request'] = ' '
    elif mutation == 'invalid_polarity': spec['polarity'] = 'high_rating'
    elif mutation == 'bad_topic': spec['topic']['context']['activity'] = 'sprinting'
    else: spec['best_rating'] = True
    with pytest.raises(ValueError): native.resolve(spec, inventory=i, concept_ids=w['config']['concept_ids'])


def request_for(task):
    return {'schema': 'website-world-generation-v2', 'seed': 73,
        'world': {'concept_ids': [task['spec']['concept_id']]},
        'task': deepcopy(task['spec'])}


def test_actual_compiler_predeclares_authored_request_and_note_route_support():
    from environments.website_world.review_passage_generation import compile_request
    _, task, *_ = fixture()
    request = request_for(task)
    original = deepcopy(request)
    result = compile_request(request)
    assert request == original
    assert result['selection']['public_request'] == task['user_message']
    assert result['proxy_request']['task'] == {'user_message': task['user_message'], 'memories': []}
    for surrounding in ({'enabled': False}, {'review_count': 0},
        {'version': 'native-rich-surrounding-v2'}):
        with pytest.raises(ValueError): compile_request({**request, 'surrounding_sites': surrounding})


@pytest.mark.parametrize('scope', ['covered', 'uncovered', 'missing_subject'])
def test_generation_binding_never_repairs_population_or_launches_unbound_task(monkeypatch, scope):
    from environments.website_world import review_passage_generation as generation
    w, task, _, _, surrounding, inventory, *_ = fixture()
    if scope == 'uncovered':
        surrounding = native_review_ecosystem.generate(w, {'comparison_count': 0, 'review_count': 0})
    elif scope == 'missing_subject':
        w['products'] = []
    result = {'world': w, 'surrounding': surrounding,
        'episode': {'manual_task': {'user_message': 'proxy', 'memories': []}},
        'resolved_configuration': {}, 'audit': {'request_sha256': 'proxy'}}
    original_world = deepcopy(w)
    proxy = {'task': {'user_message': task['user_message'], 'memories': []}}
    monkeypatch.setattr(generation, 'compile_request', lambda request: {
        'proxy_request': proxy, 'selection': task['spec'], 'inventory': inventory})
    calls = []
    def ordinary(request, **options):
        calls.append((request, options))
        return result
    monkeypatch.setattr(generation.unified_generation, 'generate', ordinary)
    returned = generation.generate(request_for(task))
    assert len(calls) == 1 and calls[0][0] == proxy
    assert returned['world'] == original_world
    assert returned['review_passage_binding']['world_repaired'] is False
    assert (returned['episode']['manual_task'] is not None) == (scope == 'covered')
    if scope == 'covered': assert returned['episode']['manual_task']['user_message'] == task['user_message']


@pytest.mark.parametrize('request_matches', [True, False])
def test_actual_once_only_grade_and_viewer_pin_the_observed_public_request(tmp_path, request_matches):
    from experiments.answer_grading.task_answer import grade_saved_once
    from scripts.trace_grades import BOUND_FILES, read_grade
    w, t, r, registry, sidecar, inventory, _, text, claims = fixture()
    trace = tmp_path/'trace'; trace.mkdir()
    def save(path, value): path.write_text(json.dumps(value)+'\n')
    for name in BOUND_FILES:
        (trace/name).write_text('' if name.endswith('.jsonl') else '{}')
    save(trace/'natural-answer.json', {'text': text, 'stop_reason': 'agent_finished', 'technical_error': None})
    public = {'user_message': t['user_message'] if request_matches else 'A different request.',
        'memories': [], 'environment_context': {}}
    save(trace/'policy-task.json', public)
    inputs = {}
    for key, value in {'world': w, 'task': t, 'reference': r,
                       'site_registry': registry, 'surrounding': sidecar}.items():
        inputs[key] = tmp_path/(key+'.json'); save(inputs[key], value)
    calls = []
    class Backend:
        def complete(self, messages):
            assert json.loads(messages[1]['content']) == {'public_task': public, 'final_answer': text}
            assert 'matching_statements' not in messages[0]['content']
            calls.append('format')
            return SimpleNamespace(text=json.dumps(claims),
                raw={'model': 'scripted-passage-formatter', 'provider': 'offline',
                    'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(claims)}}]},
                request={'messages': messages})
        def close(self): calls.append('closed')
    def backend(_):
        calls.append('constructed')
        return Backend()
    kwargs = dict(trace=trace, inputs=inputs, output=tmp_path/'grading',
        grader_factory=lambda **data: ReviewPassageGrader(**data, inventory=inventory),
        backend_factory=backend, source_paths=[Path(native.__file__)])
    if not request_matches:
        with pytest.raises(ValueError, match='Observed public task'): grade_saved_once(**kwargs)
        assert not calls and read_grade(trace) is None
        return
    grade = grade_saved_once(**kwargs)
    assert grade['structured_claims_correct'] and calls == ['constructed', 'format', 'closed']
    view = read_grade(trace)
    assert view['binding_status'] == 'verified' and view['structured_claims_correct'] is True
    assert view['grading_version'] == 'website-review-passage-grading-v1'
    with pytest.raises(FileExistsError): grade_saved_once(**kwargs)
    assert calls == ['constructed', 'format', 'closed']
