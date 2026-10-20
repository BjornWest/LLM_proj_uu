"""Accounting and native-grade semantics used by the finite model caller."""
import json
import tempfile
import time
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
        self.assertEqual(usage_totals([{'provider': 'codex-subscription', 'usage': {'prompt_tokens': 20}}])['source'],
                         'Codex subscription response usage')

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



class FakeClock:
    """Simulated time for the retry loops: sleeps and timed-out requests advance it."""
    def __init__(self):
        self.now = 0.0
    def monotonic(self):
        return self.now
    def time(self):
        return 1_800_000_000 + self.now
    def sleep(self, seconds):
        self.now += seconds


def completion(usage=None):
    return {'choices': [{'message': {'content': 'finished'}}], 'usage': usage or {'prompt_tokens': 3}}


class SelfHostedEndpointTests(unittest.TestCase):
    """self_hosted_backend retries, deadlines and probe without network or real waiting."""
    def build(self, tmp, handler, probe=None, retry_seconds=600, request_timeout=900):
        import httpx
        from scripts import hindrance_model_run as run
        clock, records, holder, probes = FakeClock(), [], {}, []
        def get(url, **kwargs):
            probes.append(kwargs.get('headers') or {})
            if probe:
                return probe(len(probes))
            return httpx.Response(200, json={'data': [{'id': 'served', 'max_model_len': 40000}]},
                                  request=httpx.Request('GET', url))
        options = {'openai_base_url': 'http://127.0.0.1:9/v1', 'model': 'served', 'retry_seconds': retry_seconds,
                   'request_timeout': request_timeout, 'endpoint_wait_seconds': 900}
        with patch.object(run, 'time', clock), patch('httpx.get', get), \
                patch.dict('os.environ', {'SELF_HOSTED_API_KEY': 'offline-key'}):
            backend = run.self_hosted_backend(options, Path(tmp), records, holder)
        hooks, headers = backend.client.event_hooks, backend.client.headers
        backend.client.close()
        sent = []
        def transport(request):
            sent.append(request)
            return handler(len(sent), request, clock)
        backend.client = httpx.Client(transport=httpx.MockTransport(transport), event_hooks=hooks,
                                      headers=headers, timeout=request_timeout)
        return run, backend, clock, records, holder, sent, probes

    def complete(self, run, backend, clock):
        with patch.object(run, 'time', clock):
            return backend.complete([{'role': 'user', 'content': 'hello'}])

    def test_retry_budget_bounds_attempts_and_backoff(self):
        import httpx
        def hang(count, request, clock):
            clock.now += min(request.extensions['timeout']['read'], 550)
            raise httpx.ReadTimeout('simulated', request=request)
        with tempfile.TemporaryDirectory() as tmp:
            run, backend, clock, _, holder, sent, _ = self.build(tmp, hang)
            with self.assertRaises(run.SelfHostedEndpointUnavailable):
                self.complete(run, backend, clock)
            self.assertLessEqual(clock.now, 600)
            self.assertGreaterEqual(len(sent), 2)
            self.assertLessEqual(sent[-1].extensions['timeout']['read'], 600 - 550)
            self.assertIn('Self-hosted endpoint failed', holder['infrastructure_error'])
            self.assertEqual(backend.client.timeout.read, 900)
            # The first attempt keeps the full request timeout; nothing is retried past the budget.
            clock.now = 0
            def slow(count, request, clock):
                clock.now += request.extensions['timeout']['read']
                raise httpx.ReadTimeout('simulated', request=request)
            run, backend, clock, _, holder, sent, _ = self.build(tmp + '/', slow)
            with self.assertRaises(run.SelfHostedEndpointUnavailable):
                self.complete(run, backend, clock)
            self.assertEqual((len(sent), clock.now), (1, 900))

    def test_every_5xx_is_retried_and_exhaustion_is_infrastructure(self):
        import httpx
        from intent_browser.backend import BackendResponseError
        for status in (500, 501, 507, 599, 429):
            with tempfile.TemporaryDirectory() as tmp:
                run, backend, clock, _, holder, sent, _ = self.build(tmp,
                    lambda count, request, clock: httpx.Response(status if count == 1 else 200,
                                                                 json={} if count == 1 else completion()))
                self.assertEqual(self.complete(run, backend, clock).text, 'finished')
                self.assertEqual(len(sent), 2)
                self.assertNotIn('infrastructure_error', holder)
        with tempfile.TemporaryDirectory() as tmp:
            run, backend, clock, _, holder, sent, _ = self.build(tmp,
                lambda count, request, clock: httpx.Response(501, json={}))
            with self.assertRaises(run.SelfHostedEndpointUnavailable):
                self.complete(run, backend, clock)
            self.assertIn('BackendResponseError', holder['infrastructure_error'])
            self.assertLessEqual(clock.now, 600)
        with tempfile.TemporaryDirectory() as tmp:
            run, backend, clock, _, holder, sent, _ = self.build(tmp,
                lambda count, request, clock: httpx.Response(422, json={}))
            with self.assertRaises(BackendResponseError):
                self.complete(run, backend, clock)
            self.assertEqual(len(sent), 1)
            self.assertNotIn('infrastructure_error', holder)

    def test_non_object_json_error_body_is_still_retried(self):
        import httpx
        with tempfile.TemporaryDirectory() as tmp:
            run, backend, clock, records, holder, sent, _ = self.build(tmp,
                lambda count, request, clock: httpx.Response(503, json=['backend unavailable']) if count == 1
                else httpx.Response(200, json=completion()))
            self.assertEqual(self.complete(run, backend, clock).text, 'finished')
            self.assertEqual(len(sent), 2)
            self.assertEqual([r['http_status'] for r in records], [503, 200])
            self.assertEqual(records[1]['usage'], {'prompt_tokens': 3})
        self.assertEqual(run.json_object(httpx.Response(200, json=[1, 2])), {})
        self.assertEqual(run.json_object(httpx.Response(200, content=b'not json')), {})

    def test_probe_authenticates_and_fails_fast_on_rejection(self):
        import httpx
        ok = lambda count, request, clock: httpx.Response(200, json=completion())
        with tempfile.TemporaryDirectory() as tmp:
            run, backend, clock, _, _, sent, probes = self.build(tmp, ok)
            self.complete(run, backend, clock)
            self.assertEqual(probes, [{'Authorization': 'Bearer offline-key'}])
            self.assertEqual(sent[0].headers['authorization'], 'Bearer offline-key')
        for status in (401, 403, 404):
            with tempfile.TemporaryDirectory() as tmp:
                def rejected(count):
                    return httpx.Response(status, text='no', request=httpx.Request('GET', 'http://127.0.0.1:9/v1/models'))
                with self.assertRaisesRegex(ValueError, f'HTTP {status}.*not retried'):
                    self.build(tmp, ok, probe=rejected)
        with tempfile.TemporaryDirectory() as tmp:
            def flaky(count):
                request = httpx.Request('GET', 'http://127.0.0.1:9/v1/models')
                return (httpx.Response(503, request=request) if count == 1 else
                        httpx.Response(200, json={'data': [{'id': 'served'}]}, request=request))
            *_, probes = self.build(tmp, ok, probe=flaky)
            self.assertEqual(len(probes), 2)


