"""Monitored container services for the existing Qwen host worker.

The state keys match its internal service interface; they are not systemd
observations. Actual guardian/root identities and containment receipts are kept
separately. This backend promises sampled thresholds, not per-job kernel caps.
"""
from hashlib import sha256
import ctypes
import json
import math
import os
import platform
from pathlib import Path
import signal
import subprocess
import time

from qwen_suite_qualification import read_pin, process_identity, publish, pin


def pidfd_syscall(number, *arguments):
    # Managed manylinux Python may omit these wrappers even on a capable host.
    # These numbers are the Linux x86_64 ABI, verified in unistd_64.h.
    if platform.system() != 'Linux' or platform.machine() != 'x86_64' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RuntimeError('pidfd fallback requires the qualified Linux x86_64 host')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    result = libc.syscall(ctypes.c_long(number), *arguments)
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return result


def open_pidfd(pid):
    native = getattr(os, 'pidfd_open', None)
    return native(pid) if callable(native) else pidfd_syscall(434, ctypes.c_int(pid), ctypes.c_uint(0))


def send_pidfd(descriptor, signum):
    native = getattr(signal, 'pidfd_send_signal', None)
    if callable(native):
        return native(descriptor, signum)
    return pidfd_syscall(424, ctypes.c_int(descriptor), ctypes.c_int(signum), ctypes.c_void_p(0), ctypes.c_uint(0))


def identity_matches(record, actual):
    return all(record.get(key) == actual[key] for key in ('pid', 'start_ticks'))


def checked_record(record, spec):
    if (record.get('schema') != 'container-job-v1' or record.get('mode') != 'monitored_process_tree'
            or record.get('source_sha256') != spec['container_launcher']['sha256']):
        raise ValueError('Pinned actual guardian protocol required')


def launch_argv(spec, run, remaining, name, *, binding=None):
    if not math.isfinite(remaining) or remaining < 1:
        raise TimeoutError('Original rental ended')
    memory = 512 if binding else spec['server_memory_mib']
    if type(memory) is not int or (not binding and not 49152 <= memory <= 65536):
        raise ValueError('Explicit serving threshold48..64GiB required')
    read_pin(spec['container_launcher'])
    entry = Path(spec['host_root'])/'training/scripts'
    env = {'HOME': os.environ['HOME'], 'USER': os.environ.get('USER', ''),
           'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
           'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1'}
    if binding:
        payload = [spec['browser_python'], '-I', '-B', str(entry/'qwen_suite_qualification.py'),
                   '--binding', binding['path'], '--binding-sha256', binding['sha256'],
                   '--output', str(run/'ready')]
    else:
        payload = [spec['rl_python'], '-I', '-B', str(entry/'serve_qwen_suite.py'),
                   '--snapshot', spec['snapshot'], '--receipt', str(run/'installed-serving.json'),
                   '--cache-root', spec['cache_root'], '--max-num-seqs', str(spec.get('max_num_seqs', 8))]
    return [spec['browser_python'], '-I', '-B', spec['container_launcher']['path'],
            # Memory is the guard; thread caps (0) only kill services under load.
            '--memory-mib', str(memory), '--tasks', '0',
            '--receipt', str(run/name), '--wall-seconds', str(remaining),
            '--grace-seconds','10','--cleanup-seconds','20','--',
            '/usr/bin/env', '-i', *[k+'='+v for k, v in env.items()], *payload]


