"""Serve a policy-only task card bound to an already running connected world.

This process does not publish a second world and has no oracle or grading routes.
The trusted runtime output directory contains manifest.json and provenance.json.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
from threading import Event,Thread
from types import SimpleNamespace
from urllib.request import urlopen

from .episode import Episode


class PolicyHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

    def do_GET(self):
        if self.path=='/':self.path='/task.html'
        if self.path not in ('/task.html','/task.json'):
            self.send_error(404);return
        super().do_GET()

    def do_HEAD(self):
        if self.path=='/':self.path='/task.html'
        if self.path not in ('/task.html','/task.json'):
            self.send_error(404);return
        super().do_HEAD()

    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
        super().end_headers()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',type=Path,required=True)
    parser.add_argument('--runtime-output',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args()
    manifest=json.loads((args.runtime_output/'manifest.json').read_text())
    descriptor=SimpleNamespace(public_manifest=manifest,index_origin=manifest['index_url'],
        provenance=json.loads((args.runtime_output/'provenance.json').read_text()))
    if descriptor.provenance.get('comparison_coverage_sha256') is not None:
        descriptor.comparison_coverage=json.loads((args.runtime_output/'comparison-coverage.json').read_text())
        descriptor.bindings=json.loads((args.runtime_output/'bindings.json').read_text())
    if descriptor.provenance.get('product_review_evidence_sha256') is not None:
        descriptor.product_review_evidence=json.loads((args.runtime_output/'product-review-evidence.private.json').read_text())
    if descriptor.provenance.get('interaction_patterns_sha256') is not None:
        descriptor.interaction_patterns=json.loads((args.runtime_output/'interaction-patterns.public.json').read_text())
    if descriptor.provenance.get('storefront_content_sha256') is not None:
        descriptor.storefront_content=json.loads((args.runtime_output/'storefront-content.public.json').read_text())
    episode=Episode.from_runtime(json.loads(args.scenario.read_text()),descriptor)
    with urlopen(episode.policy_input()['start_url'],timeout=10) as response:
        if response.status!=200:raise ValueError('Connected index is not available')
    args.output.mkdir(parents=True,exist_ok=False)
    public=args.output/'public';episode.write_policy_bundle(public)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(PolicyHandler,directory=str(public.resolve())))
    stop=Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    task_url=f'http://localhost:{server.server_port}/task.html'
    metadata={'pid':os.getpid(),'task_url':task_url,'index_url':manifest['index_url'],
              'episode_id':episode.episode_id,'runtime_output':str(args.runtime_output),
              'scenario':str(args.scenario),'scope':'Policy-only task delivery; no oracle HTTP routes'}
    (args.output/'process.json').write_text(json.dumps(metadata,indent=2)+'\n')
    thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True);thread.start()
    print(json.dumps(metadata),flush=True)
    try:stop.wait()
    finally:server.shutdown();server.server_close();thread.join(timeout=2)


if __name__=='__main__':main()
