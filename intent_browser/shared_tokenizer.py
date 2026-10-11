"""Opt-in stateless tokenizer RPC. No episode histories or accounting are shared.

The server preloads an explicit digest allowlist. Clients cannot request file
loads, change tokenizer settings, stop the server, or trigger a local fallback.
Wire JSON preserves insertion order; text never enters diagnostics.
"""
from dataclasses import dataclass
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import socket
import stat
import struct
import time

PROTOCOL = 'shared-tokenizer-v1'
VERSION = '0.23.2'
MAX_FRAME_BYTES = 16 * 1024 * 1024


class SharedTokenizerError(RuntimeError):
    """Unavailable, mismatched or rejected service; never silently load locally."""


def asset_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _hash(value):
    return (isinstance(value, str) and len(value) == 64 and
            all(c in '0123456789abcdef' for c in value))


@dataclass(frozen=True)
class SharedTokenizerConfig:
    socket_path: str
    timeout_seconds: float = 30
    max_frame_bytes: int = MAX_FRAME_BYTES

    def __post_init__(self):
        if not isinstance(self.socket_path, str) or not Path(self.socket_path).is_absolute():
            raise ValueError('Shared tokenizer requires an absolute Unix socket path')
        if (type(self.timeout_seconds) not in (int, float) or
                not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 120):
            raise ValueError('Shared tokenizer timeout must be finite and at most 120 seconds')
        if type(self.max_frame_bytes) is not int or not 1024 <= self.max_frame_bytes <= MAX_FRAME_BYTES:
            raise ValueError('Shared tokenizer frame bound must be between 1024 and 16777216 bytes')

    def describe(self):
        return {'protocol': PROTOCOL, 'socket_path': self.socket_path,
                'timeout_seconds': self.timeout_seconds, 'max_frame_bytes': self.max_frame_bytes}


