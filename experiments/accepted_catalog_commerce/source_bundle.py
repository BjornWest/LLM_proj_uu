"""Immutable content-addressed source archives with verified detached handles."""
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import MappingProxyType
import json
import os
import tempfile

VERSION = 'accepted-catalog-source-bundle-v1'


def _path(name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('Source paths must be canonical repository-relative paths')
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in ('.', '..') for p in name.split('/')) or str(path) != name:
        raise ValueError('Source paths must be canonical repository-relative paths')
    return name


def _hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Invalid SHA-256 identity')
    return value


def _inside(root, relative):
    result = (root / relative).resolve()
    if not result.is_relative_to(root):
        raise ValueError('Archive path escapes designated root')
    return result


def _bytes(manifest):
    return (json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, separators=(',', ':')) + '\n').encode()


def _atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Existing immutable archive object is corrupt: ' + str(path))
        return
    fd, temp = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Link only the fresh immutable temporary object, never a working-tree file.
        try:
            os.link(temp, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError('Existing immutable archive object is corrupt: ' + str(path))
    finally:
        os.unlink(temp)


class Bundle:
    __slots__ = ('__manifest', '__blobs', '__id')

    def __init__(self, identity, manifest, blobs):
        self.__id = identity
        self.__manifest = MappingProxyType(dict(manifest['source_sha256']))
        self.__blobs = MappingProxyType(dict(blobs))

    @property
    def descriptor(self):
        return {'schema_version': VERSION, 'bundle_id': self.__id,
                'source_sha256': dict(self.__manifest)}

    def read(self, repo_relative_path):
        name = _path(repo_relative_path)
        if name not in self.__manifest:
            raise ValueError('Path is not declared in source bundle')
        return self.__blobs[self.__manifest[name]]

    def materialize(self, output):
        root = Path(output).resolve()
        root.mkdir(parents=True, exist_ok=False)
        for name in self.__manifest:
            target = _inside(root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(self.read(name))
        return self.descriptor


def capture(source_sha256, *, repository_root, store):
    if not isinstance(source_sha256, dict):
        raise ValueError('Supply the complete source path/hash map')
    sources = {_path(n): _hash(h) for n, h in source_sha256.items()}
    root, archive = Path(repository_root).resolve(), Path(store).resolve()
    manifest = {'schema_version': VERSION, 'source_sha256': sources}
    raw_manifest = _bytes(manifest)
    identity = sha256(raw_manifest).hexdigest()
    # Manifest is committed last. Failed captures retain unreferenced complete blobs.
    committed = set()
    for name, expected in sources.items():
        raw = _inside(root, name).read_bytes()
        if sha256(raw).hexdigest() != expected:
            raise ValueError('Source changed during archive capture: ' + name)
        if expected not in committed:
            _atomic(_inside(archive, 'blobs/' + expected), raw)
            committed.add(expected)
    _atomic(_inside(archive, 'bundles/' + identity + '.json'), raw_manifest)
    return {'schema_version': VERSION, 'bundle_id': identity, 'source_sha256': sources}


def open_bundle(bundle_id, *, store):
    identity = _hash(bundle_id)
    root = Path(store).resolve()
    try:
        raw = _inside(root, 'bundles/' + identity + '.json').read_bytes()
        manifest = json.loads(raw)
    except (OSError, ValueError) as error:
        raise ValueError('Missing or malformed source bundle manifest') from error
    if (not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'source_sha256'}
            or manifest['schema_version'] != VERSION or _bytes(manifest) != raw
            or sha256(raw).hexdigest() != identity or not isinstance(manifest['source_sha256'], dict)):
        raise ValueError('Source bundle manifest identity changed')
    sources = {_path(n): _hash(h) for n, h in manifest['source_sha256'].items()}
    blobs = {}
    for expected in set(sources.values()):
        try:
            data = _inside(root, 'blobs/' + expected).read_bytes()
        except OSError as error:
            raise ValueError('Missing source bundle blob: ' + expected) from error
        if sha256(data).hexdigest() != expected:
            raise ValueError('Source bundle blob identity changed: ' + expected)
        blobs[expected] = data
    return Bundle(identity, manifest, blobs)
