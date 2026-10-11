"""Narrow authenticated Modal relay and loopback client bridge for this pilot."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit
import hmac
import json
import time

ALLOW = {('GET', '/health'), ('GET', '/v1/models'), ('GET', '/tokenizer_info'),
         ('GET', '/qualification'), ('POST', '/tokenize'),
         ('POST', '/v1/chat/completions')}
MAX_BODY = 64 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def tokenize_payload(body):
    # Exact prompt fields shared with pinned ChatCompletionRequest. Sampling and
    # output limits do not change prompt rendering. Never silently drop extras.
    if set(body) - {'model', 'messages', 'temperature', 'max_tokens', 'stream',
                    'tools', 'tool_choice', 'parallel_tool_calls'}:
        raise ValueError('Unqualified complete-request fields')
    if body.get('stream') is not False:
        raise ValueError('This pilot qualifies non-streaming chat only')
    if body.get('tool_choice', 'auto') not in {'auto', 'none'}:
        raise ValueError('Unqualified tool_choice')
    if body.get('tools') and body.get('tool_choice') == 'none':
        raise ValueError('Tool schema with tool_choice none is outside this pilot')
    result = deepcopy({k: body[k] for k in ('model', 'messages')})
    # vLLM 0.28 ChatCompletionRequest performs this alias normalization;
    # TokenizeChatRequest does not. Match generation's canonical reasoning
    # precedence in a count-only copy, preserving the original generation wire.
    for message in result['messages']:
        reasoning_content = message.pop('reasoning_content', None)
        if reasoning_content is not None and message.get('reasoning') is None:
            message['reasoning'] = reasoning_content
    if body.get('tools') and body.get('tool_choice', 'auto') != 'none':
        result['tools'] = deepcopy(body['tools'])
    return result


def handler(*, upstream, token=None, add_token=None, qualification=None,
            deadline=None, transform_tokens=False):
    u = urlsplit(upstream)
    if u.path not in {'', '/'} or u.query or u.fragment or u.username or u.password:
        raise ValueError('Bare upstream origin required')
    connection = HTTPSConnection if u.scheme == 'https' else HTTPConnection
    if u.scheme not in {'https', 'http'}:
        raise ValueError('HTTP(S) upstream required')

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass  # Do not print headers, credentials, prompts or tunnel URLs.

        def reply(self, status, body, content_type='application/json'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch()

        def dispatch(self):
            if token and not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                return self.reply(401, b'{"error":"unauthorized"}')
            if (self.command, self.path) not in ALLOW:
                return self.reply(404, b'{"error":"route not allowed"}')
            if deadline and time.time() >= deadline:
                return self.reply(503, b'{"error":"pilot deadline expired"}')
            if self.path == '/qualification' and qualification is not None:
                return self.reply(200, canonical(qualification))
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > MAX_BODY or self.headers.get('Transfer-Encoding'):
                    return self.reply(413, b'{"error":"bounded content length required"}')
                self.connection.settimeout(30)
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError('Truncated request')
                timeout = min(600, max(1, deadline-time.time())) if deadline else 600
                conn = connection(u.hostname, u.port, timeout=timeout)
                try:
                    headers = {'Content-Type': 'application/json'}
                    if add_token:
                        headers['Authorization'] = 'Bearer ' + add_token
                    conn.request(self.command, self.path, body=body, headers=headers)
                    response = conn.getresponse()
                    data = response.read(MAX_BODY + 1)
                    if len(data) > MAX_BODY:
                        raise ValueError('Response exceeds relay bound')
                    if transform_tokens and self.path == '/tokenize' and response.status == 200:
                        value = json.loads(data)
                        ids = value.pop('tokens')
                        if len(ids) != value['count']:
                            raise ValueError('Server token count inconsistent')
                        value.pop('token_strs', None)
                        value['token_ids_sha256'] = sha256(canonical(ids)).hexdigest()
                        data = canonical(value)
                    return self.reply(response.status, data, response.getheader('Content-Type', 'application/json'))
                finally:
                    conn.close()
            except (OSError, ValueError, KeyError, TimeoutError):
                self.reply(502, b'{"error":"relay transport failure"}')

    return Handler


@contextmanager
def serve(address, **kwargs):
    server = ThreadingHTTPServer(address, handler(**kwargs))
    server.daemon_threads = True
    server.timeout = .5
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
