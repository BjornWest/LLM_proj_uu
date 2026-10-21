"""Demo provider stalls retry once with identical payload and visible progress."""
import json
import httpx
import pytest
from apps.raven.episode import DemoBackend


@pytest.mark.parametrize('recover',[True,False])
def test_provider_timeout_retries_same_request_once(recover):
    requests=[]
    progress=[]
    def transport(request):
        requests.append(json.loads(request.content))
        if len(requests)==1 or not recover:
            raise httpx.ReadTimeout('provider stalled',request=request)
        return httpx.Response(200,json={'choices':[{'message':{'content':'done'}}]})
    backend=DemoBackend('https://fixture.invalid/v1','mock',on_retry=lambda:progress.append('retry'))
    assert backend.client.timeout.read==120
    backend._request_client=lambda:httpx.Client(transport=httpx.MockTransport(transport))
    backend.sampling={'temperature':0.6}
    try:
        if recover:
            assert backend.complete([{'role':'user','content':'question'}]).text=='done'
        else:
            with pytest.raises(httpx.ReadTimeout):
                backend.complete([{'role':'user','content':'question'}])
        assert len(requests)==2 and requests[0]==requests[1]
        assert progress==['retry']
    finally: backend.close()


def test_keepalive_whitespace_cannot_extend_request_deadline():
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            calls.append(1)
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.end_headers()
            try:
                for _ in range(20):
                    self.wfile.write(b' ');self.wfile.flush();time.sleep(0.03)
                self.wfile.write(b'{"choices":[{"message":{"content":"too late"}}]}')
            except (BrokenPipeError,ConnectionResetError): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    progress=[]
    backend=DemoBackend('http://127.0.0.1:'+str(server.server_port),'mock',
                        on_retry=lambda:progress.append('retry'),request_timeout=0.12)
    started=time.monotonic()
    try:
        with pytest.raises(httpx.TimeoutException): backend.complete([{'role':'user','content':'question'}])
        assert time.monotonic()-started < 0.5
        assert len(calls)==2 and progress==['retry']
    finally:
        backend.close();server.shutdown();server.server_close()


def test_price_excerpt_matches_localized_currency_and_spacing():
    from apps.raven.episode import evidence_excerpt
    captured='\n'.join(['RAM Minne','8 GB']+['Other product text']*200+['Pris','2 149 SEK','Inkl. 25% moms'])
    excerpt=evidence_excerpt(captured,'Raspberry Pi med 8 GB kostar **2 149 kr**.')
    assert '2 149 SEK' in excerpt and 'Pris' in excerpt and 'Inkl. 25% moms' in excerpt
    assert excerpt.index('2 149 SEK') < excerpt.index('8 GB')


def test_demo_launch_removes_marker_and_pins_invisible_display(monkeypatch):
    from apps.raven.browser_launch import demo_launch_options
    monkeypatch.setenv('DISPLAY', ':0')
    monkeypatch.setenv('RAVEN_BROWSER_DISPLAY', ':99')
    options = demo_launch_options(args=['--start-minimized'],
        ignore_default_args=['--hide-scrollbars'], env={'DISPLAY': ':0'})
    assert options['env']['DISPLAY'] == ':99'
    assert options['ignore_default_args'] == ['--hide-scrollbars', '--enable-automation']
    assert options['args'] == ['--start-minimized', '--disable-blink-features=AutomationControlled']


def test_background_handover_focus_failure_still_delivers_terminal_events():
    import queue
    from types import SimpleNamespace
    from unittest.mock import Mock
    from apps.raven.backend import Run, Service
    events = queue.Queue()
    events.put({'type': 'handover', 'tab_id': 'tab-1', 'message': 'Please verify the site.'})
    events.put({'type': 'done', 'stop_reason': 'error'})
    run = Run('test', {'mode': 'background_window'}, process=SimpleNamespace(
        is_alive=lambda: False, join=lambda **kwargs: None))
    service = SimpleNamespace(focus=Mock(side_effect=ValueError('Tab no longer exists')))
    Service.collect(service, run, events)
    assert run.done
    assert run.events[0]['type'] == 'handover'
    assert 'Please open the tab yourself' in run.events[0]['message']
    assert run.events[-1] == {'type': 'done', 'stop_reason': 'error'}


def test_raven_worker_skips_chrome_component_extension_workers():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from apps.raven.shared_browser import active_target, raven_worker
    component = SimpleNamespace(url='chrome-extension://component/thunk.js', evaluate=Mock())
    raven = SimpleNamespace(url='chrome-extension://raven/background.js', evaluate=Mock(return_value='human-target'))
    context = Mock(service_workers=[component, raven])
    assert raven_worker(context) is raven
    assert active_target(context) == 'human-target'
    component.evaluate.assert_not_called()
    context.wait_for_event.assert_not_called()


def test_raven_worker_waits_for_matching_extension_on_startup():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from apps.raven.shared_browser import raven_worker
    component = SimpleNamespace(url='chrome-extension://component/thunk.js')
    raven = SimpleNamespace(url='chrome-extension://raven/background.js')
    context = Mock(service_workers=[component])
    context.wait_for_event.return_value = raven
    assert raven_worker(context) is raven
    args, kwargs = context.wait_for_event.call_args
    assert args == ('serviceworker',)
    assert not kwargs['predicate'](component) and kwargs['predicate'](raven)


