"""Generate or serve a fresh conditioned native or accepted-catalog world; never invokes a model."""
import argparse
import json
from pathlib import Path
from threading import Event

from environments.website_world.generation import GeneratedEpisode, SamplingBudgetExceeded, prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('generate', 'serve'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-output',type=Path,help='Optional fresh private runtime/URL-binding export directory')
    args = parser.parse_args()
    if args.mode == 'generate':
        if args.config is None:
            parser.error('generate requires --config')
        request = json.loads(args.config.read_text())
        try:
            result = prepare(request, args.output)
        except SamplingBudgetExceeded as error:
            print(json.dumps({'status': 'budget_exhausted', 'feasibility': 'unknown',
                'audit': str(args.output/'sampling-audit.private.json'),
                'proposals': len(error.audit['proposals'])}), flush=True)
            raise SystemExit(2)
        print(json.dumps({'output': str(args.output.resolve()), 'world_id': result['world_id'],
            'summary': result['summary'], 'model_runs': 0}), flush=True)
    else:
        with GeneratedEpisode(args.output) as episode:
            if args.runtime_output is not None:episode.export_private_runtime(args.runtime_output)
            print(json.dumps({'start_url': episode.public['start_url'],
                'user_message': episode.public['user_message'],
                'memories': episode.public['memories'],
                'retailers': episode.runtime.manifest['sites'], 'model_runs': 0}), flush=True)
            try:
                # Serve until the process is stopped; no inference client exists.
                Event().wait()
            except KeyboardInterrupt:
                pass


if __name__ == '__main__':
    main()
