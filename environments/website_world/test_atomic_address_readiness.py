"""Initial setup drain only; native baselines and failure behavior stay intact."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from . import atomic_address_execution as execution


class Ready:
    def __init__(self, page): self.page = page
    def wait(self, *, timeout_ms, quiet_ms):
        assert quiet_ms == 100
        self.page.wait_for_load_state('chromium_network',timeout=timeout_ms)


class Page:
    def __init__(self, *, drain_error=None):
        self.url = 'https://initial.test/#/product/original'
        self.context = SimpleNamespace(pages=[self])
        self.calls = []
        self.drain_error = drain_error
        self.default_timeout = 60000

    def wait_for_load_state(self, state, *, timeout):
        self.calls.append(('drain', state, timeout))
        if self.drain_error is not None:
            raise self.drain_error

    def goto(self, url):
        self.calls.append(('goto', url))
        self.url = url

    def wait_for_selector(self, selector):
        self.calls.append(('selector', selector))

    def evaluate(self, source, key):
        assert source == '(key)=>localStorage.getItem(key)'
        self.calls.append(('storage_read', key))
        return 'native-rendered-state'


def capture():
    value = object.__new__(execution.AddressCapture)
    value.installed, value.initialized = True, False
    value.binding = {'retailers': {
        'retailer-' + str(i): {'origin': 'https://shop-' + str(i) + '.test',
                              'storage_key': 'native-key-' + str(i)}
        for i in range(9)}}
    value.setup_requests = []
    return value


def test_one_bounded_drain_precedes_all_nine_native_baselines_and_original_start():
    value, page = capture(), Page()
    start, pages = page.url, list(page.context.pages)
    value.initialize(page, readiness=Ready(page))
    assert page.calls[0] == ('drain', 'chromium_network', 5000)
    assert [c for c in page.calls if c[0] == 'goto'] == [
        ('goto', row['origin'] + '/#/home') for row in value.binding['retailers'].values()
    ] + [('goto', start)]
    assert len([c for c in page.calls if c[0] == 'drain']) == 1
    assert len([c for c in page.calls if c[0] == 'storage_read']) == 9
    assert page.default_timeout == 60000
    assert page.url == start and page.context.pages == pages and value.initialized
    assert len(value.setup_requests) == 9
    assert all(r['browser_storage_writes_by_capture'] is False for r in value.setup_requests)
    before = list(page.calls)
    with pytest.raises(ValueError, match='exactly one baseline'):
        value.initialize(page, readiness=Ready(page))
    assert page.calls == before


@pytest.mark.parametrize('error', [PlaywrightTimeoutError('initial setup did not settle'),
                                  RuntimeError('connection lost'), KeyboardInterrupt()])
def test_drain_failures_propagate_unchanged_without_visiting_or_accepting_baselines(error):
    value, page = capture(), Page(drain_error=error)
    with pytest.raises(type(error)) as caught:
        value.initialize(page, readiness=Ready(page))
    assert caught.value is error
    assert page.calls == [('drain', 'chromium_network', 5000)]
    assert not value.initialized and value.setup_requests == []


@pytest.mark.parametrize('installed,initialized', [(False, False), (True, True)])
def test_invalid_capture_lifecycle_does_not_start_a_wait(installed, initialized):
    value, page = capture(), Page()
    value.installed, value.initialized = installed, initialized
    with pytest.raises(ValueError, match='exactly one baseline'):
        value.initialize(page, readiness=Ready(page))
    assert page.calls == []


def test_missing_native_baseline_still_fails_after_drain(monkeypatch):
    value, page = capture(), Page()
    error = ValueError('native storage did not persist')
    def wait(*args, **kwargs):
        raise error
    monkeypatch.setattr(execution.setup, '_wait', wait)
    with pytest.raises(ValueError) as caught:
        value.initialize(page, readiness=Ready(page))
    assert caught.value is error
    assert not value.initialized and value.setup_requests == []
    assert len([c for c in page.calls if c[0] == 'goto']) == 1


def test_page_identity_guard_remains_active():
    value, page = capture(), Page()
    original = page.goto
    def goto(url):
        original(url)
        page.context.pages.append(object())
    page.goto = goto
    with pytest.raises(ValueError, match='retained tabs'):
        value.initialize(page, readiness=Ready(page))
    assert not value.initialized




def test_missing_early_observer_is_rejected():
    with pytest.raises(ValueError, match='must precede navigation'):
        capture().initialize(Page())


@pytest.mark.parametrize('failure', [None, 'wait', 'navigation', 'evidence'])
def test_setup_persists_actual_wait_failure_without_masking_original(monkeypatch, tmp_path, failure):
    error = PlaywrightTimeoutError('setup failed')
    class Observation:
        def __init__(self):
            self.record = {'scope':'initial_task_start_page_network_quietness','status':'not_waited'}
            self.closed = False
        def __enter__(self): return self
        def __exit__(self, *args): self.closed = True
        def wait(self, *, timeout_ms, quiet_ms):
            self.record.update(timeout_ms=timeout_ms,quiet_ms=quiet_ms,status='failed',elapsed_seconds=.1)
            if failure in ('wait','evidence'):raise error
            self.record['status'] = 'passed'
    observation = Observation()
    class Entry:
        def setup(self, page):
            if failure == 'navigation':raise error
            return ('native_goal', {'native_info': True})
    class Base:
        def __init__(self, public, *, origins, files, attachments, headless, profile_name):
            self.public, self.policy_navigation_origins, self.files = public, origins, files
            self.attachments, self.headless = attachments, headless
            self.supported_harness_profiles = [profile_name]
        def make_env(self, video=None):
            return SimpleNamespace(unwrapped=SimpleNamespace(task_entrypoint=Entry))
    value, page = capture(), Page()
    value.install = lambda context: None
    base = Base({},origins=[],files={},attachments=[],headless=True,profile_name='native')
    task = execution.prepared_task(base, value, None,
        SimpleNamespace(initial_page_readiness=lambda page: observation))
    task.trace = SimpleNamespace(directory=tmp_path)
    (tmp_path/'manual-review-private').mkdir()
    monkeypatch.setattr(execution.setup,'apply',lambda *a,**kw:{'native_setup':'unchanged'})
    if failure == 'evidence':
        def fail_write(*a,**kw):raise OSError('disk failed')
        monkeypatch.setattr(execution.capture_api,'save_new',fail_write)
    entry = task.make_env().unwrapped.task_entrypoint()
    if failure is None:
        assert entry.setup(page) == ('native_goal', {'native_info': True})
        assert value.initialized
    else:
        with pytest.raises(PlaywrightTimeoutError) as caught:entry.setup(page)
        assert caught.value is error and not value.initialized
    assert observation.closed
    if failure == 'evidence':
        assert 'OSError' in error.__notes__[0]
    else:
        path=tmp_path/'manual-review-private/initial-page-readiness.private.json'
        assert json.loads(path.read_text()) == observation.record
        assert observation.record['status'] == ('not_waited' if failure=='navigation' else 'failed' if failure else 'passed')
