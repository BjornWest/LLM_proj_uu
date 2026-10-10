"""Configuration permutations, native grading and immutable saved-input controls."""
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from . import task_instances as api
from .catalog_statistics_grading import CatalogStatisticsGrader
from .test_catalog_statistics_task import fixture, answer
from .test_catalog_review_task import fixture as review_fixture


@pytest.fixture
def saved(tmp_path, monkeypatch):
    world, surrounding, task, reference, sites = fixture('count')
    directory = tmp_path/'saved'
    directory.mkdir()
    records = {'pin/world.private.json': world, 'surrounding.private.json': surrounding,
        'catalog-statistics-task.private.json': task,
        'catalog-statistics-reference.private.json': reference,
        'episode.json': {'task_id': task['task_id'], 'start': {'kind': 'directory'},
            'manual_task': {'user_message': task['user_message'], 'memories': []}},
        'execution.private.json': {}, 'presentation.json': {'unchanged': True},
        'saved-answer-setup.private.json': {'old_public_setup': True}}
    for name, value in records.items():
        api._write(directory/name, api._bytes(value))
    manifest = {'recipe': 'website-catalog-statistics-publication-v1',
        'files': {name: api.publication.file_hash(directory/name) for name in records},
        'source_sha256': {}, 'saved_answer_recipe': api.publication.VERSION}
    api._write(directory/'manifest.json', api._bytes(manifest))
    instance = {'schema': api.VERSION, 'family': 'catalog_statistics',
        'source': {'recipe': str(directory), 'manifest_sha256': api.publication.file_hash(directory/'manifest.json')},
        'parameters': {'kind': 'comparison_catalog_statistics', 'concept_id': 'footwear.walking_shoes',
            'comparison_site_id': 'comparison-00', 'operation': 'median', 'grain': 'listing'},
        'user_message': 'How many priced walking-shoe listings are there, and what is their median price in SEK?',
        'start': {'kind': 'comparison_catalog', 'comparison_site_id': 'comparison-00'},
        'requirements': {'status': 'summary', 'minimum_population': 1}}
    # These tests exercise real native constructors/graders and the real shared
    # publication writer. Only expensive producer/source collection is isolated.
    calls = []
    def freeze(world, destination):
        calls.append(world)
        destination.mkdir(parents=True)
        return {'files': {}, 'source_sha256': {}}
    monkeypatch.setattr(api.publication, 'Execution', lambda **kwargs: SimpleNamespace(freeze=freeze))
    monkeypatch.setattr(api.publication, '_bind', lambda *args, **kwargs: lambda: {})
    return SimpleNamespace(instance=instance, directory=directory, sites=sites,
        world=world, surrounding=surrounding, calls=calls)


def test_new_operation_and_grain_use_existing_native_grader(saved):
    before = deepcopy(saved.instance)
    checked = api.inspect(saved.instance)
    assert saved.instance == before and checked['reference']['population_count'] == 8
    assert checked['reference']['aggregate_sek'] == '850.00'
    text, claims = answer(checked['reference'])
    grader = CatalogStatisticsGrader(saved.world, checked['task'], checked['reference'],
        saved.sites, surrounding=saved.surrounding)
    assert grader.grade(claims, text)['structured_claims_correct']
    wrong = deepcopy(claims)
    wrong['population_count'] = {'value': 2, 'evidence': text + '; 2'}
    assert not grader.grade(wrong, text + '; 2')['structured_claims_correct']


