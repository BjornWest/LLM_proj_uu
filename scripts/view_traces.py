"""Launch common_agent_util's read-only BrowserGym episode viewer."""
import argparse
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--common-util', type=Path, default=root.parent / 'common_agent_util')
    parser.add_argument('--runs', type=Path, help='View only this directory (legacy single-source mode)')
    parser.add_argument('--registry', type=Path, default=root / '.local/trace-viewer/sources.json', help='Trusted trace roots/patterns for the shared viewer')
    parser.add_argument('--port', type=int, default=8878)
    args = parser.parse_args()
    if (args.common_util / 'agent_trace/adapters/browsergym.py').is_file():
        sys.path.insert(0, str(args.common_util.resolve()))
    try:
        from agent_trace.adapters import browsergym  # noqa: F401
        from agent_trace.cli import main as serve
    except ImportError:
        parser.error('Use the common_agent_util checkout with BrowserGym support alongside this repo, '
                     'or specify --common-util PATH, or install that package.')
    if args.runs is not None:
        serve(['serve', '--runs', str(args.runs), '--port', str(args.port)])
    else:
        import json
        if not args.registry.exists():
            args.registry.parent.mkdir(parents=True,exist_ok=True)
            args.registry.write_text(json.dumps({'project_root':str(root),'roots':[str(root/'runs')],
                'patterns':['.local/real-web-*/runs','.local/synthetic-*/live/runs']},indent=2))
        try:
            from .trace_hub import serve as serve_hub
        except ImportError:
            from trace_hub import serve as serve_hub
        serve_hub(args.registry,args.port)


if __name__ == '__main__':
    main()
