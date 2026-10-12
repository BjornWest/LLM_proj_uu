import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import portable_source_bundle as bundle


def fixture(tmp_path):
    shared = tmp_path / 'shared.txt'; shared.write_bytes(b'identical frozen source')
    exe = tmp_path / 'entry.py'; exe.write_bytes(b'print("test")\n')
    sh, eh = bundle.digest_file(shared), bundle.digest_file(exe)
    entry = lambda path, sha, mode: {'sha256': sha, 'bytes': path.stat().st_size, 'mode': mode}
    data = {'roots': {
        'r1': {'commit': 'a' * 40, 'files': {'foo.txt': entry(shared, sh, '100644'),
                                           'scripts/run.py': entry(exe, eh, '100755')}},
        'r2': {'commit': 'b' * 40, 'files': {'nested/foo.txt': entry(shared, sh, '100644')}}},
        'content_blobs': {sh: {'source': str(shared), 'bytes': shared.stat().st_size},
                          eh: {'source': str(exe), 'bytes': exe.stat().st_size}}}
    p = tmp_path / 'inventory.json'; p.write_text(json.dumps(data))
    return p, data, shared


def test_round_trip_deduplicates_transfer_and_preserves_isolated_roots(tmp_path):
    inventory, data, shared = fixture(tmp_path)
    archive = tmp_path / 'source.tar.gz'
    receipt = bundle.build(inventory, bundle.digest_file(inventory), archive)
    assert receipt['roots'] == 2 and receipt['files'] == 3
    assert receipt['unique_source_bytes'] < receipt['reconstructed_source_bytes']
    with tarfile.open(archive) as tar:
        assert len(tar.getnames()) == 3  # Index plus two unique blobs.
    result = bundle.unpack(archive, receipt['archive_sha256'], tmp_path / 'remote')
    first = Path(result['destination']) / 'roots/r1/foo.txt'
    second = Path(result['destination']) / 'roots/r2/nested/foo.txt'
    assert first.read_bytes() == second.read_bytes() == shared.read_bytes()
    assert first.stat().st_ino != second.stat().st_ino
    assert (tmp_path / 'remote/roots/r1/scripts/run.py').stat().st_mode & 0o777 == 0o755
    first.write_text('independent mutation')
    assert second.read_bytes() == shared.read_bytes()
    assert archive.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('which', ['inventory', 'source', 'existing'])
def test_build_fails_closed_on_changed_source_or_existing_output(tmp_path, which):
    inventory, data, shared = fixture(tmp_path)
    sha = bundle.digest_file(inventory); archive = tmp_path / 'source.tar.gz'
    if which == 'inventory': inventory.write_text('{}')
    if which == 'source': shared.write_text('changed')
    if which == 'existing': archive.write_text('preserve')
    with pytest.raises(ValueError): bundle.build(inventory, sha, archive)
    assert archive.read_text() == 'preserve' if which == 'existing' else not archive.exists()
    assert not list(tmp_path.glob('.source-capsule-*'))


@pytest.mark.parametrize('path', ['../escape', '/absolute', 'x/../../escape', '.env',
                                 '.ssh/id_ed25519', 'a//b', 'a/./b', 'a\\b', '.',
                                 '.env.local', '.env.production', '.envrc', '.netrc',
                                 '.aws/credentials', 'id_rsa'])
def test_unsafe_inventory_paths_rejected(tmp_path, path):
    inventory, data, shared = fixture(tmp_path)
    data['roots']['r1']['files'][path] = data['roots']['r1']['files']['foo.txt']
    inventory.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        bundle.build(inventory, bundle.digest_file(inventory), tmp_path / 'source.tar.gz')


