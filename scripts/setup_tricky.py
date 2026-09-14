"""Fetch the pinned shopping import closure, retaining source/blob evidence.

No full benchmark checkout, analytics, model requests or training data. Download
is capped at 25 MiB; cached files are reused after Git blob verification.
"""
import hashlib
import json
import posixpath
import re
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REV = '8201821fb64a5075f50b015f99653881ab09a030'
DEST = ROOT / '.local/tricky/upstream'
LIMIT = 25 * 1024 * 1024


def main():
    tree_path = ROOT / '.local/tricky/source-tree.json'
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    if not tree_path.exists():
        with urlopen(f'https://api.github.com/repos/devinat1/agenttrickydps/git/trees/{REV}?recursive=1') as r:
            tree_path.write_bytes(r.read())
    tree = json.loads(tree_path.read_text())
    assert tree['sha'] == REV and not tree.get('truncated')
    blobs = {r['path']: r for r in tree['tree'] if r['type'] == 'blob'}
    pending = ['src/components/ShoppingSite.jsx']
    records = {}
    total = 0
    while pending:
        path = pending.pop()
        if path in records:
            continue
        blob = blobs[path]
        total += blob['size']
        if total > LIMIT:
            raise ValueError('Source closure exceeds the 25 MiB download limit')
        output = DEST / path
        output.parent.mkdir(parents=True, exist_ok=True)
        cache = ROOT / '.research/tricky-preflight' / path
        if not output.exists():
            if cache.exists():
                data = cache.read_bytes()
            else:
                with urlopen(f'https://raw.githubusercontent.com/devinat1/agenttrickydps/{REV}/{path}', timeout=30) as response:
                    data = response.read(LIMIT + 1)
            output.write_bytes(data)
        data = output.read_bytes()
        assert len(data) == blob['size']
        assert hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest() == blob['sha'], path
        records[path] = {'git_blob': blob['sha'], 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        if output.suffix in ('.js', '.jsx', '.css'):
            source = '\n'.join(line for line in data.decode().splitlines() if not line.lstrip().startswith('//'))
            for name in re.findall(r'(?:from\s+|import\s+)[\'"]([^\'"]+)[\'"]', source):
                if not name.startswith('.'):
                    continue
                base = posixpath.normpath(posixpath.join(posixpath.dirname(path), name))
                matches = [p for p in (base, base+'.jsx', base+'.js', base+'/index.jsx', base+'/index.js') if p in blobs]
                if len(matches) != 1:
                    raise ValueError(f'Unresolved or ambiguous import {path}: {name}')
                pending.append(matches[0])
    report = {'repository': 'devinat1/agenttrickydps', 'revision': REV, 'files': records,
              'total_bytes': total, 'scope': 'Unmodified shopping import closure; local-only source cache.'}
    (ROOT / '.local/tricky/source-manifest.json').write_text(json.dumps(report, indent=2))
    print(f'Verified {len(records)} files; {total / 1024**2:.2f} MiB in {DEST}')


if __name__ == '__main__':
    main()
