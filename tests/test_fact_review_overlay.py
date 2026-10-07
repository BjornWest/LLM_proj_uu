"""Pinned copy and actual fragment controls; no world/browser/model launch."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

import pytest

from training.browser_training.fact_review_overlay import copied_review_classes
from training.browser_training.fact_render_overlay import ASSET
from training.browser_training.fact_exposure import utf16_slice

ROOT=Path(__file__).resolve().parents[1]
APPROVED_PINS={'surrounding_pages':'666a2e3113e2b0d7d28a8c1b46db9b40d40158dfcea475a221b03fc445cc2d8e',
               'native_review_pages':'961db9223afbdc44c6192a144dfd0a10103066e5448f8762405066ee9dd286fc'}


@pytest.fixture(scope='module')
def copies():
    # These inputs are source-pinned only. Accepted runtime closure is separate.
    sources=[];expected={}
    for name in ['surrounding_pages','native_review_pages']:
        path=f'environments/website_world/{name}.py'
        sources.append((ROOT/path).read_text())
        expected[name]=APPROVED_PINS[name]
    return (copied_review_classes(*sources,enabled=False),
            copied_review_classes(*sources,enabled=True,expected_sha256=expected),sources,expected)


def fixture(cls,layout):
    p={'product_id':'p','name':'Test Shirt','family_id':'tops',
       'facts':{'cotton':False,'weight_g':0,'secret':None,'model_price_factor':4},
       'fact_status':{'secret':'unknown'},
       'skus':[{'sku_id':'s1','product_id':'p','size_label':'S'},
               {'sku_id':'s2','product_id':'p','size_label':'L'}],
       'reviews':[{'review_id':f'note-{n}','reviewer':f'Reader {n}','product_id':'p',
                   'sku_id':'s1' if n%2 else 's2','rating':5 if n%2 else 3,
                   'text':f'Exact note {n} 🛍 <raw>' if n<5 else ''} for n in range(7)],
       'rating_summary':{'rating_count':7,'written_review_count':5,'rating_only_count':2,
                         'average_rating':3.86,'star_counts':{'1':0,'2':0,'3':4,'4':0,'5':3}}}
    site={'id':'review-host','name':'Review Atlas','layout':layout,'families':['tops'],
          'family_labels':{'tops':'Tops'},'review_presentation':{'page_size':2}}
    return cls(site,{'p':p},{},{},None)


def decode(html):
    payload=json.loads(re.search(r'<script type="application/json"[^>]*>(.*?)</script>',html,re.S).group(1))
    clean=re.sub(r' data-fr-review="review-\d+"','',html)
    clean=re.sub(r'\n(?:<script[^>]*data-fact-recording-private[^>]*>.*?</script>\n)+','',clean,flags=re.S)
    return payload,clean


@pytest.mark.parametrize('layout',['lab-directory','editorial-magazine','community-feed'])
@pytest.mark.parametrize('case',['all','sku','specifications'])
def test_exact_visible_document_and_scoped_bindings(copies,layout,case):
    off,on,_,_=copies
    query={'part':'readers'} if layout=='editorial-magazine' else {}
    if case=='sku':query['sku']='s1'
    if case=='specifications' and layout=='editorial-magazine':query={'part':'specifications'}
    baseline=fixture(off['NativeReviewPage'],layout)
    recorded=fixture(on['NativeReviewPage'],layout)
    before=deepcopy(recorded.products)
    expected=baseline.page('/reviews/p',query)[1]
    payload,clean=decode(recorded.page('/reviews/p',query)[1])
    assert clean==expected and recorded.products==before
    assert payload['meta']['response_html_sha256']==sha256(expected.encode()).hexdigest()
    records=payload['registrations']
    assert all(r['occurrence']['binding']['product_id']=='p' for r in records)
    aggregates=[r for r in records if r['occurrence']['binding']['authority']=='renderer_native_review_aggregate']
    if not (case=='specifications' and layout=='editorial-magazine'):
        assert len(aggregates)==9
        assert all(r['occurrence']['binding']['grain']=='model' for r in aggregates)
        counts=[r for r in aggregates if r['occurrence']['binding']['field'].endswith('count')]
        assert len(counts)==3 and len({r['anchor'] for r in counts})==1
        for r in counts:
            part=r['content']['parts'][0]
            assert int(utf16_slice(r['content']['text'],part['start'],part['end']))==r['occurrence']['binding']['displayed_value']
    if case=='sku':
        assert all(r['occurrence']['binding']['sku_id']=='s1' for r in records
                   if r['occurrence']['binding']['authority']=='renderer_native_review_text')
        # A filtered written view never turns seven all-model ratings into two.
        assert next(r['occurrence']['binding']['displayed_value'] for r in aggregates
                    if r['occurrence']['binding']['field']=='rating_count')==7
    for r in records:
        assert r['occurrence']['binding'].get('field') not in ['secret','model_price_factor']


def test_disabled_copy_is_exact_and_does_not_patch_shared_modules(copies):
    from environments.website_world.native_review_pages import NativeReviewPage
    off,on,sources,pins=copies
    base=fixture(NativeReviewPage,'lab-directory'); plain=fixture(off['NativeReviewPage'],'lab-directory')
    assert plain.page('/reviews/p',{})==base.page('/reviews/p',{})
    assert 'data-fact-recording' not in plain.page('/reviews/p',{})[1]
    assert on['receipt']['shared_files_modified'] is False
    assert (ROOT/'environments/website_world/native_review_pages.py').read_text()==sources[1]


@pytest.mark.parametrize('mutation',['drift','missing_pins'])
def test_enabled_copy_refuses_changed_or_unapproved_source(copies,mutation):
    _,_,sources,pins=copies
    if mutation=='drift':sources=[sources[0]+'\n# changed',sources[1]]
    else:pins=None
    with pytest.raises(ValueError,match='source pins'):
        copied_review_classes(*sources,enabled=True,expected_sha256=pins)


def test_three_facts_on_one_existing_node_all_survive_private_adoption():
    source=ASSET.read_text()
    script=r'''
const text='7 ratings; 5 written reviews, 2 ratings without comments.';
const leaf={nodeType:3,nodeName:'#text',nodeValue:text,childNodes:[]};
const paragraph={nodeType:1,nodeName:'P',nodeValue:null,attributes:[],childNodes:[leaf],textContent:text};
const root={nodeType:1,nodeName:'MAIN',nodeValue:null,attributes:[],childNodes:[paragraph],
  contains:node=>node===paragraph,querySelectorAll:()=>[]};
paragraph.parentNode=root;leaf.parentNode=paragraph;
let output;const recorder=createFactRecorder({enabled:true,sink:r=>output=r});
for(let n=0;n<3;n++)recorder.adopt(paragraph,{id:`fact-${n}`,binding:{field:n},effective_state:{}},
  {text,parts:[{part:'value',start:n,end:n+1}]});
recorder.commit(root,{});
console.log(JSON.stringify(output.registrations.map(r=>({id:r.occurrence.id,path:r.element_path,parts:r.parts}))));
'''
    result=subprocess.run(['node','--input-type=module','-e',source+script],capture_output=True,text=True,check=True)
    records=json.loads(result.stdout)
    assert len(records)==3 and {r['id'] for r in records}=={'fact-0','fact-1','fact-2'}
    assert all(r['path']==[0] for r in records)
    assert [r['parts'][0]['ranges'][0]['start'] for r in records]==[0,1,2]


def test_native_site_id_is_preserved_and_missing_identity_is_rejected(copies):
    _,on,_,_=copies
    page=fixture(on['NativeReviewPage'],'lab-directory')
    payload,_=decode(page.page('/reviews/p',{} )[1])
    assert payload['meta']['site_id']=='review-host'
    assert all(r['occurrence']['binding']['site_id']=='review-host' for r in payload['registrations'])
    # Real surrounding sites use site_id; a friendly site name is not an ID.
    site=dict(page.site);site.pop('id',None);site['site_id']='canonical-review'
    native=on['NativeReviewPage'](site,page.products,page.bindings,page.retailer_names,page.index_origin)
    assert decode(native.page('/reviews/p',{})[1])[0]['meta']['site_id']=='canonical-review'
    site.pop('site_id')
    with pytest.raises(ValueError,match='identity'):
        on['NativeReviewPage'](site,page.products,page.bindings,page.retailer_names,page.index_origin)


def test_mount_copy_changes_only_its_private_renderer_globals(copies):
    from training.browser_training.fact_review_overlay import copied_review_mount
    from environments.website_world import surrounding
    _,on,_,_=copies
    source=(ROOT/'environments/website_world/surrounding.py').read_text()
    private=copied_review_mount(source,on,expected_sha256='548968f602a6c2757f22a5c58c53a3c49c02aff516f29c9b5ef0702ccfbe31da')
    assert private.NativeReviewPage is on['NativeReviewPage']
    assert surrounding.NativeReviewPage is not private.NativeReviewPage
    assert private.mount.__globals__['NativeReviewPage'] is on['NativeReviewPage']
    with pytest.raises(ValueError,match='pin changed'):copied_review_mount(source+'\n',on,expected_sha256='wrong')


def test_retailer_page_alias_and_canonical_task_subject_stay_separate():
    from training.browser_training.fact_render_overlay import HELPERS
    script=ASSET.read_text()+"\nconst site='retailer-one';\n"+HELPERS+r'''
const p={id:'page-red',canonicalProductId:'canonical-model'};
const v={skuId:'red-42',offerId:'offer-r',key:'red-42',selection:{size:'42'}};
const f={field:'product.facts.cushioning',subjectType:'product',subjectId:'canonical-model',value:'firm'};
console.log(JSON.stringify({state:factState(p,v),binding:fieldBinding(f,p,v)}));
'''
    result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,check=True)
    row=json.loads(result.stdout)
    assert row['state']['product_id']==row['binding']['product_id']=='canonical-model'
    assert row['state']['page_id']==row['binding']['page_id']=='page-red'
    assert row['binding']['subject_id']=='canonical-model'
    assert row['state']['sku_id']=='red-42'


def test_copied_review_recording_uses_same_origin_asset_under_native_csp(copies):
    off,on,_,_=copies
    recorded=fixture(on['NativeReviewPage'],'lab-directory')
    html=recorded.page('/reviews/p',{})[1]
    assert '<script src="/__fact-recorder-private.js"' in html
    assert 'const payload=' not in html
    status,script,mime=recorded.page('/__fact-recorder-private.js',{})
    assert status==200 and mime.startswith('text/javascript')
    assert "JSON.parse(data.textContent)" in script and '__recordFactCommit' in script
    subprocess.run(['node','--check','--input-type=commonjs'],input=script,text=True,capture_output=True,check=True)
    assert recorded.page('/__fact-recorder-private.js',{'foreign':'1'})[0]==400
    with pytest.raises(KeyError):fixture(off['NativeReviewPage'],'lab-directory').page('/__fact-recorder-private.js',{})
