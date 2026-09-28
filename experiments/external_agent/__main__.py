"""Local model endpoint for the EXISTING harness CLI/Python runner, not a new loop."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from .server import serve


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode', required=True)
    sub.add_parser('inspect', help='List installed models without authenticating or running inference')
    server = sub.add_parser('serve', help='One-episode loopback model endpoint; no browser or tools of its own')
    server.add_argument('--model', required=True)
    server.add_argument('--output', type=Path, required=True, help='New artifact directory')
    server.add_argument('--reasoning-effort', choices=['low', 'medium', 'high', 'xhigh'], default='medium')
    server.add_argument('--max-requests', type=int, default=200)
    server.add_argument('--timeout', type=float, default=180)
    server.add_argument('--port', type=int, default=0)
    server.add_argument('--provider-output-limit', action='store_true',
        help='Explicit opt-in: subscription endpoint rejects max_output_tokens; record provider-default output limit')
    args = p.parse_args()
    if args.mode == 'inspect':
        envelope = {'version': 1, 'id': 'inspect', 'pi_cli': shutil.which('pi'), 'timeout_ms': 1000}
        result = subprocess.run(['node', str(Path(__file__).with_name('worker.mjs'))],
            input=json.dumps(envelope), text=True, capture_output=True, check=True)
        print(result.stdout)
    else:
        if not 1 <= args.max_requests <= 200 or args.timeout <= 0 or not 0 <= args.port <= 65535:
            p.error('Use 1..200 requests, a positive timeout and valid loopback port')
        serve(args)


if __name__ == '__main__': main()