def test_prepare_keeps_world_sites_old_prose_and_one_freeze(saved, tmp_path):
    parent = {str(p.relative_to(saved.directory)): p.read_bytes()
              for p in saved.directory.rglob('*') if p.is_file()}
    output = tmp_path/'prepared'
    receipt = api.prepare(saved.instance, output)
    recipe = output/'recipe'
    assert receipt['runtime_acceptance'] == 'pending' and len(saved.calls) == 1
    manifest = json.loads((recipe/'manifest.json').read_bytes())
    tokenizer = 'intent_browser/model_tokenizers.json'
    assert manifest['source_sha256'][tokenizer] == api.publication.file_hash(api.publication.ROOT/tokenizer)
    assert (recipe/'pin/source-snapshot'/tokenizer).read_bytes() == (api.publication.ROOT/tokenizer).read_bytes()
    for asset in ('intent_browser/assets/chat/chat.html',
                  'intent_browser/assets/chat/LICENSE.browsergym.txt',
                  'intent_browser/observation_revision.js'):
        assert manifest['source_sha256'][asset] == api.publication.file_hash(api.publication.ROOT/asset)
        assert (recipe/'pin/source-snapshot'/asset).read_bytes() == (api.publication.ROOT/asset).read_bytes()
    policy_dir = 'environments/product_world/data/product_feature_policies/catalogue_v2/'
    policies = json.loads((api.publication.ROOT/policy_dir/'manifest.json').read_bytes())
    for member in policies['concepts'].values():
        assert manifest['source_sha256'][policy_dir + member['file']] == member['sha256']
        assert (recipe/'pin/source-snapshot'/policy_dir/member['file']).is_file()
    for name, payload in parent.items():
        assert (saved.directory/name).read_bytes() == payload
    for name in ('pin/world.private.json', 'surrounding.private.json', 'presentation.json'):
        assert (recipe/name).read_bytes() == parent[name]
    for name in ('catalog-statistics-task.private.json', 'catalog-statistics-reference.private.json',
                 'episode.json', 'saved-answer-setup.private.json'):
        assert (recipe/'instance-history'/saved.instance['source']['manifest_sha256']/name).read_bytes() == parent[name]
    task = json.loads((recipe/'catalog-statistics-task.private.json').read_bytes())
    setup = json.loads((recipe/'saved-answer-setup.private.json').read_bytes())
    episode = json.loads((recipe/'episode.json').read_bytes())
    assert task['operation'] == 'median' and task['grain'] == 'listing'
    assert setup['user_message'] == saved.instance['user_message']
    assert episode['manual_task']['user_message'] == task['user_message']
    assert setup['task_id'] == episode['task_id'] == receipt['task_id']
    assert setup['memories'] == task['memories'] == []


def test_wording_edit_keeps_native_id_and_reference(saved):
    first = api.inspect(saved.instance)
    saved.instance['user_message'] = 'What is the median listed price here?'
    second = api.inspect(saved.instance)
    assert first['task'] == second['task'] and first['reference'] == second['reference']
    assert first['setup']['user_message'] != second['setup']['user_message']


def test_prepared_recipe_can_seed_another_permutation(saved, tmp_path):
    first = tmp_path/'first'
    api.prepare(saved.instance, first)
    next_instance = deepcopy(saved.instance)
    next_instance['source'] = {'recipe': str(first/'recipe'),
        'manifest_sha256': api.publication.file_hash(first/'recipe/manifest.json')}
    next_instance['parameters']['operation'] = 'maximum'
    next_instance['user_message'] = 'What is the maximum listed price?'
    second = tmp_path/'second'
    receipt = api.prepare(next_instance, second)
    task = json.loads((second/'recipe/catalog-statistics-task.private.json').read_bytes())
    assert task['operation'] == 'maximum' and len(saved.calls) == 2
    assert receipt['task_id'] != json.loads((first/'prepared-instance.json').read_bytes())['task_id']
    old_config = second/'recipe/instance-history'/next_instance['source']['manifest_sha256']/'task-instance.private.json'
    assert old_config.read_bytes() == (first/'recipe/task-instance.private.json').read_bytes()


def test_ordinary_native_review_recipe_gets_validated_saved_start(saved, tmp_path):
    world, task, reference, _, surrounding, _ = review_fixture('rating_summary')
    source = tmp_path/'ordinary-review'
    source.mkdir()
    records = {'pin/world.private.json': world, 'surrounding.private.json': surrounding,
        'catalog-review-task.private.json': task, 'catalog-review-reference.private.json': reference,
        'episode.json': {'task_id': task['task_id'], 'start': {'kind': 'directory'},
                        'manual_task': {'user_message': task['user_message'], 'memories': []}},
        'execution.private.json': {}}
    for name, value in records.items():
        api._write(source/name, api._bytes(value))
    parent = {'recipe': 'website-catalog-review-publication-v1',
        'files': {name: api.publication.file_hash(source/name) for name in records}}
    api._write(source/'manifest.json', api._bytes(parent))
    instance = {**saved.instance, 'family': 'catalog_review',
        'source': {'recipe': str(source), 'manifest_sha256': api.publication.file_hash(source/'manifest.json')},
        'parameters': {'kind': 'summarize_product_reviews', 'concept_id': task['concept_id'],
                       'operation': 'rating_summary'},
        'user_message': 'Summarize the customer ratings.',
        'start': {'kind': 'review_product', 'site_id': surrounding['sites'][0]['site_id']}}
    output = tmp_path/'review-prepared'
    api.prepare(instance, output)
    manifest = json.loads((output/'recipe/manifest.json').read_bytes())
    setup = json.loads((output/'recipe/saved-review-setup.private.json').read_bytes())
    assert manifest['saved_review_recipe'] == 'website-saved-review-publication-v1'
    assert setup['start']['product_id'] == task['subject']['product_id']
    assert setup['start']['site_id'] == instance['start']['site_id']
    assert 'saved_review_recipe' not in json.loads((source/'manifest.json').read_bytes())


