"""Read a pinned small source file, optionally restoring its public raw URL.

Callers own their cache and pin records. No credentials or inferred revisions.
"""
import hashlib
from pathlib import Path
from urllib.request import urlopen


def checked_source(path, pin, *, fetch=False):
    path = Path(path)
    if path.is_file():
        data = path.read_bytes()
    elif fetch:
        if not pin['url'].startswith('https://raw.githubusercontent.com/'):
            raise ValueError('Only explicitly pinned public GitHub source URLs are supported')
        if not 0 < pin['bytes'] <= 200_000:
            raise ValueError('Source size exceeds local fixture restoration bound')
        with urlopen(pin['url'], timeout=30) as response:
            data = response.read(pin['bytes'] + 1)
    else:
        raise FileNotFoundError(f'Pinned source cache missing: {path}. Run setup with --fetch to restore it.')
    if len(data) != pin['bytes'] or hashlib.sha256(data).hexdigest() != pin['sha256']:
        raise ValueError('Pinned source size/SHA256 mismatch: '+str(path))
    if pin.get('git_blob') and hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest() != pin['git_blob']:
        raise ValueError('Pinned Git blob mismatch: '+str(path))
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return data
