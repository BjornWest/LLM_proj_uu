"""No browser/model/producer imports: copied-source and exact DOM-span contract."""
from copy import deepcopy
from pathlib import Path
import pytest

from training.browser_training.fact_render_overlay import instrument_shop, overlay_assets
from training.browser_training.fact_render_capture import normalize
from training.browser_training.fact_exposure import utf16_slice

ROOT = Path(__file__).resolve().parents[1]


def test_off_keeps_original_assets_and_avoids_recorder():
    original={'shop.js':b'not even a recognized renderer','other.js':b'unchanged'}
    assets,receipt=overlay_assets(original,enabled=False)
    assert assets==original and assets is not original
    assert 'fact-recorder.js' not in assets and receipt['enabled'] is False
    assert instrument_shop('unknown seam',enabled=False)[0]=='unknown seam'


def test_current_renderer_overlay_and_served_review_extension():
    original=(ROOT/'environments/website_drafts/shop.js').read_text()
    # The actual Runtime wraps this function; instrumentation must compose with it.
    served=original.replace('function productPage(id,params) {','function originalProductPage(id,params) {')
    served+='\nfunction productPage(id,params){return originalProductPage(id,params);}\n'
    copied,receipt=instrument_shop(served,enabled=True)
    assert receipt['seams']==16 and receipt['source_sha256']!=receipt['output_sha256']
    assert 'function originalProductPage' in copied and 'recordedQuoteAmount' in copied
    assert original==(ROOT/'environments/website_drafts/shop.js').read_text()


@pytest.mark.parametrize('marker',["function render({captureDisclosures=true}={}) {",'<p class="amount">${money(v.price)}</p>','<dd><strong>${money(result.total)}</strong></dd>'])
@pytest.mark.parametrize('change',['remove','duplicate'])
def test_source_drift_fails_explicitly(marker,change):
    original=(ROOT/'environments/website_drafts/shop.js').read_text()
    changed=original.replace(marker,'' if change=='remove' else marker+marker)
    with pytest.raises(ValueError,match='Renderer seam changed'):
        instrument_shop(changed,enabled=True)


def fixture():
    # Two facts in one text node: shipping price can be read without postcode.
    text='49 kr → 75310 🛍'
    commit={'schema':'fact-render-dom-v1','offset_unit':'utf16_code_units','revision':3,'diagnostics':[],
      'registrations':[{'occurrence':{'id':'o1','binding':{'authority':'native_public_field','field':'shipping'},
        'effective_state':{'sku_id':'blue-42','quote_id':'same','selected_service':'home-719'}},
        'element_path':[0], 'runs':[{'relative_child_path':[0],'kind':'text_node','text':text,'start':0,'end':16}],
        'parts':[{'part':'fee','start':0,'end':5,'ranges':[{'run_index':0,'start':0,'end':5}]},
                 {'part':'postcode','start':8,'end':13,'ranges':[{'run_index':0,'start':8,'end':13}]}]}]}
    app={'nodeType':1,'backendNodeId':10,'children':[{'nodeType':1,'backendNodeId':11,
         'children':[{'nodeType':3,'backendNodeId':12,'nodeValue':text}]}]}
    return commit,app


def normalized(commit,app):
    return normalize(commit,app,snapshot_id='s1',document_id='d1',frame_id='f1')


def test_independent_parts_preserve_state_and_real_nodes():
    commit,app=fixture();result=normalized(commit,app)
    run=result['runs'][0];parts=result['occurrences'][0]['parts']
    assert run['backend_node_id']==12
    assert utf16_slice(run['text'],parts[0]['spans'][0]['start'],parts[0]['spans'][0]['end'])=='49 kr'
    assert utf16_slice(run['text'],parts[1]['spans'][0]['start'],parts[1]['spans'][0]['end'])=='75310'
    assert result['occurrences'][0]['effective_state']['selected_service']=='home-719'
    assert result['delivery_evidence'] is False and result['inventory_complete'] is False
    assert result['occurrences'][0]['exposure']=='unknown'


@pytest.mark.parametrize('mutation',['text','path','interval','state'])
def test_stale_or_conflicting_bindings_fail(mutation):
    commit,app=fixture()
    if mutation=='text':app['children'][0]['children'][0]['nodeValue']='same price, different postcode'
    elif mutation=='path':commit['registrations'][0]['element_path']=[0,0]
    elif mutation=='interval':commit['registrations'][0]['parts'][0]['ranges'][0]['end']=4
    else:
        copy=deepcopy(commit['registrations'][0]);copy['occurrence']['effective_state']['selected_service']='home-669'
        commit['registrations'].append(copy)
    with pytest.raises(ValueError):normalized(commit,app)


def test_cross_snapshot_occurrences_do_not_share_credit():
    commit,app=fixture();one=normalized(commit,app)
    two=normalize(commit,app,snapshot_id='s2',document_id='d2',frame_id='f1')
    assert one['occurrences'][0]['id']!=two['occurrences'][0]['id']
    assert one['runs'][0]['id']!=two['runs'][0]['id']


def test_live_control_values_require_independent_capture():
    commit,app=fixture();r=commit['registrations'][0];r['element_path']=[0]
    r['runs']=[{'relative_child_path':[],'kind':'control_value','text':'42','start':0,'end':2}]
    r['parts']=[{'part':'selected_size','start':0,'end':2,'ranges':[{'run_index':0,'start':0,'end':2}]}]
    with pytest.raises(ValueError,match='Verified live control'):normalized(commit,app)
    result=normalize(commit,app,snapshot_id='s1',document_id='d1',frame_id='f1',control_values={11:'42'})
    assert result['runs'][0]['backend_node_id']==11
    with pytest.raises(ValueError,match='Verified live control'):
        normalize(commit,app,snapshot_id='s1',document_id='d1',frame_id='f1',control_values={11:'39'})


def test_harness_packet_preserves_parts_and_unknowns():
    from training.browser_training.fact_render_capture import harness_source_packet
    commit,app=fixture();n=normalized(commit,app)
    run=n['runs'][0];n['ax_sources']=[dict(run,binding={'snapshot_id':'s1','document_id':'d1','frame_id':'f1','node_id':'13','field':'name'})]
    n['ax_diagnostics']=[]
    packet=harness_source_packet(n)
    assert packet['schema']=='ax-fact-sources-v1'
    assert packet['sources'][0]['binding']['snapshot_id']=='s1'
    assert {p['part'] for p in packet['sources'][0]['opaque_binding']['parts']}=={'fee','postcode'}
    assert not packet['private_context']['delivery_evidence']
    packet['private_context']['occurrences'][0]['effective_state']['selected_service']='different'
    assert n['occurrences'][0]['effective_state']['selected_service']=='home-719'