@pytest.mark.parametrize('change', [
    {'requirements': {'minimum_population': 9}},
    {'start': {'kind': 'comparison_catalog', 'comparison_site_id': 'wrong'}},
    {'memories': [{'text': 'Use a different population.'}]},
    {'family': 'feature_offer'},
])
def test_incompatible_instance_stops_before_output_or_freeze(saved, tmp_path, change):
    instance = {**saved.instance, **change}
    with pytest.raises(ValueError):
        api.prepare(instance, tmp_path/'rejected')
    assert not (tmp_path/'rejected').exists() and not saved.calls


def test_saved_input_drift_rejects_before_reference(saved):
    (saved.directory/'surrounding.private.json').write_text('{}')
    with pytest.raises(ValueError, match='Saved recipe file changed'):
        api.inspect(saved.instance)


def test_dispatch_uses_existing_graded_runner_and_detects_changed_config(saved, tmp_path):
    destination = tmp_path/'prepared'
    api.prepare(saved.instance, destination)
    options = {'policy_session': object(), 'metadata': {'tags': ['scripted']},
               'runner_options': {'max_steps': 2}, 'viewer_projection': object()}
    with patch.object(api.adapters.statistics_saved_answer, 'run', return_value='graded') as run:
        assert api.run(destination, tmp_path/'run', **options) == 'graded'
        run.assert_called_once_with(destination/'recipe', tmp_path/'run', **options)
        (destination/'recipe/task-instance.private.json').write_text('{}')
        with pytest.raises(ValueError, match='Saved recipe file changed'):
            api.run(destination, tmp_path/'run2', **options)
        assert run.call_count == 1


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '{"a":1,"a":2}'])
def test_ambiguous_or_nonfinite_json_rejected(tmp_path, value):
    path = tmp_path/'bad.json'
    path.write_text(value)
    with pytest.raises(ValueError):
        api.load(path)


@pytest.mark.parametrize('change', [
    {'allow_ungraded': True}, {'schema': 'v0'}, {'family': 'arbitrary'},
    {'user_message': ' '}, {'requirements': {'minimum_population': True}},
    {'source': {'recipe': '.', 'manifest_sha256': '0'}},
])
def test_config_validation_keeps_errors_local(saved, change):
    with pytest.raises(ValueError):
        api.validate({**saved.instance, **change})


def test_state_adapter_receives_authenticated_snapshot_and_native_config(saved, monkeypatch, tmp_path):
    delegate = api.adapters.ADAPTERS['catalog_statistics']
    seen = {}
    class StateAdapter:
        stem = delegate.stem
        recipe = delegate.recipe
        task_file = delegate.task_file
        reference_file = delegate.reference_file
        inventory_file = delegate.inventory_file
        def recipe_matches(self, manifest):
            return manifest['recipe'] == delegate.recipe
        def construct(self, world, surrounding, parameters, *, snapshot):
            seen['construct'] = snapshot
            return delegate.construct(world, surrounding, parameters)
        def records(self, *args, snapshot, instance):
            seen['records'] = snapshot
            seen['instance'] = deepcopy(instance)
            return delegate.records(*args)
        def metrics(self, reference):
            return {'status': 'ready', 'population': reference['population_count']}
        def manifest_updates(self, prepared):
            return {'state_protocol': 'actual-capture-v1'}
        def execution_overrides(self, prepared):
            return {'answer_grading': {'mode': 'subscription-post-run', 'model': 'fixture-extractor', 'reasoning_effort': 'low'}}
        def run(self, *args, **options):
            return delegate.run(*args, **options)
    monkeypatch.setitem(api.adapters.ADAPTERS, 'state_fixture', StateAdapter())
    instance = {**saved.instance, 'family': 'state_fixture', 'requirements': {'status': 'ready', 'minimum_population': 1}}
    output = tmp_path/'state-prepared'
    api.prepare(instance, output)
    assert seen['construct'] == seen['records']
    assert seen['construct'][2]['pin/world.private.json'] == (saved.directory/'pin/world.private.json').read_bytes()
    assert seen['instance'] == instance
    execution = json.loads((output/'recipe/execution.private.json').read_bytes())
    assert execution['answer_grading'] == {'mode': 'subscription-post-run', 'model': 'fixture-extractor', 'reasoning_effort': 'low'}
    manifest = json.loads((output/'recipe/manifest.json').read_bytes())
    assert manifest['state_protocol'] == 'actual-capture-v1'
    assert manifest['automatic_grader_supported'] and not manifest['automatic_grading_attached']


