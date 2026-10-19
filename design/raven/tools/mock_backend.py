#!/usr/bin/env python3
"""Offline Raven contract v1 server. Scripted fixtures, no browser/model calls.

python3 scripts/run_bounded_job.py --memory-mib 1024 -- python3 design/raven/tools/mock_backend.py --port 8767 --delay 2
Use a question containing [error] to exercise an error, or --error for all runs.
"""
import argparse
import base64
from datetime import datetime, timezone
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

WEB = Path(__file__).resolve().parents[1] / 'outputs' / 'raven'
sys.path.insert(0, str(WEB))
from server import Handler as PreviewHandler

SITES = [
    ('https://www.blender.org/', 'Blender'),
    ('https://developer.mozilla.org/', 'MDN Web Docs'),
    ('https://en.wikipedia.org/wiki/Common_raven', 'Wikipedia'),
]
ICON = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')


class Run:
    def __init__(self, payload, delay, error):
        self.payload, self.delay, self.error = payload, delay, error
        self.events = []
        self.condition = threading.Condition()
        self.cancelled = threading.Event()
        self.done = False
        threading.Thread(target=self.produce, daemon=True).start()

    def emit(self, event):
        with self.condition:
            if self.done:
                return
            self.events.append(event)
            if event['type'] == 'done':
                self.done = True
            self.condition.notify_all()

    def cancel(self):
        self.cancelled.set()
        self.emit({'type': 'done', 'stop_reason': 'cancelled'})

    def produce(self):
        self.emit({'type': 'status', 'state': 'starting'})
        for index, (url, title) in enumerate(SITES, 1):
            if self.cancelled.wait(self.delay):
                return
            self.emit({'type': 'status', 'state': 'working'})
            self.emit({'type': 'tab', 'action': 'opened', 'tab_id': str(index), 'url': url, 'title': title, 'owner': 'agent'})
            self.emit({'type': 'site', 'url': url, 'title': title, 'favicon': urlsplit(url)._replace(path='/favicon.ico', query='', fragment='').geturl(), 'tab_id': str(index)})
            self.emit({'type': 'step', 'index': index, 'summary': f'Checking {title} ({index}/3)'})
        if self.cancelled.wait(self.delay):
            return
        if self.error or '[error]' in self.payload['text'].lower():
            self.emit({'type': 'error', 'message': 'Scripted offline error. Please try another question.'})
            self.emit({'type': 'done', 'stop_reason': 'error'})
            return
        self.emit({'type': 'status', 'state': 'finishing'})
        sources = [{'id': f'site-{i}', 'kind': 'review', 'url': url, 'title': title, 'siteName': title,
                    'evidence': f'Offline scripted fixture for {title}; this excerpt was not fetched from the live website.',
                    'checkedAt': datetime.now(timezone.utc).isoformat(), 'illustrative': True}
                   for i, (url, title) in enumerate(SITES, 1)]
        self.emit({'type': 'final', 'markdown': '## Offline research complete\n\n**Scripted demo:** no live research was performed.\n\n'
                   'These sample visits demonstrate background research and captured citation cards.\n\n'
                   '| Website | Example topic |\n| --- | --- |\n| Blender [[site-1]] | 3D creation |\n'
                   '| MDN Web Docs [[site-2]] | Web documentation |\n| Wikipedia [[site-3]] | The common raven |', 'sources': sources})
        self.emit({'type': 'done', 'stop_reason': 'completed'})


class Handler(PreviewHandler):
    def json(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self.allowed_client():
            self.send_error(403)
            return
        path = urlsplit(self.path).path.strip('/').split('/')
        payload = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or '{}')
        if path == ['api', 'tasks']:
            run_id = uuid4().hex
            self.server.runs[run_id] = Run(payload, self.server.delay, self.server.error)
            self.json({'run_id': run_id})
        elif len(path) == 4 and path[:2] == ['api', 'tasks'] and path[2] in self.server.runs:
            if path[3] == 'cancel':
                self.server.runs[path[2]].cancel()
                self.json({'cancelled': True})
            elif path[3] == 'handback':
                self.json({'ok': True})
            else:
                self.send_error(404)
        elif len(path) == 4 and path[:2] == ['api', 'tabs'] and path[3] == 'focus':
            self.json({'ok': True})
        else:
            self.send_error(404)

    def do_GET(self):
        if not self.allowed_client():
            self.send_error(403)
            return
        parsed = urlsplit(self.path)
        path = parsed.path.strip('/').split('/')
        if path == ['api', 'health']:
            self.json({'ok': True, 'model': 'offline-scripted-mock', 'modes': ['background'], 'metadata': {'tags': ['scripted']}})
        elif path == ['api', 'tabs']:
            self.json({'tabs': [{'tab_id': str(i), 'url': url, 'title': title, 'owner': 'agent', 'active': i == 3} for i, (url, title) in enumerate(SITES, 1)]})
        elif path == ['api', 'link-preview']:
            url = parse_qs(parsed.query).get('url', [''])[0]
            self.json({'status': 'unavailable', 'url': url})
        elif path == ['api', 'link-preview-image']:
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(ICON)))
            self.end_headers()
            self.wfile.write(ICON)
        elif len(path) == 4 and path[:2] == ['api', 'tasks'] and path[3] == 'events' and path[2] in self.server.runs:
            run = self.server.runs[path[2]]
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            cursor = 0
            try:
                while True:
                    with run.condition:
                        run.condition.wait_for(lambda: len(run.events) > cursor or run.done, timeout=10)
                        events, done = run.events[cursor:], run.done
                        cursor = len(run.events)
                    for event in events:
                        self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
                    self.wfile.flush()
                    if done:
                        break
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            super().do_GET()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--delay', type=float, default=2, help='Seconds before each of three sites and the final event')
    parser.add_argument('--error', action='store_true')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(WEB)))
    server.daemon_threads = True
    server.runs, server.delay, server.error = {}, args.delay, args.error
    print(f'Offline scripted Raven: http://localhost:{args.port}/chat-fullpage-v42.html (delay={args.delay}s)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