class BridgeOutageTests(unittest.TestCase):
    def test_exhausted_bridge_retries_are_infrastructure(self):
        import httpx
        from unittest.mock import Mock
        from intent_browser.backend import BackendResponseError
        from scripts import hindrance_model_run as run
        server = Mock(server_port=9, serve_forever=lambda: None)
        holder, records = {}, []
        with tempfile.TemporaryDirectory() as tmp, \
                patch('experiments.external_agent.backend.ExternalAgentBackend'), \
                patch('experiments.external_agent.server.BridgeServer', return_value=server), \
                patch('experiments.external_agent.episode_admission.EpisodeConcurrency'), \
                patch('experiments.external_agent.subscription_quota.SubscriptionQuotaGuard'), \
                patch('intent_browser.hindrance_context.PreflightInputCounter'), \
                patch('intent_browser.input_budget.QwenInputCounter'):
            options = {'offline': False, 'bridge': 'gpt-test', 'suite_id': 'hindrance/test', 'concurrency': 1,
                       'suite_episodes': 1}
            backend = run.backend_for(options, Path(tmp), records, holder)
            hooks = backend.client.event_hooks
            backend.client.close()
            statuses = []
            def transport(request):
                statuses.append(507)
                return httpx.Response(507, json=['bridge unavailable'])
            backend.client = httpx.Client(transport=httpx.MockTransport(transport), event_hooks=hooks)
            with patch.object(run.time, 'sleep'), self.assertRaises(BackendResponseError):
                backend.complete([{'role': 'user', 'content': 'hello'}])
        self.assertEqual(len(statuses), 6)
        self.assertIn('Codex bridge failed 6 attempts', holder['infrastructure_error'])


