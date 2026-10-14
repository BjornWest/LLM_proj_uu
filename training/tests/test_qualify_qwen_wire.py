"""Fake transport checks; no GPU or actual serving qualification."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'training/scripts/qualify_qwen_wire.py'
RUNTIME = Path(os.environ.get('QWEN_TEST_RUNTIME_SOURCE', ROOT / 'scripts/qwen_suite_runtime.py'))
spec = importlib.util.spec_from_file_location('wire_probe', SCRIPT)
Q = importlib.util.module_from_spec(spec); spec.loader.exec_module(Q)


def project(body):
    return {key: body[key] for key in ('model', 'messages', 'tools') if key in body}


def reference(body):
    if body['messages'][0]['content'] == 'boundary': return [7] * Q.BOUNDARY
    return list(Q.wire(body))


def selected():
    values = []
    for label in ('image-64x64', 'image-1280x720', 'image-2048x1024',
                  'retained-history', '250000-input-boundary', 'structured-output'):
        body = dict(model=Q.MODEL, messages=[{'role': 'user', 'content':
            'boundary' if label == '250000-input-boundary' else label}],
            temperature=0, max_tokens=2, stream=False)
        if label != 'structured-output':
            body['tools'] = [{'type': 'function', 'function': {'name': 'native_test',
                'parameters': {'type': 'object', 'properties': {'z': {'type': 'string'}, 'a': {'type': 'string'}}}}}]
        else: body['response_format'] = {'type': 'json_schema'}
        values.append((label, body, label in {'retained-history', '250000-input-boundary', 'structured-output'}))
    return values


class WireTests(unittest.TestCase):
    def setUp(self):
        self.calls = []; self.records = []

    def test_reviewed_runtime_loads_through_measurement_source_gate(self):
        loaded = Q.source_runtime(Q.pin(RUNTIME))
        self.assertEqual(loaded['MODEL'], Q.MODEL)
        self.assertEqual(loaded['CONTEXT'], Q.CONTEXT)
        self.assertEqual(loaded['projection_sha256'](),
                         'e818865d35a1a4cd9c6d3abc1c3fa02786cad1cb8eb89bd57b870f2ae6b8c27e')
        self.assertTrue(callable(loaded['QwenFactories'].http_timeout))

    def test_old_runtime_pin_rejected_before_source_read(self):
        for digest in ('4491d896a025b728ea1ab6eca4640b2efc030cc7a33769d4d538f5056c32c7dd',
                       'c0684c3ff0923a5054d5804c85b61d231caf774837963ed94641046351419ff3'):
            with self.subTest(runtime_sha256=digest), \
                    patch.object(Q, 'read_pin', side_effect=AssertionError('Unexpected source read')):
                with self.assertRaisesRegex(ValueError, 'independently reviewed exact runtime'):
                    Q.source_runtime(dict(path=str(RUNTIME), sha256=digest))

    def test_changed_runtime_bytes_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / 'qwen_suite_runtime.py'
            runtime.write_text("raise AssertionError('Unreviewed code executed')\n")
            with self.assertRaises(ValueError):
                Q.source_runtime(dict(path=str(runtime), sha256=Q.RUNTIME_SHA256))

    def exchange(self, path, body):
        self.calls.append((path, deepcopy(body)))
        ids = reference(project(body))
        if path == '/tokenize': return dict(tokens=ids, count=len(ids), max_model_len=Q.CONTEXT)
        return dict(prompt_token_ids=ids, usage={'prompt_tokens': len(ids), 'completion_tokens': body['max_tokens']})

    def record(self, rows): self.records.append(deepcopy(rows))

    def test_five_generations_and_ordered_schema_controls(self):
        report = Q.qualify(selected(), project, reference, self.exchange, self.record)
        self.assertEqual(report['diagnostic_generation_requests'], 5)
        calls = [body for path, body in self.calls if path == '/v1/chat/completions']
        self.assertEqual(sum(body['max_tokens'] for body in calls), 9)
        self.assertTrue(all(body['return_token_ids'] is True for body in calls))
        self.assertIn('response_format', calls[-2]); self.assertNotIn('response_format', calls[-1])
        self.assertEqual(list(calls[0]['tools'][0]['function']['parameters']['properties']), ['z', 'a'])
        self.assertTrue(all(report['checks'].values()))

    def test_same_length_different_server_ids_stops_before_generation(self):
        def corrupt(path, body):
            result = self.exchange(path, body)
            result['tokens'] = [0] * result['count']
            return result
        with self.assertRaisesRegex(ValueError, 'complete token parity'):
            Q.qualify(selected(), project, reference, corrupt, self.record)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.records)
        saved = self.records[-1][-1]['server_count']
        self.assertIn('token_ids_sha256', saved)
        self.assertEqual(saved['mismatch_response']['tokens'], [0] * saved['count'])

    def test_paid_response_saved_before_usage_mismatch(self):
        def corrupt(path, body):
            result = self.exchange(path, body)
            if path == '/v1/chat/completions': result['usage']['prompt_tokens'] += 1
            return result
        with self.assertRaisesRegex(ValueError, 'Generation prompt/output parity'):
            Q.qualify(selected(), project, reference, corrupt, self.record)
        saved = self.records[-1][-1]['generations']
        self.assertEqual(len(saved), 1); self.assertIn('response', saved[0])
        self.assertEqual(sum(path == '/v1/chat/completions' for path, body in self.calls), 1)

    def test_schema_inserting_hidden_prompt_is_rejected(self):
        def changed(path, body):
            result = self.exchange(path, body)
            if path == '/v1/chat/completions' and 'response_format' in body:
                result['prompt_token_ids'].append(9); result['usage']['prompt_tokens'] += 1
            return result
        with self.assertRaisesRegex(ValueError, 'structured-output'):
            Q.qualify(selected(), project, reference, changed, self.record)
        self.assertIn('response_format', self.calls[-1][1])
        self.assertEqual(len(self.records[-1][-1]['generations']), 1)

    def test_partial_missing_or_shortened_boundary_cannot_pass(self):
        for values in ([], selected()[:-1], [selected()[0]] * 6):
            with self.subTest(count=len(values)), self.assertRaises(ValueError):
                Q.qualify(values, project, reference, self.exchange, self.record)
        def shortened(body):
            return [7] * 10 if body['messages'][0]['content'] == 'boundary' else reference(body)
        with self.assertRaisesRegex(ValueError, 'Boundary'):
            Q.qualify(selected(), project, shortened, self.exchange, self.record)

    def test_count_context_and_completion_budget_checked(self):
        for mutation in ('context', 'completion', 'ids'):
            def changed(path, body):
                result = self.exchange(path, body)
                if mutation == 'context' and path == '/tokenize': result['max_model_len'] -= 1
                if path == '/v1/chat/completions':
                    if mutation == 'completion': result['usage']['completion_tokens'] += 1
                    if mutation == 'ids': result['prompt_token_ids'][0] += 1
                return result
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                Q.qualify(selected(), project, reference, changed, self.record)

    def test_plan_uses_pins_with_no_GPU_import_or_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp); args = []
            for name in ('runtime', 'request', 'launch', 'owner', 'rental'):
                path = directory / (name + '.json'); path.write_text('{}')
                args += ['--' + name, str(path), '--' + name + '-sha256', sha256(path.read_bytes()).hexdigest()]
            result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), *args,
                '--snapshot', '/nonexistent/snapshot', '--deadline-utc', '1', '--output', str(directory / 'out')],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report['no_GPU_HTTP_download_or_dispatch']); self.assertFalse((directory / 'out').exists())
            # Pin mismatch remains terminal even for planning.
            Path(args[1]).write_text('{"changed":true}')
            result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), *args,
                '--snapshot', '/nonexistent/snapshot', '--deadline-utc', '1', '--output', str(directory / 'out')],
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)

    def test_official_reference_retains_reasoning_and_argument_order_without_changing_wire(self):
        messages = [{'role': 'assistant', 'reasoning': 'kept reasoning', 'content': None,
            'tool_calls': [{'function': {'name': 'native', 'arguments': '{"z":1,"a":2}'}}]}]
        original = Q.wire(messages)
        mapped = Q.official_messages(messages)
        self.assertEqual(mapped[0]['reasoning_content'], 'kept reasoning')
        self.assertEqual(list(mapped[0]['tool_calls'][0]['function']['arguments']), ['z', 'a'])
        self.assertEqual(Q.wire(messages), original)

    def test_generation_attempt_recorded_before_exchange_failure(self):
        def fail(path, body):
            if path == '/v1/chat/completions':
                attempt = self.records[-1][-1]['generations'][-1]
                self.assertEqual(attempt['state'], 'dispatch_attempt')
                self.assertEqual(attempt['request_sha256'], sha256(Q.wire(body)).hexdigest())
                raise Q.ExchangeError({'http_status': 500, 'error_type': 'server_failure',
                    'body_prefix_base64': base64.b64encode(b'failure sentinel').decode()})
            return self.exchange(path, body)
        with self.assertRaises(Q.ExchangeError):
            Q.qualify(selected(), project, reference, fail, self.record)
        attempt = self.records[-1][-1]['generations'][-1]
        self.assertEqual(attempt['state'], 'failed')
        self.assertEqual(base64.b64decode(attempt['observation']['body_prefix_base64']), b'failure sentinel')

    def test_HTTP_failure_body_and_post_receive_guard_failure_are_preserved(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                data = b'failure sentinel' if self.server.status == 500 else b'{"response":"received"}'
                self.send_response(self.server.status); self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(3)))
        server.status = 500
        with patch.object(Q, 'owned_listener'), self.assertRaises(Q.ExchangeError) as caught:
            Q.http_exchange(f'http://127.0.0.1:{server.server_port}', '/v1/chat/completions', {},
                            deadline=time.time() + 10, owner={})
        observed = caught.exception.observation
        self.assertEqual(observed['http_status'], 500)
        self.assertTrue(observed['request_written']); self.assertTrue(observed['response_received'])
        self.assertEqual(base64.b64decode(observed['body_prefix_base64']), b'failure sentinel')
        server.status = 200
        with patch.object(Q, 'owned_listener', side_effect=[[], ValueError('owner changed')]), self.assertRaises(Q.ExchangeError) as caught:
            Q.http_exchange(f'http://127.0.0.1:{server.server_port}', '/v1/chat/completions', {},
                            deadline=time.time() + 10, owner={})
        self.assertEqual(caught.exception.observation['received_response'], {'response': 'received'})
        self.assertTrue(caught.exception.observation['response_received'])

    def test_bootstrap_plan_rejects_containment_and_generic_directories(self):
        script = ROOT / 'training/scripts/bootstrap_qwen_host.sh'
        for args in (['--runtime', '/opt'], ['--models', '/mnt'],
                     ['--release', '/opt/release', '--runtime', '/opt/release/env'],
                     ['--release', '/opt/release/src', '--runtime', '/opt/release']):
            result = subprocess.run(['bash', str(script), *args], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('apt-get update', result.stdout)
        result = subprocess.run(['bash', str(script)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('# Plan only', result.stdout)
        self.assertNotIn('Bootstrap commands complete', result.stdout)

    def test_HTTP_dripping_response_has_overall_rental_bound(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200); self.send_header('Content-Length', '1000'); self.end_headers()
                try:
                    for _ in range(20):
                        self.wfile.write(b' '); self.wfile.flush(); time.sleep(.1)
                except OSError: pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(3)))
        started = time.monotonic()
        with patch.object(Q, 'owned_listener'), self.assertRaises(Q.ExchangeError) as caught:
            Q.http_exchange(f'http://127.0.0.1:{server.server_port}', '/v1/chat/completions', {},
                            deadline=time.time() + .3, owner={})
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertTrue(caught.exception.observation['request_written'])
        self.assertEqual(caught.exception.observation['http_status'], 200)
        self.assertTrue(caught.exception.observation['deadline_timer_fired'])
        self.assertTrue(caught.exception.observation['body_incomplete'])
        self.assertFalse(caught.exception.observation['response_received'])

    def test_bootstrap_timeout_inside_sudo_and_zero_budget_refused(self):
        # Exercise the real runner function without the install/execution body.
        script = (ROOT / 'training/scripts/bootstrap_qwen_host.sh').read_text()
        function = script[script.index('run() {'):script.index('# Credentials and workstation')]
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            # Fake privilege boundary, no sudo or installations. Log argv order.
            sudo = directory / 'sudo'; sudo.write_text('#!/bin/sh\nprintf "privileged:%s\\n" "$*"\n'); sudo.chmod(0o755)
            code = f'set -euo pipefail\nexecute=true\ndeadline={time.time()+60}\n'+function+'\nrun sudo -n printf bounded\n'
            result = subprocess.run(['bash', '-c', code], env={**os.environ, 'PATH':str(directory)+':'+os.environ['PATH']},
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('privileged:-n timeout --signal=TERM --kill-after=5s', result.stdout)
            code = 'set -euo pipefail\nexecute=true\ndeadline=$(python3 -c "import time;print(time.time()+5.6)")\n'+function+'\nrun printf UNBOUNDED\n'
            result = subprocess.run(['bash', '-c', code], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('UNBOUNDED', result.stdout)

    def test_real_probe_builder_preserves_system_with_large_schema_overhead(self):
        system = [{'role': 'system', 'content': 'KEEP THIS SYSTEM x x'}]
        template = {'model': Q.MODEL, 'messages': system,
                    'tools': [{'type': 'function', 'function': {'name': 'native'}}]}
        def count(body):
            return [7] * (5000 + sum(m.get('content', '').count(' x')
                          for m in body['messages'] if m['role'] == 'user' and isinstance(m.get('content'), str)))
        with patch.object(Q, 'png', return_value={'type': 'image_url', 'image_url': {'url': 'fixture'}}):
            built = Q.probes(template, project, count)
        self.assertEqual(len(built), 6)
        for label, body, _ in built:
            self.assertEqual(body['messages'][0], system[0], label)
        boundary = next(body for label, body, _ in built if label == '250000-input-boundary')
        self.assertEqual(len(count(project(boundary))), Q.BOUNDARY)
        self.assertEqual(boundary['messages'][-1]['role'], 'user')
        self.assertEqual(template['messages'], system)

    def test_HTTP_raw_200_overflow_and_short_body_evidence(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                data = self.server.body
                self.send_response(200); self.send_header('Content-Length', str(len(data) + self.server.extra))
                self.end_headers(); self.wfile.write(data); self.close_connection = True
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(3)))
        server.body = b'{ "z": 1, "a": 2 }'; server.extra = 0
        with patch.object(Q, 'owned_listener'):
            value = Q.http_exchange(f'http://127.0.0.1:{server.server_port}', '/', {}, deadline=time.time()+10, owner={})
        self.assertEqual(value.observation['raw_body'], server.body)
        self.assertEqual(value.observation['http_status'], 200)
        for data, extra in ((b' {"usage":"' + b'x' * 100000, 5000), (b'{"number":1e999}', 0)):
            server.body, server.extra = data, extra
            with patch.object(Q, 'owned_listener'), self.assertRaises(Q.ExchangeError) as caught:
                Q.http_exchange(f'http://127.0.0.1:{server.server_port}', '/', {}, deadline=time.time()+10, owner={})
            observation = caught.exception.observation
            self.assertEqual(observation['raw_body'], data)
            self.assertEqual(observation['declared_content_length'], len(data)+extra)
            self.assertEqual(observation['body_incomplete'], bool(extra))
            self.assertEqual(observation['response_received'], not bool(extra))
            self.assertFalse(observation['body_truncated'])

    def run_mock_main(self, directory, *, stop=False):
        """Exercise CLI publication/lifecycle with fake GPU/processor/transport."""
        directory.chmod(0o700)
        snapshot = directory / 'models--Qwen--Qwen3.8-27B-FP8' / 'snapshots' / Q.REVISION
        snapshot.mkdir(parents=True)
        allocated = time.time() - 1; deadline = allocated + 3600
        launch = {'status': 'source_checks_passed_before_exec', 'pid': os.getpid(),
                  'attempt_id': str(uuid4()), 'command': ['mock'],
                  'launch_settings': {'max_num_seqs': 8, 'gpu_memory_utilization': .9}}
        # main binds the actual command snapshot at index5.
        launch['command'] = ['mock'] * 5 + [str(snapshot)]
        values = {'runtime': {}, 'owner': {'pid': os.getpid()}, 'launch': launch,
            'request': {'model': Q.MODEL, 'messages': [{'role': 'system', 'content': 'Keep me'}],
                        'tools': [{'type': 'function', 'function': {'name': 'native'}}]},
            'rental': {'run_id': str(uuid4()), 'instance_id': str(uuid4()),
                'qualification_authorized': True, 'allocation_utc': allocated, 'approved_rental_seconds': 3600,
                'deadline_utc': deadline, 'serving_session_id': launch['attempt_id']}}
        argv = ['wire']
        for name, value in values.items():
            path = directory / (name + '.json'); path.write_text(json.dumps(value))
            argv += ['--' + name, str(path), '--' + name + '-sha256', sha256(path.read_bytes()).hexdigest()]
        output = directory / 'output'
        argv += ['--snapshot', str(snapshot), '--deadline-utc', str(deadline), '--output', str(output), '--execute']
        def count(body):
            return [7] * (4000 + sum(m.get('content', '').count(' x') for m in body['messages']
                                    if m['role'] == 'user' and isinstance(m.get('content'), str)))
        def exchange(origin, path, body, **kwargs):
            if stop:
                # Reproduce a library FD scan catching OSError. A stop must escape.
                try: Q.signal.getsignal(Q.signal.SIGTERM)(Q.signal.SIGTERM, None)
                except OSError: pass
                self.fail('Stop signal was swallowed and dispatch continued')
            ids = count(project(body))
            value = ({'count':len(ids), 'tokens':ids, 'max_model_len':Q.CONTEXT} if path == '/tokenize'
                else {'prompt_token_ids':ids, 'usage': {'prompt_tokens':len(ids), 'completion_tokens':body['max_tokens']}})
            raw = json.dumps(value, indent=1).encode()
            return Q.ExchangeResult(value, {'http_status':200, 'raw_body':raw,
                'body_sha256':sha256(raw).hexdigest(), 'received_response':value})
        handlers = {s: Q.signal.getsignal(s) for s in (Q.signal.SIGTERM, Q.signal.SIGINT, Q.signal.SIGHUP)}
        with patch.object(sys, 'argv', argv), patch.object(Q, 'gpu_check'), patch.object(Q, 'owned_listener'), \
             patch.object(Q, 'models', return_value={'data':[{'id':Q.MODEL, 'max_model_len':Q.CONTEXT}]}), \
             patch.object(Q, 'serving_command', return_value=launch['command']), \
             patch.object(Q, 'source_runtime', return_value={'tokenize_payload':project, 'projection_sha256':lambda:'fixture'}), \
             patch.object(Q, 'processor_counter', return_value=count), \
             patch.object(Q, 'png', return_value={'type':'image_url', 'image_url': {'url':'fixture'}}), \
             patch.object(Q, 'http_exchange', side_effect=exchange):
            if stop:
                with self.assertRaises(Q.StopRequested): Q.main()
            else: Q.main()
        self.assertEqual(handlers, {s: Q.signal.getsignal(s) for s in handlers})
        return output, json.loads((output / 'wire-proof.json').read_text())

    def test_main_signal_cannot_be_swallowed_by_oserror_handler(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, report = self.run_mock_main(Path(temporary), stop=True)
            self.assertFalse(report['passed'])
            self.assertEqual(report['stopped_by_signal'], [Q.signal.SIGTERM])
            self.assertEqual(report['diagnostic_generation_attempts'], 0)
            self.assertEqual(report['error_type'], 'StopRequested')

    def test_main_stores_original_bytes_once_and_success_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, report = self.run_mock_main(Path(temporary))
            self.assertTrue(report['passed'])
            self.assertEqual(report['diagnostic_generation_attempts'], 5)
            artifacts = list(output.glob('*.body'))
            self.assertEqual(len(artifacts), 5)
            for row in report['probes']:
                for generation in row['generations']:
                    saved = generation['response']; self.assertEqual(saved['http_status'], 200)
                    raw = Path(saved['raw_body_artifact']['path']).read_bytes()
                    self.assertEqual(sha256(raw).hexdigest(), saved['raw_body_artifact']['sha256'])
                    self.assertIn(b'\n "prompt_token_ids"', raw)
            self.assertLess((output / 'wire-proof.json').stat().st_size, 100000)


if __name__ == '__main__': unittest.main()
