from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import pytest
from . import source_bundle as api


@pytest.fixture
def inputs(tmp_path):
    root=tmp_path/'repo';root.mkdir()
    (root/'a').write_bytes(b'one');(root/'b').write_bytes(b'one');(root/'c').write_bytes(b'two')
    hashes={n:sha256((root/n).read_bytes()).hexdigest() for n in ('a','b','c')}
    return root,tmp_path/'store',hashes


def test_dedup_verified_handle_and_complete_materialization(inputs,tmp_path):
    root,store,hashes=inputs
    descriptor=api.capture(hashes,repository_root=root,store=store)
    assert len(list((store/'blobs').iterdir()))==2
    assert api.capture(hashes,repository_root=root,store=store)==descriptor
    bundle=api.open_bundle(descriptor['bundle_id'],store=store)
    (root/'a').write_bytes(b'changed')
    saved=bundle.descriptor;saved['source_sha256'].clear()
    assert bundle.read('a')==bundle.read('b')==b'one'
    bundle.materialize(tmp_path/'standalone')
    assert {(tmp_path/'standalone'/n).read_bytes() for n in hashes}=={b'one',b'two'}
    # A previously verified bytes handle stays safe; a newly opened corrupt store rejects.
    (store/'blobs'/hashes['a']).write_bytes(b'corrupt')
    assert bundle.read('a')==b'one'
    with pytest.raises(ValueError,match='blob identity'):api.open_bundle(descriptor['bundle_id'],store=store)


@pytest.mark.parametrize('name',['../escape','/absolute','a/../b','./a','a//b','a\\b','a/'])
def test_paths_reject(inputs,name):
    root,store,hashes=inputs
    with pytest.raises(ValueError):api.capture({name:hashes['a']},repository_root=root,store=store)


def test_failed_capture_has_no_complete_manifest(inputs):
    root,store,hashes=inputs;hashes['c']='0'*64
    with pytest.raises(ValueError,match='Source changed'):api.capture(hashes,repository_root=root,store=store)
    assert not (store/'bundles').exists() and list((store/'blobs').iterdir())


def test_parallel_capture_atomic_reuse(inputs):
    root,store,hashes=inputs
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda unused:api.capture(hashes,repository_root=root,store=store),range(8)))
    assert all(r==results[0] for r in results)
    assert not list(store.rglob('.pending-*'))
    assert api.open_bundle(results[0]['bundle_id'],store=store).read('c')==b'two'


def test_manifest_missing_corrupt_blob_and_existing_corruption(inputs):
    root,store,hashes=inputs;d=api.capture(hashes,repository_root=root,store=store)
    blob=store/'blobs'/hashes['c'];blob.unlink()
    with pytest.raises(ValueError,match='Missing source bundle blob'):api.open_bundle(d['bundle_id'],store=store)
    api.capture(hashes,repository_root=root,store=store)
    blob.write_bytes(b'wrong')
    with pytest.raises(ValueError,match='immutable archive'):api.capture(hashes,repository_root=root,store=store)
    (store/'bundles'/(d['bundle_id']+'.json')).write_text('{}')
    with pytest.raises(ValueError,match='manifest identity'):api.open_bundle(d['bundle_id'],store=store)


def test_symlinks_outside_designated_roots_reject(inputs,tmp_path):
    root,store,hashes=inputs
    outside=tmp_path/'outside';outside.write_bytes(b'one')
    (root/'a').unlink();(root/'a').symlink_to(outside)
    with pytest.raises(ValueError,match='escapes'):api.capture(hashes,repository_root=root,store=store)