class ContainerServices:
    def __init__(self, spec):
        descriptor = open_pidfd(os.getpid())
        try:
            send_pidfd(descriptor, 0)  # Fail closed before any service is started.
        finally:
            os.close(descriptor)
        self.spec = spec
        self.rows = {}

    def call(self, argv, timeout=10):
        read_pin(self.spec['container_launcher'])
        if argv[:4] != [self.spec['browser_python'], '-I', '-B', self.spec['container_launcher']['path']]:
            raise ValueError('Only the pinned guardian may be launched')
        receipt = Path(argv[argv.index('--receipt')+1])
        name = receipt.name
        if name in self.rows or receipt.exists():
            raise ValueError('Exclusive new service receipt required')
        run = receipt.parent
        log = run/('qualification.log' if name.endswith('-qualification') else 'vllm.log')
        output = log.open('xb'); log.chmod(0o600)
        try:
            child = subprocess.Popen(argv, cwd=run, stdout=output, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True,
                                     env={k:v for k,v in os.environ.items() if k in ('HOME','USER','PATH','LANG')})
        except BaseException:
            output.close(); raise
        row = {'child': child, 'output': output, 'receipt': receipt, 'run': run,
               'guardian': None, 'root': None, 'invocation': None, 'entry': None}
        self.rows[name] = row  # Ambiguous start still belongs to this exact owner.
        row['guardian'] = process_identity(child.pid)
        row['invocation'] = sha256(json.dumps(row['guardian'], sort_keys=True).encode()).hexdigest()
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            if child.poll() is not None:
                raise RuntimeError('Guardian exited during launch; inspect '+str(log))
            path = receipt/'entry.json'
            if path.is_file():
                entry = json.loads(path.read_text())
                checked_record(entry, self.spec)
                if not identity_matches(entry['supervisor'], row['guardian']):
                    raise ValueError('Guardian entry belongs to another supervisor')
                root = entry['root']; actual = process_identity(root['pid'])
                if not identity_matches(root, actual):
                    raise ValueError('Guardian root birth differs')
                row['root'] = actual
                row['entry'] = pin(path)
                publish(run/(name+'-service.json'), {
                    'schema': 'qwen-container-service-v1', 'backend': 'container-monitored-v1',
                    'guardian': row['guardian'], 'root': actual, 'entry': row['entry'],
                    'receipt_directory': str(receipt),
                    'per_job_kernel_limits': False, 'thresholds': 'sampled RSS and thread count',
                    'original_wall_seconds': float(argv[argv.index('--wall-seconds')+1])})
                return ''
            time.sleep(.05)
        raise TimeoutError('Guardian launch receipt missing')

    def state(self, name):
        row = self.rows.get(name)
        if row is None:
            return {'LoadState': 'not-found'}
        live = row['child'].poll() is None
        if live:
            try:
                live = process_identity(row['child'].pid) == row['guardian']
                if row['root'] is not None:
                    live = live and process_identity(row['root']['pid']) == row['root']
            except (OSError, ValueError):
                live = False
        return {'LoadState': 'loaded', 'ActiveState': 'active' if live else 'inactive',
                'MainPID': str(row['root']['pid']) if live and row['root'] else '0',
                'InvocationID': row['invocation'] or '', 'WorkingDirectory': str(row['run']),
                'backend': 'container-monitored-v1'}

    def stop(self, name, invocation, *, expected_directory=None):
        row = self.rows.get(name)
        if row is None:
            return
        if invocation is not None and invocation != row['invocation']:
            raise ValueError('Guardian invocation differs')
        if invocation is None and expected_directory != row['run']:
            raise ValueError('Ambiguous service belongs to another directory')
        child = row['child']
        try:
            if child.poll() is None:
                # Open first, then verify birth: pidfd cannot target a reused PID.
                descriptor = None
                try:
                    descriptor = open_pidfd(child.pid)
                    try:
                        actual = process_identity(child.pid)
                    except (OSError, ValueError):
                        child.wait(timeout=1)  # Already exited/zombie: reap, then verify result.
                    else:
                        if actual != row['guardian']:
                            raise ValueError('Guardian process replaced; do not signal it')
                        send_pidfd(descriptor, signal.SIGTERM)
                except ProcessLookupError:
                    child.wait(timeout=1)
                finally:
                    if descriptor is not None:os.close(descriptor)
                child.wait(timeout=35)
            if row['entry'] is None:
                raise RuntimeError('No verified payload entry; refuse cleanup success')
            entry = json.loads(read_pin(row['entry']))
            result_pin = pin(row['receipt']/'result.json')
            result = json.loads(read_pin(result_pin))
            checked_record(result, self.spec)
            if (not identity_matches(result['supervisor'], row['guardian'])
                    or not identity_matches(result['root'], row['root'])
                    or not identity_matches(entry['root'], row['root'])):
                raise ValueError('Guardian terminal identity differs')
            if any(result.get(key) is not True for key in ('cleanup_verified','entry_verified','payload_gate_released')):
                raise RuntimeError('Guardian cleanup not verified')
            if type(result.get('returncode')) is not int or result['returncode'] != child.returncode:
                raise RuntimeError('Unexpected guardian exit status')
            if row['root'] is not None:
                try:
                    if process_identity(row['root']['pid']) == row['root']:
                        raise RuntimeError('Service root still alive after cleanup')
                except (FileNotFoundError, ProcessLookupError, ValueError):
                    pass
            publish(row['run']/(name+'-service-terminal.json'), {
                'schema': 'qwen-container-service-terminal-v1', 'guardian': row['guardian'],
                'root': row['root'], 'guardian_exit_code': child.returncode,
                'cleanup_verified': True, 'guardian_result': result_pin,
                'first_stop_reason':result.get('first_stop_reason')})
        finally:
            row['output'].close()
