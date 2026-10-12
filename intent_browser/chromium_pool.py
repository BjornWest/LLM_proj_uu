"""Opt-in local supervisor/client transport for qualified Chromium reuse.

Only the supervisor launches/stops browser processes. Workers acquire independent
Playwright connections; disconnection reaps their contexts in the server.
No model, world or browser-session state is shared by this module.
"""
from __future__ import annotations

import hashlib
import http.client
from importlib.metadata import version
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import time

VERSION = 'shared-chromium-v1'


class PoolError(RuntimeError):
    """Infrastructure/admission failure; never permission for action/model replay."""


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def installed_manifest():
    import playwright
    package = Path(playwright.__file__).parent/'driver/package'
    data = json.loads((package/'package.json').read_text())
    chromium = next(row for row in json.loads((package/'browsers.json').read_text())['browsers']
                    if row['name'] == 'chromium')
    # Resolve the installed revision without starting another Playwright driver.
    cache = Path(os.environ.get('PLAYWRIGHT_BROWSERS_PATH', Path.home()/'.cache/ms-playwright'))
    if str(cache) == '0': cache = package/'.local-browsers'
    executable = cache/('chromium-'+chromium['revision'])/'chrome-linux/chrome'
    if version('playwright') != '1.44.0' or data['version'] != '1.44.0-beta-1715802478000':
        raise PoolError('Shared Chromium requires the qualified Playwright 1.44 driver')
    manifest = {'version': VERSION, 'python_playwright_version': version('playwright'),
                'node_playwright_version': data['version'], 'chromium_revision': chromium['revision'],
                'chromium_version': chromium['browserVersion'], 'executable_sha256': _sha(executable),
                'package_json_sha256': _sha(package/'package.json'),
                'browser_server_sha256': _sha(package/'lib/browserServerImpl.js'),
                'node_executable_sha256': _sha(package.parent/'node'),
                'broker_asset_sha256': _sha(Path(__file__).parent/'assets/chromium_pool.cjs'),
                'python_client_sha256': _sha(__file__),
                'browsergym_adapter_sha256': _sha(Path(__file__).parent/'shared_browsergym.py'),
                'browsergym_shutdown_sha256': _sha(Path(__file__).parent/'browser_shutdown.py'),
                'loopback_patch': 'qualified-1.44-launchServer-loopback-v1'}
    return package, executable, manifest


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__('localhost', timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        try: self.sock.connect(self.path)
        except BaseException:
            self.sock.close()
            raise


class PoolClient:
    def __init__(self, descriptor, *, timeout=15):
        self.descriptor = dict(descriptor)
        if self.descriptor.get('version') != VERSION:
            raise PoolError('Unsupported Chromium pool descriptor')
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise ValueError('Pool HTTP timeout must be finite, at most30seconds')
        _, _, actual = installed_manifest()
        if actual != self.descriptor.get('manifest'):
            raise PoolError('Client/server Playwright or Chromium qualification mismatch')
        self.timeout = timeout

    @classmethod
    def from_file(cls, path, **kwargs):
        return cls(json.loads(Path(path).read_text()), **kwargs)

    def request(self, operation, body=None):
        raw = json.dumps(body or {}, allow_nan=False, separators=(',', ':')).encode()
        if len(raw) > 8192: raise PoolError('Pool request exceeds8192bytes')
        connection = _UnixHTTP(self.descriptor['socket'], self.timeout)
        try:
            connection.request('POST', '/'+operation, raw,
                {'Authorization': 'Bearer '+self.descriptor['secret'], 'Content-Type': 'application/json'})
            response = connection.getresponse()
            payload = response.read(262145)
            if len(payload) > 262144: raise PoolError('Pool response exceeds262144bytes')
            value = json.loads(payload)
            if response.status != 200: raise PoolError(value.get('error', 'Pool admission rejected'))
            return value
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise PoolError('Chromium pool transport failed: '+type(error).__name__) from error
        finally: connection.close()

    def status(self):
        return self.request('status')

    def episode(self, owner, *, background=False):
        from .shared_browsergym import PoolEpisode
        return PoolEpisode(self, owner, background=background)


class PoolSupervisor:
    """Explicit suite-owned lifetime; run under the bounded launcher.

    The directory must be new. Terminating a worker does not terminate this
    process; supervisor close intentionally invalidates all attached episodes.
    """
    def __init__(self, directory, *, max_servers=4, max_leases=16, per_server=8,
                 pending_seconds=15):
        self.directory = Path(directory).resolve()
        for value, maximum in ((max_servers,16),(max_leases,128),(per_server,64),(pending_seconds,60)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('Pool caps must be explicit positive bounded integers')
        self.limits = dict(maxServers=max_servers, maxLeases=max_leases,
                           perServer=per_server, pendingSeconds=pending_seconds)
        self.process = None
        self.client = None
        self._admin = None
        self.log = None
        self.transport_directory = None

    def start(self):
        if self.process is not None: raise PoolError('Supervisor is already started')
        package, executable, manifest = installed_manifest()
        self.directory.mkdir(mode=0o700)
        # Unix sockets have short path limits; the random private directory keeps
        # the control address short even when the evidence root is long.
        import tempfile
        self.transport_directory = Path(tempfile.mkdtemp(prefix='chromium-pool-'))
        socket_path = self.transport_directory/'control.sock'
        self.descriptor_path = self.directory/'descriptor.json'
        config = {**self.limits, 'package': str(package), 'executable': str(executable),
                  'manifest': manifest, 'secret': secrets.token_hex(32), 'admin_secret': secrets.token_hex(32),
                  'socket': str(socket_path),
                  'events': str(self.directory/'events.jsonl'),
                  'ready': str(self.descriptor_path)}
        config_path = self.directory/'config.json'
        fd = os.open(config_path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as stream: json.dump(config, stream)
        self.log = (self.directory/'supervisor.log').open('x')
        node = package.parent/'node'
        asset = Path(__file__).parent/'assets/chromium_pool.cjs'
        try:
            self.process = subprocess.Popen([str(node), str(asset), str(config_path)],
                                            stdout=self.log, stderr=subprocess.STDOUT)
            deadline = time.monotonic()+15
            while not self.descriptor_path.exists():
                if self.process.poll() is not None: raise PoolError('Chromium supervisor startup failed')
                if time.monotonic() >= deadline: raise PoolError('Chromium supervisor startup timed out')
                time.sleep(.025)
            self.client = PoolClient.from_file(self.descriptor_path)
            self._admin = PoolClient({**self.client.descriptor, 'secret': config['admin_secret']})
            return self.client
        except BaseException:
            self.close()
            raise

    def close(self):
        failure = None
        if self.process is not None and self.process.poll() is None:
            try:
                if self._admin is not None: self._admin.request('shutdown')
                else: self.process.terminate()
                self.process.wait(timeout=20)
            except PoolError as error:
                # A simultaneous process-group stop can close the control socket
                # before the parent's request. A clean broker exit still qualifies.
                try: self.process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    failure = error
                    self.process.terminate()
                    try: self.process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        self.process.kill(); self.process.wait(timeout=5)
            except subprocess.TimeoutExpired as error:
                failure = error
                self.process.terminate()
                try: self.process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait(timeout=5)
        if self.process is not None and self.process.returncode not in (None,0):
            failure = failure or PoolError('Supervisor exited abnormally: '+str(self.process.returncode))
        if self.log is not None: self.log.close()
        if self.transport_directory is not None and self.transport_directory.exists():
            for path in self.transport_directory.iterdir(): path.unlink()
            self.transport_directory.rmdir()
        if failure is not None: raise PoolError('Supervisor shutdown failed') from failure

    def drain(self, group):
        return self._admin.request('drain', {'group': group})

    def abort_browser(self, group):
        """Supervisor-only explicit crash/retirement, never action/model replay."""
        return self._admin.request('kill', {'group': group})

    def inspect_contexts(self, group):
        """Privileged diagnostic identity check, not a policy-visible tool."""
        return self._admin.request('contexts', {'group': group})

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--max-servers', type=int, default=4)
    parser.add_argument('--max-leases', type=int, default=16)
    parser.add_argument('--per-server', type=int, default=8)
    args = parser.parse_args()
    supervisor = PoolSupervisor(args.directory, max_servers=args.max_servers,
                                max_leases=args.max_leases, per_server=args.per_server)
    stopping = False
    def stop(signum, frame):
        nonlocal stopping
        stopping = True
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}
    for sig in handlers: signal.signal(sig, stop)
    try:
        supervisor.start()
        print(str(supervisor.descriptor_path), flush=True)
        while supervisor.process.poll() is None and not stopping: time.sleep(.1)
    finally:
        try: supervisor.close()
        finally:
            for sig, handler in handlers.items(): signal.signal(sig, handler)


if __name__ == '__main__': main()
