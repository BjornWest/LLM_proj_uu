"""Isolated real-browser acceptance with Pi transport mocked; zero model calls."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from threading import Thread

from .backend import ExternalAgentBackend, ROOT, save
from .protocol import digest, request_body
from .server import BridgeServer


def case(arguments):
    mode, output = arguments
    output = Path(output) / mode; output.mkdir()
    os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH', '')
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from intent_browser.actions import make_action_set
    from intent_browser.evaluation import Evaluation
    from intent_browser.harness import native_tools_profile
    from intent_browser.runner import run_episode
    from intent_browser.standard_profile import standard_profile
    from intent_browser.observation_pipeline import ObservationPipelineConfig
    page_html = '''<!doctype html><title>Bridge acceptance</title><main><h1>Save a name</h1>
      <label>Name<input aria-label="Name"></label><button onclick="window.saves++; document.querySelector('[role=status]').textContent='Saved '+document.querySelector('input').value">Save</button>
      <p role="status">Not saved</p></main><script>window.saves=0; window.privateVerifier='PRIVILEGED_SENTINEL'</script>'''
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers(); self.wfile.write(page_html.encode())
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'
    goal = 'Enter Ada in Name, save once, and report completion.'
    class Task:
        supports_observation_pipeline = 'native_full_only'
        def prepare(self, trace): return {'scripted': True, 'network_model_calls': 0}
        def capture_initial(self, env, observation, info): return {'url': observation['url']}
        def evaluate(self, env, trace, outcome):
            page = env.unwrapped.page
            state = {'value': page.get_by_role('textbox', name='Name').input_value(),
                     'saved': page.get_by_role('status').inner_text(), 'saves': page.evaluate('window.saves')}
            save(trace.directory / 'private-state.json', state)
            passed = state == {'value': 'Ada', 'saved': 'Saved Ada', 'saves': 1}
            return Evaluation('offline-form-state', '1', task_completed=passed,
                authorization_satisfied=state['saves'] <= 1, evidence=['private-state.json'])
    standard = mode in ('standard', 'http-standard')
    profile = standard_profile(navigation_origins=[url], helpers=False) if standard else native_tools_profile(reasoning_replay='preserve')
    Task.supported_harness_profiles = (profile.name,)
    config = ObservationPipelineConfig((), full_capture_only=True) if standard else None
    backend = ExternalAgentBackend('gpt-5.6-sol', output / 'transport', timeout=10,
        command=['node', str(Path(__file__).parent / 'tests/browser_fixture.mjs'), mode],
        # Independent OFFLINE simulations only; live CLI always uses the shared lock.
        lock_path=output / 'offline.lock')
    external = backend; bridge_server = None
    if mode == 'http-standard':
        from intent_browser.backend import ChatCompletionsBackend
        external.begin_episode('offline-http-episode')
        bridge_server = BridgeServer(external, 'offline-local-key')
        Thread(target=bridge_server.serve_forever, daemon=True).start()
        backend = ChatCompletionsBackend(f'http://127.0.0.1:{bridge_server.server_port}/v1',
            'gpt-5.6-sol', 'offline-local-key', timeout=20, max_tokens=16384, supports_images=True)
    def factory(video):
        return BrowserEnv(task_entrypoint=OpenEndedTask, task_kwargs={'start_url': url, 'goal': goal},
            headless=True, wait_for_user_message=False, action_mapping=make_action_set().to_python_code)
    try:
        trace, summary = run_episode(factory, backend, {'task': 'external-bridge-offline',
            'driver': 'scripted_validation', 'training_eligible': False, 'network_model_calls': 0},
            output=str(output / 'runs'), max_steps=6, episode_task=Task(), harness_profile=profile,
            observation_pipeline=config, max_input_tokens=100000 if standard else None)
    finally:
        backend.close()
        if bridge_server:
            bridge_server.shutdown(); bridge_server.server_close(); external.close()
        server.shutdown(); server.server_close()
    rows = [json.loads(line) for line in (trace / 'steps.jsonl').read_text().splitlines()]
    expected = 5 if standard else 1 if mode == 'forbidden' else 3
    assert len(rows) == expected, (mode, summary)
    for i, row in enumerate(rows, 1):
        folder = output / 'transport' / f'{i:04d}'
        req = json.loads((folder / 'harness-request.json').read_text())
        assert row['model_request'] == req
        assert 'PRIVILEGED_SENTINEL' not in json.dumps(req)
        sent = json.loads((folder / 'responses-request.json').read_text())
        assert sent['instructions'] == ''
        assert sent['tools'] == request_body(req)['tools']
        assert json.loads((folder / 'dispatch.json').read_text())['exact_payload_verified']
        assert json.loads((folder / 'bridge-result.json').read_text())['sends'] == 1
    if mode == 'forbidden':
        assert summary['error'] and summary['browser_step_count'] == 0, summary
        assert summary['evaluation']['task_completed'] is False
    else:
        assert summary['error'] is None and summary['action_error_count'] == 0, summary
        assert summary['evaluation']['task_completed'] is True, summary
    events = [json.loads(line)['event'] for line in (trace / 'events.jsonl').read_text().splitlines()]
    assert events.index('evaluation_completed') < events.index('environment_close_started')
    return {'mode': mode, 'passed': True, 'trace': str(trace), 'decisions': len(rows),
            'summary': summary, 'model_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    # Separate processes, browser contexts, ports, traces, and fake-provider locks.
    with ProcessPoolExecutor(max_workers=2) as pool:
        cases = list(pool.map(case, [(mode, output) for mode in ('basic', 'standard', 'forbidden', 'http-standard')]))
    files = list(Path(__file__).parent.rglob('*.py')) + list(Path(__file__).parent.rglob('*.mjs')) + list((ROOT / 'intent_browser').glob('*.py'))
    report = {'passed': True, 'model_calls': 0, 'cases': cases,
              'scope': 'Offline tool/context transport and real browser actions; not model capability or live subscription acceptance',
              'sources': {str(f.resolve()): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}
    save(output / 'report.json', report)
    print(json.dumps({'passed': True, 'report': str(output / 'report.json'), 'cases': len(cases)}))


if __name__ == '__main__': main()
