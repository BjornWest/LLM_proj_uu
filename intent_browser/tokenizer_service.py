"""Bounded same-user Unix-socket tokenizer host; no dynamic loads or text logs.

Run with ``python -m intent_browser.tokenizer_service --socket ABS --manifest
FILE`` under scripts/run_bounded_job.py. Only the foreground owner stops it.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import stat
import struct
import threading
import time
import uuid

from .shared_tokenizer import (PROTOCOL, VERSION, MAX_FRAME_BYTES, _hash,
                               receive_frame, send_frame, SharedTokenizerError)


class RequestRejected(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class TokenizerService:
    def __init__(self, socket_path, assets, *, max_assets=4, max_clients=4,
                 request_seconds=30, max_text_bytes=4*1024*1024,
                 max_ids=1_000_000, max_frame_bytes=MAX_FRAME_BYTES):
        from .shared_tokenizer import SharedTokenizerConfig
        SharedTokenizerConfig(str(socket_path), request_seconds, max_frame_bytes)
        for value, upper in [(max_assets, 8), (max_clients, 128),
                             (max_text_bytes, 8*1024*1024), (max_ids, 2_000_000)]:
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError('Invalid finite tokenizer service limit')
        if importlib.metadata.version('tokenizers') != VERSION:
            raise ValueError('Qualified tokenizers version required')
        if not isinstance(assets, list) or not assets or len(assets) > max_assets:
            raise ValueError('Explicit bounded asset allowlist required')
        self.path = Path(socket_path)
        parent = self.path.parent
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
                stat.S_IMODE(info.st_mode) != 0o700 or parent.is_symlink()):
            raise ValueError('Tokenizer socket parent must be an owned private 0700 directory')
        if self.path.exists() or self.path.is_symlink():
            raise ValueError('Tokenizer socket already exists; do not replace another service')
        self.request_seconds = request_seconds
        self.max_text_bytes = max_text_bytes
        self.max_ids = max_ids
        self.max_frame_bytes = max_frame_bytes
        self.instance = uuid.uuid4().hex
        self.assets = {}
        self.load_count = 0
        from tokenizers import Tokenizer
        for item in assets:
            if (not isinstance(item, dict) or set(item) != {'path', 'sha256', 'normalization'} or
                    not _hash(item['sha256']) or item['normalization'] not in ('raw', 'ascii-json')):
                raise ValueError('Exact path/digest/normalization asset binding required')
            path = Path(item['path'])
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 64*1024*1024:
                raise ValueError('Invalid or oversized tokenizer asset')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != item['sha256']:
                raise ValueError('Tokenizer digest mismatch')
            key = (item['sha256'], item['normalization'])
            if key not in self.assets:
                # Load exactly the verified bytes; no second pathname read/TOCTOU.
                text = raw.decode('utf-8')
                if item['normalization'] == 'ascii-json':
                    text = json.dumps(json.loads(text))
                self.assets[key] = Tokenizer.from_str(text)
                self.load_count += 1
        self._slots = threading.BoundedSemaphore(max_clients)
        self._threads = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._listener = None
        self._socket_inode = None

    def dispatch(self, request):
        if not isinstance(request, dict):
            raise ValueError('Invalid tokenizer request')
        base = {'protocol', 'version', 'asset', 'normalization', 'operation'}
        operation = request.get('operation')
        fields = {'describe': set(), 'count': {'text', 'add_special_tokens'},
                  'encode': {'text', 'add_special_tokens'}, 'decode': {'ids', 'skip_special_tokens'},
                  'encode_batch': {'texts', 'add_special_tokens'},
                  'count_batch': {'texts', 'add_special_tokens'},
                  'decode_batch': {'sequences', 'skip_special_tokens'}}
        if operation not in fields or set(request) != base | fields[operation]:
            raise ValueError('Unsupported tokenizer operation/fields')
        if request['protocol'] != PROTOCOL or request['version'] != VERSION:
            raise ValueError('Tokenizer protocol/version mismatch')
        key = (request['asset'], request['normalization'])
        tokenizer = self.assets.get(key)
        if tokenizer is None:
            raise RequestRejected('asset')
        if operation in ('encode_batch', 'count_batch'):
            texts = request['texts']
            if (not isinstance(texts, list) or len(texts) > 256 or
                    any(not isinstance(t, str) for t in texts) or
                    sum(len(t.encode('utf-8')) for t in texts) > self.max_text_bytes or
                    type(request['add_special_tokens']) is not bool):
                raise RequestRejected('bound')
            encodings = tokenizer.encode_batch(texts, add_special_tokens=request['add_special_tokens'])
            if operation == 'encode_batch' and sum(len(e.ids) for e in encodings) > self.max_ids:
                raise RequestRejected('bound')
            result = [len(e.ids) for e in encodings] if operation == 'count_batch' else [{'ids':e.ids,'offsets':e.offsets} for e in encodings]
        elif operation == 'decode_batch':
            sequences = request['sequences']
            if (not isinstance(sequences, list) or len(sequences) > 256 or
                    any(not isinstance(ids, list) for ids in sequences) or
                    sum(len(ids) for ids in sequences) > self.max_ids or
                    type(request['skip_special_tokens']) is not bool or
                    any(type(i) is not int or not 0 <= i <= 0xffffffff for ids in sequences for i in ids)):
                raise RequestRejected('bound')
            result = tokenizer.decode_batch(sequences, skip_special_tokens=request['skip_special_tokens'])
            if sum(len(t.encode('utf-8')) for t in result) > self.max_text_bytes:
                raise RequestRejected('bound')
        elif operation in ('count', 'encode'):
            text = request['text']
            if (not isinstance(text, str) or len(text.encode('utf-8')) > self.max_text_bytes or
                    type(request['add_special_tokens']) is not bool):
                raise RequestRejected('bound')
            encoding = tokenizer.encode(text, add_special_tokens=request['add_special_tokens'])
            ids = encoding.ids
            if operation == 'encode' and len(ids) > self.max_ids:
                raise RequestRejected('bound')
            result = len(ids) if operation == 'count' else {'ids':ids,'offsets':encoding.offsets}
        elif operation == 'decode':
            ids = request['ids']
            if (not isinstance(ids, list) or len(ids) > self.max_ids or
                    type(request['skip_special_tokens']) is not bool or
                    any(type(i) is not int or not 0 <= i <= 0xffffffff for i in ids)):
                raise RequestRejected('bound')
            result = tokenizer.decode(ids, skip_special_tokens=request['skip_special_tokens'])
            if len(result.encode('utf-8')) > self.max_text_bytes:
                raise RequestRejected('bound')
        else:
            result = {'immutable_assets': len(self.assets), 'loads': self.load_count,
                      'request_cache_entries': 0}
        return {'ok': True, 'identity': {k: request[k] for k in ('protocol', 'version', 'asset', 'normalization')},
                'instance': self.instance, 'result': result}

    def _handle(self, connection, deadline):
        try:
            peer = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if peer[1] != os.getuid():
                return
            try:
                request = receive_frame(connection, self.max_frame_bytes, deadline)
                # A timed-out queued client closes its socket. Do not encode its
                # abandoned request after admission. Closing after this check is
                # still a bounded unavoidable race with native computation.
                connection.setblocking(False)
                try:
                    if connection.recv(1, socket.MSG_PEEK) == b'':
                        return
                except BlockingIOError:
                    pass
                response = self.dispatch(request)
            except RequestRejected as error:
                response = {'ok': False, 'error': error.code}
            except TimeoutError:
                response = {'ok': False, 'error': 'timeout'}
            except (ValueError, TypeError, KeyError):
                response = {'ok': False, 'error': 'protocol'}
            except Exception:
                response = {'ok': False, 'error': 'internal'}
            if time.monotonic() >= deadline:
                response={'ok':False,'error':'timeout'}
                deadline=time.monotonic()+.1  # Diagnostic-only grace, no computation.
            try:
                send_frame(connection, response, self.max_frame_bytes, deadline)
            except SharedTokenizerError as error:
                if error.code != 'bound':
                    raise
                send_frame(connection, {'ok':False,'error':'bound'},
                           self.max_frame_bytes,time.monotonic()+.1)
        except Exception:
            pass  # Closed/timed-out clients do not stop the service or trigger retry.
        finally:
            with self._lock:
                self._threads.discard(threading.current_thread())
            self._slots.release()
            connection.close()

    def serve(self, ready=None, on_ready=None):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(self.path))
                self._socket_inode = self.path.lstat().st_ino
                os.chmod(self.path, 0o600)
                listener.listen(16)
                listener.settimeout(0.1)
                self._listener = listener
                if ready is not None:
                    ready.set()
                if on_ready is not None:
                    on_ready()
                while not self._stop.is_set():
                    try:
                        connection, _ = listener.accept()
                    except socket.timeout:
                        continue
                    # One accepted waiter plus the finite kernel backlog. Admission
                    # consumes the SAME request deadline as handling; no unbounded
                    # handler/queue growth and no spurious instant capacity rejection.
                    deadline = time.monotonic() + self.request_seconds
                    admitted = False
                    while not self._stop.is_set() and time.monotonic() < deadline:
                        if self._slots.acquire(timeout=min(.05,max(0,deadline-time.monotonic()))):
                            admitted=True
                            break
                    if not admitted:
                        try:
                            if not self._stop.is_set():
                                grace=time.monotonic()+.1
                                # Drain exactly one bounded frame so close does not
                                # reset unread payload before the rejection arrives.
                                receive_frame(connection,self.max_frame_bytes,grace)
                                send_frame(connection, {'ok': False, 'error': 'saturated'},
                                           self.max_frame_bytes, grace)
                        except Exception:
                            pass
                        finally:
                            connection.close()
                        continue
                    worker = threading.Thread(target=self._handle, args=(connection, deadline), daemon=True)
                    with self._lock:
                        self._threads.add(worker)
                    try:
                        worker.start()
                    except Exception:
                        with self._lock:
                            self._threads.discard(worker)
                        self._slots.release()
                        connection.close()
                        raise
        finally:
            self._listener = None
            if self._socket_inode is not None:
                try:
                    if self.path.lstat().st_ino == self._socket_inode:
                        self.path.unlink()
                except FileNotFoundError:
                    pass

    def stop(self):
        """Trusted in-process owner only; there is deliberately no shutdown RPC."""
        self._stop.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--manifest', required=True, help='JSON list of path/sha256/normalization bindings')
    parser.add_argument('--max-clients', type=int, default=4)
    parser.add_argument('--request-seconds', type=float, default=30)
    args = parser.parse_args()
    assets = json.loads(Path(args.manifest).read_text())
    service = TokenizerService(args.socket, assets, max_clients=args.max_clients,
                               request_seconds=args.request_seconds)
    import signal
    signal.signal(signal.SIGTERM, lambda *_: service.stop())
    signal.signal(signal.SIGINT, lambda *_: service.stop())
    service.serve(on_ready=lambda: print(json.dumps({'ready': True, 'protocol': PROTOCOL,
                                                    'instance': service.instance}), flush=True))


if __name__ == '__main__':
    main()
