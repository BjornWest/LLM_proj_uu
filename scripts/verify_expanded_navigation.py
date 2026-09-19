"""Native-profile slow navigation boundary: one dispatch, explicit deadline only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def case(output, timeout):
    from intent_browser.backend import Completion
    from intent_browser.expanded_tasks import runner_options
    from intent_browser.runner import run_episode
    from intent_browser.actions import make_action_set
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    requests, holder = [], {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            requests.append(self.path)
            if self.path == '/slow': time.sleep(6)
            body = b'<h1>Arrived</h1>' if self.path == '/slow' else b'<a href="/slow">Open slow page</a>'
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
            try: self.wfile.write(body)
            except BrokenPipeError: pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    class Backend:
        calls = 0
        supports_native_tools = True
        def configure_tools(self, options): self.options = options
        def complete(self, messages):
            self.calls += 1
            if self.calls == 1:
                name = 'click'; args = {'bid': holder['env'].page.get_by_role('link').get_attribute('bid')}
            else: name = 'send_msg_to_user'; args = {'text': 'Done'}
            raw = {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'call{self.calls}', 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(args)}}]}}]}
            return Completion('', raw, {'messages': messages, **self.options})
    def factory(video):
        holder['env'] = BrowserEnv(task_entrypoint=OpenEndedTask,
            task_kwargs={'start_url': f'http://127.0.0.1:{server.server_port}', 'goal': 'Open the slow page.'},
            headless=True, wait_for_user_message=False, action_mapping=make_action_set().to_python_code)
        return holder['env']
    row = {'profile': {'name': 'core-tools-v3', 'max_steps': 2, 'observation_text_limit': 48000},
           'policy_input': {'terminal_response_instruction': 'After the page opens, finish with Done.'}}
    try:
        trace, summary = run_episode(factory, Backend(), {'model_calls': 0, 'driver': 'scripted-deadline-test'},
            output=output / 'traces', before_observation=lambda: None, **runner_options(row, action_timeout_ms=timeout))
        steps = [json.loads(line) for line in (trace / 'steps.jsonl').read_text().splitlines()]
        metadata = json.loads((trace / 'metadata.json').read_text())
        checks = {'single_dispatch': requests.count('/slow') == 1,
                  'expected_action_error': bool(steps[0].get('action_error')) == (timeout == 5000),
                  'recorded_deadline': metadata['browser_action_execution']['action_timeout_ms'] == timeout,
                  'no_force_retry': metadata['browser_action_execution']['retry_with_force'] is False,
                  'finished_without_technical_error': summary['error'] is None}
        report = {'passed': all(checks.values()), 'checks': checks, 'timeout_ms': timeout, 'requests': requests,
                  'trace': str(trace), 'action_error': steps[0].get('action_error'), 'model_calls': 0}
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if not report['passed']: raise ValueError('Deadline acceptance failed')
    finally: server.shutdown(); server.server_close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--timeout', type=int, choices=[5000, 30000])
    args = p.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH', '')
    if args.timeout: return case(args.output, args.timeout)
    def run(timeout):
        with (args.output / f'{timeout}.log').open('x') as log:
            subprocess.run([sys.executable, __file__, '--output', str(args.output / str(timeout)), '--timeout', str(timeout)],
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
        return json.loads((args.output / str(timeout) / 'report.json').read_text())
    with ThreadPoolExecutor(max_workers=2) as pool: reports = list(pool.map(run, [5000, 30000]))
    (args.output / 'report.json').write_text(json.dumps({'cases': reports, 'passed': all(r['passed'] for r in reports), 'model_calls': 0}, indent=2))


if __name__ == '__main__': main()
