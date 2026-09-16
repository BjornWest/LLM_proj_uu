"""Exact-byte screenshot deduplication for closed traces; no retention deletion.

Run per filesystem/owner. Original trace paths remain regular hard-linked files.
The pool must be outside every episode directory. Completed episodes are treated
as immutable; this tool never processes screenshots of active/incomplete runs.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import uuid
import zipfile

PNG = b'\x89PNG\r\n\x1a\n'
LIMIT = 20_000_000_000


def signature(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def regular_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Not a regular file: ' + str(path))
        raw = stream.read()
        if signature(before) != signature(os.fstat(stream.fileno())):
            raise ValueError('File changed during read: ' + str(path))
    return raw, before


def closed_episode(path, root, cutoff):
    for parent in path.parents:
        if parent == root.parent:
            break
        marker = parent / 'episode.json'
        if marker.exists() or marker.is_symlink():
            if marker.is_symlink():
                return False
            raw, info = regular_read(marker)
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                return False
            return (info.st_mtime <= cutoff and isinstance(value, dict)
                    and bool(value.get('episode_id')) and 'stop_reason' in value)
    return False


def files_under(root, pool):
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory)/d).is_symlink()
                         and Path(directory)/d != pool)
        for name in sorted(files):
            path = Path(directory)/name
            if not path.is_symlink() and path.is_file():
                yield path


def install_object(pool, digest, raw, source):
    # Keep owners separate; do not make private images readable through a
    # different Unix identity. The pool itself is private to its maintenance user.
    directory = pool / f'{source.st_uid}-{source.st_gid}-{source.st_mode & 0o444:o}' / digest[:2]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError('Symlink in object pool')
    destination = directory/(digest + '.png')
    if destination.exists() or destination.is_symlink():
        existing, _ = regular_read(destination)
        if existing != raw:
            raise ValueError('Corrupt screenshot object: ' + digest)
        return destination
    temporary = directory/('.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, source.st_mode & 0o444)
        if temporary.stat().st_uid != source.st_uid or temporary.stat().st_gid != source.st_gid:
            os.chown(temporary, source.st_uid, source.st_gid)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            existing, _ = regular_read(destination)
            if existing != raw:
                raise ValueError('Conflicting screenshot object: ' + digest)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def replace_reference(path, destination, expected, expected_raw):
    if path.is_symlink() or signature(path.stat()) != signature(expected):
        raise ValueError('Screenshot changed before linking: ' + str(path))
    # No symlinks: existing artifact serving and ZIP export keep ordinary paths.
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.link')
    try:
        os.link(destination, temporary)  # EXDEV fails; never silently relocate/copy.
        if path.is_symlink() or signature(path.stat()) != signature(expected):
            raise ValueError('Screenshot changed before replacement: ' + str(path))
        current, _ = regular_read(path)
        if current != expected_raw:
            raise ValueError('Screenshot bytes changed before replacement: ' + str(path))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def scan(root, pool, *, apply=False, min_age=60, threshold=LIMIT):
    root, pool = Path(root).absolute(), Path(pool).absolute()
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise ValueError('Root must be an existing real directory')
    if pool.is_symlink() or pool.resolve() != pool or pool == root:
        raise ValueError('Pool must be a separate real path')
    if any((p/'episode.json').exists() for p in [pool, *pool.parents]):
        raise ValueError('Pool must not be inside an episode')
    if min_age < 0 or threshold <= 0:
        raise ValueError('Invalid age/threshold')
    if apply:
        pool.mkdir(parents=True, exist_ok=True, mode=0o700)
        if pool.stat().st_dev != root.stat().st_dev:
            raise ValueError('Pool and root must share a filesystem')
        lock = (pool/'.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        lock = None
    report = {'schema_version': 1, 'root': str(root), 'pool': str(pool), 'apply': apply,
              'threshold_bytes': threshold, 'scanned_at': time.time(), 'retention_deletion': False,
              'png_files': 0, 'logical_png_bytes': 0, 'eligible_files': 0, 'linked_files': 0,
              'skipped_unfinished_or_recent': 0, 'skipped_non_png': 0,
              'archive_png_entries': 0, 'archive_png_compressed_bytes': 0,
              'errors': [], 'unique_content_bytes': 0}
    before, after, hashes, pool_inodes = {}, {}, {}, {}
    pool_objects = []
    cutoff = time.time()-min_age
    try:
        for path in files_under(root, pool):
            if path.suffix.lower() == '.zip':
                try:
                    with zipfile.ZipFile(path) as archive:
                        for entry in archive.infolist():
                            if entry.filename.lower().endswith('.png'):
                                report['archive_png_entries'] += 1
                                report['archive_png_compressed_bytes'] += entry.compress_size
                except (OSError, zipfile.BadZipFile) as e:
                    report['errors'].append({'path': str(path), 'error': type(e).__name__})
                continue
            if path.suffix.lower() != '.png':
                continue
            try:
                raw, initial = regular_read(path)
                if not raw.startswith(PNG):
                    report['skipped_non_png'] += 1
                    continue
                digest = hashlib.sha256(raw).hexdigest()
                key = (initial.st_dev, initial.st_ino)
                before[key] = initial.st_blocks*512
                report['png_files'] += 1
                report['logical_png_bytes'] += len(raw)
                entry = hashes.setdefault(digest, {'sha256': digest, 'bytes': len(raw), 'references': 0})
                entry['references'] += 1
                eligible = initial.st_mtime <= cutoff and closed_episode(path, root, cutoff)
                if not eligible:
                    report['skipped_unfinished_or_recent'] += 1
                else:
                    report['eligible_files'] += 1
                    if apply:
                        destination = install_object(pool, digest, raw, initial)
                        obj = destination.stat()
                        if key != (obj.st_dev, obj.st_ino):
                            replace_reference(path, destination, initial, raw)
                            # Verify every resulting reference, not just the first object.
                            final_raw, _ = regular_read(path)
                            if final_raw != raw:
                                raise ValueError('Reference byte verification failed')
                            report['linked_files'] += 1
                final = path.stat()
                after[(final.st_dev, final.st_ino)] = final.st_blocks*512
            except (OSError, ValueError) as e:
                report['errors'].append({'path': str(path), 'error': str(e)})
                # A failed replacement must not disappear from the usage total.
                try:
                    info = path.stat(follow_symlinks=False)
                    after[(info.st_dev, info.st_ino)] = info.st_blocks*512
                except OSError:
                    pass
        if pool.exists():
            for path in files_under(pool, pool/'__none__'):
                if path.suffix != '.png':
                    continue
                info = path.stat()
                pool_inodes[(info.st_dev, info.st_ino)] = info.st_blocks*512
                pool_objects.append({'sha256': path.stem, 'bytes': info.st_size,
                                     'allocated_bytes': info.st_blocks*512,
                                     'hardlink_references': max(0, info.st_nlink-1),
                                     'owner_permissions_namespace': path.parent.parent.name})
        report['unique_content_bytes'] = sum(e['bytes'] for e in hashes.values())
        report['unique_images'] = len(hashes)
        report['physical_png_bytes_before'] = sum(before.values())
        report['physical_png_bytes_after_including_pool'] = sum({**after, **pool_inodes}.values())
        report['pool_bytes_outside_scan'] = sum(size for key, size in pool_inodes.items() if key not in after)
        report['unreferenced_pool_bytes'] = sum(o['allocated_bytes'] for o in pool_objects if o['hardlink_references'] == 0)
        report['pool_objects'] = pool_objects
        report['storage_budget_bytes'] = report['physical_png_bytes_after_including_pool'] + report['archive_png_compressed_bytes']
        report['threshold_reached'] = (report['storage_budget_bytes'] >= threshold
                                       if not report['errors'] else None)
        report['references'] = sorted(hashes.values(), key=lambda e: (-e['references'], e['sha256']))
        report['ok'] = not report['errors']
        return report
    finally:
        if lock:
            lock.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('--pool', required=True, type=Path)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--min-age-seconds', type=float, default=60)
    p.add_argument('--threshold-bytes', type=int, default=LIMIT)
    args = p.parse_args()
    report = scan(args.root, args.pool, apply=args.apply, min_age=args.min_age_seconds,
                  threshold=args.threshold_bytes)
    print(json.dumps(report))
    if not report['ok']:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
