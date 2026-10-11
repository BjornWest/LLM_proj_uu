"""Native policy controls with synthetic counts; no provider/browser dispatch."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import unittest

from scripts import modal_b06_full_episode as caller
from scripts.remote_counter_bridge import Bridge, serving_limits, canonical
import tests.test_remote_counter_bridge as legacy


class NativeBridgeTests(unittest.TestCase):
    wire_proof = legacy.Controls.wire_proof

    def setUp(self):
        legacy.Controls.setUp(self)
        self.live.update(server_context=262144, isl=262143, input_admission={
            'scope': 'native-context-output-headroom', 'minimum_output_tokens': 1})
        self.server.update(server_context=262144, isl=262143)
        self.raw['max_model_len'] = 262144
        self.tokens = 200000
        for name in ('qualification_receipt', 'complete_wire_count_parity_proof'):
            data = json.loads(Path(self.live[name]['path']).read_text())
            if name == 'qualification_receipt':
                data.update(server_context=262144, isl=262143)
            else:
                for row in data['parity_probes']:
                    row['server']['max_model_len'] = 262144
                    if row['probe'] == '100000-input-boundary':
                        row.update(probe='native-context-input-boundary', input_tokens=262143)
                        row['server']['count'] = 262143
                        row['generation']['prompt_tokens'] = 262143
            self.repin(name, data)
        self.repin('deployment_receipt', {'qualification': self.server,
            'serving_session_id': 'unit-server', 'deadline': 1500})
        self.b = self.build()
        self.request['max_tokens'] = 62144

    def repin(self, name, data):
        path = Path(self.live[name]['path']); path.write_bytes(canonical(data))
        self.live[name]['sha256'] = sha256(path.read_bytes()).hexdigest()

    def build(self):
        return Bridge(self.live, 400, exchange=self.exchange, mono=lambda: self.m,
            utc=lambda: self.u, environ={'LOCAL_TEST_RELAY_TOKEN': 'secret'})

    def native_caller_inputs(self):
        import ast, time
        started = time.time() - 1
        platform = dict(mode='episode-owned', expiry_kind='provider-platform-maximum',
            started_at_utc=started, expires_at_utc=started + 86400, provider_max_seconds=86400)
        rental = dict(started_at_utc=started, expires_at_utc=started + 1800, agreed_seconds=1800)
        self.live.update(platform_lifetime=platform, rental_lifetime=rental,
            gpu_deadline_utc=platform['expires_at_utc'])
        self.server.update(deadline=platform['expires_at_utc'], parser_patch_sha256='3' * 64)
        def pinned(name, value):
            path = Path(self.tmp.name) / name; path.write_bytes(canonical(value))
            return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}
        source = Path(caller.__file__).with_name('remote_counter_bridge.py')
        source_pin = {'path': str(source), 'sha256': sha256(source.read_bytes()).hexdigest()}
        relay = Path(self.live['relay_source']['path']); code = relay.read_text()
        fn = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name == 'tokenize_payload')
        projection = dict(counter_source_sha256=source_pin['sha256'],
            counter_wire_function_sha256='f21b9f8becf3a8713ad3bcf59d610cc59f97406a5d17b6396013191dd5ad2de3',
            tokenize_projection_source_sha256=self.live['relay_source']['sha256'],
            relay_source_sha256=self.live['relay_source']['sha256'],
            tokenize_projection_function_sha256=sha256(ast.get_source_segment(code, fn).encode()).hexdigest())
        digest = sha256(canonical(projection)).hexdigest()
        proof = json.loads(Path(self.live['complete_wire_count_parity_proof']['path']).read_text())
        proof.update(parser_patch_sha256='3' * 64, runtime_projection=projection,
            counter_projection_sha256=digest,
            counter_projection_digest_format='sha256-compact-sorted-utf8-json-of-runtime-projection-v1')
        self.repin('complete_wire_count_parity_proof', proof)
        self.server['counter_projection_sha256'] = digest
        self.repin('deployment_receipt', dict(qualification=self.server, platform_lifetime=platform,
            rental_lifetime=rental, serving_session_id='unit-server', deadline=platform['expires_at_utc']))
        binding = dict(original_source_sha256='1' * 64, patched_source_sha256='2' * 64, patch_sha256='3' * 64)
        regression = pinned('parser-regression.json', dict(passed=True,
            patched_source_sha256='2' * 64, serving_session_id='unit-server'))
        self.live['parser_patch_receipt'] = pinned('parser-receipt.json', dict(**binding,
            passed=True, serving_session_id='unit-server', regression_receipt=regression))
        spec = dict(schema='modal-native-context-B06-v1', case='B06', rental_seconds=1800,
            context_policy=dict(server_context=262144, minimum_output_tokens=1),
            watchdogs=dict(startup_seconds=180, request_seconds=600),
            parser_patch_binding=binding, ordered_counter_source=source_pin)
        return spec

    def test_native_preflight_build_and_actual_counter_entrypoints(self):
        from unittest.mock import patch
        spec = self.native_caller_inputs()
        watchdogs = caller.preflight(spec, self.live)
        self.assertLess(watchdogs.remaining(), 1800)
        self.assertEqual(caller.verify_projection(self.live, spec['ordered_counter_source']), self.server['counter_projection_sha256'])
        with patch.dict(os.environ, LOCAL_TEST_RELAY_TOKEN='secret'):
            runtime = caller.build_runtime(spec, self.live, watchdogs)
        counter = runtime['complete_request_counter'].__self__
        counter.exchange = self.exchange
        self.assertEqual(runtime['runner_input_counter']([], [])['input_tokens'], 200000)
        self.assertEqual(runtime['readiness']()['server_context'], 262144)
        self.assertLessEqual(counter.deadline, watchdogs.deadline_monotonic)

    def test_unreviewed_counter_is_rejected_before_execution(self):
        from types import SimpleNamespace
        spec = self.native_caller_inputs()
        path = Path(self.tmp.name) / 'unreviewed.py'
        path.write_text("raise AssertionError('Unreviewed code executed')\n")
        spec['ordered_counter_source'] = dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError, 'Released reviewed ordered counter'):
            caller.build_runtime(spec, self.live, SimpleNamespace(deadline_monotonic=100))

    def test_native_rental_must_match_actual_deployment_receipt(self):
        spec = self.native_caller_inputs()
        self.live['rental_lifetime'] = {**self.live['rental_lifetime'],
            'expires_at_utc': self.live['rental_lifetime']['started_at_utc'] + 600,
            'agreed_seconds': 600}
        spec['rental_seconds'] = 600
        with self.assertRaisesRegex(ValueError, 'deployment rental'):
            caller.preflight(spec, self.live)

    def test_above_old_input_cap_is_counted_without_clipping(self):
        result = self.b.count(self.request)
        self.assertEqual(result['input_tokens'], 200000)
        self.assertEqual(result['count_receipt']['max_model_len'], 262144)
        self.assertEqual(self.b.readiness()['isl'], 262143)

    def test_full_native_input_can_be_measured_for_skipped_dispatch(self):
        self.tokens = 262144
        self.assertEqual(self.b.runner_count([], [])['input_tokens'], 262144)
        self.assertEqual(serving_limits(self.live)[1], 262143)

    def test_historical_boundary_proof_does_not_qualify_native_context(self):
        data = json.loads(Path(self.live['complete_wire_count_parity_proof']['path']).read_text())
        data['parity_probes'][-1]['probe'] = '100000-input-boundary'
        self.repin('complete_wire_count_parity_proof', data)
        with self.assertRaisesRegex(ValueError, 'Missing qualified'):
            self.build()

    def test_stale_tokenize_context_is_rejected(self):
        self.raw['max_model_len'] = 131072
        with self.assertRaisesRegex(ValueError, 'count/context'):
            self.b.count(self.request)

    def test_independent_input_cap_cannot_be_reintroduced(self):
        self.live['isl'] = 100000
        with self.assertRaises(ValueError):
            self.build()

    def test_rental_deadline_bounds_counter_even_with_later_platform_expiry(self):
        self.b = Bridge(self.live, 150, exchange=self.exchange,
            mono=lambda: self.m, utc=lambda: self.u,
            environ={'LOCAL_TEST_RELAY_TOKEN': 'secret'})
        self.m = 150
        with self.assertRaises(TimeoutError):
            self.b.count(self.request)


class NativePolicyTests(unittest.TestCase):
    def setUp(self):
        self.spec = {'schema': 'modal-native-context-B06-v1',
            'context_policy': {'server_context': 262144, 'minimum_output_tokens': 1},
            'rental_seconds': 1800}
        self.live = {'server_context': 262144, 'isl': 262143,
            'input_admission': {'scope': 'native-context-output-headroom', 'minimum_output_tokens': 1},
            'platform_lifetime': {'mode': 'episode-owned',
                'expiry_kind': 'provider-platform-maximum',
                'started_at_utc': 1000, 'expires_at_utc': 87400,
                'provider_max_seconds': 86400},
            'gpu_deadline_utc': 87400,
            'rental_lifetime': {'started_at_utc': 1000, 'expires_at_utc': 2800,
                                'agreed_seconds': 1800}}

    def test_native_context_derives_only_physical_input_admission(self):
        self.assertEqual(caller.context_limits(self.spec, self.live), (262144, 262143))

    def test_missing_or_artificial_native_limits_fail_closed(self):
        for value in [100000, None, True, 262144]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                caller.context_limits(self.spec, {**self.live, 'isl': value})
        for value in [True, 0, 32]:
            spec = deepcopy(self.spec); spec['context_policy']['minimum_output_tokens'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                caller.context_limits(spec, self.live)

    def test_float_context_policy_rejected(self):
        self.spec['context_policy']['server_context'] = 262144.0
        with self.assertRaises(ValueError): caller.context_limits(self.spec, self.live)

    def test_rental_window_cannot_restart_after_allocation(self):
        self.live['rental_lifetime'].update(started_at_utc=50000, expires_at_utc=51800)
        with self.assertRaises(ValueError): caller.agreed_rental_lifetime(self.spec, self.live)

    def test_rental_expiry_is_not_reported_as_an_operation_stall(self):
        import time
        utc = time.time()
        self.live['platform_lifetime'].update(started_at_utc=utc, expires_at_utc=utc + 86400)
        self.live['gpu_deadline_utc'] = utc + 86400
        self.spec['rental_seconds'] = 0.02
        self.live['rental_lifetime'] = dict(started_at_utc=utc, expires_at_utc=utc + .02, agreed_seconds=.02)
        rental = caller.agreed_rental_lifetime(self.spec, self.live)
        watchdog = caller.Watchdogs(self.live, rental_lifetime=rental)
        with self.assertRaisesRegex(TimeoutError, 'Agreed rental lifetime expired'):
            with watchdog.operation('healthy request', 1): time.sleep(.1)

    def test_agreed_rental_expiry_and_startup_request_watchdogs_are_retained(self):
        rental = caller.agreed_rental_lifetime(self.spec, self.live)
        clocks = {'utc': 1001, 'mono': 50}
        watchdog = caller.Watchdogs(self.live, rental_lifetime=rental,
            utc=lambda: clocks['utc'], mono=lambda: clocks['mono'])
        self.assertEqual(watchdog.remaining(), 1799)
        self.assertEqual(watchdog.timeout(), 600)
        clocks['utc'] = 2800; clocks['mono'] = 1849
        with self.assertRaises(TimeoutError): watchdog.remaining()

    def test_unagreed_nonfinite_missing_or_extended_rental_is_rejected(self):
        for seconds in [None, True, 0, -1, float('inf'), 3600]:
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                caller.agreed_rental_lifetime({**self.spec, 'rental_seconds': seconds}, self.live)
        live = deepcopy(self.live); live['rental_lifetime']['expires_at_utc'] = 87401
        with self.assertRaises(ValueError): caller.agreed_rental_lifetime(self.spec, live)

    def test_historical_schema_keeps_historical_limits_and_lifetime(self):
        spec = {'schema': 'modal-full-B06-v1'}
        self.assertEqual(caller.context_limits(spec, {'server_context': 131072, 'isl': 100000}), (131072, 100000))
        self.assertIsNone(caller.agreed_rental_lifetime(spec, self.live))
        with self.assertRaises(ValueError): caller.context_limits(spec, self.live)


class FrozenFactoryNativeHeadroomTests(unittest.TestCase):
    def setUp(self):
        source = os.environ.get('NATIVE_CONTEXT_FACTORY_SOURCE')
        if not source:
            self.skipTest('Pinned factory fixture absent; set NATIVE_CONTEXT_FACTORY_SOURCE')
        path = Path(source)
        expected = 'd68a69ef32cefc65e2e40caaa6a23cbeb2a1ddbf7781d20d0b26f9ac230943fc'
        self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected)
        self.factories = runpy.run_path(str(path))['PrivateFactories']
        self.identity = dict(model='Qwen/Qwen3.8-27B-FP8', serving_revision='fixture',
            tokenizer_sha256='fixture', template_sha256='fixture',
            image_processor_sha256='fixture', tool_parser='fixture',
            source_commit='95e9ac988ea515f7194cbdc82ae327e248fc94fa')

    def test_actual_factory_uses_remaining_context_for_policy_and_extraction(self):
        from types import SimpleNamespace
        identity = self.identity; dispatched = []; measured = []; tokens = [200000]
        class Transport:
            def __init__(self, base_url, model, api_key, **options):
                self.model = model; self.max_tokens = options['max_tokens']; self.request_options = options['request_options']
            def complete(self, messages):
                request = dict(model=self.model, messages=messages, temperature=0,
                    max_tokens=self.max_tokens, stream=False, **self.request_options)
                dispatched.append(request)
                return SimpleNamespace(request=request, raw={})
            def close(self): pass
        def count(request):
            measured.append(deepcopy(request))
            return {'input_tokens': tokens[0], 'identity': identity, 'exact_complete_request': True}
        ready = {'ready': True, 'identity': identity, 'server_context': 262144,
            'isl': 262143, 'vision': True, 'native_tools': True, 'exact_complete_request_counter': True}
        factory = self.factories(backend_class=Transport, base_url='http://127.0.0.1:19123/v1',
            model=identity['model'], api_key=None, server_context=262144, isl=262143,
            complete_request_counter=count, expected_identity=identity, readiness=lambda: ready,
            extraction_before_dispatch=lambda: None, meter=lambda event: None)
        with factory.policy_session(before_dispatch=lambda: None) as backend:
            backend.complete([])
            self.assertEqual(dispatched[-1]['max_tokens'], 62144)
            tokens[0] = 262143; backend.complete([])
            self.assertEqual(dispatched[-1]['max_tokens'], 1)
            tokens[0] = 262144
            with self.assertRaises(ValueError): backend.complete([])
            self.assertEqual(len(dispatched), 2)
        tokens[0] = 250000
        extractor = factory.extraction_backend_factory('synthetic-output')
        extractor.complete([]); extractor.close()
        self.assertEqual(dispatched[-1]['max_tokens'], 12144)
        for request in dispatched:
            # The exact final request was counted before this injected dispatch.
            self.assertIn(request, measured)


if __name__ == '__main__': unittest.main()
