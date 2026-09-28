import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from playwright.sync_api import CDPSession
from intent_browser.cdp_json import send_json, extract_json


def session(payload, calls, error=None):
    obj = object.__new__(CDPSession)
    async def send(**kwargs):
        calls.append(kwargs)
        if error: raise error
        return payload
    obj._impl_obj = SimpleNamespace(send=send)
    obj._sync = asyncio.run
    return obj


@pytest.mark.parametrize('method', ['Accessibility.getFullAXTree', 'DOMSnapshot.captureSnapshot'])
def test_plain_json_reuses_result_without_copy_or_parameter_change(method):
    payload = {'nodes': [{'nodeId': '42', 'name': {'value': 'Ångström'}, 'childIds': ['43']}]}
    calls = []; cdp = session(payload, calls); params = {'depth': 2}
    with patch('intent_browser.cdp_json._reviewed_version', return_value=True):
        assert send_json(cdp, method, params) is payload
    assert calls == [{'method': method, 'params': params}]


def test_unknown_version_uses_public_conversion():
    payload = {'nodes': [{'nodeId': '1'}]}; calls = []; cdp = session(payload, calls)
    with patch('intent_browser.cdp_json._reviewed_version', return_value=False):
        result = send_json(cdp, 'Accessibility.getFullAXTree')
    assert result == payload and result is not payload
    assert len(calls) == 1


def test_other_methods_keep_public_conversion():
    payload = {'value': ['public']}; calls = []; cdp = session(payload, calls)
    result = send_json(cdp, 'Runtime.evaluate', {'expression': '42'})
    assert result == payload and result is not payload
    assert len(calls) == 1


def test_instrumented_public_send_is_not_bypassed():
    cdp = session({}, [])
    with patch.object(CDPSession, 'send', return_value={'observed': True}) as public:
        assert send_json(cdp, 'Accessibility.getFullAXTree') == {'observed': True}
        public.assert_called_once_with('Accessibility.getFullAXTree', None)


def test_error_does_not_trigger_second_dispatch():
    calls = []; error = RuntimeError('target navigated'); cdp = session({}, calls, error)
    with patch('intent_browser.cdp_json._reviewed_version', return_value=True):
        with pytest.raises(RuntimeError) as caught:
            send_json(cdp, 'Accessibility.getFullAXTree')
    assert caught.value is error and len(calls) == 1


def test_extractor_proxy_unwraps_real_target_and_delegates_cleanup():
    seen = []; cdp = SimpleNamespace(send=lambda *args: seen.append(args) or {'nodes': []},
                                    detach=lambda: seen.append('detached'))
    page = SimpleNamespace(url='http://local/')
    def new_session(target):
        assert target is page
        return cdp
    page.context = SimpleNamespace(new_cdp_session=new_session)
    def extractor(view):
        assert view.url == page.url
        child = view.context.new_cdp_session(view)
        try: return child.send('Accessibility.getFullAXTree', {'depth': 2})
        finally: child.detach()
    assert extract_json(extractor, page) == {'nodes': []}
    assert seen == [('Accessibility.getFullAXTree', {'depth': 2}), 'detached']


def test_capture_keeps_lifecycle_wrapper_and_its_errors():
    from intent_browser.cdp_json import capture_json
    calls = []
    class Owner:
        def capture(self):
            calls.append('custody_checked')
            raise RuntimeError('custody changed')
    with pytest.raises(RuntimeError, match='custody changed'):
        capture_json(Owner().capture)
    assert calls == ['custody_checked']
