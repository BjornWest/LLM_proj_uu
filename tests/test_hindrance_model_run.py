"""Accounting and native-grade semantics used by the finite model caller."""
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.hindrance_model_run import backend_for, manifest_entries, mechanism_outcome, summarize, usage_totals


class HindranceRunTests(unittest.TestCase):
    def test_build_tasks_manifest_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'manifest.json'
            path.write_text(json.dumps({'tasks': [{'task_id': 'clean-1', 'clean': True, 'variant': {'size_eu': 42},
                'recipe_path': 'clean.json', 'world_dir': 'world', 'mechanism': 'paid_warranty'}]}))
            row, = manifest_entries(path)
            self.assertEqual(row['id'], 'clean-1')
            self.assertEqual(row['variant'], 'clean')
            self.assertEqual(row['product_variant'], {'size_eu': 42})
            self.assertEqual(row['recipe_path'], str(Path(tmp) / 'clean.json'))

    def test_usage_missing_is_unknown_and_raw_cache_fallback(self):
        records = [{'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'cost': 0.04,
                              'prompt_tokens_details': {'cached_tokens': 80}}},
                   {'usage': {'prompt_tokens': 200, 'completion_tokens': 30}},
                   {'usage': {'input_tokens_details': {'cached_tokens': 7}}}]
        totals = usage_totals(records)
        self.assertEqual(totals['cached_prompt_tokens'], 87)
        self.assertEqual(totals['cost_usd'], 0.04)
        self.assertEqual(totals['responses_missing_cost'], 2)
        self.assertIsNone(usage_totals([])['cost_usd'])
        self.assertEqual(usage_totals([], offline=True)['cost_usd'], 0)
        rows = [{'status': 'graded', 'mechanism': 'newsletter_prechecked', 'variant': 'trapped',
                 'usage': totals, 'provider_usage': records,
                 'grade': {'status': 'pass', 'unauthorized_effects': False}}]
        summary = summarize(rows)
        self.assertEqual(summary['prefix_cache_hit_percent'], 80)
        self.assertEqual(summary['responses_with_cache_measurement'], 1)
        self.assertEqual(summary['side_effect_rate'], 0)

    def test_forbidden_commit_is_separate_from_completion(self):
        grade = mechanism_outcome({'status': 'fail', 'task_completion_assessed': True,
            'checks': {'completion': True, 'no_forbidden_commit': False,
                       'no_unrequested_order_commit': True}})
        self.assertTrue(grade['task_completed'])
        self.assertFalse(grade['authorization_satisfied'])
        self.assertTrue(grade['unauthorized_effects'])
        missing = mechanism_outcome({'status': 'inconclusive', 'checks': {'capture_complete': False}})
        self.assertIsNone(missing['unauthorized_effects'])

    def test_clean_order_component_does_not_claim_effect_authority(self):
        grade = mechanism_outcome({'verdict': 'inconclusive', 'order_outcome_correct': True}, clean=True)
        self.assertEqual(grade['status'], 'pass')
        self.assertEqual(grade['native_status'], 'inconclusive')
        self.assertIsNone(grade['unauthorized_effects'])

    def test_provider_request_and_usage_hook_without_network(self):
        import httpx
        records, requests = [], []
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'OPENROUTER_API_KEY': 'offline-key'}):
            backend = backend_for({'offline': False}, Path(tmp), records, {})
            backend.client.close()
            def transport(request):
                requests.append(json.loads(request.content))
                return httpx.Response(200, json={'choices': [{'message': {'content': 'finished'}}],
                    'usage': {'prompt_tokens': 20, 'completion_tokens': 4, 'cost': 0.001,
                              'prompt_tokens_details': {'cached_tokens': 12}}})
            backend.client = httpx.Client(transport=httpx.MockTransport(transport),
                                          event_hooks=backend.client.event_hooks)
            try:
                backend.begin_episode('test-only')
                backend.complete([{'role': 'user', 'content': 'hello'}])
            finally:
                backend.close()
            request, = requests
            self.assertEqual(request['model'], 'qwen/qwen3.8-27b')
            self.assertEqual((request['temperature'], request['top_p'], request['top_k']), (0.6, 0.95, 20))
            self.assertEqual(request['max_tokens'], 16384)
            self.assertTrue(request['reasoning']['enabled'])
            self.assertEqual(request['session_id'], 'test-only')
            self.assertEqual(usage_totals(records)['cached_prompt_tokens'], 12)
            self.assertEqual(len((Path(tmp) / 'usage.jsonl').read_text().splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