@pytest.mark.parametrize('overrides', [
    {'answer_grading': {'mode': 'off'}},
    {'answer_grading': {'mode': 'subscription-post-run', 'model': ''}},
    {'answer_grading': {'mode': 'subscription-post-run', 'allow_ungraded': True}},
    {'source_sha256': {}},
    {'runtime_options': {}},
])
def test_execution_protocol_cannot_disable_grading_or_replace_bindings(saved, tmp_path, overrides):
    snapshot = api.publication.read_recipe(saved.directory,
        expected_manifest_sha256=saved.instance['source']['manifest_sha256'])
    task = json.loads(snapshot[2]['catalog-statistics-task.private.json'])
    setup = {'schema': api.publication.VERSION, 'task_id': task['task_id'],
             'memories': task['memories'], 'user_message': 'Count these models.'}
    with pytest.raises(ValueError):
        api.publication.prepare_saved(snapshot, tmp_path/'rejected-protocol',
            expected_manifest_sha256=saved.instance['source']['manifest_sha256'], setup=setup,
            task_filename='catalog-statistics-task.private.json', adapter_file=api.__file__,
            execution_overrides=overrides)
    assert not (tmp_path/'rejected-protocol').exists() and not saved.calls


def test_adapter_extension_cannot_overwrite_source_or_grader_binding():
    adapter = SimpleNamespace(manifest_updates=lambda prepared: {'source_sha256': {}})
    with pytest.raises(ValueError, match='core bindings'):
        api._manifest_updates(adapter, {})


@pytest.mark.parametrize('kind,accepted', [
    ('select_exact_variant', True), ('add_exact_quantity', True),
    ('read_listed_price', False), ('read_public_fact', False),
])
def test_native_atomic_state_protocol_needs_no_answer_extractor(saved, tmp_path, kind, accepted):
    snapshot = api.publication.read_recipe(saved.directory,
        expected_manifest_sha256=saved.instance['source']['manifest_sha256'])
    root, manifest, buffers = snapshot
    task = json.loads(buffers['catalog-statistics-task.private.json'])
    task['kind'] = kind
    buffers = {**buffers, 'atomic-product-task.private.json': api._bytes(task)}
    # The shared preparation stage archives the previous public setup instead
    # of presenting it as an unchanged file to the source freezer.
    manifest = {**manifest, 'files': {name: value for name, value in manifest['files'].items()
                                     if name != 'saved-answer-setup.private.json'}}
    setup = {'schema': api.publication.VERSION, 'task_id': task['task_id'],
             'memories': task['memories'], 'user_message': 'Use the selected option.'}
    args = dict(expected_manifest_sha256=saved.instance['source']['manifest_sha256'],
                setup=setup, task_filename='atomic-product-task.private.json',
                adapter_file=api.__file__, execution_overrides={'answer_grading': {'mode': 'off'}})
    output = tmp_path/'native-state'
    if not accepted:
        with pytest.raises(ValueError):
            api.publication.prepare_saved((root,manifest,buffers), output, **args)
        assert not output.exists() and not saved.calls
        return
    api.publication.prepare_saved((root,manifest,buffers), output, **args)
    execution = json.loads((output/'execution.private.json').read_bytes())
    published = json.loads((output/'manifest.json').read_bytes())
    assert execution['answer_grading'] == {'mode': 'off'}
    assert published['automatic_grader_supported']
    assert not published['automatic_grading_attached']