def test_corrupted_archive_and_existing_destination_preserved(tmp_path):
    inventory, data, shared = fixture(tmp_path)
    archive = tmp_path / 'source.tar.gz'
    receipt = bundle.build(inventory, bundle.digest_file(inventory), archive)
    destination = tmp_path / 'remote'; destination.mkdir(); (destination / 'keep').write_text('keep')
    with pytest.raises(ValueError): bundle.unpack(archive, receipt['archive_sha256'], destination)
    assert (destination / 'keep').read_text() == 'keep'
    with pytest.raises(ValueError): bundle.unpack(archive, '0' * 64, tmp_path / 'new')
    assert not (tmp_path / 'new').exists()


def test_archive_extra_member_never_extracted(tmp_path):
    inventory, data, shared = fixture(tmp_path)
    index = bundle.index_for(data, bundle.digest_file(inventory))
    archive = tmp_path / 'bad.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        raw = json.dumps(index).encode(); member = tarfile.TarInfo('index.json'); member.size = len(raw)
        tar.addfile(member, io.BytesIO(raw))
        member = tarfile.TarInfo('../escape'); member.size = 1
        tar.addfile(member, io.BytesIO(b'x'))
    with pytest.raises(ValueError): bundle.unpack(archive, bundle.digest_file(archive), tmp_path / 'remote')
    assert not (tmp_path / 'escape').exists() and not (tmp_path / 'remote').exists()


def test_racing_empty_destination_is_never_replaced(tmp_path, monkeypatch):
    inventory, _, _ = fixture(tmp_path)
    archive = tmp_path / 'source.tar.gz'; receipt = bundle.build(inventory, bundle.digest_file(inventory), archive)
    original = bundle.publish_tree
    def raced(stage, destination):
        destination.mkdir(mode=0o750)
        original(stage, destination)
    monkeypatch.setattr(bundle, 'publish_tree', raced)
    with pytest.raises(FileExistsError):
        bundle.unpack(archive, receipt['archive_sha256'], tmp_path / 'remote')
    assert (tmp_path / 'remote').stat().st_mode & 0o777 == 0o750
    assert not list(tmp_path.glob('.source-unpack-*'))


def test_capsule_hash_reproducible_without_local_metadata(tmp_path):
    inventory, _, _ = fixture(tmp_path)
    a, b = tmp_path / 'a.gz', tmp_path / 'b.gz'
    bundle.build(inventory, bundle.digest_file(inventory), a)
    bundle.build(inventory, bundle.digest_file(inventory), b)
    assert bundle.digest_file(a) == bundle.digest_file(b)
    assert a.read_bytes()[4:8] == b'\0' * 4
    with tarfile.open(a) as tar:
        assert all(m.uid == m.gid == m.mtime == 0 and m.uname == m.gname == '' for m in tar)


def test_unpack_consumes_the_hashed_file_descriptor_not_a_replaced_path(tmp_path, monkeypatch):
    inventory, _, shared = fixture(tmp_path)
    archive = tmp_path / 'a.gz'; a = bundle.build(inventory, bundle.digest_file(inventory), archive)
    original = bundle.hashlib.file_digest
    def swapped(stream, algorithm):
        digest = original(stream, algorithm)
        if stream.name == str(archive):
            other = tmp_path / 'replacement'; other.write_bytes(b'not the verified capsule')
            other.replace(archive)
        return digest
    monkeypatch.setattr(bundle.hashlib, 'file_digest', swapped)
    bundle.unpack(archive, a['archive_sha256'], tmp_path / 'out')
    assert (tmp_path / 'out/roots/r1/foo.txt').read_bytes() == shared.read_bytes()
    assert archive.read_bytes() == b'not the verified capsule'


def test_file_directory_collision_rejected_before_archive_build(tmp_path):
    inventory, data, _ = fixture(tmp_path)
    data['roots']['r1']['files']['foo.txt/inner'] = data['roots']['r1']['files']['foo.txt']
    inventory.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='collides'):
        bundle.build(inventory, bundle.digest_file(inventory), tmp_path / 'source.gz')
    assert not (tmp_path / 'source.gz').exists()
