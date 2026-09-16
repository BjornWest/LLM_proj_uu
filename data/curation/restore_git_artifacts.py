"""Restore missing archived artifacts from pinned Git history, without overwrites.

Default is verification only. No network, inference, or budget initialization.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name('git_artifact_retention_v1.json')


def restore(destination, restore_missing=False):
    manifest = json.loads(MANIFEST.read_text())
    destination = Path(destination).resolve()
    checked = restored = missing = 0
    for row in manifest['files']:
        if row['kind'] == 'runtime_lock':
            continue  # Processes create their own locks; never replace live inodes.
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe manifest path')
        target = destination / relative
        if target.is_symlink() or not target.resolve().is_relative_to(destination):
            raise ValueError('Unsafe destination: ' + row['path'])
        if target.exists():
            raw = target.read_bytes()
        elif restore_missing:
            raw = subprocess.check_output(
                ['git', 'cat-file', 'blob', row['git_blob']], cwd=ROOT)
        else:
            missing += 1
            continue
        if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('Different content; leaving untouched: ' + row['path'])
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(raw)
            restored += 1
        checked += 1
    return {'verified': checked, 'restored': restored, 'missing': missing}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore-missing', action='store_true')
    parser.add_argument('--destination', type=Path, default=ROOT)
    args = parser.parse_args()
    result = restore(args.destination, args.restore_missing)
    print(json.dumps(result))
    raise SystemExit(1 if result['missing'] else 0)