def test_native_infrastructure_failure_is_system_failure_for_every_backend(tmp_path):
    from contextlib import ExitStack
    from types import SimpleNamespace
    from unittest.mock import Mock
    from scripts import hindrance_model_run as run, hindrance_suite as build
    for name, backend_options in (('bridge', {'bridge': 'gpt-test'}), ('openrouter', {}),
                                  ('self-hosted', {'openai_base_url': 'http://127.0.0.1:9/v1', 'model': 'served'})):
        directory = tmp_path / name
        trace = directory / 'runs' / 'saved-trace'
        trace.mkdir(parents=True)
        (trace / 'episode.json').write_text(json.dumps({'step_count': 2, 'error': 'browser crashed'}))
        native = {'status': 'inconclusive', 'reasons': ['episode_infrastructure_failure'], 'checks': {}}
        (trace / 'automatic-grade.json').write_text(json.dumps({'raw_grade': {'native_grade': native}}))
        (trace / 'suite-order-grade.json').write_text(json.dumps({'status': 'inconclusive'}))
        class Episode:
            runtime = Mock()
            task = SimpleNamespace(files={}, make_env=Mock())
            profile = object()
            site_discovery = None
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with ExitStack() as stack:
            stack.enter_context(patch.object(build, 'prepare_task',
                return_value=({}, Episode(), Mock(adapter=Mock()), Mock(), {})))
            stack.enter_context(patch.object(run, 'core_profile'))
            stack.enter_context(patch.object(run, 'backend_for', return_value=Mock()))
            stack.enter_context(patch.object(run, 'recording_runner', return_value=lambda *a, **k: (trace, {})))
            stack.enter_context(patch.object(build, 'finish_order'))
            row = run.execute_one({'id': 'fixture', 'mechanism': 'paid_warranty', 'variant': 'trapped',
                                   'recipe_path': 'fixture.json'},
                                  {'offline': False, 'fact_provenance': False, 'max_steps': 2,
                                   'max_input_tokens': 150000, **backend_options}, directory)
        assert row['status'] == 'system_failure', name
        assert row['grade'] == {}
        assert 'episode_infrastructure_failure' in row['infrastructure_error']
        assert (directory / 'infrastructure-failure.json').exists()


def _dummy_episode(entry, options, directory):
    from scripts.hindrance_model_run import save, usage_totals
    directory = Path(directory)
    directory.mkdir()
    started = time.time()
    time.sleep(1.0)
    (directory / 'interval.json').write_text(json.dumps([started, time.time()]))
    save(directory / 'result.json', {**entry, 'status': 'graded', 'grade': {'status': 'pass'},
                                     'usage': usage_totals([], offline=True)})


def _runner(concurrency_file, output, barrier):
    from types import SimpleNamespace
    from scripts import hindrance_model_run as run
    run.run_one = _dummy_episode
    real_sleep = time.sleep
    time.sleep = lambda seconds: real_sleep(min(seconds, 0.05))
    output = Path(output)
    output.mkdir()
    args = SimpleNamespace(concurrency_file=Path(concurrency_file), concurrency=4, offline=True, worker_start='spawn')
    barrier.wait()
    run.run_dynamic_pool(args, [{'id': output.name + '-episode', 'mechanism': 'paid_warranty', 'variant': 'trapped'}],
                         {}, output, [])


def test_shared_concurrency_cap_admits_one_episode_across_runners(tmp_path):
    import multiprocessing
    context = multiprocessing.get_context('spawn')
    concurrency_file = tmp_path / 'concurrency.txt'
    concurrency_file.write_text('1\n')
    barrier = context.Barrier(2)
    runners = [context.Process(target=_runner, args=(str(concurrency_file), str(tmp_path / name), barrier))
               for name in ('runner-a', 'runner-b')]
    for runner in runners:
        runner.start()
    for runner in runners:
        runner.join(60)
    assert [r.exitcode for r in runners] == [0, 0]
    intervals = sorted(json.loads(p.read_text()) for p in tmp_path.glob('runner-*/episode-*/interval.json'))
    assert len(intervals) == 2
    assert intervals[1][0] >= intervals[0][1], f'episodes overlapped: {intervals}'


if __name__ == '__main__':
    unittest.main()
