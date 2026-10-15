"""Chromium identity accounting and explicit setup lifecycle controls."""
from types import SimpleNamespace

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from . import local_origins as origins


class Session:
    def __init__(self):
        self.listeners = {}
        self.detached = False
    def on(self, name, callback):
        self.listeners[name] = callback
    def send(self, method):
        if method == 'Page.getFrameTree':
            return {'frameTree': {'frame': {'id': 'main'}}}
        assert method == 'Network.enable'
        return {}
    def detach(self):
        self.detached = True
    def emit(self, name, data):
        self.listeners['Network.' + name](data)


class Page:
    def __init__(self):
        self.url = 'about:blank'
        self.clock = 0.
        self.session = Session()
        self.scheduled = []
        self.context = SimpleNamespace(new_cdp_session=lambda page: self.session)
    def wait_for_timeout(self, milliseconds):
        self.clock += milliseconds / 1000
        due = [x for x in self.scheduled if x[0] <= self.clock]
        self.scheduled = [x for x in self.scheduled if x[0] > self.clock]
        for _, callback in due:
            callback()


def begin(monkeypatch):
    page = Page()
    monkeypatch.setattr(origins, 'monotonic', lambda: page.clock)
    tracker = origins.InitialPageNetwork(page)
    tracker.__enter__()
    page.session.emit('requestWillBeSent', {'requestId': 'document', 'type': 'Document',
        'frameId': 'main', 'request': {'method': 'GET'}})
    page.session.emit('loadingFinished', {'requestId': 'document'})
    return page, tracker


def test_held_request_past_500ms_prevents_pass_until_terminal_then_real_quiet(monkeypatch):
    page, tracker = begin(monkeypatch)
    page.session.emit('requestWillBeSent', {'requestId': 'held', 'request': {'method': 'GET'}})
    page.scheduled.append((.8, lambda: page.session.emit('loadingFinished', {'requestId': 'held'})))
    result = tracker.wait(timeout_ms=1500, quiet_ms=100)
    assert result['status'] == 'passed' and result['elapsed_seconds'] >= .9
    assert result['pending_requests'] == 0 and result['finished_requests'] == 2
    tracker.close()
    assert page.session.detached


def test_held_request_times_out_without_noop_success(monkeypatch):
    page, tracker = begin(monkeypatch)
    page.session.emit('requestWillBeSent', {'requestId': 'held', 'request': {'method': 'GET'}})
    with pytest.raises(PlaywrightTimeoutError):
        tracker.wait(timeout_ms=850, quiet_ms=100)
    assert tracker.record['status'] == 'failed'
    assert tracker.record['pending_requests'] == 1
    assert tracker.record['elapsed_seconds'] >= .85
    tracker.close()


def test_redirect_same_identity_remains_pending_and_failure_keeps_mutation_effects_unknown(monkeypatch):
    page, tracker = begin(monkeypatch)
    page.session.emit('requestWillBeSent', {'requestId': 'redirect', 'request': {'method': 'GET'}})
    page.session.emit('requestWillBeSent', {'requestId': 'redirect', 'request': {'method': 'GET'}, 'redirectResponse': {}})
    assert len(tracker.pending) == 1
    page.session.emit('loadingFinished', {'requestId': 'redirect'})
    page.session.emit('requestWillBeSent', {'requestId': 'mutation', 'request': {'method': 'POST'}})
    page.session.emit('loadingFailed', {'requestId': 'mutation', 'canceled': True})
    result = tracker.wait(timeout_ms=1000, quiet_ms=100)
    assert result['status'] == 'passed' and result['redirect_hops'] == 1
    assert result['failed_requests'] == result['failed_mutations'] == 1
    assert result['failed_mutation_backend_effects'] == 'unknown'
    assert result['semantic_completeness'] == 'unclaimed'
    tracker.close()


def test_requires_observation_before_navigation():
    page = Page()
    page.url = 'https://already-loaded.test/'
    with pytest.raises(ValueError, match='before initial navigation'):
        with origins.InitialPageNetwork(page):
            pass


def test_no_document_observed_is_not_quiet_success(monkeypatch):
    page = Page()
    monkeypatch.setattr(origins, 'monotonic', lambda: page.clock)
    with origins.InitialPageNetwork(page) as tracker:
        with pytest.raises(PlaywrightTimeoutError):
            tracker.wait(timeout_ms=250, quiet_ms=50)
        assert tracker.record['document_seen'] is False


@pytest.mark.parametrize('timeout,quiet', [(0, 100), (True, 100), (5000, 0), (5000, 5000), (5000, True)])
def test_bad_bounds_are_rejected(monkeypatch, timeout, quiet):
    page, tracker = begin(monkeypatch)
    with pytest.raises(ValueError):
        tracker.wait(timeout_ms=timeout, quiet_ms=quiet)
    tracker.close()


def test_wait_is_once_only_and_close_is_idempotent(monkeypatch):
    page, tracker = begin(monkeypatch)
    tracker.wait(timeout_ms=1000, quiet_ms=100)
    with pytest.raises(ValueError, match='once-only'):
        tracker.wait()
    tracker.close()
    tracker.close()


def test_invalid_event_identity_fails_closed_without_poisoning_callback(monkeypatch):
    page, tracker = begin(monkeypatch)
    page.session.emit('requestWillBeSent', {'requestId': None})
    with pytest.raises(ValueError, match='observation failed'):
        tracker.wait()
    tracker.close()
