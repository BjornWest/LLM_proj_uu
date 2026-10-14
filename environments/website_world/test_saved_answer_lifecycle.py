"""Focused controls for immutable native tasks and saved input confinement."""
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from .saved_answer_lifecycle import PresentedGrader, native_input_snapshot
from .saved_answer_publication import read_recipe
from .statistics_saved_answer import comparison_start


def test_presented_prose_preserves_native_grade_task():
    native_task = {'task_id': 'count-1', 'memories': [], 'user_message': 'Native wording',
                   'operation': 'count', 'grain': 'model'}
    native = SimpleNamespace(task=native_task, grade=lambda claims, answer: native_task['user_message'])
    grader = PresentedGrader(native, {**native_task, 'user_message': 'Natural question'})
    assert grader.task['user_message'] == 'Natural question'
    assert grader.grade({}, 'answer') == 'Native wording'
    assert native.task == native_task
    grader.task['memories'].append('different')
    assert native_task['memories'] == []


@pytest.mark.parametrize('field,value', [('task_id', 'other'), ('memories', ['other'])])
def test_presented_prose_cannot_change_identity_or_memories(field, value):
    task = {'task_id': 'count-1', 'memories': [], 'user_message': 'Native'}
    with pytest.raises(ValueError):
        PresentedGrader(SimpleNamespace(task=task), {**task, field: value})


def test_direct_comparison_start_resolves_actual_site():
    runtime = SimpleNamespace(site_registry=[{'site_id': 'comparison-00', 'kind': 'aggregator',
                                             'name': 'Prislyktan', 'origin': 'https://prislyktan.test'}])
    task = {'comparison_site_id': 'comparison-00', 'comparison_site_name': 'Prislyktan'}
    assert comparison_start(runtime, task) == 'https://prislyktan.test/search'
    with pytest.raises(ValueError):
        comparison_start(runtime, {**task, 'comparison_site_name': 'Another site'})


def test_saved_recipe_rejects_escaping_file(tmp_path):
    saved = tmp_path/'saved'
    saved.mkdir()
    outside = tmp_path/'outside.json'
    outside.write_text('{}')
    manifest = {'files': {'../outside.json': sha256(outside.read_bytes()).hexdigest()}}
    payload = json.dumps(manifest).encode()
    (saved/'manifest.json').write_bytes(payload)
    with pytest.raises(ValueError):
        read_recipe(saved, expected_manifest_sha256=sha256(payload).hexdigest())


def test_saved_publication_consumes_authenticated_snapshot(tmp_path, monkeypatch):
    from . import saved_answer_publication as publication
    saved, output, root = tmp_path/'saved', tmp_path/'output', tmp_path/'root'
    saved.mkdir()
    root.mkdir()
    task = {'task_id': 'count-1', 'memories': [], 'kind': 'catalog_statistics', 'source_sha256': {}}
    records = {'task.json': json.dumps(task).encode(), 'execution.private.json': b'{}',
               'pin/world.private.json': b'{"world_id":"original"}', 'episode.json': b'{"original":true}'}
    for name, payload in records.items():
        target = saved/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    manifest_payload = json.dumps({'files': {n: sha256(b).hexdigest() for n,b in records.items()}}).encode()
    (saved/'manifest.json').write_bytes(manifest_payload)
    expected = sha256(manifest_payload).hexdigest()
    snapshot = read_recipe(saved, expected_manifest_sha256=expected)
    # Replace consumed files after authentication; restore before the final drift check.
    for name in records:
        (saved/name).write_bytes(b'{"replacement":true}')
    def freeze(world, destination):
        assert world == {'world_id': 'original'}
        destination.mkdir(parents=True)
        for name, payload in records.items():
            (saved/name).write_bytes(payload)
        return {'files': {}, 'source_sha256': {}}
    monkeypatch.setattr(publication, 'ROOT', root)
    monkeypatch.setattr(publication, '_bind', lambda *args, **kwargs: lambda: {})
    monkeypatch.setattr(publication, 'Execution', lambda **kwargs: SimpleNamespace(freeze=freeze))
    (root/'scripts').mkdir()
    (root/'scripts/trace_grades.py').write_bytes(b'# test-only grade reader')
    # Preparation pins this data dependency as well as traced Python imports.
    # Keep the synthetic root complete rather than reading mutable project data.
    (root/'intent_browser').mkdir()
    (root/'intent_browser/model_tokenizers.json').write_bytes(b'{}')
    for relative in ('intent_browser/assets/chat/chat.html',
                     'intent_browser/assets/chat/LICENSE.browsergym.txt',
                     'intent_browser/observation_revision.js'):
        path = root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'test-only data dependency')
    for version in ('catalogue_v1', 'catalogue_v2'):
        path = root/'environments/product_world/data/product_feature_policies'/version/'manifest.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'concepts': {}}))
    setup = {'schema': publication.VERSION, 'task_id': 'count-1', 'memories': [], 'user_message': 'Count?'}
    publication.prepare_saved(snapshot, output, expected_manifest_sha256=expected,
        setup=setup, task_filename='task.json', adapter_file=__file__)
    for name in ('task.json', 'episode.json', 'pin/world.private.json'):
        assert (output/name).read_bytes() == records[name]