def _wire(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _receive(connection, count, deadline):
    chunks = bytearray()
    while len(chunks) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Tokenizer deadline exceeded')
        connection.settimeout(remaining)
        part = connection.recv(count - len(chunks))
        if not part:
            raise SharedTokenizerError('Tokenizer connection closed')
        chunks.extend(part)
    return bytes(chunks)


def receive_frame(connection, bound, deadline):
    length = struct.unpack('!I', _receive(connection, 4, deadline))[0]
    if not 0 < length <= bound:
        raise SharedTokenizerError('Tokenizer frame exceeds configured bound')
    return json.loads(_receive(connection, length, deadline))


def send_frame(connection, value, bound, deadline):
    data = _wire(value)
    if len(data) > bound:
        raise SharedTokenizerError('Tokenizer frame exceeds configured bound')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Tokenizer deadline exceeded')
    connection.settimeout(remaining)
    connection.sendall(struct.pack('!I', len(data)) + data)


@dataclass(frozen=True)
class Encoding:
    ids: list


class SharedTokenizer:
    def __init__(self, config, digest, normalization='raw'):
        if not isinstance(config, SharedTokenizerConfig):
            raise ValueError('Explicit SharedTokenizerConfig required')
        if not _hash(digest) or normalization not in ('raw', 'ascii-json'):
            raise ValueError('Qualified tokenizer digest and normalization required')
        if importlib.metadata.version('tokenizers') != VERSION:
            raise SharedTokenizerError('Qualified tokenizers version mismatch')
        self.config = config
        self.digest = digest
        self.normalization = normalization
        self._instance = None
        self._closed = False
        self._rpc('describe')  # Fail at construction, before episode dispatch.
        self.provenance = {**config.describe(), 'tokenizers_version': VERSION,
                           'tokenizer_sha256': digest, 'normalization': normalization}

    def _rpc(self, operation, **values):
        if self._closed:
            raise SharedTokenizerError('Tokenizer client closed')
        request = {'protocol': PROTOCOL, 'version': VERSION, 'asset': self.digest,
                   'normalization': self.normalization, 'operation': operation, **values}
        deadline = time.monotonic() + self.config.timeout_seconds
        try:
            info = os.lstat(self.config.socket_path)
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or
                    stat.S_IMODE(info.st_mode) != 0o600):
                raise SharedTokenizerError('Tokenizer socket owner/mode mismatch')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(max(0.001, deadline - time.monotonic()))
                connection.connect(self.config.socket_path)
                peer = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if peer[1] != os.getuid():
                    raise SharedTokenizerError('Tokenizer peer owner mismatch')
                send_frame(connection, request, self.config.max_frame_bytes, deadline)
                response = receive_frame(connection, self.config.max_frame_bytes, deadline)
        except (OSError, ValueError, SharedTokenizerError, TimeoutError):
            raise SharedTokenizerError('Shared tokenizer request unavailable or rejected; no fallback') from None
        identity = {'protocol': PROTOCOL, 'version': VERSION,
                    'asset': self.digest, 'normalization': self.normalization}
        if (not isinstance(response, dict) or response.get('ok') is not True or
                response.get('identity') != identity or not isinstance(response.get('instance'), str)):
            raise SharedTokenizerError('Shared tokenizer asset/protocol mismatch or request rejected')
        if self._instance is not None and self._instance != response['instance']:
            raise SharedTokenizerError('Shared tokenizer restarted; requalification required')
        self._instance = response['instance']
        return response.get('result')

    def encode(self, text, add_special_tokens=True):
        if not isinstance(text, str) or type(add_special_tokens) is not bool:
            raise ValueError('Tokenizer encode requires text and a boolean special-token flag')
        ids = self._rpc('encode', text=text, add_special_tokens=add_special_tokens)
        if not isinstance(ids, list) or any(type(i) is not int or not 0 <= i <= 0xffffffff for i in ids):
            raise SharedTokenizerError('Invalid token IDs returned')
        return Encoding(ids)

    def encode_batch(self, texts, add_special_tokens=True):
        if (not isinstance(texts, list) or any(not isinstance(t, str) for t in texts) or
                type(add_special_tokens) is not bool):
            raise ValueError('Tokenizer batch requires a list of texts and boolean flag')
        results = self._rpc('encode_batch', texts=texts, add_special_tokens=add_special_tokens)
        if (not isinstance(results, list) or len(results) != len(texts) or
                any(not isinstance(ids, list) or any(type(i) is not int or not 0 <= i <= 0xffffffff
                                                     for i in ids) for ids in results)):
            raise SharedTokenizerError('Invalid batched token IDs returned')
        return [Encoding(ids) for ids in results]

    def count_batch(self, texts):
        if not isinstance(texts, list) or any(not isinstance(t, str) for t in texts):
            raise ValueError('Tokenizer batch requires a list of texts')
        results = self._rpc('count_batch', texts=texts, add_special_tokens=False)
        if (not isinstance(results, list) or len(results) != len(texts) or
                any(type(i) is not int or i < 0 for i in results)):
            raise SharedTokenizerError('Invalid batched token counts returned')
        return results

    def decode_batch(self, sequences, skip_special_tokens=True):
        if (not isinstance(sequences, list) or type(skip_special_tokens) is not bool or
                any(not isinstance(ids, list) or any(type(i) is not int or not 0 <= i <= 0xffffffff
                                                     for i in ids) for ids in sequences)):
            raise ValueError('Tokenizer batch decode requires unsigned ID lists and boolean flag')
        results = self._rpc('decode_batch', sequences=sequences, skip_special_tokens=skip_special_tokens)
        if (not isinstance(results, list) or len(results) != len(sequences) or
                any(not isinstance(t, str) for t in results)):
            raise SharedTokenizerError('Invalid batched decoded text returned')
        return results

    def count(self, text, add_special_tokens=False):
        if not isinstance(text, str) or type(add_special_tokens) is not bool:
            raise ValueError('Tokenizer count requires text and a boolean special-token flag')
        result = self._rpc('count', text=text, add_special_tokens=add_special_tokens)
        if type(result) is not int or result < 0:
            raise SharedTokenizerError('Invalid token count returned')
        return result

    def decode(self, ids, skip_special_tokens=True):
        if (not isinstance(ids, list) or type(skip_special_tokens) is not bool or
                any(type(i) is not int or not 0 <= i <= 0xffffffff for i in ids)):
            raise ValueError('Tokenizer decode requires unsigned IDs and a boolean special-token flag')
        result = self._rpc('decode', ids=ids, skip_special_tokens=skip_special_tokens)
        if not isinstance(result, str):
            raise SharedTokenizerError('Invalid decoded text returned')
        return result

    def close(self):
        # There is no shared episode lease or shutdown RPC. Other clients live on.
        self._closed = True


def load_tokenizer(path, *, shared=None, normalization='raw'):
    if shared is not None:
        return SharedTokenizer(shared, asset_digest(path), normalization)
    from tokenizers import Tokenizer
    if normalization == 'ascii-json':
        return Tokenizer.from_str(json.dumps(json.loads(Path(path).read_text())))
    if normalization != 'raw':
        raise ValueError('Unknown tokenizer normalization')
    return Tokenizer.from_file(str(path))


def count_text(tokenizer, text):
    if isinstance(tokenizer, SharedTokenizer):
        return tokenizer.count(text, add_special_tokens=False)
    return len(tokenizer.encode(text, add_special_tokens=False).ids)
