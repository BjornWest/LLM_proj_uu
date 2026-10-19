"""Verify this curated asset import. Standard library only; no browser/network/model calls."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import hashlib
import json
import sys

PACKAGE = Path(__file__).resolve().parent.parent
REPOSITORY = PACKAGE.parent.parent
WEB = PACKAGE / 'outputs' / 'raven'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.references = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.append(attrs['id'])
        for key in ('src', 'href'):
            if attrs.get(key):
                self.references.append(attrs[key])


def verify():
    manifest = json.loads((PACKAGE / 'manifest.json').read_text(encoding='utf-8'))
    checked = 0
    for item in manifest['files']:
        path = (REPOSITORY / item['path']).resolve()
        assert path.is_relative_to(REPOSITORY.resolve()), 'Escaping manifest path: ' + item['path']
        assert path.is_file(), 'Missing: ' + item['path']
        assert path.stat().st_size == item['bytes'], 'Size mismatch: ' + item['path']
        assert sha(path) == item['sha256'], 'Hash mismatch: ' + item['path']
        checked += 1
    html_checked = 0
    for page in sorted(WEB.glob('*.html')):
        parsed = References()
        parsed.feed(page.read_text(encoding='utf-8'))
        assert len(parsed.ids) == len(set(parsed.ids)), 'Duplicate HTML IDs: ' + page.name
        for reference in parsed.references:
            url = urlsplit(reference)
            if url.scheme or url.netloc or not url.path or url.path.startswith('/api/'):
                continue
            path = (WEB / unquote(url.path.lstrip('/')) if url.path.startswith('/') else page.parent / unquote(url.path)).resolve()
            assert path.is_relative_to(WEB.resolve()) and path.is_file(), f'{page.name}: missing local reference {reference}'
        html_checked += 1
    bank = json.loads((WEB / 'live-raven-v34.json').read_text(encoding='utf-8'))
    binary = WEB / bank['binary']['uri']
    sizes = {'Float32': 4, 'Uint16': 2, 'Uint32': 4}
    for item in bank['arrays']:
        assert item['byteOffset'] >= 0 and item['count'] >= 0
        assert item['byteOffset'] + item['count'] * sizes[item['type']] <= binary.stat().st_size
    required = {'perch', 'idle', 'pet', 'caw', 'takeoff', 'glide', 'glide_right', 'diving', 'attention'}
    assert required.issubset(bank['clips']), 'Missing native clips'
    for directory in ('vendor-v33', 'vendor-v34'):
        vendor = json.loads((WEB / directory / 'manifest.json').read_text(encoding='utf-8'))
        if 'libraries' in vendor:
            for item in vendor['libraries']:
                assert sha(WEB / directory / item['file']) == item['sha256']
                assert sha(WEB / directory / item['licenseFile']) == item['licenseSha256']
        else:
            for name, item in vendor['files'].items():
                assert sha(WEB / directory / name) == item['sha256']
    return {'status': 'passed', 'hashedFiles': checked, 'htmlPages': html_checked,
            'bankClips': len(bank['clips']), 'bankArrays': len(bank['arrays']),
            'binaryBytes': binary.stat().st_size, 'vendorLicenses': 'verified',
            'scope': 'offline asset integrity and local references; no harness/model episode'}


if __name__ == '__main__':
    try:
        print(json.dumps(verify(), indent=2))
    except (AssertionError, KeyError, OSError, ValueError) as error:
        print('Raven export verification failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
