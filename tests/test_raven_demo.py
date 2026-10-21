"""Bounded episode recovery, error disclosure and stream replay; no model calls."""
import json
import queue
import threading
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.request import Request, urlopen

import pytest

from apps.raven.backend import FRIENDLY_ERROR, Handler, Run, Service, ThreadingHTTPServer


def attempt_events(*events):
    result = queue.Queue()
    for event in events:
        result.put(event)
    return result


def fake_process():
    return SimpleNamespace(is_alive=lambda: False, join=lambda **kw: None, exitcode=7)


def service(demo=True):
    result = Service.__new__(Service)
    result.demo_mode = demo
    result.stop_process = Mock()
    return result


@pytest.mark.parametrize('failure', ['Provider failed: secret', 'CaptureError: stack', 'Worker.evaluate: gone', None])
@pytest.mark.parametrize('recover', [True, False])
def test_episode_retries_once_and_keeps_diagnostics(tmp_path, failure, recover, caplog):
    svc = service()
    run = Run('test', {'mode': 'user_window', 'text': 'same request'}, process=fake_process(), trace=str(tmp_path))
    run.tabs = [{'tab_id': 'tab-1', 'active': True}]
    run.targets = {'tab-1': 'same-browser-target'}
    def restart(actual, scripted):
        assert actual is run and actual.attempt == 1
        assert actual.payload == {'mode': 'user_window', 'text': 'same request', '_background_target': 'same-browser-target'}
        actual.process = fake_process()
        actual._events = attempt_events(*([
            {'type': 'final', 'markdown': 'Recovered answer', 'sources': []},
            {'type': 'done', 'stop_reason': 'agent_finished'}] if recover else [
            {'type': 'error', 'message': 'Second raw error'}, {'type': 'done', 'stop_reason': 'error'}]))
    svc.start_attempt = Mock(side_effect=restart)
    original = attempt_events(*([{'type': 'error', 'message': failure}, {'type': 'done', 'stop_reason': 'error'}] if failure else []))
    svc.collect(run, original)
    assert run.done and run.attempt == 1
    svc.start_attempt.assert_called_once()
    assert sum(e['type'] == 'step' and e['summary'] == 'Taking another look…' for e in run.events) == 1
    if recover:
        assert [e['type'] for e in run.events] == ['step', 'final', 'done']
    else:
        assert [e['type'] for e in run.events] == ['step', 'error', 'done']
        assert run.events[-2]['message'] == FRIENDLY_ERROR
    assert 'Second raw error' not in json.dumps(run.events)
    if failure:
        assert failure in (tmp_path / 'service-events.jsonl').read_text()
        assert failure in caplog.text
        assert failure not in json.dumps(run.events)


def test_off_keeps_raw_errors_and_does_not_retry():
    svc = service(False)
    svc.start_attempt = Mock()
    run = Run('test', {'mode': 'background'}, process=fake_process())
    svc.collect(run, attempt_events({'type': 'error', 'message': 'Worker.evaluate raw'}, {'type': 'done', 'stop_reason': 'error'}))
    assert run.events[0]['message'] == 'Worker.evaluate raw'
    svc.start_attempt.assert_not_called()


def test_sse_drop_uses_same_retry_allowance():
    svc = service()
    svc.start_attempt = Mock()
    run = Run('test', {'mode': 'background'}, process=fake_process(), attempt=1)
    svc.retry(run)
    svc.collect(run, attempt_events())
    assert run.events == [{'type': 'error', 'message': FRIENDLY_ERROR}, {'type': 'done', 'stop_reason': 'error'}]
    svc.start_attempt.assert_not_called()


def test_cancellation_during_recovery_cannot_restart():
    svc = service()
    svc.start_attempt = Mock()
    run = Run('test', {'mode': 'background'}, process=fake_process(), cancelled=True)
    svc.collect(run, attempt_events({'type': 'error', 'message': 'provider down'}, {'type': 'done', 'stop_reason': 'error'}))
    svc.start_attempt.assert_not_called()


def test_final_answer_is_not_repeated_on_late_cleanup_error():
    svc = service()
    svc.start_attempt = Mock()
    run = Run('test', {'mode': 'background'}, process=fake_process())
    svc.collect(run, attempt_events({'type': 'final', 'markdown': 'Answer'}, {'type': 'error', 'message': 'cleanup failed'}, {'type': 'done', 'stop_reason': 'error'}))
    assert sum(e['type'] == 'final' for e in run.events) == 1
    svc.start_attempt.assert_not_called()


def test_api_error_masking_and_indexed_replay():
    from apps.raven.smoke import MockService
    svc = MockService()
    run = svc.submit({'mode': 'background', 'text': 'offline'})
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.service = svc
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(Request(base + f'/api/tasks/{run.run_id}/events', headers={'Last-Event-ID': '1'})) as response:
            data = response.read().decode()
        assert 'id: 2\n' in data and 'id: 3\n' in data
        assert 'Checking the sample page' not in data
        from urllib.error import HTTPError
        with pytest.raises(HTTPError) as caught:
            urlopen(Request(base + '/api/tasks', data=b'{}', headers={'Content-Type': 'application/json'}))
        assert json.load(caught.value)['error'] == FRIENDLY_ERROR
    finally:
        server.shutdown()
        server.server_close()


