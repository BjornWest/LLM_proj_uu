"""Offline wheel boundary check for capture assets and input-budget dependencies."""
import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import re
import zipfile


def verify(wheel, source):
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate wheel members')
        metadata = [name for name in names if name.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise ValueError('Expected one wheel metadata record')
        requirements = BytesParser().parsebytes(archive.read(metadata[0])).get_all('Requires-Dist', [])
        # Jinja is mandatory, not an optional-extra requirement.
        if not any(re.match(r'^jinja2(?:\s|[<>=!~;(]|$)', req, re.I)
                   and ';' not in req for req in requirements):
            raise ValueError('Missing unconditional Jinja2 dependency')
        asset = archive.read('intent_browser/observation_revision.js')
        if asset != Path(source).read_bytes():
            raise ValueError('Revision tracker differs from source')
    return {'passed': True, 'wheel_sha256': hashlib.sha256(Path(wheel).read_bytes()).hexdigest(),
            'revision_sha256': hashlib.sha256(asset).hexdigest(),
            'scope': 'Wheel asset bytes and direct Jinja2 dependency; no browser/model calls'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] /
                        'intent_browser/observation_revision.js')
    args = parser.parse_args()
    print(json.dumps(verify(args.wheel, args.source), indent=2))
