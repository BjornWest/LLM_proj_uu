#!/usr/bin/env python3
"""Read-only fresh-instance adapter for a previously qualified serving stack.

This does not qualify a new stack, allocate, download, or generate tokens. A
reviewed worker must supply measured deployment/launch evidence and an actual
passed capability. Case/episode approval remains a separate caller requirement.
"""
import argparse
from copy import deepcopy
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))
from serve_qwen_suite import command as serving_command

MAX_EVIDENCE = 4 << 20
PROFILE = 'qwen38-native-262144-fp8-mtp3-cpu20g-v1'
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':'), sort_keys=True).encode()


def pin(path):
    path = Path(path).absolute()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def read_pin(row):
    if not isinstance(row, dict) or set(row) != {'path', 'sha256'}:
        raise ValueError('Exact path/SHA256 pin required')
    path = Path(row['path'])
    digest = row['sha256']
    if (not path.is_absolute() or path.is_symlink() or not isinstance(digest, str)
            or len(digest) != 64 or any(x not in '0123456789abcdef' for x in digest)):
        raise ValueError('Absolute immutable evidence pin required')
    with path.open('rb') as stream:
        data = stream.read(MAX_EVIDENCE + 1)
    if len(data) > MAX_EVIDENCE or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Evidence exceeds bound or changed')
    return data


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Finite numeric UTC time required')
    return value


def endpoint(value, expected_path):
    if not isinstance(value, str) or '?' in value or '#' in value or any(c.isspace() for c in value):
        raise ValueError('Canonical localhost endpoint required')
    u = urlsplit(value)
    if (u.scheme != 'http' or u.hostname != '127.0.0.1' or not u.port
            or u.path != expected_path or u.username or u.password or u.query or u.fragment):
        raise ValueError('Explicit IPv4 localhost endpoint required')
    return value.rstrip('/'), u.port


def publish(path, value):
    """Private atomic no-clobber evidence publication; never replace history."""
    path = Path(path)
    stage = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
            stage = Path(f.name)
            f.write(encoded(value) + b'\n'); f.flush(); os.fsync(f.fileno())
        stage.chmod(0o600)
        os.link(stage, path)
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)
    return pin(path)


