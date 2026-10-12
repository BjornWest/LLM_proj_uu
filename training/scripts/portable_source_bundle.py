#!/usr/bin/env python3
"""Hash-bound private source capsule: deduplicated transfer, separate roots.

Source files only. This does not supply environments, outside assets, recipes,
callers, qualification or launch approval. It performs no network/cloud action.
"""
import argparse
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile

CHUNK = 1 << 20
INDEX_LIMIT = 64 << 20
SHA = re.compile(r'[0-9a-f]{64}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}\Z')


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            h.update(chunk)
    return h.hexdigest()


def credential_path(path):
    parts = Path(path).parts
    name = Path(path).name
    return ('.ssh' in parts or '.aws' in parts or '.azure' in parts
            or name in ('.env', '.envrc', '.netrc', 'id_rsa', 'id_ed25519', 'id_dsa', 'id_ecdsa')
            or name.startswith('.env.') and name not in ('.env.example', '.env.sample', '.env.template'))


def relative(value):
    if not isinstance(value, str) or not value or '\0' in value or '\\' in value:
        raise ValueError('Invalid relative source path')
    p = PurePosixPath(value)
    if (not p.parts or p.is_absolute() or '..' in p.parts or str(p) != value
            or credential_path(value)):
        raise ValueError('Unsafe source path or credentials file')
    return value


def index_for(inventory, inventory_sha):
    if not isinstance(inventory_sha, str) or not SHA.fullmatch(inventory_sha):
        raise ValueError('Invalid inventory SHA256')
    roots, blobs = {}, {}
    for name, root in inventory['roots'].items():
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', name):
            raise ValueError('Invalid portable root name')
        if not isinstance(root['commit'], str) or not COMMIT.fullmatch(root['commit']):
            raise ValueError('Invalid Git source commit')
        files = {}
        for path, entry in root['files'].items():
            relative(path)
            sha, size, mode = entry['sha256'], entry['bytes'], entry['mode']
            if not SHA.fullmatch(sha) or type(size) is not int or size < 0 or mode not in ('100644', '100755'):
                raise ValueError('Invalid source entry; only ordinary tracked files supported')
            if sha in blobs and blobs[sha] != size:
                raise ValueError('Conflicting content sizes')
            blobs[sha] = size
            files[path] = {'sha256': sha, 'bytes': size, 'mode': mode}
        if any(str(parent) in files for path in files for parent in PurePosixPath(path).parents):
            raise ValueError('Source file path collides with a directory')
        roots[name] = {'commit': root['commit'], 'files': files}
    if not roots or not blobs:
        raise ValueError('Empty source inventory')
    for sha, size in blobs.items():
        if inventory['content_blobs'][sha]['bytes'] != size:
            raise ValueError('Blob inventory differs from root inventory')
    return {'format': 'private-frozen-source-capsule-v1', 'inventory_sha256': inventory_sha,
            'roots': roots, 'blobs': blobs,
            'scope': 'Source-only preparation; not an execution or allocation release'}


