"""Build cached P10 sources; --fetch restores missing small pinned files only."""
import argparse
import json
import subprocess
from pathlib import Path
try:
    from scripts.cache_pinned_source import checked_source
except ModuleNotFoundError:
    from cache_pinned_source import checked_source

ROOT = Path(__file__).resolve().parents[1]
REV = '8201821fb64a5075f50b015f99653881ab09a030'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='Restore missing pinned public sources; no dependency install')
    args = parser.parse_args()
    source = json.loads((ROOT/'environments/tricky_privacy/source-pins.json').read_text())
    if source['revision'] != REV:
        raise ValueError('Pinned source revision mismatch')
    local = ROOT/'.local/tricky-privacy'
    for name, pin in source['files'].items():
        target = local/'upstream'/name
        candidates = [ROOT/'.research/tricky-preflight'/name, ROOT/'.local/tricky/upstream'/name, target]
        cached = next((path for path in candidates if path.is_file()), target)
        raw = checked_source(cached, pin, fetch=args.fetch)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    # Restoration URLs are not changes to the already-reviewed source-manifest.
    record = {**source, 'files': {name: {key:value for key,value in pin.items() if key != 'url'} for name,pin in source['files'].items()}}
    (local/'source-manifest.json').write_text(json.dumps(record, indent=2))
    dependencies = ROOT/'environments/tricky_privacy/node_modules'
    if not dependencies.exists():
        dependencies.symlink_to(ROOT/'environments/tricky/node_modules', target_is_directory=True)
    subprocess.run(['node', str(ROOT/'environments/tricky_privacy/build.mjs')], check=True, cwd=ROOT)


if __name__ == '__main__':
    main()
