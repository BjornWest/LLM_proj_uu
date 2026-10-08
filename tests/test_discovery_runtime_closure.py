"""Offline discovery closure: real runner and transport, no world/browser/provider."""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx
import numpy as np
from tokenizers import Tokenizer, models, pre_tokenizers

from intent_browser.ax_explorer import AXConfig
from intent_browser.backend import ChatCompletionsBackend, Completion
from intent_browser.harness import native_tools_profile, SemanticFeedback, with_site_discovery, with_subagents
from intent_browser.runner import run_episode
from intent_browser.site_discovery import SiteDiscoverySession


def public_response(query='', kind=None, limit=5, offset=0):
    return {'total': 1, 'offset': offset, 'limit': limit, 'next_offset': None,
            'sites': [] if offset else [{'site_id': 'retailer-one', 'kind': kind or 'retailer',
                'name': 'Public store', 'url': 'http://store.test/', 'description': 'Public assortment.'}]}


def completion(arguments):
    return Completion('', {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
        'tool_calls': [{'type': 'function', 'id': 'discover', 'function': {
            'name': 'discover_sites', 'arguments': json.dumps(arguments)}}]}}]})


class DiscoveryRuntimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        tok = Tokenizer(models.WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
        tok.pre_tokenizer = pre_tokenizers.Whitespace()
        self.tokenizer = self.root / 'tokenizer.json'; tok.save(str(self.tokenizer))
        self.base = replace(native_tools_profile(ax_config=AXConfig(str(self.tokenizer))),
                            feedback_factory=SemanticFeedback)
        self.profile = with_site_discovery(self.base)

    def test_opt_in_registry_schema_and_default_preservation(self):
        original = deepcopy(self.base.tools.request_options())
        self.assertNotIn('discover_sites', self.base.describe()['tools'])
        self.assertIn('discover_sites', self.profile.describe()['tools'])
        self.assertEqual(self.base.tools.request_options(), original)
        self.assertEqual(self.base.instructions, native_tools_profile(
            ax_config=AXConfig(str(self.tokenizer))).instructions)
        self.assertFalse(self.base.tools.site_discovery_tools)
        decision, _ = self.profile.tools.parse_completion(completion({}))
        self.assertEqual(decision.name, 'discover_sites')
        with self.assertRaises(ValueError): self.base.tools.parse_completion(completion({}))
        with self.assertRaises(ValueError): with_site_discovery(self.profile)
        for args in ({'limit': True}, {'limit': 21}, {'offset': -1}, {'kind': 'private'},
                     {'private_reference': 'secret'}, {'query': 'x' * 257}):
            with self.subTest(args=args), self.assertRaises(Exception):
                self.profile.tools.parse_completion(completion(args))
        definitions = self.profile.tools.definitions()
        self.assertEqual(definitions, self.profile.tools.definitions())
        helpers = with_subagents(self.profile)
        self.assertIn('discover_sites', [d['function']['name'] for d in
            replace(helpers.tools, allow_spawn=False).definitions()])

    def test_misconfiguration_blocks_environment_and_transport(self):
        for profile, options in ((self.profile, {}),
            (self.profile, {'site_discovery': 3}),
            (self.profile, {'site_discovery': public_response, 'site_discovery_audit_id': ''}),
            (self.base, {'site_discovery': public_response}),
            (self.base, {'site_discovery_audit_id': 'private'}),
            (replace(self.profile, ax_config=None), {'site_discovery': public_response})):
            with self.subTest(options=options), self.assertRaises(ValueError):
                run_episode(lambda _: self.fail('environment created'), object(), {},
                    harness_profile=profile, allow_ungraded=True,
                    ungraded_reason='Offline callback validation', **options)

    def run_case(self, *, batch=False, failure=False, invalid=False):
        requests, calls, actions = [], [], []
        def obs():
            return {'goal': 'Find public stores.', 'url': 'http://fixture/', 'last_action_error': '',
                'axtree_object': {'nodes': [{'nodeId': '0', 'role': {'value': 'RootWebArea'},
                    'name': {'value': 'Neutral original discovery start'}, 'childIds': []}]},
                'screenshot': np.zeros((2, 2, 3), dtype=np.uint8)}
        class Env:
            def reset(self, seed): return obs(), {}
            def step(self, action):
                actions.append(action); return obs(), 0, False, False, {}
            def close(self): pass
        def callback(**args):
            calls.append(deepcopy(args))
            if failure: raise RuntimeError('PRIVATE_CALLBACK_SENTINEL')
            value = public_response(**args)
            return {**value, 'oracle': 'PRIVATE_ORACLE'} if invalid else value
        def transport(req):
            request = json.loads(req.content); requests.append(request); turn = len(requests)
            selected = ([('discover_sites', {'query': 'one'})] if turn == 1 else
                        [('send_msg_to_user', {'text': 'Finished.'})])
            if turn == 1 and batch: selected.append(('discover_sites', {'query': 'two'}))
            tools = [{'type': 'function', 'id': f'call-{turn}-{i}', 'function': {
                'name': name, 'arguments': json.dumps(args)}} for i, (name, args) in enumerate(selected)]
            return httpx.Response(200, json={'choices': [{'finish_reason': 'tool_calls',
                'message': {'role': 'assistant', 'content': None, 'tool_calls': tools}}], 'usage': {'cost': 0}})
        backend = ChatCompletionsBackend('https://offline.invalid/v1', 'offline')
        backend.client.close(); backend.client = httpx.Client(transport=httpx.MockTransport(transport))
        self.addCleanup(backend.close)
        profile = replace(self.profile, tools=replace(self.profile.tools, batch_size=4 if batch else 1))
        with ExitStack() as stack:
            stack.enter_context(patch('intent_browser.harness.flatten_axtree_to_str', return_value='Neutral original discovery start'))
            stack.enter_context(patch('intent_browser.runner.refresh_observation', side_effect=lambda *a, **k: obs()))
            stack.enter_context(patch('intent_browser.batching.document_signature', return_value=['same']))
            directory, summary = run_episode(lambda _: Env(), backend, {'tags': ['scripted']},
                output=self.root / 'runs', max_steps=2, harness_profile=profile,
                site_discovery=callback, site_discovery_audit_id='PRIVATE_AUDIT',
                observation_pipeline='native', allow_ungraded=True,
                ungraded_reason='Offline synthetic transport; no provider/world/browser',
                async_recording=False)
        rows = [json.loads(x) for x in (directory/'steps.jsonl').read_text().splitlines()]
        return directory, summary, rows, requests, calls, actions

    def test_actual_runner_exact_callback_batch_and_delivery(self):
        for batch in (False, True):
            with self.subTest(batch=batch):
                directory, summary, rows, requests, calls, actions = self.run_case(batch=batch)
                self.assertIsNone(summary['error']); self.assertEqual(summary['stop_reason'], 'agent_finished')
                self.assertEqual(len(requests), 2); self.assertEqual(len(calls), 2 if batch else 1)
                self.assertEqual(len(actions), 1); self.assertTrue(actions[0].startswith('send_msg_to_user'))
                self.assertEqual(calls[0], {'query': 'one', 'kind': None, 'limit': 5, 'offset': 0})
                members = rows[0]['batch_calls'] if batch else [rows[0]]
                self.assertEqual(len(members), len(calls))
                self.assertEqual(len({m['site_discovery_artifact'] for m in members}), len(calls))
                for member in members:
                    self.assertFalse(member['browser_stepped']); self.assertEqual(member['kind'], 'site_discovery')
                    saved = json.loads((directory/member['site_discovery_artifact']).read_text())
                    self.assertEqual(saved['response'], public_response(**saved['arguments']))
                    self.assertEqual(saved['feedback'], member['policy_feedback'])
                delivery = [s for s in rows[1]['policy_delivery']['items'] if s['kind'] == 'site_discovery_result']
                self.assertEqual(len(delivery), len(calls))
                for source in delivery:
                    self.assertTrue(source['confirmed']); evidence = json.loads((directory/source['artifact']).read_text())
                    span = source['message_span']; message = requests[1]['messages'][span['message_index']]
                    self.assertEqual(message['role'], 'tool')
                    self.assertEqual(message['content'][span['start']:span['end']], evidence['text'])
                    self.assertTrue(evidence['provenance']['site_discovery_artifact'])
                self.assertNotIn('PRIVATE_', json.dumps(requests))
                self.assertEqual(requests[0]['tools'], requests[1]['tools'])
                self.assertEqual(requests[1]['messages'][:len(requests[0]['messages'])], requests[0]['messages'])
                metadata = json.loads((directory/'metadata.json').read_text())
                self.assertEqual(metadata['site_discovery']['version'], 'public-site-discovery-v1')
                self.assertIn('scripted', metadata['tags'])

    def test_callback_error_and_private_response_are_not_delivered_or_retried(self):
        for failure, invalid in ((True, False), (False, True)):
            with self.subTest(failure=failure, invalid=invalid):
                directory, summary, rows, requests, calls, actions = self.run_case(failure=failure, invalid=invalid)
                self.assertIsNone(summary['error']); self.assertEqual(len(calls), 1)
                self.assertEqual(len(actions), 1); self.assertEqual(len(requests), 2)
                saved = json.loads((directory/rows[0]['site_discovery_artifact']).read_text())
                self.assertIsNone(saved['response']); self.assertIsNotNone(saved['error'])
                self.assertEqual(rows[0]['tool_output']['execution'], 'failed')
                self.assertNotIn('PRIVATE_', json.dumps(requests))

    def test_helper_options_inherit_only_explicit_callback(self):
        runtime = Mock(); runtime.run.return_value = ('root', {'fixture': True})
        with patch('intent_browser.delegation.AgentRuntime', return_value=runtime) as constructor:
            result = run_episode(lambda _: self.fail('env created'), object(), {},
                harness_profile=with_subagents(self.profile), site_discovery=public_response,
                site_discovery_audit_id='private-audit', observation_pipeline='native',
                allow_ungraded=True, ungraded_reason='Offline helper registry fixture')
        self.assertEqual(result, runtime.run.return_value)
        options = constructor.call_args.args[5]
        self.assertIs(options['site_discovery'], public_response)
        self.assertEqual(options['site_discovery_audit_id'], 'private-audit')

    def test_artifact_collision_never_reexecutes_callback(self):
        callback = Mock(side_effect=public_response)
        session = SiteDiscoverySession(callback, self.root, Tokenizer.from_file(str(self.tokenizer)))
        session.execute({}, 0)
        with self.assertRaises(FileExistsError): session.execute({}, 0)
        callback.assert_called_once_with(query='', kind=None, limit=5, offset=0)


class DiscoveryFeedbackBoundTests(unittest.TestCase):
    def test_empty_page_pagination_obeys_final_feedback_bound(self):
        class ScalarTokenizer:
            def encode(self, text, **options):
                return type('Encoded', (), {'ids': list(text)})()
        with tempfile.TemporaryDirectory() as path:
            session = SiteDiscoverySession(public_response, path, ScalarTokenizer())
            result, artifact = session.execute({'offset': int('9' * 1800)}, 0)
            self.assertEqual(result['execution'], 'failed')
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 1500)
            saved = json.loads((Path(path)/artifact).read_text())
            self.assertIsNone(saved['error'])
            self.assertEqual(saved['response'], public_response(**saved['arguments']))
            self.assertEqual(saved['arguments']['offset'], int('9' * 1800))
            self.assertNotIn('9' * 100, json.dumps(result))

    def test_ordinary_empty_page_preserves_pagination(self):
        class ScalarTokenizer:
            def encode(self, text, **options):
                return type('Encoded', (), {'ids': list(text)})()
        with tempfile.TemporaryDirectory() as path:
            session = SiteDiscoverySession(public_response, path, ScalarTokenizer())
            result, _ = session.execute({'offset': 1}, 0)
            self.assertEqual(result['execution'], 'completed')
            self.assertEqual(result['offset'], 1)
            self.assertEqual(result['sites'], [])
            self.assertIsNone(result['next_offset'])
