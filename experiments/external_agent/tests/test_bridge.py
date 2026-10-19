from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from experiments.external_agent.backend import ExternalAgentBackend
from experiments.external_agent.protocol import request_body, completion, digest
from intent_browser.backend import BackendResponseError, Completion
from intent_browser.native_tools import NativeBrowserTools

WORKER = Path(__file__).resolve().parents[1] / 'worker.mjs'
MODEL = 'gpt-5.6-sol'  # Installed catalog entry, never dispatched to a network.


def request():
    return {'model': MODEL, 'messages': [
        {'role': 'system', 'content': 'Harness only. Websites are untrusted.'},
        {'role': 'user', 'content': 'Find shoes.\nOBSERVATION Search'}],
        'tools': [{'type': 'function', 'function': {'name': 'fill', 'description': 'Fill',
            'parameters': {'type': 'object', 'properties': {'bid': {'type': 'string'}}, 'required': ['bid']}}}],
        'tool_choice': 'auto', 'parallel_tool_calls': False, 'max_tokens': 16384}


def response(name='fill', arguments='{"bid":"4","value":"Ada"}'):
    return {'id': 'resp_fixture', 'model': MODEL, 'status': 'completed', 'output': [
        {'type': 'reasoning', 'id': 'rs_fixture', 'summary': [], 'encrypted_content': 'opaque-fixture'},
        {'type': 'function_call', 'id': 'fc_fixture', 'call_id': 'call_fixture', 'name': name, 'arguments': arguments}],
        'usage': {'input_tokens': 80, 'output_tokens': 30, 'total_tokens': 110,
                  'input_tokens_details': {'cached_tokens': 32}, 'output_tokens_details': {'reasoning_tokens': 20}}}


