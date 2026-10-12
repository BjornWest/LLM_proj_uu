"""Local fake-evidence controls; none of these fixtures qualify a GPU stack."""
from copy import deepcopy
from hashlib import sha256
from http.server import HTTPServer, BaseHTTPRequestHandler
import importlib.util
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import urlopen, Request
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('qualification', ROOT / 'training/scripts/qwen_suite_qualification.py')
Q = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(Q)
RUNTIME = Path(os.environ.get('QWEN_TEST_RUNTIME_SOURCE', ROOT / 'scripts/qwen_suite_runtime.py'))
RUNTIME_SHA = os.environ.get('QWEN_TEST_RUNTIME_SHA256', '4491d896a025b728ea1ab6eca4640b2efc030cc7a33769d4d538f5056c32c7dd')


class RawHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.server.calls.append(('GET', self.path))
        time.sleep(self.server.health_delay if self.path == '/health' else 0)
        if self.path == '/v1/models':
            answer = Q.encoded({'data': self.server.models})
            self.send_response(200); self.send_header('Content-Length', str(len(answer)))
            self.end_headers(); self.wfile.write(answer); return
        self.send_response(self.server.health_status)
        self.send_header('Content-Length', '0'); self.end_headers()

    def do_POST(self):
        self.server.calls.append(('POST', self.path))
        data = self.rfile.read(int(self.headers['Content-Length']))
        self.server.payloads.append(json.loads(data))
        answer = Q.encoded({'count': 3, 'tokens': [1, 2, 3], 'max_model_len': 262144})
        self.send_response(200); self.send_header('Content-Length', str(len(answer)))
        self.end_headers(); self.wfile.write(answer)


