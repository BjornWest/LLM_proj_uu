"""Finite route-plan controls; no browser/world/model/public sufficiency claim."""
from types import SimpleNamespace
import pytest
from training.browser_training.fact_pilot_public_capture import capture_targets


def fixture():
    return SimpleNamespace(public_catalogs={
        'b': {'products': [{'id': 'friendly-b', 'canonicalProductId': 'native-2'}]},
        'a': {'products': [{'id': 'friendly-a', 'canonicalProductId': 'native-1'},
                          {'id': 'unrelated', 'canonicalProductId': 'other'}]}},
        bindings={'retailer_pages': {'a': {'friendly-a': 'https://a/#/product/friendly-a'},
                                    'b': {'friendly-b': 'https://b/#/product/friendly-b'}},
                  'surrounding': {'review_products': {
                      'native-1': ['https://review/reviews/native-1', 'https://review/reviews/native-1'],
                      'native-2': ['https://other-review/reviews/native-2']}}},
        preview_url=lambda url: url.replace('https://', 'http://transport/'))


def test_plan_uses_native_identity_and_existing_binding_routes_without_world_truth():
    task={'comparison_task': {'models': [{'product_id': 'native-2'}, {'product_id': 'native-1'}]}}
    runtime=fixture()
    targets=capture_targets(runtime, task)
    assert len(targets)==4
    assert [t['product_id'] for t in targets]==['native-1','native-2','native-2','native-1']
    assert {t['source_family'] for t in targets}=={'retailer','product_reviews'}
    assert all(t['transport_url'].startswith('http://transport/') for t in targets)
    assert not any('unrelated' in t['url'] for t in targets)
    assert runtime.public_catalogs['a']['products'][0]['id']=='friendly-a'


def test_missing_review_route_stays_missing_rather_than_inventing_a_route():
    runtime=fixture();runtime.bindings['surrounding']['review_products'].pop('native-2')
    targets=capture_targets(runtime, {'comparison_task': {'models': [
        {'product_id':'native-1'},{'product_id':'native-2'}]}})
    assert not any(t['product_id']=='native-2' and t['source_family']=='product_reviews' for t in targets)


def test_duplicate_native_models_fail_without_launch():
    with pytest.raises(ValueError,match='two model identities'):
        capture_targets(fixture(), {'comparison_task': {'models': [
            {'product_id':'native-1'},{'product_id':'native-1'}]}})


@pytest.mark.parametrize('failures', [(), ('provider',), ('browser',), ('provider', 'browser')])
def test_public_capture_closes_before_audit_and_never_creates_policy_delivery(tmp_path, monkeypatch, failures):
    import sys
    import json
    import training.browser_training.fact_pilot_public_capture as module
    from contextlib import contextmanager
    events=[]
    class Page:
        def on(self,*args):pass
        def goto(self,url):events.append(('goto',url))
        def wait_for_load_state(self,state):pass
        def wait_for_selector(self,selector):pass
    page=Page()
    class Browser:
        def new_context(self,**options):
            assert options=={'accept_downloads':False,'service_workers':'block'}
            return SimpleNamespace(new_page=lambda:page)
        def close(self):
            events.append(('browser_close',None))
            if 'browser' in failures:raise ValueError('browser failed')
    @contextmanager
    def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw:Browser()))
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=playwright))
    monkeypatch.setitem(sys.modules,'environments.website_world.catalog_compare_review_execution',
                        SimpleNamespace(public_binding=lambda runtime:'a'*64))
    class Provider:
        def __init__(self,page,enabled):
            assert enabled;self.cdp=SimpleNamespace(send=lambda command:{'nodes':[]});self.diagnostics=[]
        def install(self):events.append(('install',None))
        def observe(self,operation):return operation()
        def result(self,observation):return {'normalized':{'snapshot_id':'authored-test-only'}}
        def close(self):
            events.append(('provider_close',None))
            if 'provider' in failures:raise RuntimeError('detach failed')
    monkeypatch.setattr(module,'FactSourceProvider',Provider)
    task={'schema_version':'website-catalog-compare-review-task-v1','kind':'compare_facts_and_reviews',
          'task_id':'task','comparison_task':{'models':[{'product_id':'native-1'},{'product_id':'native-2'}],
                                            'fields':['product.facts.x']},
          'required_obligations':[{'role_id':'m1.x','product_id':'native-1','source_family':'retailer',
                                   'field':'product.facts.x'}]}
    def audit(task,reference,paths,*,runtime_binding_sha256):
        assert not failures, 'No audit after cleanup failure'
        assert events[-2:]==[('provider_close',None),('browser_close',None)]
        assert len(paths)==4 and runtime_binding_sha256=='a'*64
        assert all(json.loads(path.read_bytes())['normalized']['snapshot_id']=='authored-test-only' for path in paths)
        return {'status':'unresolved','delivery_evidence':False}
    monkeypatch.setattr(module,'audit_captures',audit)
    out=tmp_path/'audit'
    if failures:
        expected_type = RuntimeError if 'provider' in failures else ValueError
        with pytest.raises(expected_type) as failure:
            module.FactPilotPublicAudit(out)(runtime=fixture(),task=task,reference={'task_id':'task'})
        if 'provider' in failures:assert 'detach failed' in str(failure.value)
        if 'browser' in failures:assert 'browser failed' in str(failure.value)
        assert events.count(('provider_close',None))==events.count(('browser_close',None))==1
        assert not (out/'manifest.json').exists()
        return
    report=module.FactPilotPublicAudit(out)(runtime=fixture(),task=task,reference={'task_id':'task'})
    assert report['delivery_evidence'] is False
    manifest=json.loads((out/'manifest.json').read_text())
    assert manifest['policy_browser'] is False and manifest['retries']==0
    assert len(manifest['captures'])==4 and all(not r['delivery_evidence'] for r in manifest['captures'])
    assert len([e for e in events if e[0]=='goto'])==4