def process_identity(pid, *, proc=Path('/proc')):
    if type(pid) is not int or pid <= 0:
        raise ValueError('Positive owned serving PID required')
    fields = (proc / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
    if fields[0] in ('Z', 'X', 'x'):
        raise ValueError('Serving process is no longer live')
    return {'pid': pid, 'start_ticks': int(fields[19]),
            'boot_id': (proc / 'sys/kernel/random/boot_id').read_text().strip()}


def owned_listener(owner, port, *, proc=Path('/proc')):
    """Bind listening socket to the same live process or its descendants.

    vLLM may rewrite its process title, so cmdline text is not used as authority.
    The launch receipt and PID birth identity are captured by the process owner.
    Missing/ambiguous ownership fails closed; no privileged mutation endpoint.
    """
    if process_identity(owner['pid'], proc=proc) != owner:
        raise ValueError('Owned serving process changed')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid listener port')
    rows = []
    for line in (proc / 'net/tcp').read_text().splitlines()[1:]:
        fields = line.split()
        if (fields[3] == '0A' and int(fields[1].split(':')[1], 16) == port
                and fields[1].split(':')[0] == '0100007F'):
            rows.append(fields)
    # Prove this selected IPv4 endpoint. Unrelated IPv4/IPv6 listeners at a
    # different address do not expose it and must not cause false unavailability.
    if len(rows) != 1:
        raise ValueError('One private serving listener required')
    inode = rows[0][9]
    def holds(pid):
        try:
            entries = list((proc / str(pid) / 'fd').iterdir())
            if len(entries) > 8192:
                raise ValueError('Serving FD inventory exceeds finite bound')
            for fd in entries:
                try:
                    if os.readlink(fd) == 'socket:[' + inode + ']':
                        return True
                except OSError:
                    pass
        except OSError:
            pass
        return False
    # The normal API process owns its listener directly. Avoid scanning every
    # host process for each admission when this small FD check proves ownership.
    if holds(owner['pid']):
        if process_identity(owner['pid'], proc=proc) != owner:
            raise ValueError('Owned serving process changed during listener check')
        return [owner['pid']]
    parents = {}
    children = [p for p in proc.iterdir() if p.name.isdigit()]
    if len(children) > 8192:
        raise ValueError('Process inventory exceeds finite ownership bound')
    for path in children:
        try:
            fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            if fields[0] not in ('Z', 'X', 'x'):
                parents[int(path.name)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue  # A process exiting during the read is not ownership.
    descendants = {owner['pid']}
    for _ in range(len(parents)):
        added = {pid for pid, parent in parents.items() if parent in descendants} - descendants
        if not added:
            break
        descendants.update(added)
    holders = {pid for pid in descendants if holds(pid)}
    if not holders or process_identity(owner['pid'], proc=proc) != owner:
        raise ValueError('Raw serving port is not owned by the recorded process')
    return sorted(holders)


def close_socket(stream):
    try:
        stream.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def raw_get(origin, path, *, timeout, json_body=False):
    """Direct IPv4 local HTTP, no proxy/redirect, with an overall receive bound."""
    _, port = endpoint(origin, '')
    if path not in ('/health', '/v1/models') or not 0 < timeout <= 10:
        raise ValueError('Bounded read-only raw request required')
    end = time.monotonic() + timeout
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    timer = None
    try:
        connection.connect()  # Fixed numeric local address; no DNS/proxy lookup.
        if time.monotonic() >= end:
            raise TimeoutError('Raw request connection exhausted budget')
        timer = threading.Timer(end - time.monotonic(), close_socket, (connection.sock,))
        timer.daemon = True; timer.start()
        connection.request('GET', path)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Raw serving request must be HTTP200')
        if not json_body:
            return True  # Health may be empty; do not read an unbounded body.
        data = response.read((1 << 20) + 1)
        if len(data) > (1 << 20):
            raise ValueError('Raw control-plane response exceeded bound')
        return json.loads(data)
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()


def health(origin, *, timeout):
    return raw_get(origin, '/health', timeout=timeout)


def models(origin, *, timeout):
    return raw_get(origin, '/v1/models', timeout=timeout, json_body=True)


def supported_profile(launch, compatibility):
    """Bind reusable evidence to the actual fixed suite command, not its label."""
    argv = launch['command']
    if (not isinstance(argv, list) or any(not isinstance(x, str) for x in argv)
            or not 6 <= len(argv) <= 256 or argv[:5] != [argv[0], '-P', '-m', 'vllm.entrypoints.cli.main', 'serve']):
        raise ValueError('Exact suite serving command required')
    snapshot = Path(argv[5])
    if (not snapshot.is_absolute() or snapshot != snapshot.resolve(strict=True)
            or snapshot.name != '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
            or snapshot.parent.name != 'snapshots'
            or snapshot.parent.parent.name != 'models--Qwen--Qwen3.8-27B-FP8'
            or hashlib.sha256((snapshot / 'config.json').read_bytes()).hexdigest() != launch['checkpoint_config_sha256']):
        raise ValueError('Pinned actual HF snapshot/config binding required')
    settings = launch['launch_settings']
    expected = serving_command(snapshot, port=int(settings['port']),
                               max_num_seqs=int(settings['max_num_seqs']),
                               memory_fraction=float(settings['gpu_memory_utilization']))
    # The serving and browser environments use separate virtualenv executables.
    # The worker owns the PID and captures its launch receipt before publication.
    if not Path(argv[0]).is_absolute():
        raise ValueError('Absolute serving interpreter required')
    expected[0] = argv[0]
    if argv != expected:
        raise ValueError('Serving argv differs from the exact reviewed constructor')
    def option(flag):
        return expected[expected.index(flag) + 1]
    serving = compatibility['serving']
    mtp = {'method': 'mtp', 'num_speculative_tokens': 3}
    if (json.loads(option('--speculative-config')) != mtp or serving['mtp_mode'] != mtp
            or serving['lora_mode'] is not None
            or json.loads(option('--default-chat-template-kwargs')) != {
                'enable_thinking': True, 'preserve_thinking': True}
            or json.loads(option('--limit-mm-per-prompt')) != serving['image_limits']['limit_mm_per_prompt']
            or json.loads(option('--mm-processor-kwargs')) != serving['image_limits']['mm_processor_kwargs']):
        raise ValueError('Speculation/adapter/image/thinking profile mismatch')
    if launch['vllm_version'] != '0.28.0' or compatibility['runtime']['vllm_version'] != '0.28.0':
        raise ValueError('Pinned vLLM0.28.0 suite required')


class Evidence:
    def __init__(self, binding_pin, *, clock=time.time, monotonic=time.monotonic,
                 probe=owned_listener, check_health=health, check_models=models,
                 should_stop=lambda: False):
        self.clock, self.monotonic, self.probe, self.health = clock, monotonic, probe, check_health
        self.should_stop = should_stop
        self.publication_directory = None
        self.binding_pin = deepcopy(binding_pin)
        binding = json.loads(read_pin(binding_pin))
        if (binding.get('schema') != 'qwen-fresh-instance-binding-v1'
                or set(binding) != {'schema', 'runtime', 'capability', 'deployment', 'launch',
                                   'raw_base_url', 'qualification_base_url', 'dispatch_approval'}):
            raise ValueError('Complete fresh-instance binding required')
        self.binding = binding
        runtime_source = read_pin(binding['runtime'])
        self.runtime = {'__file__': binding['runtime']['path'], '__name__': '_qwen_frozen_runtime'}
        exec(compile(runtime_source, binding['runtime']['path'], 'exec'), self.runtime)
        self.capability = json.loads(read_pin(binding['capability']))
        self.deployment = json.loads(read_pin(binding['deployment']))
        self.launch = json.loads(read_pin(binding['launch']))
        self.cap = self.capability
        self.dep = self.deployment
        for key in ('run_id', 'instance_id'):
            if not isinstance(self.dep.get(key), str) or str(UUID(self.dep[key])) != self.dep[key]:
                raise ValueError('Canonical current allocation/run UUIDs required')
        if self.dep['run_id'] == self.dep['instance_id']:
            raise ValueError('Run and provider instance UUIDs must be distinct')
        if (self.dep.get('server_context') != 262144
                or any(self.dep.get(k) is not True for k in ('vision_configured', 'native_tools_configured', 'exact_request_counter'))):
            raise ValueError('Measured deployment configuration/counter flags required')
        self.raw, self.port = endpoint(binding['raw_base_url'], '')
        self.qualification, self.qualification_port = endpoint(binding['qualification_base_url'], '')
        if self.port == self.qualification_port:
            raise ValueError('Separate raw serving and qualification ports required')
        self.deadline = number(self.dep['deadline_utc'])
        allocation = number(self.dep['allocation_utc'])
        duration = self.dep['approved_rental_seconds']
        if type(duration) is not int or not 0 < duration <= 86400 or allocation + duration != self.deadline:
            raise ValueError('Finite allocation-anchored deadline required')
        now = number(clock())
        if not allocation <= now < self.deadline:
            raise TimeoutError('Fresh observation must fall inside the original rental')
        self.mono_end = monotonic() + self.deadline - now
        if self.dep.get('passed') is not True or self.dep.get('synthetic') is not False:
            raise ValueError('Measured actual successful deployment required')
        if self.dep['launch_receipt'] != binding['launch']:
            raise ValueError('Deployment must pin this exact launch receipt')
        self.owner = deepcopy(self.dep['serving_process'])
        if (set(self.owner) != {'pid', 'start_ticks', 'boot_id'}
                or type(self.owner['start_ticks']) is not int or self.owner['start_ticks'] <= 0
                or not isinstance(self.owner['boot_id'], str) or not self.owner['boot_id']):
            raise ValueError('Measured serving process birth identity required')
        if (self.launch.get('status') != 'source_checks_passed_before_exec'
                or self.launch.get('profile') != PROFILE or self.launch['pid'] != self.owner['pid']
                or self.dep['serving_session_id'] != self.launch['attempt_id']
                or self.launch['launch_settings']['port'] != str(self.port)):
            raise ValueError('Actual owned serving attempt/profile/port mismatch')
        self.identity = deepcopy(self.dep['identity'])
        self.compatibility = deepcopy(self.dep['observed_compatibility'])
        self.runtime['validate_compatibility'](self.compatibility)
        supported_profile(self.launch, self.compatibility)
        self.fingerprint = self.runtime['digest'](self.compatibility, sorted_keys=True)
        assets = {'tokenizer_sha256': self.identity.get('tokenizer_sha256'),
                  'template_sha256': self.identity.get('template_sha256'),
                  'processor_sha256': self.identity.get('image_processor_sha256')}
        if (set(self.identity) != self.runtime['IDENTITY_KEYS']
                or self.identity['model'] != self.runtime['MODEL']
                or self.identity['serving_revision'] != self.runtime['REVISION']
                or self.identity['tool_parser'] != 'qwen3_coder'
                or self.compatibility['assets'] != assets
                or self.compatibility['model'] != {'repository': self.identity['model'],
                                                    'revision': self.identity['serving_revision']}
                or self.compatibility['runtime']['counter_projection_sha256'] != self.runtime['projection_sha256']()):
            raise ValueError('Counter projection or general serving identity differs')
        for value in assets.values():
            self.runtime['hex_hash'](value)
        if (self.cap.get('schema') != 'serving-stack-capability-v1'
                or self.cap.get('status') != 'passed' or self.cap.get('synthetic') is not False
                or self.cap['compatibility'] != self.compatibility
                or self.cap['fingerprint'] != self.fingerprint
                or any(self.cap.get('checks', {}).get(k) is not True for k in self.runtime['CHECKS'])
                or set(self.cap['proofs']) != {'qualification', 'deployment', 'processor'}):
            raise ValueError('Exact reusable actual capability with all required checks needed')
        self.proof_pins = list(self.cap['proofs'].values())
        for kind, row in self.cap['proofs'].items():
            proof = json.loads(read_pin(row))
            if (proof.get('passed') is not True or proof.get('synthetic') is not False
                    or proof.get('proof_kind') != kind or proof.get('fingerprint') != self.fingerprint):
                raise ValueError('Typed successful original nonsynthetic matching proof required')
        # The caller also verifies detailed identity/assets, serializer, and
        # capability/readiness/deployment consistency before any dispatch.
        self.dispatch_authorized = False
        self.case_ids = []
        approval_pin = binding['dispatch_approval']
        if approval_pin is not None:
            approval = json.loads(read_pin(approval_pin))
            cases = approval.get('case_ids')
            if (approval.get('allocation_authorized') is not True
                    or approval.get('dispatch_authorized') is not True
                    or approval.get('approved_rental_seconds') != duration
                    or any(approval.get(k) != self.dep.get(k) or k not in self.dep
                           for k in ('run_id', 'instance_id', 'allocation_utc', 'deadline_utc'))
                    or not isinstance(cases, list) or not cases
                    or len(set(cases)) != len(cases)
                    or any(not isinstance(x, str) or not x.startswith('qwen-') for x in cases)):
                raise ValueError('Separate actual finite Qwen episode approval required')
            self.dispatch_authorized = True
            self.case_ids = deepcopy(cases)
        self.check()
        actual = check_models(self.raw, timeout=self.request_timeout())
        if (not isinstance(actual, dict) or actual.get('data') != [
                row for row in actual.get('data', []) if isinstance(row, dict)
                and row.get('id') == self.identity['model'] and row.get('max_model_len') == self.dep['server_context']]
                or len(actual.get('data', [])) != 1):
            raise ValueError('Actual served model/context metadata mismatch')
        self.check()

    def request_timeout(self):
        remaining = min(10, self.deadline - number(self.clock()), self.mono_end - self.monotonic())
        if remaining <= 0:
            raise TimeoutError('Original rental lifetime ended')
        return remaining

    def check(self):
        if self.should_stop():
            raise InterruptedError('Qualification adapter was stopped')
        for row in [self.binding_pin, self.binding['runtime'], self.binding['capability'],
                    self.binding['deployment'], self.binding['launch'], *self.proof_pins]:
            read_pin(row)
        if self.binding['dispatch_approval'] is not None:
            read_pin(self.binding['dispatch_approval'])
        if number(self.clock()) >= self.deadline or self.monotonic() >= self.mono_end:
            raise TimeoutError('Original rental lifetime ended')
        self.probe(self.owner, self.port)
        if self.health(self.raw, timeout=self.request_timeout()) is not True:
            raise ValueError('Actual raw serving health failed')
        self.probe(self.owner, self.port)  # Health cannot mask a process/port replacement.
        if self.should_stop():
            raise InterruptedError('Qualification adapter was stopped during health')
        if self.clock() >= self.deadline or self.monotonic() >= self.mono_end:
            raise TimeoutError('Rental ended during fresh health check')

    def response(self):
        self.check()
        return {'status': 'ready', 'exact_request_counter': True,
                'serving_session_id': self.dep['serving_session_id'], 'identity': self.identity,
                'fingerprint': self.fingerprint, 'server_context': 262144, 'isl': 250000,
                'deadline_utc': self.deadline, 'observed_compatibility': self.compatibility,
                'qualification_mode': 'reused-capability', 'diagnostic_generation_requests': 0}

    def publish(self, directory):
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.publication_directory = directory.absolute()
        self.check()
        instance = {'schema': 'serving-instance-readiness-v1', 'status': 'ready',
                    'capability': self.binding['capability'], 'deployment_receipt': self.binding['deployment'],
                    'fingerprint': self.fingerprint, 'observed_compatibility': self.compatibility,
                    'identity': self.identity, 'base_url': self.raw + '/v1',
                    'serving_session_id': self.dep['serving_session_id'], 'gpu_deadline_utc': self.deadline,
                    'server_context': 262144, 'isl': 250000, 'vision_configured': True,
                    'native_tools_configured': True, 'exact_request_counter': True,
                    'issued_at_utc': number(self.clock()), 'expires_at_utc': self.deadline,
                    'diagnostic_generation_requests': 0, 'synthetic_100k_forward_requests': 0}
        instance['dispatch_approval_receipt'] = self.binding['dispatch_approval']
        instance_pin = publish(directory / 'instance-readiness.json', instance)
        live = {'schema': 'qualified-serving-live-v1', 'base_url': self.raw + '/v1',
                'qualification_base_url': self.qualification, 'identity': self.identity,
                'server_context': 262144, 'isl': 250000, 'deadline_utc': self.deadline,
                'serving_session_id': self.dep['serving_session_id'],
                'capability_receipt': self.binding['capability'], 'instance_readiness_receipt': instance_pin,
                'deployment_receipt': self.binding['deployment'],
                'dispatch_authorized': self.dispatch_authorized,
                'dispatch_approval_receipt': self.binding['dispatch_approval'],
                'case_ids': self.case_ids}
        live_pin = publish(directory / 'qualified-serving-live.json', live)
        # Reuse the exact pinned consumer, instead of duplicating its full schema.
        self.runtime['ServingAdmission'](live_pin, clock=self.clock)
        self.check()
        return live_pin


def handler(evidence):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup(); self.connection.settimeout(2)

        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path != '/qualification':
                self.send_error(404); return
            try:
                value = evidence.response(); status = 200
            except Exception as exc:
                status = 503
                value = {'status': 'unavailable', 'error_type': type(exc).__name__}
            data = encoded(value)
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close'); self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass  # A timed-out client cannot block cleanup or other clients.
    return Handler


class QualificationServer(ThreadingHTTPServer):
    """Eight bounded connections; slow clients cannot pin the serving loop."""
    daemon_threads = True
    block_on_close = False
    request_queue_size = 16

    def __init__(self, evidence):
        self.evidence = evidence
        self.slots = threading.BoundedSemaphore(8)
        self.connections = {}
        self.lock = threading.Lock()
        super().__init__(('127.0.0.1', evidence.qualification_port), handler(evidence))
        self.timeout = .25

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            body = b'{"status":"unavailable","error_type":"ConnectionCapacity"}'
            try:
                request.settimeout(.1)
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n'
                    b'Retry-After: 1\r\nContent-Type: application/json\r\nContent-Length: ' +
                    str(len(body)).encode() + b'\r\n\r\n' + body)
            except OSError:
                pass
            self.shutdown_request(request); return
        remaining = min(self.evidence.deadline - self.evidence.clock(),
                        self.evidence.mono_end - self.evidence.monotonic())
        timer = threading.Timer(min(15, max(.01, remaining)), close_socket, (request,))
        timer.daemon = True
        with self.lock:
            self.connections[request] = timer
        timer.start()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.finished(request); self.shutdown_request(request); raise

    def finished(self, request):
        with self.lock:
            timer = self.connections.pop(request, None)
        if timer is not None:
            timer.cancel(); self.slots.release()

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.finished(request)

    def server_close(self):
        with self.lock:
            active = list(self.connections.items())
        for request, timer in active:
            timer.cancel(); close_socket(request)
        super().server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--binding-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    stopped = False; stop_signal = None
    def stop(signum, _):
        nonlocal stopped, stop_signal
        stopped = True; stop_signal = signum
    for sig in STOP_SIGNALS:
        signal.signal(sig, stop)
    evidence = None; entered = False
    try:
        evidence = Evidence({'path': str(args.binding.absolute()), 'sha256': args.binding_sha256},
                            should_stop=lambda: stopped)
        with QualificationServer(evidence) as server:
            live_pin = evidence.publish(args.output)
            evidence.check()
            publish(args.output / 'adapter-ready.json', {'status': 'listening_at_publication',
                    'process': process_identity(os.getpid()),
                    'live': live_pin, 'qualification_base_url': evidence.qualification,
                    'synthetic': False, 'diagnostic_generation_requests': 0})
            evidence.check()  # A stop observed during publication is not startup success.
            entered = True
            print(json.dumps({'live': live_pin, 'diagnostic_generation_requests': 0}), flush=True)
            while (not stopped and evidence.clock() < evidence.deadline
                   and evidence.monotonic() < evidence.mono_end):
                server.handle_request()
    except InterruptedError:
        if stopped:
            raise SystemExit(128 + stop_signal)
        raise
    finally:
        if evidence is not None and evidence.publication_directory == args.output.absolute():
            publish(args.output / 'adapter-stopped.json', {'status': 'stopped',
                    'startup_completed': entered, 'signal': stop_signal,
                    'process': process_identity(os.getpid())})


if __name__ == '__main__':
    main()