def test_setup_checks_consumed_buffer_not_a_later_read(tmp_path, monkeypatch):
    from . import statistics_saved_answer as adapter
    good = json.dumps({'schema': 'website-saved-answer-publication-v1', 'task_id': 'count-1',
                      'user_message': 'Original', 'memories': [],
                      'start': {'kind': 'comparison_catalog', 'comparison_site_id': 'comparison-00'}}).encode()
    bad = good.replace(b'Original', b'Replacement')
    setup_path = tmp_path/'saved-answer-setup.private.json'
    setup_path.write_bytes(good)
    closed = []
    def parent(self, output, **kwargs):
        self.manifest = {'saved_answer_recipe': 'website-saved-answer-publication-v1',
                         'files': {'saved-answer-setup.private.json': sha256(good).hexdigest()}}
        self.answer_grader = SimpleNamespace(task={'task_id': 'count-1', 'memories': [],
            'comparison_site_id': 'comparison-00'})
        self.runtime = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(adapter.CatalogStatisticsEpisode, '__init__', parent)
    original_read = type(setup_path).read_bytes
    reads = []
    def changing_read(path):
        if path == setup_path:
            reads.append(True)
            return bad if len(reads) == 1 else good
        return original_read(path)
    monkeypatch.setattr(type(setup_path), 'read_bytes', changing_read)
    with pytest.raises(ValueError, match='Saved setup differs'):
        adapter.SavedStatisticsEpisode(tmp_path)
    assert reads == [True] and closed == [True]


def test_pre_dispatch_native_drift_cannot_replace_frozen_pin(tmp_path):
    task = tmp_path/'task.json'
    original = b'{"task_id":"original"}'
    task.write_bytes(original)
    bound = {str(task): sha256(original).hexdigest()}
    native, references = native_input_snapshot({'task': task}, bound)
    assert native['task_id'] == 'original' and references == bound
    task.write_bytes(b'{"task_id":"replacement"}')
    with pytest.raises(ValueError, match='Native input differs'):
        native_input_snapshot({'task': task}, bound)
    assert bound[str(task)] == sha256(original).hexdigest()


@pytest.fixture
def statistics_constructor(tmp_path, monkeypatch):
    """Exercise real episode constructors with offline Runtime/profile boundaries."""
    from . import catalog_statistics_execution as parent, runtime as runtime_module
    from . import comparison_sku_task
    from intent_browser import standard_profile as profiles, connected_world_task, harness
    native = {'task_id': 'count-1', 'memories': [], 'user_message': 'Native',
              'comparison_site_id': 'comparison-00', 'comparison_site_name': 'Prislyktan'}
    setup = {'schema': 'website-saved-answer-publication-v1', 'task_id': 'count-1',
             'user_message': 'How many models?', 'memories': [],
             'start': {'kind': 'comparison_catalog', 'comparison_site_id': 'comparison-00'}}
    records = {
        'episode.json': {'task_id': 'count-1', 'manual_task': {'user_message': 'Native', 'memories': []},
                         'start': {'kind': 'tool_discovery'}},
        'catalog-statistics-task.private.json': native,
        'catalog-statistics-binding.private.json': {'status': 'bound', 'comparison_site_id': 'comparison-00',
                                                   'world_repaired': False},
        'catalog-statistics-reference.private.json': {}, 'presentation.json': {},
        'surrounding.private.json': {}, 'basket-plan.private.json': {}, 'checkout-domain.private.json': {},
        'compositions.private.json': {}, 'saved-answer-setup.private.json': setup,
    }
    for name, record in records.items():
        (tmp_path/name).write_text(json.dumps(record))
    manifest = {'recipe': 'website-catalog-statistics-publication-v1',
                'saved_answer_recipe': 'website-saved-answer-publication-v1', 'source_sha256': {},
                'files': {name: sha256((tmp_path/name).read_bytes()).hexdigest() for name in records}}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    calls = {'runtime': [], 'close': [], 'profile': [], 'discovery': []}
    class OfflineRuntime:
        def __init__(self, output, **options):
            calls['runtime'].append(options)
            self.compositions = {}; self.world = {'world_id': 'offline-statistics-world', 'quote_as_of': '2026-09-30'}
            self.navigation_origins = ['https://prislyktan.test']; self.index_origin = 'https://index.test'
            self.research_origin = 'https://discover.test'; self.discovery_mode = options['discovery_mode']
            self.site_registry = [{'site_id': 'comparison-00', 'kind': 'aggregator',
                                  'name': 'Prislyktan', 'origin': 'https://prislyktan.test'}]
            self.site_discovery = SimpleNamespace(search=lambda query: [])
        def close(self):
            calls['close'].append(True)
    monkeypatch.setattr(runtime_module, 'Runtime', OfflineRuntime)
    monkeypatch.setattr(parent.shared, 'load', lambda output: manifest)
    monkeypatch.setattr(parent, 'CatalogStatisticsGrader', lambda world, task, reference, registry, **kwargs:
                        SimpleNamespace(task=task))
    def profile(**kwargs):
        calls['profile'].append(kwargs)
        return SimpleNamespace(**kwargs)
    monkeypatch.setattr(profiles, 'standard_profile', profile)
    monkeypatch.setattr(connected_world_task, 'public_projection', lambda value: value)
    monkeypatch.setattr(comparison_sku_task, 'episode_task', lambda runtime, public, profile, **kwargs:
                        SimpleNamespace(files=kwargs['files'], attachments=kwargs['attachments']))
    monkeypatch.delattr(harness, 'with_site_discovery', raising=False)
    return SimpleNamespace(output=tmp_path, native=native, setup=setup, manifest=manifest,
                           calls=calls, harness=harness, parent=parent, monkeypatch=monkeypatch)


