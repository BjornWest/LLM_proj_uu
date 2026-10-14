"""Pinned copy and actual fragment controls; no world/browser/model launch."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

import pytest

from training.browser_training.fact_review_overlay import (
    copied_review_classes, LEGACY_RENDERER_PINS, SKU_RENDERER_PINS, SKU_SCOPE_PIN)
from training.browser_training.fact_render_overlay import ASSET
from training.browser_training.fact_exposure import utf16_slice

ROOT=Path(__file__).resolve().parents[1]
APPROVED_PINS=LEGACY_RENDERER_PINS
LEGACY_COMMIT='609fec8f400e40b47f487795b6494cc4a1cb60a4'
SKU_COMMIT='7338ce4e51ca1571b76cac8eaef225005e21bc41'


def frozen_source(commit,name,expected):
    import os
    raw=subprocess.check_output(['git','-C',str(ROOT),'show',
        commit+':environments/website_world/'+name+'.py'],
        env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'})
    assert sha256(raw).hexdigest()==expected
    return raw.decode()


@pytest.fixture(scope='module')
def copies():
    # These inputs are source-pinned only. Accepted runtime closure is separate.
    sources=[];expected={}
    for name in ['surrounding_pages','native_review_pages']:
        sources.append(frozen_source(LEGACY_COMMIT,name,APPROVED_PINS[name]))
        expected[name]=APPROVED_PINS[name]
    return (copied_review_classes(*sources,enabled=False),
            copied_review_classes(*sources,enabled=True,expected_sha256=expected),sources,expected)


def fixture(cls,layout,*,empty=False,reviews=None):
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
    if reviews is not None:
        from environments.product_world.review_population import summarize_ratings
        p['reviews']=deepcopy(reviews);p['rating_summary']=summarize_ratings(p['reviews'])
    if empty:p['skus'].append({'sku_id':'empty','product_id':'p','size_label':'XL'})
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
    original=(ROOT/'environments/website_world/native_review_pages.py').read_text()
    plain=fixture(off['NativeReviewPage'],'lab-directory')
    if sha256(original.encode()).hexdigest()==APPROVED_PINS['native_review_pages']:
        assert plain.page('/reviews/p',{})==fixture(NativeReviewPage,'lab-directory').page('/reviews/p',{})
    assert NativeReviewPage is not on['NativeReviewPage']
    assert 'data-fact-recording' not in plain.page('/reviews/p',{})[1]
    assert on['receipt']['shared_files_modified'] is False
    assert (ROOT/'environments/website_world/native_review_pages.py').read_text()==original


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
    source=frozen_source(LEGACY_COMMIT,'surrounding','548968f602a6c2757f22a5c58c53a3c49c02aff516f29c9b5ef0702ccfbe31da')
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


@pytest.fixture(scope='module')
def sku_copies():
    sources=[frozen_source(SKU_COMMIT,name,SKU_RENDERER_PINS[name])
             for name in ('surrounding_pages','native_review_pages')]
    helper=frozen_source(SKU_COMMIT,'review_rating_scopes',SKU_SCOPE_PIN)
    pins={**SKU_RENDERER_PINS,'review_rating_scopes':SKU_SCOPE_PIN}
    off=copied_review_classes(*sources,enabled=False,rating_scope_source=helper)
    on=copied_review_classes(*sources,enabled=True,expected_sha256=pins,rating_scope_source=helper)
    return off,on,sources,helper,pins


@pytest.mark.parametrize('layout',['lab-directory','editorial-magazine','community-feed'])
@pytest.mark.parametrize('route',['selected','option','filtered','model'])
def test_sku_renderer_visible_parity_and_distinct_aggregate_identity(sku_copies,layout,route):
    off,on,_,_,_=sku_copies
    baseline=fixture(off['NativeReviewPage'],layout);page=fixture(on['NativeReviewPage'],layout)
    query={'part':'readers'} if layout=='editorial-magazine' else {}
    path='/reviews/p'
    if route=='option':path='/variants/s1';query={}
    elif route!='model':query['sku']='s1'
    if route=='filtered':query.update(stars='1',page='9999',sort='lowest')
    original=deepcopy(page.products)
    payload,clean=decode(page.page(path,query)[1])
    assert clean==baseline.page(path,query)[1] and page.products==original
    assert payload['meta']['response_html_sha256']==sha256(clean.encode()).hexdigest()
    assert payload['meta']['renderer_source_sha256']==sku_copies[-1]
    aggregates=[r for r in payload['registrations']
                if r['occurrence']['binding']['authority']=='renderer_native_review_aggregate']
    model=[r for r in aggregates if r['occurrence']['binding']['grain']=='model']
    sku=[r for r in aggregates if r['occurrence']['binding']['grain']=='sku']
    assert len(model)==(0 if route=='option' else 9)
    assert len(sku)==(0 if route=='model' else 9)
    assert all(r['occurrence']['binding']['product_id']=='p' for r in aggregates)
    assert all(r['occurrence']['binding']['sku_id']=='s1' and
               r['occurrence']['effective_state']['sku_id']=='s1' and
               r['occurrence']['binding']['basis']=='all_recorded_ratings_one_option_including_silent'
               for r in sku)
    for records,total,written,silent in ((model,7,5,2),(sku,3,2,1)):
        if not records:continue
        values={r['occurrence']['binding']['field']:r['occurrence']['binding']['displayed_value']
                for r in records if r['occurrence']['binding']['field'].endswith('count')}
        assert values=={'rating_count':total,'written_review_count':written,'rating_only_count':silent}
        assert sum(r['occurrence']['binding']['displayed_value'] for r in records
                   if r['occurrence']['binding']['field']=='star_counts')==total
        for r in records:
            for part in r['content']['parts']:
                text=utf16_slice(r['content']['text'],part['start'],part['end'])
                assert text
                if part['part'] in ('count','value'):
                    assert float(text)==r['occurrence']['binding']['displayed_value']
    if sku:
        average=next(r for r in sku if r['occurrence']['binding']['field']=='average_rating')
        assert average['content']['text']=='5.00 / 5'
        assert average['occurrence']['binding']['rendered_value']=='5.00'
        counts=[r for r in sku if r['occurrence']['binding']['field'].endswith('count')]
        assert len({r['anchor'] for r in counts})==1
        assert 'Option-specific customer rating summary' in clean
    if model:assert 'Model-wide customer rating summary' in clean


@pytest.mark.parametrize('layout',['lab-directory','editorial-magazine','community-feed'])
def test_empty_sku_mean_is_explicit_undefined_without_numeric_or_scale_parts(sku_copies,layout):
    off,on,_,_,_=sku_copies
    base=fixture(off['NativeReviewPage'],layout,empty=True)
    page=fixture(on['NativeReviewPage'],layout,empty=True)
    payload,clean=decode(page.page('/variants/empty',{})[1])
    assert clean==base.page('/variants/empty',{})[1]
    records=[r for r in payload['registrations'] if r['occurrence']['binding'].get('grain')=='sku']
    assert len(records)==9
    avg=next(r for r in records if r['occurrence']['binding']['field']=='average_rating')
    assert avg['occurrence']['binding']['displayed_value'] is None
    assert avg['occurrence']['binding']['value_status']=='undefined_no_ratings'
    assert avg['content']['text']=='Mean rating undefined (no ratings)'
    assert [p['part'] for p in avg['content']['parts']]==['status']
    assert all(r['occurrence']['binding']['displayed_value']==0 for r in records if r is not avg)


@pytest.mark.parametrize('mutation',['missing_product','wrong_product','unknown_sku','wrong_mean','wrong_count','boolean_count','model_record','no_helper'])
def test_sku_summary_cannot_relabel_model_values_or_forge_public_scope(sku_copies,mutation):
    from training.browser_training.fact_review_overlay import review_average
    page=fixture(sku_copies[1]['NativeReviewPage'],'lab-directory')
    record={'product_id':'p','sku_id':'s1',
            'rating_summary':page._fact_sku_rating_summary(page.products['p'],'s1')}
    if mutation=='missing_product':record.pop('product_id')
    elif mutation=='wrong_product':record['product_id']='other'
    elif mutation=='unknown_sku':record['sku_id']='other'
    elif mutation=='wrong_mean':record['rating_summary']['mean_rounded']='1.00'
    elif mutation=='wrong_count':record['rating_summary']['rating_count']=7
    elif mutation=='boolean_count':record['rating_summary']['rating_only_count']=True
    elif mutation=='model_record':record['rating_summary']=deepcopy(page.products['p']['rating_summary'])
    else:page._fact_sku_rating_summary=None
    with pytest.raises(ValueError):review_average(page,record,'p','5.00 / 5')


@pytest.mark.parametrize('mutation',['missing_helper','changed_helper','changed_renderer','missing_helper_pin','mixed_pair'])
def test_modern_recording_requires_exact_full_three_source_closure(sku_copies,copies,mutation):
    _,_,sources,helper,pins=sku_copies
    sources=list(sources);pins=dict(pins)
    if mutation=='missing_helper':helper=None
    elif mutation=='changed_helper':helper+='\n# changed'
    elif mutation=='changed_renderer':sources[0]+='\n# changed'
    elif mutation=='missing_helper_pin':pins.pop('review_rating_scopes')
    else:sources[1]=copies[2][1]
    with pytest.raises(ValueError,match='pin|scope source'):
        copied_review_classes(*sources,enabled=True,expected_sha256=pins,rating_scope_source=helper)


@pytest.mark.parametrize('layout',['journal','community'])
@pytest.mark.parametrize('query',[{}, {'sku':'s1'}, {'sku':'s1','stars':'1'}])
def test_legacy_layouts_modern_summary_has_exact_parity_and_option_grain(sku_copies,layout,query):
    off,on,_,_,_=sku_copies
    base=fixture(off['ReviewPage'],layout);page=fixture(on['ReviewPage'],layout)
    payload,clean=decode(page.page('/reviews/p',query)[1])
    assert clean==base.page('/reviews/p',query)[1]
    records=[r for r in payload['registrations'] if r['occurrence']['binding']['authority']=='renderer_native_review_aggregate']
    assert len(records)==(18 if query.get('sku') else 9)
    sku=[r for r in records if r['occurrence']['binding']['grain']=='sku']
    assert len(sku)==(9 if query.get('sku') else 0)
    if sku:
        assert all(r['occurrence']['binding']['sku_id']=='s1' for r in sku)
        assert next(r['occurrence']['binding']['displayed_value'] for r in sku
                    if r['occurrence']['binding']['field']=='rating_count')==3


@pytest.mark.parametrize('ratings,expected',[
    ([4,5],'4.50'), ([3,3,4],'3.33'), ([4]*199+[5],'4.01')])
def test_silent_and_half_up_rounded_mean_parts_match_actual_display(sku_copies,ratings,expected):
    rows=[{'review_id':f'silent-{n}','product_id':'p','sku_id':'s1','reviewer':'Silent',
           'rating':stars,'text':''} for n,stars in enumerate(ratings)]
    # A written vote on another option must affect only the model summary.
    rows.append({'review_id':'other','product_id':'p','sku_id':'s2','reviewer':'Other',
                 'rating':1,'text':'Different option'})
    off,on,_,_,_=sku_copies
    base=fixture(off['NativeReviewPage'],'lab-directory',reviews=rows)
    page=fixture(on['NativeReviewPage'],'lab-directory',reviews=rows)
    payload,clean=decode(page.page('/reviews/p',{'sku':'s1','stars':'1'})[1])
    assert clean==base.page('/reviews/p',{'sku':'s1','stars':'1'})[1]
    records=[r for r in payload['registrations'] if r['occurrence']['binding'].get('grain')=='sku']
    byfield={r['occurrence']['binding']['field']:r for r in records}
    assert byfield['rating_count']['occurrence']['binding']['displayed_value']==len(ratings)
    assert byfield['written_review_count']['occurrence']['binding']['displayed_value']==0
    assert byfield['rating_only_count']['occurrence']['binding']['displayed_value']==len(ratings)
    avg=byfield['average_rating'];binding=avg['occurrence']['binding']
    assert avg['content']['text']==expected+' / 5'
    assert binding['rendered_value']==expected and binding['displayed_value']==float(expected)
    value=next(p for p in avg['content']['parts'] if p['part']=='value')
    assert utf16_slice(avg['content']['text'],value['start'],value['end'])==expected
    assert binding['value_basis']=='rounded_public_mean'


@pytest.mark.parametrize('mutation',['duplicate_sku','sku_parent','product_record','rendered_text'])
def test_public_sku_identity_and_display_are_conjunctively_bound(sku_copies,mutation):
    from training.browser_training.fact_review_overlay import review_average
    page=fixture(sku_copies[1]['NativeReviewPage'],'lab-directory')
    record={'product_id':'p','sku_id':'s1','rating_summary':page._fact_sku_rating_summary(page.products['p'],'s1')}
    if mutation=='duplicate_sku':page.products['p']['skus'].append(deepcopy(page.products['p']['skus'][0]))
    elif mutation=='sku_parent':page.products['p']['skus'][0]['product_id']='other'
    elif mutation=='product_record':record=deepcopy(page.products['p']);record['sku_id']='s1'
    text='1.00 / 5' if mutation=='rendered_text' else '5.00 / 5'
    with pytest.raises(ValueError):review_average(page,record,'p',text)


def test_new_disabled_renderer_has_no_private_payload_and_keeps_native_modules(sku_copies):
    import sys
    original={name:module for name,module in sys.modules.items() if name in (
        'environments.website_world.native_review_pages',
        'environments.website_world.surrounding_pages',
        'environments.website_world.review_rating_scopes')}
    off,on,_,_,_=sku_copies
    html=fixture(off['NativeReviewPage'],'lab-directory').page('/reviews/p',{'sku':'s1'})[1]
    assert 'fact-recording-private-data' not in html and 'data-fr-review' not in html
    assert on['receipt']['source_sha256']==sku_copies[-1]
    assert on['receipt']['inventory_complete'] is False and on['receipt']['producer_qualified'] is False
    assert all(sys.modules[name] is module for name,module in original.items())


@pytest.mark.parametrize('part',['readers','specifications'])
def test_editorial_registrations_refer_only_to_fragments_actually_emitted(sku_copies,part):
    page=fixture(sku_copies[1]['NativeReviewPage'],'editorial-magazine')
    html=page.page('/reviews/p',{'part':part,'sku':'s1'})[1]
    payload,clean=decode(html)
    anchors=set(re.findall(r' data-fr-review="(review-\d+)"',html))
    assert payload['registrations']
    assert all(r['anchor'] in anchors for r in payload['registrations'])
    if part=='readers':
        assert not any(r['occurrence']['binding']['authority']=='native_public_field'
                       for r in payload['registrations'])
        assert 'id="specifications"' not in clean
    else:
        assert not any(r['occurrence']['binding']['authority']=='renderer_native_review_aggregate'
                       for r in payload['registrations'])


def test_legacy_model_object_with_sku_key_retains_original_response_and_registration_grain(copies):
    off,on,_,_=copies
    base=fixture(off['NativeReviewPage'],'lab-directory');page=fixture(on['NativeReviewPage'],'lab-directory')
    for view in (base,page):view.products['p']['sku_id']='unrelated-model-metadata'
    payload,clean=decode(page.page('/reviews/p',{})[1])
    assert clean==base.page('/reviews/p',{})[1]
    assert all(r['occurrence']['binding']['grain']=='model' for r in payload['registrations']
               if r['occurrence']['binding']['authority']=='renderer_native_review_aggregate')


@pytest.mark.parametrize('mutation',['duplicate_sku','missing_sku_product'])
def test_recording_identity_failure_preserves_native_response_and_reports_no_registrations(sku_copies,mutation):
    off,on,_,_,_=sku_copies
    base=fixture(off['NativeReviewPage'],'lab-directory');page=fixture(on['NativeReviewPage'],'lab-directory')
    for view in (base,page):
        if mutation=='duplicate_sku':view.products['p']['skus'].append(deepcopy(view.products['p']['skus'][0]))
        else:view.products['p']['skus'][0].pop('product_id')
    status,html,mime=page.page('/reviews/p',{'sku':'s1'})
    payload,clean=decode(html)
    expected=base.page('/reviews/p',{'sku':'s1'})
    assert (status,clean,mime)==expected
    assert not payload['registrations']
    assert payload['meta']['recording_diagnostics'][0]['reason']=='review_registration_rejected'
    # Error context is request-local; the next valid render is not disabled.
    if mutation=='duplicate_sku':page.products['p']['skus'].pop()
    else:page.products['p']['skus'][0]['product_id']='p'
    good,_=decode(page.page('/reviews/p',{'sku':'s1'})[1])
    assert good['registrations'] and 'recording_diagnostics' not in good['meta']


def test_modern_rounded_model_mean_binding_matches_public_text_too(sku_copies):
    off,on,_,_,_=sku_copies
    base=fixture(off['NativeReviewPage'],'lab-directory');page=fixture(on['NativeReviewPage'],'lab-directory')
    for view in (base,page):view.products['p']['rating_summary']['mean_rounded']='3.86'
    payload,clean=decode(page.page('/reviews/p',{})[1])
    assert clean==base.page('/reviews/p',{})[1]
    avg=next(r for r in payload['registrations'] if r['occurrence']['binding']['field']=='average_rating')
    assert avg['content']['text']=='3.86 / 5'
    assert avg['occurrence']['binding']['displayed_value']==3.86
    assert avg['occurrence']['binding']['rendered_value']=='3.86'


def test_two_pin_modern_caller_and_disabled_without_helper_are_explicitly_rejected(sku_copies):
    _,_,sources,_,_=sku_copies
    with pytest.raises(ValueError,match='pinned scope source'):
        copied_review_classes(*sources,enabled=True,expected_sha256=SKU_RENDERER_PINS)
    with pytest.raises(ValueError,match='pinned scope source'):
        copied_review_classes(*sources,enabled=False)


def test_rounded_helper_uses_checked_private_population_instead_of_ambient_function(sku_copies,monkeypatch):
    from environments.product_world import review_population
    monkeypatch.setattr(review_population,'summarize_ratings',lambda rows:(_ for _ in ()).throw(AssertionError('ambient used')))
    _,_,sources,helper,pins=sku_copies
    on=copied_review_classes(*sources,enabled=True,expected_sha256=pins,rating_scope_source=helper)
    page=fixture(on['NativeReviewPage'],'lab-directory')
    assert decode(page.page('/reviews/p',{'sku':'s1'})[1])[0]['registrations']
    assert on['receipt']['native_dependency_sha256']['review_population']


def test_sku_projection_extra_keys_are_not_admitted(sku_copies):
    from training.browser_training.fact_review_overlay import review_average
    page=fixture(sku_copies[1]['NativeReviewPage'],'lab-directory')
    record={'product_id':'p','sku_id':'s1','rating_summary':page._fact_sku_rating_summary(page.products['p'],'s1'),'hidden':'extra'}
    with pytest.raises(ValueError):review_average(page,record,'p','5.00 / 5')


@pytest.mark.parametrize('rounded',['n/a',None,'nan','inf','5.01','<invalid>'])
def test_bad_model_rounded_display_preserves_native_html_and_reports_rejection(sku_copies,rounded):
    off,on,_,_,_=sku_copies
    plain=fixture(off['NativeReviewPage'],'lab-directory');recorded=fixture(on['NativeReviewPage'],'lab-directory')
    for page in (plain,recorded):page.products['p']['rating_summary']['mean_rounded']=rounded
    native=plain.page('/reviews/p',{});status,html,mime=recorded.page('/reviews/p',{})
    payload,clean=decode(html)
    assert (status,clean,mime)==native
    assert not payload['registrations'] and payload['meta']['recording_diagnostics']
    assert 'NaN' not in json.dumps(payload)


def test_private_review_sink_keeps_rejection_in_normalized_capture_diagnostics():
    from training.browser_training.fact_review_overlay import private_review_script
    from training.browser_training.fact_render_capture import normalize
    script=r'''
      const failure={reason:'review_registration_rejected',detail:'unsupported identity'};
      const payload={registrations:[],meta:{recording_diagnostics:[failure]}};
      const data={textContent:JSON.stringify(payload),remove(){}};
      const root={nodeType:1,nodeName:'MAIN',nodeValue:null,attributes:[],childNodes:[],
        outerHTML:'<main id="main"></main>',querySelectorAll:()=>[],contains:()=>false,addEventListener(){}};
      global.document={getElementById:()=>data,querySelector:()=>root};
      global.location={href:'https://reviews.example/reviews/p'};
      global.__recordFactCommit=record=>{global.saved=record;};
    '''
    result=subprocess.run(['node','-e',script+private_review_script()+"\nconsole.log(JSON.stringify(global.saved));"],
                          capture_output=True,text=True,check=True,timeout=10)
    commit=json.loads(result.stdout)
    captured=normalize(commit,{},snapshot_id='snapshot',document_id='doc',frame_id='frame')
    assert captured['diagnostics']==[{'reason':'review_registration_rejected','detail':'unsupported identity'}]
    assert not captured['occurrences']


@pytest.mark.parametrize('origin',[None,'compiled.pyc','missing.py'])
def test_modern_population_missing_source_has_labelled_setup_failure(sku_copies,monkeypatch,origin):
    import training.browser_training.fact_review_overlay as overlay
    from types import SimpleNamespace
    monkeypatch.setattr(overlay.importlib.util,'find_spec',lambda _:None if origin is None else SimpleNamespace(origin=origin))
    _,_,sources,helper,pins=sku_copies
    with pytest.raises(ValueError,match='Review population dependency'):
        copied_review_classes(*sources,enabled=True,expected_sha256=pins,rating_scope_source=helper)


def test_modern_population_drift_fails_closed_before_helper_execution(sku_copies,monkeypatch,tmp_path):
    import training.browser_training.fact_review_overlay as overlay
    from types import SimpleNamespace
    changed=tmp_path/'changed.py';changed.write_text("raise AssertionError('unchecked population executed')\n")
    monkeypatch.setattr(overlay.importlib.util,'find_spec',lambda _:SimpleNamespace(origin=str(changed)))
    _,_,sources,helper,pins=sku_copies
    with pytest.raises(ValueError,match='dependency source pin changed'):
        copied_review_classes(*sources,enabled=True,expected_sha256=pins,rating_scope_source=helper)


def test_verified_corpus_rejection_uses_native_fallback(sku_copies):
    off,on,_,_,_=sku_copies
    plain=fixture(off['NativeReviewPage'],'lab-directory');recorded=fixture(on['NativeReviewPage'],'lab-directory')
    real=recorded._fact_sku_rating_summary
    def changed_check(product,sid):
        summary=real(product,sid);summary['rating_count']+=1;return summary
    recorded._fact_sku_rating_summary=changed_check
    payload,clean=decode(recorded.page('/reviews/p',{'sku':'s1'})[1])
    assert clean==plain.page('/reviews/p',{'sku':'s1'})[1]
    assert not payload['registrations']
    assert payload['meta']['recording_diagnostics'][0]['detail']=='Review summary differs from the complete public SKU corpus'
