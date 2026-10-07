from copy import deepcopy
from unittest.mock import patch
import pytest

from training.browser_training.fact_source_provider import FactSourceProvider
from training.browser_training.fact_exposure import object_digest


def fixture():
    provider=FactSourceProvider(enabled=True)
    commit={'revision':3,'meta':{'url':'https://site.test/','state_key':'s','draft':{'sku':'42'}}}
    obs={'axtree_object':{'nodes':[{'nodeId':'1'}]}}
    normalized={'schema':'fact-render-normalized-v1','render_revision':3,'occurrences':[],
        'ax_sources':[{'id':'source','text':'49 kr','sha256':'sha','binding':{'snapshot_id':'old','document_id':'doc','frame_id':'f','node_id':'1','field':'name'}}],
        'diagnostics':[],'ax_diagnostics':[]}
    result={'commit':commit,'normalized':normalized}
    provider._attest=lambda:deepcopy(commit)
    return provider,commit,obs,result


def test_off_touches_no_browser_and_preserves_observation():
    p=FactSourceProvider(page=object(),enabled=False);p.install()
    obs={};calls=[]
    assert p.observe(lambda:(calls.append(True) or obs)) is obs
    assert calls==[True] and p.pairs=={}


def test_provider_consumes_exact_paired_observation_and_frozen_state():
    p,commit,obs,result=fixture();calls=[]
    with patch('training.browser_training.fact_source_provider.capture',return_value=result) as capture:
        assert p.observe(lambda:(calls.append(True) or obs)) is obs
        assert capture.call_args.kwargs['raw_ax'] is obs['axtree_object']['nodes']
    packet=p(None,obs,{'snapshot_id':'actual-snapshot','step':0,'coverage':'full'})
    assert calls==[True] and packet['sources'][0]['binding']['snapshot_id']=='actual-snapshot'
    assert packet['private_context']['pairing']['raw_ax_sha256']==object_digest(obs['axtree_object'])
    assert normalized_snapshot(result)=='old'
    p.latest={'revision':999} # Later state cannot overwrite the frozen capture.
    assert p(None,obs,{'snapshot_id':'actual-snapshot'})==packet


def normalized_snapshot(result):
    return result['normalized']['ax_sources'][0]['binding']['snapshot_id']


@pytest.mark.parametrize('mutation',['deepcopy','raw_change','unwrapped'])
def test_equal_or_modified_observations_are_not_relocated(mutation):
    p,c,obs,result=fixture()
    with patch('training.browser_training.fact_source_provider.capture',return_value=result):p.observe(lambda:obs)
    if mutation=='deepcopy':obs=deepcopy(obs)
    elif mutation=='raw_change':obs['axtree_object']['nodes'][0]['nodeId']='different'
    else:obs={'axtree_object':{'nodes':[{'nodeId':'1'}]}}
    with pytest.raises(ValueError,match='not paired'):p(None,obs,{'snapshot_id':'new'})


def test_render_race_and_recording_failure_leave_browser_result_unchanged():
    p,c,obs,result=fixture();versions=iter([c,{**c,'revision':4}]);p._attest=lambda:next(versions)
    assert p.observe(lambda:obs) is obs
    assert p.result(obs) is None and p.diagnostics
    p._attest=lambda:(_ for _ in ()).throw(ValueError('missing'))
    calls=[];assert p.observe(lambda:(calls.append(True) or obs)) is obs
    assert calls==[True]


def test_failed_recapture_cannot_reuse_same_object_previous_pair():
    p,c,obs,result=fixture()
    with patch('training.browser_training.fact_source_provider.capture',return_value=result):p.observe(lambda:obs)
    p._attest=lambda:(_ for _ in ()).throw(ValueError('changed'))
    p.observe(lambda:obs)
    assert p.result(obs) is None


def test_actual_capture_error_propagates_without_retry():
    p,c,obs,result=fixture();calls=[]
    def operation():calls.append(True);raise RuntimeError('browser failed')
    with pytest.raises(RuntimeError,match='browser failed'):p.observe(operation)
    assert calls==[True]


