"""Prepare pinned membership source; --fetch restores a missing 5,209-byte cache."""
import argparse
import json
from pathlib import Path
try:
    from scripts.cache_pinned_source import checked_source
except ModuleNotFoundError:
    from cache_pinned_source import checked_source

ROOT = Path(__file__).resolve().parents[1]
REV = '8201821fb64a5075f50b015f99653881ab09a030'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='Restore missing pinned public source; no dependency install')
    args = parser.parse_args()
    source = json.loads((ROOT/'environments/tricky_membership/source-pins.json').read_text())
    if source['revision'] != REV:
        raise ValueError('Pinned revision mismatch')
    local = ROOT/'.local/tricky-membership'
    for name, pin in source['files'].items():
        data = checked_source(ROOT/'.research/tricky-preflight'/name, pin, fetch=args.fetch)
        target = local/'upstream'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    # URL is restoration metadata, not a change to the historical source-manifest.
    record = {**source, 'files': {name: {k:v for k,v in pin.items() if k != 'url'} for name,pin in source['files'].items()}}
    (local/'source-manifest.json').write_text(json.dumps(record, indent=2))
    print('Verified pinned membership source; dependencies are installed separately.')


if __name__ == '__main__':
    main()