@unittest.skipUnless(RUNTIME.is_file(), 'Exact Evaluation runtime source required; see QWEN_TEST_RUNTIME_SOURCE')
class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = HTTPServer(('127.0.0.1', 0), RawHandler)
        self.raw.calls = []; self.raw.payloads = []; self.raw.health_status = 200
        self.raw.health_delay = 0
        thread = threading.Thread(target=self.raw.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (self.raw.shutdown(), self.raw.server_close(), thread.join(3)))
        self.runtime_path = self.root / 'qwen_suite_runtime.py'
        self.assertEqual(sha256(RUNTIME.read_bytes()).hexdigest(), RUNTIME_SHA,
                         'External caller test source must match the declared release SHA')
        self.runtime_path.write_bytes(RUNTIME.read_bytes())
        self.runtime = runpy.run_path(str(self.runtime_path))
        self.now = time.time(); self.deadline = self.now + 300
        self.identity = dict(model=self.runtime['MODEL'], serving_revision=self.runtime['REVISION'],
                             tokenizer_sha256='a'*64, template_sha256='b'*64,
                             image_processor_sha256='c'*64, tool_parser='qwen3_coder')
        self.raw.models = [{'id': self.identity['model'], 'max_model_len': 262144}]
        image = {'limit_mm_per_prompt': {'image': 1562, 'video': 0},
                 'mm_processor_kwargs': {'min_pixels': 65536, 'max_pixels': 16777216,
                     'patch_size': 16, 'merge_size': 2, 'temporal_patch_size': 2}}
        self.compatibility = dict(runtime=dict(vllm_version='0.28.0', vllm_source_patch_sha256='d'*64,
            pytorch_version='2.13.0+cu130', cuda_runtime_version='13.0', runtime_lock_sha256='e'*64,
            kernel_versions={'tokenizers': '0.23.2'}, counter_projection_sha256=self.runtime['projection_sha256']()),
            hardware={'gpu_architecture': 'sm120'}, model={'repository': self.identity['model'], 'revision': self.identity['serving_revision']},
            assets=dict(tokenizer_sha256='a'*64, template_sha256='b'*64, processor_sha256='c'*64),
            serving=dict(context_tokens=262144, image_limits=image, weight_quantization='fp8', kv_cache_dtype='fp8_e4m3',
                kv_scales_sha256=None, thinking=True, preserve_thinking=True, tool_parser='qwen3_coder', reasoning_parser='qwen3',
                mtp_mode={'method': 'mtp', 'num_speculative_tokens': 3}, lora_mode=None,
                attention_backend={k: 'test-resolved' for k in ('prefill', 'decode', 'linear_attention', 'weight_compute')}))
        self.fingerprint = self.runtime['digest'](self.compatibility, sorted_keys=True)
        port = self.raw.server_port
        self.snapshot = self.root / 'hub/models--Qwen--Qwen3.8-27B-FP8/snapshots' / self.identity['serving_revision']
        self.snapshot.mkdir(parents=True)
        (self.snapshot / 'config.json').write_text('{"test_only":true}')
        argv = Q.serving_command(self.snapshot, port=port)
        self.launch = dict(pid=os.getpid(), attempt_id='test-only-current-session', profile=Q.PROFILE,
            status='source_checks_passed_before_exec',
            launch_settings={'port': str(port), 'max_num_seqs': '8', 'gpu_memory_utilization': '0.9'},
            command=argv, vllm_version='0.28.0',
            checkpoint_config_sha256=sha256((self.snapshot / 'config.json').read_bytes()).hexdigest())
        launch_pin = self.write('launch.json', self.launch)
        # Deliberately fake proof files: confined to this temporary CPU test.
        proofs = {kind: self.write(kind + '-proof.json', {'passed': True, 'synthetic': False,
            'proof_kind': kind, 'fingerprint': self.fingerprint, 'scope': 'CPU test fixture, not actual qualification'})
            for kind in ('qualification', 'deployment', 'processor')}
        self.capability = dict(schema='serving-stack-capability-v1', status='passed', synthetic=False,
            fingerprint=self.fingerprint, compatibility=self.compatibility, proofs=proofs,
            checks={k: True for k in self.runtime['CHECKS']})
        self.deployment = dict(passed=True, synthetic=False, serving_session_id=self.launch['attempt_id'], identity=self.identity,
            deadline_utc=self.deadline, allocation_utc=self.now, approved_rental_seconds=300,
            run_id='00000000-0000-4000-8000-000000000001', instance_id='00000000-0000-4000-8000-000000000002',
            server_context=262144, vision_configured=True, native_tools_configured=True, exact_request_counter=True,
            observed_compatibility=self.compatibility, serving_process=Q.process_identity(os.getpid()), launch_receipt=launch_pin)
        self.adapter = HTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
        self.addCleanup(self.adapter.server_close)
        self.binding = dict(schema='qwen-fresh-instance-binding-v1', runtime=Q.pin(self.runtime_path),
            launch=launch_pin, deployment=self.write('deployment.json', self.deployment),
            capability=self.write('capability.json', self.capability), raw_base_url=f'http://127.0.0.1:{port}',
            qualification_base_url=f'http://127.0.0.1:{self.adapter.server_port}', dispatch_approval=None)

    def write(self, name, value):
        path = self.root / name; path.write_bytes(Q.encoded(value)); return Q.pin(path)

    def evidence(self, **options):
        return Q.Evidence(self.write('binding.json', self.binding), **options)

    def run_adapter(self, evidence):
        self.adapter.RequestHandlerClass = Q.handler(evidence)
        thread = threading.Thread(target=self.adapter.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (self.adapter.shutdown(), thread.join(3)))

    def test_actual_consumer_accepts_split_health_and_adapter_without_generation(self):
        e = self.evidence(); live_pin = e.publish(self.root / 'fresh'); self.run_adapter(e)
        consumer = self.runtime['ServingAdmission'](live_pin)
        result = consumer.count(dict(model=self.identity['model'], messages=[{'role': 'user', 'content': 'hello'}], temperature=0, max_tokens=16384, stream=False))
        self.assertEqual(result['input_tokens'], 3)
        self.assertEqual(self.raw.payloads, [{'model': self.identity['model'], 'messages': [{'role': 'user', 'content': 'hello'}]}])
        self.assertEqual([x for x in self.raw.calls if x[0] == 'POST'], [('POST', '/tokenize')])
        live = json.loads(Q.read_pin(live_pin)); self.assertFalse(live['dispatch_authorized'])
        instance = json.loads(Q.read_pin(live['instance_readiness_receipt']))
        self.assertEqual(instance['diagnostic_generation_requests'], 0)
        self.assertEqual(instance['gpu_deadline_utc'], self.deadline)
        self.assertEqual((self.root / 'fresh').stat().st_mode & 0o777, 0o700)
        self.assertEqual(Path(live_pin['path']).stat().st_mode & 0o777, 0o600)

    def test_approval_is_separate_finite_input(self):
        approval = dict(case_ids=['qwen-B02'], allocation_authorized=True, dispatch_authorized=True, approved_rental_seconds=300)
        approval.update({k: self.deployment[k] for k in ('run_id', 'instance_id', 'allocation_utc', 'deadline_utc')})
        self.binding['dispatch_approval'] = self.write('approval.json', approval)
        self.assertTrue(self.evidence().dispatch_authorized)
        approval['approved_rental_seconds'] = 301
        self.binding['dispatch_approval'] = self.write('approval.json', approval)
        with self.assertRaises(ValueError): self.evidence()

    def test_each_capability_gate_required(self):
        for key in self.runtime['CHECKS']:
            with self.subTest(key=key):
                changed = deepcopy(self.capability); del changed['checks'][key]
                self.binding['capability'] = self.write('capability.json', changed)
                with self.assertRaises(ValueError): self.evidence()

    def test_synthetic_capability_deployment_and_proof_refused(self):
        for target in ('capability', 'deployment', 'proof'):
            with self.subTest(target=target):
                self.binding['capability'] = self.write('capability.json', self.capability)
                self.binding['deployment'] = self.write('deployment.json', self.deployment)
                if target == 'proof':
                    cap = deepcopy(self.capability)
                    proof = json.loads(Q.read_pin(cap['proofs']['qualification']))
                    proof['synthetic'] = True
                    cap['proofs']['qualification'] = self.write('repinned-synthetic-proof.json', proof)
                    self.binding['capability'] = self.write('capability.json', cap)
                else:
                    changed = deepcopy(getattr(self, target)); changed['synthetic'] = True
                    self.binding[target] = self.write(target + '.json', changed)
                with self.assertRaises(ValueError): self.evidence()

    def test_mutated_evidence_makes_existing_HTTP_adapter_unavailable(self):
        e = self.evidence(); e.publish(self.root / 'fresh'); self.run_adapter(e)
        Path(self.binding['launch']['path']).write_text('{}')
        with self.assertRaises(HTTPError) as caught: urlopen(e.qualification + '/qualification', timeout=3)
        self.assertEqual(caught.exception.code, 503)
        value = json.loads(caught.exception.read()); self.assertEqual(value['status'], 'unavailable')
        self.assertNotIn('identity', value)

    def test_monotonic_deadline_survives_backward_wall_clock(self):
        clock = {'wall': self.now, 'mono': 100.}
        e = self.evidence(clock=lambda: clock['wall'], monotonic=lambda: clock['mono'])
        clock.update(wall=self.now - 86400, mono=400.)
        with self.assertRaises(TimeoutError): e.response()

    def test_changed_birth_identity_cannot_reuse_live_port(self):
        changed = deepcopy(self.deployment); changed['serving_process']['start_ticks'] += 1
        self.binding['deployment'] = self.write('deployment.json', changed)
        with self.assertRaises(ValueError): self.evidence()

    def test_foreign_listener_not_proved_by_live_unrelated_PID(self):
        child = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(20)'])
        self.addCleanup(lambda: (child.terminate(), child.wait(3)))
        changed = deepcopy(self.launch); changed['pid'] = child.pid
        self.binding['launch'] = self.write('launch.json', changed)
        changed = deepcopy(self.deployment); changed['serving_process'] = Q.process_identity(child.pid)
        changed['launch_receipt'] = self.binding['launch']
        self.binding['deployment'] = self.write('deployment.json', changed)
        with self.assertRaisesRegex(ValueError, 'port is not owned'): self.evidence()

    def test_dead_health_and_expired_rental_refused(self):
        self.raw.health_status = 503
        with self.assertRaises(ValueError): self.evidence()
        self.raw.health_status = 200
        with self.assertRaises(TimeoutError): self.evidence(clock=lambda: self.deadline)

    def test_no_clobber_publication_and_no_mutation_routes(self):
        e = self.evidence(); e.publish(self.root / 'fresh')
        with self.assertRaises(FileExistsError): e.publish(self.root / 'fresh')
        self.run_adapter(e)
        for request in (e.qualification + '/health', Request(e.qualification + '/qualification', data=b'{}')):
            with self.assertRaises(HTTPError) as caught: urlopen(request, timeout=3)
            self.assertIn(caught.exception.code, (404, 501))

    def test_supported_profile_refuses_cache_and_speculation_drift(self):
        for flag, value in (('--block-size', '16'), ('--max-model-len', '131072'),
                            ('--speculative-config', '{"method":"mtp","num_speculative_tokens":1}'),
                            ('--kv-transfer-config', '{}')):
            with self.subTest(flag=flag):
                changed = deepcopy(self.launch); changed['command'][changed['command'].index(flag)+1] = value
                self.binding['launch'] = self.write('launch.json', changed)
                dep = deepcopy(self.deployment); dep['launch_receipt'] = self.binding['launch']
                self.binding['deployment'] = self.write('deployment.json', dep)
                with self.assertRaises(ValueError): self.evidence()

    def test_schema_counter_drift_refused_by_exact_pinned_consumer(self):
        changed = deepcopy(self.compatibility); changed['runtime']['counter_projection_sha256'] = 'f'*64
        cap = deepcopy(self.capability); cap['compatibility'] = changed; cap['fingerprint'] = self.runtime['digest'](changed, sorted_keys=True)
        dep = deepcopy(self.deployment); dep['observed_compatibility'] = changed
        self.binding['capability'] = self.write('capability.json', cap)
        self.binding['deployment'] = self.write('deployment.json', dep)
        with self.assertRaisesRegex(ValueError, 'Counter projection'): self.evidence().publish(self.root / 'fresh')

    def test_exact_constructor_rejects_alternate_flags_and_wrong_model(self):
        extras = [['--max-model-len=131072'], ['--max-model', '131072'],
                  ['--speculative-config={"method":"mtp","num_speculative_tokens":1}'],
                  ['--kv-transfer-config={}'], ['--chat-template', '/tmp/other.jinja'],
                  ['--config', '/tmp/override.yml'], ['--no-enable-prefix-caching'],
                  ['--lora-modules', 'a=/b'], ['--served-model-name', 'other'], ['--revision', 'deadbeef']]
        for extra in extras:
            with self.subTest(extra=extra):
                changed = deepcopy(self.launch); changed['command'] += extra
                with self.assertRaises(ValueError): Q.supported_profile(changed, self.compatibility)
        other = self.root / 'other-model'; other.mkdir()
        changed = deepcopy(self.launch); changed['command'][5] = str(other)
        with self.assertRaises(ValueError): Q.supported_profile(changed, self.compatibility)

    def test_proofs_are_typed_nonsynthetic_and_bind_capability_fingerprint(self):
        for kind in self.capability['proofs']:
            for field, value in [('synthetic', None), ('passed', False), ('proof_kind', 'wrong'), ('fingerprint', 'f'*64)]:
                with self.subTest(kind=kind, field=field):
                    cap = deepcopy(self.capability); proof = json.loads(Q.read_pin(cap['proofs'][kind]))
                    proof[field] = value; cap['proofs'][kind] = self.write('changed-proof.json', proof)
                    self.binding['capability'] = self.write('capability.json', cap)
                    with self.assertRaises(ValueError): self.evidence()

    def test_separate_approval_is_bound_and_published_for_audit(self):
        approval = dict(case_ids=['qwen-B02'], allocation_authorized=True, dispatch_authorized=True, approved_rental_seconds=300)
        approval.update({k: self.deployment[k] for k in ('run_id', 'instance_id', 'allocation_utc', 'deadline_utc')})
        for key in ['allocation_authorized', 'dispatch_authorized', 'run_id', 'instance_id', 'allocation_utc', 'deadline_utc', 'case_ids']:
            with self.subTest(key=key):
                wrong = deepcopy(approval); del wrong[key]
                self.binding['dispatch_approval'] = self.write('approval.json', wrong)
                with self.assertRaises(ValueError): self.evidence()
        self.binding['dispatch_approval'] = self.write('approval.json', approval)
        e = self.evidence(); live = json.loads(Q.read_pin(e.publish(self.root / 'fresh')))
        self.assertEqual(live['dispatch_approval_receipt'], self.binding['dispatch_approval'])
        self.assertEqual(live['case_ids'], ['qwen-B02'])

    def test_measured_flags_model_context_and_vision_required(self):
        for field in ['server_context', 'vision_configured', 'native_tools_configured', 'exact_request_counter', 'passed']:
            with self.subTest(field=field):
                dep = deepcopy(self.deployment); del dep[field]
                self.binding['deployment'] = self.write('deployment.json', dep)
                with self.assertRaises((ValueError, KeyError)): self.evidence()
        self.binding['deployment'] = self.write('deployment.json', self.deployment)
        self.raw.models[0]['max_model_len'] = 131072
        with self.assertRaises(ValueError): self.evidence()
        self.raw.models[0]['max_model_len'] = 262144
        self.raw.models[0]['id'] = 'other-model'
        with self.assertRaises(ValueError): self.evidence()
        changed = deepcopy(self.launch)
        changed['command'][changed['command'].index('--limit-mm-per-prompt')+1] = '{"image":0,"video":0}'
        comp = deepcopy(self.compatibility); comp['serving']['image_limits']['limit_mm_per_prompt'] = {'image': 0, 'video': 0}
        with self.assertRaises(ValueError): Q.supported_profile(changed, comp)

    def test_birth_check_repeated_after_health_and_wall_expiry_is_independent(self):
        e = self.evidence()
        calls = []
        def probe(owner, port):
            calls.append(1)
            if len(calls) == 2: raise ValueError('Process replaced during health')
        e.probe = probe
        with self.assertRaisesRegex(ValueError, 'replaced'): e.check()
        e = self.evidence(check_health=lambda *a, **k: True,
                          check_models=lambda *a, **k: {'data': self.raw.models})
        e.clock = lambda: self.deadline
        with self.assertRaises(TimeoutError): e.check()

    def test_slow_client_does_not_block_second_request_and_has_absolute_bound(self):
        e = self.evidence(); e.mono_end = e.monotonic() + 1.5
        self.adapter.server_close()
        server = Q.QualificationServer(e)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(3)))
        client = socket.create_connection(('127.0.0.1', e.qualification_port), timeout=2)
        self.addCleanup(client.close); client.sendall(b'GET ')
        stopped = threading.Event()
        def drip():
            while not stopped.wait(.1):
                try: client.sendall(b'x')
                except OSError: return
        sender = threading.Thread(target=drip, daemon=True); sender.start()
        self.addCleanup(lambda: (stopped.set(), sender.join(1)))
        with urlopen(e.qualification + '/qualification', timeout=1) as response:
            self.assertEqual(json.loads(response.read())['status'], 'ready')
        client.settimeout(2)
        self.assertEqual(client.recv(1), b'')

    def test_CLI_signal_during_startup_never_publishes_listening(self):
        self.adapter.server_close()  # Child must have a usable port; not EADDRINUSE.
        self.raw.health_delay = .6
        binding = self.write('binding.json', self.binding); output = self.root / 'CLI-fresh'
        child = subprocess.Popen([sys.executable, '-I', '-B', str(ROOT / 'training/scripts/qwen_suite_qualification.py'),
            '--binding', binding['path'], '--binding-sha256', binding['sha256'], '--output', str(output)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        end = time.monotonic() + 3
        while not self.raw.calls and child.poll() is None and time.monotonic() < end: time.sleep(.01)
        self.assertTrue(self.raw.calls)
        child.terminate(); stdout, stderr = child.communicate(timeout=3)
        self.assertNotEqual(child.returncode, 0)
        self.assertFalse((output / 'adapter-ready.json').exists())
        self.assertNotIn(b'"live":', stdout)

    def test_failed_second_CLI_cannot_write_stop_into_live_adapter_directory(self):
        self.adapter.server_close()
        binding = self.write('binding.json', self.binding); output = self.root / 'CLI-fresh'
        argv = [sys.executable, '-I', '-B', str(ROOT / 'training/scripts/qwen_suite_qualification.py'),
                '--binding', binding['path'], '--binding-sha256', binding['sha256'], '--output', str(output)]
        first = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: first.kill() if first.poll() is None else None)
        end = time.monotonic() + 4
        while not (output / 'adapter-ready.json').is_file() and first.poll() is None and time.monotonic() < end: time.sleep(.01)
        self.assertTrue((output / 'adapter-ready.json').is_file())
        with urlopen(self.binding['qualification_base_url'] + '/qualification', timeout=2) as response:
            self.assertEqual(json.loads(response.read())['status'], 'ready')
        rejected = subprocess.run(argv, capture_output=True, timeout=4)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertFalse((output / 'adapter-stopped.json').exists())
        first.terminate(); stdout, stderr = first.communicate(timeout=3)
        self.assertEqual(first.returncode, 0, stderr.decode())
        stopped = json.loads((output / 'adapter-stopped.json').read_bytes())
        self.assertEqual(stopped['process']['pid'], first.pid)
        self.assertTrue(stopped['startup_completed'])

    def test_preexisting_abandoned_directory_is_not_mutated_by_failed_startup(self):
        output = self.root / 'abandoned'; output.mkdir(); (output / 'original.json').write_text('{}')
        self.adapter.server_close()
        binding = self.write('binding.json', self.binding)
        rejected = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'training/scripts/qwen_suite_qualification.py'),
            '--binding', binding['path'], '--binding-sha256', binding['sha256'], '--output', str(output)], capture_output=True, timeout=4)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual([x.name for x in output.iterdir()], ['original.json'])


class PinTests(unittest.TestCase):
    def test_changed_symlink_and_oversized_inputs_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Path(folder) / 'evidence'; f.write_text('{}'); row = Q.pin(f)
            f.write_text('{"changed":true}')
            with self.assertRaises(ValueError): Q.read_pin(row)
            link = Path(folder) / 'link'; link.symlink_to(f)
            with self.assertRaises(ValueError): Q.read_pin(Q.pin(link))
            f.write_bytes(b' '*(Q.MAX_EVIDENCE + 1))
            with self.assertRaises(ValueError): Q.read_pin(Q.pin(f))


if __name__ == '__main__':
    unittest.main()