def test_saved_statistics_constructor_never_loads_unused_discovery(statistics_constructor):
    from .statistics_saved_answer import SavedStatisticsEpisode
    f = statistics_constructor
    original = (f.output/'episode.json').read_bytes()
    episode = SavedStatisticsEpisode(f.output)
    assert episode.public['start_url'] == 'https://prislyktan.test/search'
    assert episode.public['user_message'] == 'How many models?'
    assert episode.answer_grader.task == f.native
    assert episode.site_discovery is None and episode.task.site_discovery_callback is None
    assert f.calls['runtime'][0]['discovery_mode'] == 'index'
    assert f.calls['profile'][-1]['data_tools'] is False
    assert (f.output/'episode.json').read_bytes() == original
    assert not f.calls['close']


def test_ordinary_statistics_discovery_constructor_is_preserved(statistics_constructor):
    f = statistics_constructor
    def with_discovery(profile):
        f.calls['discovery'].append(profile)
        return profile
    f.monkeypatch.setattr(f.harness, 'with_site_discovery', with_discovery, raising=False)
    episode = f.parent.CatalogStatisticsEpisode(f.output)
    assert f.calls['runtime'][0]['discovery_mode'] == 'tool'
    assert episode.public['start_url'] == 'https://discover.test/'
    assert len(f.calls['discovery']) == 1
    assert episode.site_discovery == episode.runtime.site_discovery.search


@pytest.mark.parametrize('change', ['task_id', 'comparison_site_id', 'digest'])
def test_saved_statistics_start_rejects_invalid_setup_before_profiles(statistics_constructor, change):
    from .statistics_saved_answer import SavedStatisticsEpisode
    f = statistics_constructor
    if change == 'task_id':
        f.setup['task_id'] = 'other'
    elif change == 'comparison_site_id':
        f.setup['start']['comparison_site_id'] = 'other'
    else:
        f.setup['user_message'] = 'Changed after pin'
    data = json.dumps(f.setup).encode()
    (f.output/'saved-answer-setup.private.json').write_bytes(data)
    if change != 'digest':
        f.manifest['files']['saved-answer-setup.private.json'] = sha256(data).hexdigest()
    with pytest.raises(ValueError, match='Saved (statistics public setup changed|setup differs)'):
        SavedStatisticsEpisode(f.output)
    assert not f.calls['profile'] and f.calls['close'] == [True]


def test_statistics_start_factory_failure_closes_runtime(statistics_constructor):
    f = statistics_constructor
    def invalid(runtime, native):
        raise ValueError('Invalid public route')
    with pytest.raises(ValueError, match='Invalid public route'):
        f.parent.CatalogStatisticsEpisode(f.output, start_url_factory=invalid)
    assert not f.calls['profile'] and f.calls['close'] == [True]
