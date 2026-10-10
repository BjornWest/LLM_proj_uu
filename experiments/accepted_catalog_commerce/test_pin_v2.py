from hashlib import sha256
from pathlib import Path
import json
import os
import pytest
from . import model,pin_v2,source_bundle


@pytest.fixture(scope='module')
def packet(tmp_path_factory):
    root=tmp_path_factory.mktemp('new-pin-formats')
    world=json.loads(Path('.local/generation-scaling-20261005-v1/scale1-unconditioned/pin/world.private.json').read_text())
    old=model.freeze(world,root/'v1');new=pin_v2.freeze(world,root/'v2',source_store=root/'store')
    return root,world,old,new


def test_v1_and_v2_exact_values_identity_and_source_closure(packet):
    root,world,old,new=packet
    assert model.load(root/'v1')[0]==pin_v2.load(root/'v2',source_store=root/'store')[0]==world
    assert old['source_sha256']==new['source_sha256']
    for name in old['files']:
        assert json.loads((root/'v1'/name).read_text())==json.loads((root/'v2'/name).read_text())
        assert new['files'][name]==sha256((root/'v2'/name).read_bytes()).hexdigest()
    assert (root/'v2/world.private.json').stat().st_size<(root/'v1/world.private.json').stat().st_size
    assert not (root/'v2/source-snapshot').exists()
    with pytest.raises(ValueError,match='Unsupported producer'):model.load(root/'v2')


def test_v2_missing_store_and_corrupt_artifact_reject(packet,tmp_path):
    root,world,old,new=packet
    with pytest.raises(ValueError,match='manifest'):pin_v2.load(root/'v2',source_store=tmp_path/'missing')
    output=tmp_path/'altered';output.mkdir()
    for p in (root/'v2').iterdir():(output/p.name).write_bytes(p.read_bytes())
    (output/'world.private.json').write_text('{}')
    with pytest.raises(ValueError,match='artifact changed'):pin_v2.load(output,source_store=root/'store')


def test_v2_bundle_and_current_source_changes_reject(packet,tmp_path,monkeypatch):
    root,world,old,new=packet
    # A fake current repository misses required source bytes; archived bytes do not override it.
    from . import package_export
    monkeypatch.setattr(package_export,'ROOT',tmp_path)
    with pytest.raises((OSError,ValueError)):pin_v2.load(root/'v2',source_store=root/'store')


def test_source_bundle_materializes_every_declared_source(packet,tmp_path,monkeypatch):
    root,world,old,new=packet
    bundle=source_bundle.open_bundle(new['source_bundle']['bundle_id'],store=root/'store')
    bundle.materialize(tmp_path/'standalone')
    assert {str(p.relative_to(tmp_path/'standalone')) for p in (tmp_path/'standalone').rglob('*') if p.is_file()}==set(old['source_sha256'])
    assert all(sha256((tmp_path/'standalone'/n).read_bytes()).hexdigest()==h for n,h in old['source_sha256'].items())
    from . import package_export
    current=tmp_path/'standalone';target=current/'experiments/accepted_catalog_commerce/basket_quote.py'
    stat=target.stat();raw=target.read_bytes();target.write_bytes(b'!'+raw[1:])
    os.utime(target,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    monkeypatch.setattr(package_export,'ROOT',current)
    with pytest.raises(ValueError,match='Commerce source changed'):pin_v2.load(root/'v2',source_store=root/'store')
