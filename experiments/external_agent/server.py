"""Thin authenticated Chat Completions facade. No browser/task/prompt code here."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import uuid

from intent_browser.backend import BackendResponseError
from .backend import ExternalAgentBackend, save
from .episode_admission import EpisodeConcurrency
from .subscription_quota import SubscriptionQuotaGuard


class BridgeServer(ThreadingHTTPServer):
    # server_close waits for the bounded current request before releasing the
    # subscription lock; stopping the listener must not orphan a live worker.
    daemon_threads = False
    def __init__(self, backend, token, *, port=0, max_requests=200):
        self.backend, self.token = backend, token
        self.max_requests, self.attempts = max_requests, 0
        self.dispatch_lock = threading.Lock()
        super().__init__(('127.0.0.1', port), Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def reply(self, status, payload):
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded))); self.end_headers()
        try: self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError): pass

    def do_POST(self):
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + self.server.token):
            return self.reply(401, {'error': 'Local bridge credential required'})
        if self.path != '/v1/chat/completions':
            return self.reply(404, {'error': 'Only chat completions are exposed'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(415, {'error': 'JSON required'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 64 * 1024 * 1024: raise ValueError()
        except ValueError:
            return self.reply(413, {'error': 'Missing or excessive request length'})
        if not self.server.dispatch_lock.acquire(blocking=False):
            return self.reply(409, {'error': 'One request per episode at a time'})
        try:
            if self.server.attempts >= self.server.max_requests:
                return self.reply(429, {'error': 'Declared request allowance exhausted; no dispatch'})
            self.connection.settimeout(15)
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict): raise ValueError()
            self.server.attempts += 1
            result = self.server.backend.complete_request(request)
            return self.reply(200, result.raw)
        except BackendResponseError as exc:
            return self.reply(502, {'error': str(exc), 'upstream_status': exc.http_status,
                                    'bridge_response': exc.response_payload})
        except (ValueError, KeyError, TypeError, TimeoutError):
            return self.reply(400, {'error': 'Unsupported request; no automatic retry'})
        finally:
            self.server.dispatch_lock.release()


def serve(args):
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    source_files = [*Path(__file__).parent.glob('*.py'), *Path(__file__).parent.glob('*.mjs')]
    if getattr(args, 'suite_id', None):
        # Resolve the actual module used by the guard in this frozen runtime,
        # rather than assuming a location relative to a copied bridge package.
        from scripts import product_width_watch
        source_files.append(Path(product_width_watch.__file__))
    hashes = {str(f.resolve()): hashlib.sha256(f.read_bytes()).hexdigest() for f in source_files}
    def unchanged():
        if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != h for p, h in hashes.items()):
            raise RuntimeError('Bridge source changed; stop and prepare a new bridge')
    suite_id = getattr(args, 'suite_id', None)
    config = EpisodeConcurrency(suite_id, args.max_concurrent_episodes, args.max_suite_episodes) if suite_id else None
    quota_guard = SubscriptionQuotaGuard(output / 'quota', remaining_floor=1) if config else None
    backend = ExternalAgentBackend(args.model, output / 'transport', timeout=args.timeout,
        reasoning_effort=args.reasoning_effort, before_dispatch=unchanged,
        provider_output_limit=args.provider_output_limit,
        lock_path=getattr(args, 'subscription_lock', None), episode_concurrency=config, quota_guard=quota_guard)
    token = secrets.token_urlsafe(32)
    session_id = getattr(args, 'episode_id', None) or str(uuid.uuid4())
    try:
        admission = backend.begin_episode(session_id)
        server = BridgeServer(backend, token, port=args.port, max_requests=args.max_requests)
        base_url = f'http://127.0.0.1:{server.server_port}/v1'
        envfile = output / 'bridge.env'
        fd = os.open(envfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(f'MODEL_BASE_URL={base_url}\nMODEL_NAME={args.model}\nEXTERNAL_BRIDGE_KEY={token}\n')
        save(output / 'server.json', {'base_url': base_url, 'model': args.model,
            'credential_file': str(envfile), 'pid': os.getpid(), 'session_id': session_id,
            'max_requests': args.max_requests, 'reasoning_effort': args.reasoning_effort,
            'sources': hashes, 'policy_owner': 'existing intent_browser runner',
            'tools_executed_by_bridge': [], 'model_calls_at_start': 0,
            'usage_scope': 'Explicit finite authorized suite; no automatic retries or paid fallback' if config else
                           'Small-scale supervised development only; not bulk evaluation/training',
            'episode_admission': admission,
            'minimum_client_timeout_seconds': args.timeout + 10 + admission.get('admission_wait_seconds', 0),
            'subscription_remaining_floor_percent': 1 if config else None,
            'output_limit': 'provider_default (explicit override)' if args.provider_output_limit else
                            'Forwarded as max_output_tokens; subscription endpoint rejects this parameter'})
        print(json.dumps({'base_url': base_url, 'model': args.model, 'credential_file': str(envfile),
                          'note': 'Use the existing harness. Stop this bridge after its one episode.'}), flush=True)
        try: server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt: pass
        finally: server.server_close()
    finally: backend.close()