def build(inventory_path, expected_sha, archive):
    inventory_path, archive = Path(inventory_path), Path(archive)
    with inventory_path.open('rb') as stream:
        inventory_bytes = stream.read(INDEX_LIMIT + 1)
    if not SHA.fullmatch(expected_sha) or hashlib.sha256(inventory_bytes).hexdigest() != expected_sha:
        raise ValueError('Source inventory hash differs from released input')
    if len(inventory_bytes) > INDEX_LIMIT or archive.exists():
        raise ValueError('Oversized inventory or existing capsule output')
    inventory = json.loads(inventory_bytes)
    index = index_for(inventory, expected_sha)
    archive.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Materialize verified bytes first, so a source changing during archive writing
    # cannot create an archive whose header hash describes different content.
    with tempfile.TemporaryDirectory(dir=archive.parent, prefix='.source-capsule-') as tmp:
        stage = Path(tmp)
        (stage / 'blobs').mkdir()
        for sha, size in index['blobs'].items():
            source = Path(inventory['content_blobs'][sha]['source'])
            if source.is_symlink() or not source.is_file() or credential_path(source):
                raise ValueError('Blob source is not an ordinary approved file')
            target = stage / 'blobs' / sha
            with source.open('rb') as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst, CHUNK)
            if target.stat().st_size != size or digest_file(target) != sha:
                raise ValueError('Source changed or differs from frozen inventory: ' + sha)
        index_bytes = json.dumps(index, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if len(index_bytes) > INDEX_LIMIT:
            raise ValueError('Capsule index exceeds bound')
        (stage / 'index.json').write_bytes(index_bytes)
        temporary = stage / 'capsule.tar.gz'
        with temporary.open('xb') as stream, gzip.GzipFile(
                fileobj=stream, mode='wb', filename='', mtime=0, compresslevel=1) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as tar:
                for name in ['index.json', *('blobs/' + sha for sha in sorted(index['blobs']))]:
                    # No local user/UID/mtime or random stage path in the capsule.
                    info = tarfile.TarInfo(name); info.size = (stage / name).stat().st_size
                    info.mode = 0o644
                    with (stage / name).open('rb') as content:
                        tar.addfile(info, content)
        temporary.chmod(0o600)
        archive_sha = digest_file(temporary)
        archive_bytes = temporary.stat().st_size
        # Destination is never replaced, including if another caller races us.
        os.link(temporary, archive)
    return {'archive': str(archive.resolve()), 'archive_sha256': archive_sha,
            'archive_bytes': archive_bytes, 'inventory_sha256': expected_sha,
            'roots': len(index['roots']), 'files': sum(len(r['files']) for r in index['roots'].values()),
            'unique_source_bytes': sum(index['blobs'].values()),
            'reconstructed_source_bytes': sum(f['bytes'] for r in index['roots'].values() for f in r['files'].values()),
            'models_downloads_cloud': 0, 'launch_approved': False}


def publish_tree(stage, destination):
    """Atomic no-clobber publication on the supported Linux/WSL/Verda hosts."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise RuntimeError('Linux renameat2 is required for safe source publication')
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(destination), 1):  # RENAME_NOREPLACE
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def unpack(archive, expected_sha, destination):
    archive, destination = Path(archive), Path(destination)
    with archive.open('rb') as capsule:
        if not SHA.fullmatch(expected_sha) or hashlib.file_digest(capsule, 'sha256').hexdigest() != expected_sha:
            raise ValueError('Capsule checksum mismatch')
        capsule.seek(0)
        return unpack_stream(capsule, destination)


def unpack_stream(capsule, destination):
    # Consume the exact file descriptor already hashed; never reopen by path.
    if destination.exists() or destination.is_symlink():
        raise ValueError('Use a new private destination')
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.source-unpack-') as tmp:
        stage = Path(tmp)
        with tarfile.open(fileobj=capsule, mode='r:gz') as tar:
            first = tar.next()
            if first is None or first.name != 'index.json' or not first.isfile() or first.size > INDEX_LIMIT:
                raise ValueError('Capsule must begin with a bounded regular index')
            with tar.extractfile(first) as src:
                raw = src.read(INDEX_LIMIT + 1)
            index = json.loads(raw)
            if index['format'] != 'private-frozen-source-capsule-v1':
                raise ValueError('Unsupported source capsule')
            # Revalidate all filenames, modes and content sizes before any writes.
            generated = index_for({'roots': index['roots'], 'content_blobs': {
                sha: {'bytes': size} for sha, size in index['blobs'].items()}}, index['inventory_sha256'])
            if generated['blobs'] != index['blobs']:
                raise ValueError('Extra or inconsistent blob entries')
            (stage / 'blobs').mkdir()
            seen = set()
            while (member := tar.next()) is not None:
                sha = member.name.removeprefix('blobs/')
                if (not member.isfile() or member.name != 'blobs/' + sha or sha not in index['blobs']
                        or sha in seen or member.size != index['blobs'][sha]):
                    raise ValueError('Unexpected, duplicate or unsafe archive member')
                seen.add(sha)
                target = stage / 'blobs' / sha
                with tar.extractfile(member) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst, CHUNK)
                if digest_file(target) != sha:
                    raise ValueError('Corrupted content blob')
            if seen != set(index['blobs']):
                raise ValueError('Missing content blobs')
        roots = stage / 'roots'
        roots.mkdir()
        for name, root in index['roots'].items():
            for path, entry in root['files'].items():
                target = roots / name / path
                target.parent.mkdir(parents=True, exist_ok=True)
                # Separate files preserve root isolation; do not share writable
                # hardlinks between case roots. Upload dedup isn't heap sharing.
                shutil.copyfile(stage / 'blobs' / entry['sha256'], target)
                target.chmod(0o755 if entry['mode'] == '100755' else 0o644)
        (stage / 'source-index.json').write_bytes(raw)
        shutil.rmtree(stage / 'blobs')
        # Rename only a completed, validated tree into a new destination.
        publish_tree(stage, destination)
    return {'destination': str(destination.resolve()), 'roots': len(index['roots']),
            'inventory_sha256': index['inventory_sha256'], 'scope': 'source only, not runnable suite'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    build_cli = sub.add_parser('build')
    build_cli.add_argument('--inventory', type=Path, required=True)
    build_cli.add_argument('--inventory-sha256', required=True)
    build_cli.add_argument('--output', type=Path, required=True)
    unpack_cli = sub.add_parser('unpack')
    unpack_cli.add_argument('--archive', type=Path, required=True)
    unpack_cli.add_argument('--archive-sha256', required=True)
    unpack_cli.add_argument('--destination', type=Path, required=True)
    args = p.parse_args()
    result = build(args.inventory, args.inventory_sha256, args.output) if args.action == 'build' else \
             unpack(args.archive, args.archive_sha256, args.destination)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