@pytest.mark.parametrize('mode',['html','render_state'])
def test_pending_private_callback_is_bound_to_the_same_live_state_read(mode):
    part='old' if mode=='html' else {'schema':'fact-render-state-browsergym-v1','tree':['old']}
    old={'revision':3,'meta':{'state_key':'site','url':'https://site.test/#/old','draft':{'v':39},mode:part}}
    current=deepcopy(old);current['revision']=4
    current['meta'].update(url='https://site.test/#/new',draft={'v':42})
    current['meta'][mode]='new' if mode=='html' else {'schema':'fact-render-state-browsergym-v1','tree':['new']}
    p=FactSourceProvider(enabled=True);p.latest=old
    class Page:
        calls=0
        def evaluate(self, script, key):
            self.calls+=1
            p.latest=deepcopy(current) # callback delivered during this same read
            return {k:deepcopy(current['meta'][k]) for k in ['url','draft',mode]}
    p.page=Page()
    assert p._attest()==current and p.page.calls==1
    assert old['revision']==3 and old['meta']['draft']=={'v':39}


@pytest.mark.parametrize('mutation',['later_state','state_key','mode','version'])
def test_callback_pump_never_accepts_a_different_snapshot_or_scope(mutation):
    state={'schema':'fact-render-state-browsergym-v1','tree':['first']}
    first={'revision':3,'meta':{'state_key':'site','url':'https://site.test/','draft':{'v':39},'render_state':state}}
    latest=deepcopy(first);latest['revision']=4
    if mutation=='later_state':latest['meta']['draft']['v']=42
    elif mutation=='state_key':latest['meta']['state_key']='other-site'
    elif mutation=='mode':latest['meta'].pop('render_state');latest['meta']['html']='same text'
    else:latest['meta']['render_state']['schema']='unqualified'
    p=FactSourceProvider(enabled=True);p.latest=first
    class Page:
        def evaluate(self, script, key):
            p.latest=latest
            return {k:deepcopy(first['meta'][k]) for k in ['url','draft','render_state']}
    p.page=Page()
    with pytest.raises(ValueError):p._attest()


def test_navigation_pumps_new_review_scope_before_reading_root():
    old={'revision':2,'meta':{'state_key':'retailer','url':'https://shop.test/','draft':{},
         'render_state':{'schema':'fact-render-state-browsergym-v1','tree':['retailer']}}}
    review={'revision':1,'meta':{'state_key':'review:publication','url':'https://reviews.test/reviews/p',
            'root_selector':'#main','state_kind':'static_review','draft':None,
            'render_state':{'schema':'fact-render-state-browsergym-v1','tree':['review']}}}
    p=FactSourceProvider(enabled=True);p.latest=old
    class Page:
        url='https://reviews.test/reviews/p'
        calls=[]
        def evaluate(self,script,config=None):
            self.calls.append(config)
            if config is None:
                p.latest=deepcopy(review);return self.url
            assert config=={'selector':'#main','key':'review:publication','static':True}
            return {k:deepcopy(review['meta'][k]) for k in ['url','draft','render_state']}
    p.page=Page()
    assert p._attest()==review and len(p.page.calls)==2


def test_same_document_attestation_does_not_add_navigation_pump():
    review={'revision':1,'meta':{'state_key':'review:publication','url':'https://reviews.test/reviews/p',
            'root_selector':'#main','state_kind':'static_review','draft':None,
            'render_state':{'schema':'fact-render-state-browsergym-v1','tree':['review']}}}
    p=FactSourceProvider(enabled=True);p.latest=review
    class Page:
        url=review['meta']['url']
        calls=0
        def evaluate(self,script,config):
            self.calls+=1
            assert config['selector']=='#main' and config['static'] is True
            return {k:deepcopy(review['meta'][k]) for k in ['url','draft','render_state']}
    p.page=Page()
    assert p._attest()==review and p.page.calls==1