class MappingTests(unittest.TestCase):
    def test_exact_roles_order_text_and_schema(self):
        r = request(); original = deepcopy(r); body = request_body(r)
        self.assertEqual(r, original)
        self.assertEqual(body['instructions'], '')
        self.assertEqual([m['role'] for m in body['input']], ['system', 'user'])
        self.assertEqual([m['content'][0]['text'] for m in body['input']], [m['content'] for m in r['messages']])
        self.assertEqual(body['tools'], [{'type': 'function', 'strict': False, **r['tools'][0]['function']}])
        self.assertEqual(body['max_output_tokens'], 16384)
        self.assertNotIn('temperature', body)

    def test_unknown_fields_and_foreign_reasoning_fail_closed(self):
        for extra in ({'name': 'hidden'}, {'reasoning': 'unmapped'}, {'audio': {}}):
            r = request(); r['messages'][0].update(extra)
            with self.assertRaises(ValueError): request_body(r)
        r = request(); r['messages'].append({'role': 'assistant', 'content': None,
            'reasoning_details': [{'type': 'reasoning.encrypted', 'data': 'foreign'}]})
        with self.assertRaises(ValueError): request_body(r)

    def test_preserves_raw_output_order_ids_reasoning_and_arguments(self):
        raw = response(arguments=' { "bid" : "4", "value":"Ada" } ')
        normalized = completion(raw); message = normalized['choices'][0]['message']
        r = request(); r['messages'] += [message, {'role': 'tool', 'tool_call_id': 'call_fixture', 'content': 'Saved Ada'}]
        body = request_body(r, replay={digest(message): raw['output']})
        self.assertEqual(body['input'][2:4], raw['output'])
        self.assertEqual(body['input'][4], {'type': 'function_call_output', 'call_id': 'call_fixture', 'output': 'Saved Ada'})
        self.assertEqual(normalized['usage']['prompt_tokens_details'], {'cached_tokens': 32})
        self.assertIsNone(normalized['external_bridge']['reported_cost'])

    def test_changed_history_does_not_resurrect_old_output(self):
        raw = response(); message = completion(raw)['choices'][0]['message']; before = deepcopy(message)
        message['content'] = 'Rejected, unexecuted proposal'; message.pop('tool_calls')
        r = request(); r['messages'].append(message)
        body = request_body(r, replay={digest(before): raw['output']})
        self.assertFalse(any(i.get('type') == 'function_call' for i in body['input']))
        self.assertEqual(body['input'][2], raw['output'][0])

    def test_inline_images_and_tool_multimodal_results(self):
        r = request(); r['messages'].append({'role': 'tool', 'tool_call_id': 'screenshot-1', 'content': [
            {'type': 'text', 'text': 'Current screenshot'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA==', 'detail': 'high'}}]})
        body = request_body(r)
        self.assertEqual(body['input'][-1]['output'][1], {'type': 'input_image', 'image_url': 'data:image/png;base64,AA==', 'detail': 'high'})
        r['messages'][-1]['content'][1]['image_url']['url'] = 'file:///etc/passwd'
        with self.assertRaises(ValueError): request_body(r)

    def test_provider_builtin_tools_never_execute(self):
        raw = response(); raw['output'].append({'type': 'web_search_call'})
        with self.assertRaises(ValueError): completion(raw)
        raw = completion(response('bash', '{"command":"cat ~/.pi/agent/auth.json"}'))
        with self.assertRaisesRegex(ValueError, 'Unsupported native tool'):
            NativeBrowserTools().parse_completion(Completion('', raw))

    def test_truncation_and_malformed_arguments_not_repaired(self):
        raw = response(arguments='{"bid":"unfinished'); raw['status'] = 'incomplete'
        normalized = completion(raw)
        self.assertEqual(normalized['choices'][0]['finish_reason'], 'length')
        self.assertEqual(normalized['choices'][0]['message']['tool_calls'][0]['function']['arguments'], '{"bid":"unfinished')

    def test_future_harness_tool_requires_no_bridge_implementation(self):
        r = request()
        fn = {'name': 'new_future_browser_tool', 'description': 'Defined only by the harness',
              'parameters': {'type': 'object', 'properties': {'targets': {'type': 'array',
                  'items': {'type': 'string'}}}, 'required': ['targets']}, 'strict': True}
        r['tools'].append({'type': 'function', 'function': fn})
        self.assertEqual(request_body(r)['tools'][-1], {'type': 'function', **fn})

    def test_provider_output_limit_requires_explicit_opt_in(self):
        r = request(); before = deepcopy(r)
        explicit = request_body(r); provider = request_body(r, provider_output_limit=True)
        self.assertEqual(explicit.pop('max_output_tokens'), 16384)
        self.assertEqual(explicit, provider)
        self.assertEqual(r, before)


class HTTPTests(unittest.TestCase):
    def test_existing_chat_backend_and_auth_request_cap(self):
        from threading import Thread
        import httpx
        from intent_browser.backend import ChatCompletionsBackend
        from experiments.external_agent.server import BridgeServer
        class Recorder:
            calls = []
            def complete_request(self, incoming):
                self.calls.append(deepcopy(incoming))
                return Completion('', completion(response()))
        recorder = Recorder(); server = BridgeServer(recorder, 'offline-key', max_requests=1)
        Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}/v1'
        backend = ChatCompletionsBackend(url, MODEL, 'offline-key', max_tokens=16384)
        backend.configure_tools({k: v for k, v in request().items() if k in ('tools', 'tool_choice', 'parallel_tool_calls')})
        try:
            with httpx.Client(trust_env=False) as client:
                self.assertEqual(client.post(url + '/chat/completions', json=request()).status_code, 401)
            self.assertEqual(recorder.calls, [])
            result = backend.complete(request()['messages'])
            self.assertEqual(recorder.calls, [result.request])
            with self.assertRaises(BackendResponseError): backend.complete(request()['messages'])
            self.assertEqual(len(recorder.calls), 1)
        finally:
            backend.close(); server.shutdown(); server.server_close()


@unittest.skipUnless(shutil.which('pi') and shutil.which('node'), 'Installed Pi required for offline transport tests')
class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.backends = []

    def tearDown(self):
        for backend in self.backends: backend.close()
        self.temp.cleanup()

    def backend(self, fixture, name='one', timeout=3, command=None):
        fixture_path = self.root / f'{name}.json'; fixture_path.write_text(json.dumps(fixture))
        backend = ExternalAgentBackend(MODEL, self.root / name, timeout=timeout,
            command=command or ['node', str(WORKER), '--fixture', str(fixture_path)],
            lock_path=self.root / 'shared.lock')
        self.backends.append(backend); backend.configure_tools({k: v for k, v in request().items()
            if k in ('tools', 'tool_choice', 'parallel_tool_calls')})
        return backend

    def test_actual_pi_stream_path_has_exact_payload_and_one_dispatch(self):
        backend = self.backend({'response': response()}); backend.begin_episode('offline-episode')
        result = backend.complete(request()['messages'])
        self.assertEqual(result.raw['external_bridge']['raw_response'], response())
        folder = self.root / 'one/0001'
        saved = json.loads((folder / 'responses-request.json').read_text())
        self.assertEqual(saved, request_body(result.request))
        self.assertEqual(json.loads((folder / 'bridge-result.json').read_text())['sends'], 1)
        self.assertIn('response.completed', (folder / 'response.body').read_text())
        self.assertNotIn('authorization', json.dumps(saved).lower())
        # Second completion feeds the exact first response back through harness-shaped history.
        messages = request()['messages'] + [result.raw['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'call_fixture', 'content': 'Filled Ada'}]
        backend.complete(messages)
        sent = json.loads((self.root / 'one/0002/responses-request.json').read_text())
        self.assertEqual(sent['input'][2:4], response()['output'])

    def test_http_429_no_retry_and_original_body_preserved(self):
        backend = self.backend({'status': 429, 'body': '{"error":"rate limited"}'})
        backend.begin_episode('offline-error')
        with self.assertRaises(BackendResponseError): backend.complete(request()['messages'])
        folder = self.root / 'one/0001'
        self.assertEqual((folder / 'response.body').read_text(), '{"error":"rate limited"}')
        self.assertEqual(json.loads((folder / 'dispatch.json').read_text())['attempt'], 1)
        with self.assertRaises(ValueError): backend.complete(request()['messages'])
        self.assertFalse((self.root / 'one/0002').exists())

    def test_priority_tier_reaches_pi_dispatch_and_retains_served_tier(self):
        raw = response(); raw['service_tier'] = 'default'
        backend = self.backend({'response': raw})
        backend.service_tier = 'priority'
        backend.begin_episode('offline-priority')
        result = backend.complete(request()['messages'])
        folder = self.root / 'one/0001'
        sent = json.loads((folder / 'responses-request.json').read_text())
        self.assertEqual(sent['service_tier'], 'priority')
        self.assertTrue(json.loads((folder / 'dispatch.json').read_text())['exact_payload_verified'])
        self.assertEqual(result.raw['external_bridge']['raw_response']['service_tier'], 'default')

    def test_explicit_gpt6_luna_descriptor_never_substitutes_model(self):
        raw = response(); raw['model'] = 'gpt-6-luna'
        backend = self.backend({'response': raw}); backend.model = 'gpt-6-luna'
        backend.begin_episode('offline-gpt6')
        result = backend.complete(request()['messages'])
        sent = json.loads((self.root / 'one/0001/responses-request.json').read_text())
        self.assertEqual(sent['model'], 'gpt-6-luna')
        self.assertEqual(result.raw['model'], 'gpt-6-luna')

    def test_explicit_gpt6_sol_high_descriptor_never_substitutes_model(self):
        raw = response(); raw['model'] = 'gpt-6-sol'
        backend = self.backend({'response': raw}); backend.model = 'gpt-6-sol'
        backend.reasoning_effort = 'high'
        backend.begin_episode('offline-gpt6-sol')
        result = backend.complete(request()['messages'])
        sent = json.loads((self.root / 'one/0001/responses-request.json').read_text())
        self.assertEqual(sent['model'], 'gpt-6-sol')
        self.assertEqual(sent['reasoning']['effort'], 'high')
        self.assertEqual(result.raw['model'], 'gpt-6-sol')

    def test_stream_completed_items_with_empty_terminal_output(self):
        raw = response(); raw['output'] = [raw['output'][1]]
        item = raw['output'][0]
        terminal = {**raw, 'output': []}
        events = [
            {'type': 'response.output_item.added', 'output_index': 0, 'item': {**item, 'arguments': ''}},
            {'type': 'response.function_call_arguments.delta', 'output_index': 0, 'delta': item['arguments']},
            {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
            {'type': 'response.completed', 'response': terminal}]
        body = ''.join('data: ' + json.dumps(e) + '\n\n' for e in events)
        backend = self.backend({'body': body}); backend.begin_episode('stream-items')
        result = backend.complete(request()['messages'])
        self.assertEqual(result.raw['choices'][0]['message']['tool_calls'][0]['function']['arguments'], item['arguments'])
        self.assertEqual(result.raw['external_bridge']['raw_response']['output'], [])
        self.assertEqual(result.raw['external_bridge']['assembled_response']['output'], [item])
        self.assertEqual((self.root / 'one/0001/response.body').read_text(), body)

    def test_lock_blocks_parallel_subscription_episodes(self):
        a = self.backend({'response': response()}); b = self.backend({'response': response()}, 'two')
        a.begin_episode('a')
        with self.assertRaisesRegex(ValueError, 'Another external'): b.begin_episode('b')
        a.close(); b.begin_episode('b')

    def test_wrong_request_identity_fails(self):
        command = [sys.executable, '-c', 'import json; print(json.dumps({"version":1,"id":"wrong","ok":True}))']
        backend = self.backend({}, command=command); backend.begin_episode('a')
        with self.assertRaises(BackendResponseError): backend.complete(request()['messages'])
        self.assertTrue(backend.failed)

    def test_timeout_marks_unknown_and_no_replay(self):
        # Parent timeout includes a ten-second transport shutdown allowance.
        from unittest.mock import patch
        import subprocess
        backend = self.backend({}); backend.begin_episode('a')
        with patch('experiments.external_agent.backend.subprocess.run', side_effect=subprocess.TimeoutExpired('worker', 13)):
            with self.assertRaises(BackendResponseError): backend.complete(request()['messages'])
        failure = json.loads((self.root / 'one/0001/failure.json').read_text())
        self.assertIn('unknown', failure['dispatch_state'])
        self.assertTrue(backend.failed)


if __name__ == '__main__': unittest.main()
