import json
from pathlib import Path
import pytest

from intent_browser.environment_package import FORMAT, inventory, verify, safe_name, export
from intent_browser.environment_runtime import LocalSite


def fixture(tmp_path):
    root=tmp_path/'package';root.mkdir();(root/'asset.txt').write_text('immutable')
    (root/'manifest.json').write_text(json.dumps({'format':FORMAT,'schema_version':1,'files':inventory(root)}))
    return root


@pytest.mark.parametrize('change',['missing','changed','extra','symlink'])
def test_exact_package_files_required(tmp_path,change):
    root=fixture(tmp_path);verify(root)
    if change=='missing': (root/'asset.txt').unlink()
    elif change=='changed': (root/'asset.txt').write_text('changed')
    elif change=='extra': (root/'secret.env').write_text('should not be here')
    else: (root/'link').symlink_to(root/'asset.txt')
    with pytest.raises(ValueError):verify(root)


@pytest.mark.parametrize('name',['../private','/absolute','a/../b','a\\b','a//b','./file',''])
def test_noncanonical_members_rejected(name):
    with pytest.raises(ValueError):safe_name(name)


@pytest.mark.parametrize('dangling',[False,True])
def test_existing_output_rejected_before_dependency_reads(tmp_path,dangling):
    out=tmp_path/'output'
    if dangling:out.symlink_to(tmp_path/'absent')
    else:out.mkdir()
    with pytest.raises(FileExistsError):export(out,fixtures='missing',chaos='missing',miniwob='missing')


def test_static_server_never_serves_package_private_root(tmp_path):
    import httpx
    public=tmp_path/'html';public.mkdir();(public/'page.html').write_text('public fixture')
    (tmp_path/'secret.json').write_text('private verifier')
    site=LocalSite(html_root=public)
    try:
        with httpx.Client(base_url=site.origin,trust_env=False) as c:
            assert c.get('/page.html').text=='public fixture'
            assert c.get('/%2e%2e/secret.json').status_code==404
            assert c.get('/').status_code==404
            assert c.get('/manifest.json').status_code==404
    finally:site.close()


def test_campus_worlds_are_independent():
    one=LocalSite(area='shop');two=LocalSite(area='shop')
    try:
        one.world.action({'type':'cart','product':'notebook','delta':1})
        assert two.world.snapshot()['cart']=={}
        assert one.world_id!=two.world_id and one.origin!=two.origin
    finally:one.close();two.close()


def test_export_rejects_unreviewed_fixture_files_before_copy(tmp_path,monkeypatch):
    from intent_browser import hosted_tasks
    source=tmp_path/'source';(source/'environments/portable-resources').mkdir(parents=True)
    (source/'environments/portable-resources/inter.json').write_text('{"resources":{}}')
    cache=tmp_path/'cache';cache.mkdir()
    fixtures=tmp_path/'fixtures';fixtures.mkdir()
    (fixtures/'package.json').write_text('{"files_sha256":{}}')
    (fixtures/'unexpected.env').write_text('must not be copied')
    monkeypatch.setattr(hosted_tasks,'check_package',lambda _:fixtures)
    with pytest.raises(ValueError,match='unreviewed'):
        export(tmp_path/'out',fixtures=fixtures,chaos='missing',miniwob='missing',resources=cache,source=source)
    assert not (tmp_path/'out').exists()
