"""List/select a Chaos task or inspect an existing session's upstream score.

Prefer the harness --chaos-task integration for automatically isolated sessions
and evaluation. This helper never mounts or performs task actions.
"""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from intent_browser.chaos import ChaosClient
from intent_browser.trace import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True, help='Agent port printed by Chaos')
    parser.add_argument('--task-id', help='Stable task ID, required when creating a session')
    parser.add_argument('--list', action='store_true', help='List public IDs without creating a session')
    parser.add_argument('--session-file', type=Path, help='New unique file by default; required for --score')
    parser.add_argument('--score', action='store_true')
    parser.add_argument('--episode-dir', type=Path, help='Attach raw score to a matching completed episode')
    args = parser.parse_args()
    if args.list and (args.task_id or args.score or args.session_file or args.episode_dir):
        parser.error('--list cannot be combined with session options')
    if args.score and not args.session_file:
        parser.error('--score requires the exact --session-file')
    if not args.list and not args.score and not args.task_id:
        parser.error('Specify --task-id; use --list to see available tasks')
    try:
        client = ChaosClient(args.base_url)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        if args.list:
            print(json.dumps(client.catalogue(), indent=2))
            return
        if args.score:
            session = json.loads(args.session_file.read_text())
            if session.get('base_url', client.base_url) != client.base_url:
                parser.error('Session base URL does not match --base-url')
            if args.episode_dir:
                task_path = args.episode_dir / 'task.json'
                if not (args.episode_dir / 'episode.json').is_file() or not task_path.is_file():
                    parser.error('Score attachment requires an episode with matching task.json provenance')
                task = json.loads(task_path.read_text())
                if task.get('session') != session['session']:
                    parser.error('Refusing to attach another session\'s score')
            score = client.score(session)
            score_path = args.session_file.with_suffix('.score.json')
            write_json(score_path, score)
            if args.episode_dir:
                # Preserve the automatic terminal evaluation and event evidence.
                write_json(args.episode_dir / ('external-score-refresh-' + uuid4().hex[:8] + '.json'), score)
            print(json.dumps(score, indent=2))
            print(f'Saved {score_path}')
            return
        path = args.session_file or Path('runs/chaos-sessions') / (uuid4().hex + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        # Reserve exclusively before creating a server session; never overwrite.
        with path.open('x', encoding='utf-8') as stream:
            session = client.prepare(args.task_id)
            json.dump(session, stream, indent=2)
        print(f"Session: {session['session']}\nTask ID: {session['source_task_id']}")
        print(f"Task: {client.base_url}{session['selected']['taskUrl']}\nCatalogue: {path}")
    finally:
        client.close()


if __name__ == '__main__':
    main()