def test_same_stream_failure_reported_twice_cannot_consume_second_attempt():
    svc = service()
    run = Run('test', {'mode': 'background'}, attempt=1, retry_cursor=5)
    svc.retry(run, after_event_id=4)
    assert not run.retry_requested.is_set()
    svc.retry(run, after_event_id=5)
    assert run.retry_requested.is_set()


def test_browser_transport_recovers_stream_and_hides_details():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    script = r'''
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
(async()=>{
  const requests=[];let source;
  global.window={};
  global.fetch=async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({demo_mode:true})};};
  global.EventSource=class {constructor(){source=this;}close(){this.closed=true;}};
  vm.runInThisContext(fs.readFileSync('design/raven/outputs/raven/raven-transport.js','utf8'));
  const transport=window.ravenTransport;await transport.ready;
  const events=[],errors=[];
  const stream=transport.events('episode',{onEvent:e=>events.push(e),onError:e=>errors.push(e)});
  source.onmessage({data:JSON.stringify({type:'step',summary:'Reading a page'}),lastEventId:'4'});
  source.onerror();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(errors.length,0);
  assert.equal(JSON.parse(requests.at(-1).options.body).after_event_id,4);
  source.onopen();
  source.onmessage({data:JSON.stringify({type:'step',summary:'Taking another look…'}),lastEventId:'5'});
  assert.equal(events.at(-1).summary,'Taking another look…');
  stream.close();assert(source.closed);
  assert.equal(transport.errorMessage(new Error('Worker.evaluate raw stack')),"Sorry — I couldn't finish that. Could you try again or rephrase?");
  transport.demoMode=false;
  assert.equal(transport.errorMessage(new Error('Worker.evaluate raw stack')),'Worker.evaluate raw stack');
  transport.events('debug',{onEvent:()=>{},onError:e=>errors.push(e)});
  source.onerror();assert(errors.at(-1).message.includes('Connection to Korp was interrupted'));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    subprocess.run(['node', '-e', script], cwd=root, check=True)


@pytest.mark.parametrize('reason', ['max_input_tokens', 'max_total_input_tokens', 'max_total_output_tokens'])
def test_budget_exhaustion_does_not_start_another_episode(reason):
    svc = service()
    svc.start_attempt = Mock()
    run = Run('test', {'mode': 'background'}, process=fake_process())
    svc.collect(run, attempt_events(
        {'type': 'error', 'message': 'The episode ended before the agent supplied an answer.'},
        {'type': 'done', 'stop_reason': reason}))
    assert run.done and run.attempt == 0
    assert not any(e['type'] == 'error' for e in run.events)
    assert run.events[-1] == {'type': 'done', 'stop_reason': reason}
    svc.start_attempt.assert_not_called()


def test_broken_old_stream_cannot_charge_unsent_retry_marker():
    # A browser already requested recovery, but the old stream has not discovered
    # its broken socket. Its pending batch now includes an unsent retry marker.
    run = Run('drop', {'mode': 'background'}, attempt=1, retry_cursor=2)
    run.events = [{'type': 'status', 'state': 'starting'},
                  {'type': 'step', 'summary': 'Taking another look…'}]
    svc = SimpleNamespace(demo_mode=True, runs={'drop': run}, retry=Mock(), cancel=Mock())
    handler = Handler.__new__(Handler)
    handler.server = SimpleNamespace(service=svc)
    handler.path = '/api/tasks/drop/events'
    handler.headers = {'Last-Event-ID': '1'}
    handler.allowed_client = lambda: True
    handler.send_response = handler.send_header = handler.end_headers = Mock()
    handler.wfile = SimpleNamespace(write=Mock(side_effect=BrokenPipeError('old stream')), flush=Mock())
    handler.do_GET()
    assert run.subscribers == 0
    assert not run.retry_requested.is_set()
    svc.retry.assert_not_called()
    svc.cancel.assert_not_called()


def test_stream_recovery_after_early_answer_keeps_owning_live_episode():
    svc = service()
    svc.start_attempt = Mock()
    alive = {'value': True}
    process = SimpleNamespace(is_alive=lambda: alive['value'], join=lambda **kw: None, exitcode=None)
    run = Run('test', {'mode': 'user_window'}, process=process)
    events = queue.Queue()
    events.put({'type': 'final', 'markdown': 'Answer', 'sources': []})
    worker = threading.Thread(target=svc.collect, args=(run, events))
    worker.start()
    deadline = __import__('time').time() + 5
    while not any(e['type'] == 'final' for e in run.events) and __import__('time').time() < deadline:
        __import__('time').sleep(0.02)
    svc.retry(run, after_event_id=1)  # Panel stream dropped after the early answer.
    __import__('time').sleep(0.6)
    assert not run.done and not any(e['type'] == 'error' for e in run.events)
    events.put({'type': 'done', 'stop_reason': 'agent_finished'})
    worker.join(5)
    assert [e['type'] for e in run.events] == ['final', 'done']
    svc.stop_process.assert_not_called()