def test_openrouter_model_option_routes_any_model_and_keeps_qwen_pin():
    from apps.raven.episode import openrouter_request_options, OPENROUTER_MODEL
    qwen = openrouter_request_options(OPENROUTER_MODEL, {'reasoning_effort': 'low'})
    assert qwen['provider']['only']
    other = openrouter_request_options('google/gemini-3.8-flash', {'reasoning_effort': 'low'})
    assert other == {'reasoning': {'effort': 'low', 'summary': 'auto'}}


def test_health_reports_selected_openrouter_model_and_budget():
    from apps.raven.backend import Service
    svc = Service(0, model_backend='openrouter', openrouter_model='google/gemini-3.8-flash',
                  max_total_input_tokens=600000)
    assert svc.model == 'google/gemini-3.8-flash'
    assert svc.options['openrouter_model'] == 'google/gemini-3.8-flash'
    assert svc.options['max_total_input_tokens'] == 600000


def _registry_service(tmp_path, presets, default='a', fallback='b'):
    import json as _json
    from apps.raven.backend import Service
    path = tmp_path / 'models.json'
    path.write_text(_json.dumps({'default': default, 'fallback': fallback, 'presets': presets}))
    return Service(0, models_file=path), path


def test_model_presets_hot_reload_fallback_and_conversation_pinning(tmp_path, monkeypatch):
    import json as _json, os, time as _time
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    presets = [dict(id='a', label='Self', backend='selfhosted', model='Q', base_url='http://127.0.0.1:9/v1'),
               dict(id='b', label='Flash', backend='openrouter', model='google/flash')]
    svc, path = _registry_service(tmp_path, presets)
    assert svc.models.default()['id'] == 'a' and svc.model == 'Q'
    preset, notice = svc.choose_model({'conversation_id': 'c1', 'model': 'a'})
    assert preset['id'] == 'b' and notice == 'Self-hosted model unavailable — using Flash'
    # The conversation keeps its model even if the client later asks for another.
    presets.append(dict(id='c', label='Other', backend='openrouter', model='x/other'))
    path.write_text(_json.dumps({'default': 'c', 'fallback': 'b', 'presets': presets}))
    os.utime(path, (_time.time() + 5, _time.time() + 5))
    assert svc.models.default()['id'] == 'c'
    assert svc.choose_model({'conversation_id': 'c1', 'model': 'c'})[0]['id'] == 'b'
    assert svc.choose_model({'conversation_id': 'c2', 'model': 'c'}) == (svc.models.get('c'), None)
    # A broken edit keeps the previous presets.
    path.write_text('{broken')
    os.utime(path, (_time.time() + 9, _time.time() + 9))
    assert svc.models.get('c') is not None


def test_cli_selfhosted_preset_and_episode_options(tmp_path):
    from apps.raven.backend import Service, episode_options
    svc = Service(0, model_backend='selfhosted', base_url='http://127.0.0.1:18000/v1', model='Qwen/Qwen3.8-27B-FP8',
                  models_file=tmp_path / 'missing.json')
    options = episode_options(svc.models.default())
    assert options['model_backend'] == 'selfhosted' and options['base_url'] == 'http://127.0.0.1:18000/v1'
    assert options['model'] == 'Qwen/Qwen3.8-27B-FP8'


def test_raven_memory_store_matches_harness_contract(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from intent_browser.memory import MemorySession
    from apps.raven.memory_store import MemoryStore, SEED
    monkeypatch.setenv('RAVEN_MEMORY_FILE', str(tmp_path / 'memory.json'))
    store = MemoryStore()
    session = MemorySession(store, SimpleNamespace(directory=tmp_path, episode_id='e'))
    assert session.initial['values'] == SEED
    result, _ = session.execute('memory_update', {'key': 'shoe_size_eu', 'value': 43,
                                                  'expected_revision': session.initial['revision']}, 1)
    assert result['applied'] and result['snapshot']['values']['shoe_size_eu'] == 43
    stale, _ = session.execute('memory_update', {'key': 'name', 'value': 'B', 'expected_revision': '1'}, 2)
    assert stale['applied'] is False
    store.update('newsletter_opt_in', 'ask')  # UI edit between episodes (no revision).
    assert MemoryStore().snapshot()['values']['newsletter_opt_in'] == 'ask'
    import pytest as _pytest
    with _pytest.raises(Exception):
        store.update('newsletter_opt_in', 'maybe')


def test_concurrent_memory_edit_is_a_recoverable_rejection(tmp_path):
    from types import SimpleNamespace
    from intent_browser.memory import MemorySession
    from apps.raven.memory_store import MemoryStore
    store = MemoryStore(tmp_path / 'memory.json')
    session = MemorySession(store, SimpleNamespace(directory=tmp_path, episode_id='e'))
    original = store.update
    def interleaved(key, value, expected_revision=None):
        MemoryStore(tmp_path / 'memory.json').update('name', 'UI edit')  # Another writer wins the race.
        return original(key, value, expected_revision)
    store.update = interleaved
    result, _ = session.execute('memory_update', {'key': 'shoe_size_eu', 'value': 43,
                                                  'expected_revision': session.initial['revision']}, 1)
    assert result['applied'] is False and 'Stale' in result['error'] and not session.uncertain
