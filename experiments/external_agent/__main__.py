"""Local model endpoint for the EXISTING harness CLI/Python runner, not a new loop."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from .server import serve
from .episode_admission import EpisodeConcurrency


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
    server.add_argument('--suite-id', help='Explicit finite approved suite identity; required for parallel admission')
    server.add_argument('--max-concurrent-episodes', type=int, default=1)
    server.add_argument('--max-suite-episodes', type=int, help='Finite total starts (including failures); required with --suite-id')
    server.add_argument('--subscription-lock', type=Path, help='One canonical shared subscription lock for ALL frozen roots')
    server.add_argument('--episode-id', help='Stable unique episode identity; consumed once within a finite suite')
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
        try:
            if args.suite_id is not None:
                EpisodeConcurrency(args.suite_id, args.max_concurrent_episodes, args.max_suite_episodes)
                if args.subscription_lock is None or not args.episode_id:
                    raise ValueError('Suite mode requires --subscription-lock and a stable --episode-id')
            elif args.max_concurrent_episodes != 1 or args.max_suite_episodes is not None:
                raise ValueError('Parallel admission requires --suite-id and --max-suite-episodes')
        except ValueError as exc:
            p.error(str(exc))
        serve(args)


if __name__ == '__main__': main()
