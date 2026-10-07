"""Offline recipient/span/state controls; no browser, model or producer imports."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from intent_browser.policy_delivery import PolicyDelivery
from training.browser_training.fact_exposure import digest, object_digest
from training.browser_training.fact_delivery_features import extract


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))


def capture(path, *, index=0, step=0, service='home-719', mapped=True):
    sid=f'fact-capture-{index:04d}'; oid=f'{sid}/o1'; source_id=f'{sid}-source-0000'
    state={'sku_id':'blue-42', 'quote_id':'same', 'selected_service':service}
    spans=[{'part':'fee', 'spans':[{'source_id':'dom-run', 'start':0, 'end':5}]},
           {'part':'postcode', 'spans':[{'source_id':'dom-run', 'start':8, 'end':13}]}]
    source={'id':source_id, 'export_id':'dom-run', 'text':'49 kr → 75310 🛍',
            'sha256':digest('49 kr → 75310 🛍'), 'captured_step':step,
            'binding':{'snapshot_id':sid, 'document_id':'d1', 'frame_id':'f1',
                       'node_id':'n1', 'field':'name'},
            'opaque_binding':{'parts':[{'occurrence_id':oid, 'state_id':object_digest(state),
                                      'part':p['part'], 'start':p['spans'][0]['start'],
                                      'end':p['spans'][0]['end']} for p in spans]}}
    save(path/f'{sid}.json', {'schema':'ax-fact-provenance-v1', 'offset_unit':'utf16_code_units',
         'id':sid, 'step':step, 'snapshot_id':sid, 'sources':[source] if mapped else [],
         'private_context':{'schema':'fact-render-occurrence-joins-v1', 'occurrences':[
             {'id':oid, 'binding':{'authority':'renderer_native_shipment_scalar','field':'fee'},
              'effective_state':state, 'parts':spans}]}})
    return source


def delivery(path, sources_and_spans, *, step=0, ack=True, recipient='main', ledger=None,
             rows=None, stale=False):
    ledger=ledger or PolicyDelivery(SimpleNamespace(directory=path,event=lambda *a,**k:None))
    rows=rows if rows is not None else []
    # One exact retained output may cover only the fee of a compound text node.
    messages=[]; bindings=[]
    for source,start,end in sources_and_spans:
        text=source['text'][start:end]
        cid=ledger.register('ax_result',text,step=step)
        artifact=f'projection-{cid}.json'
        save(path/artifact, {'schema':'ax-fact-provenance-v1', 'offset_unit':'utf16_code_units',
            'content_id':cid, 'text_sha256':digest(text), 'projections':[
                {'source_id':source['id'], 'source_sha256':source['sha256'],
                 'binding_sha256':'wrong' if stale else object_digest(source['binding']),
                 'source_start':start,'source_end':end,'output_path':[],
                 'output_start':0,'output_end':end-start,'encoding':'identity'}]})
        ledger.sources[cid]['provenance']={'fact_projection_artifact':artifact}
        save(path/ledger.sources[cid]['artifact'],ledger.sources[cid])
        bindings.append({'content_id':cid,'message_index':len(messages),'start':0,'end':len(text)})
        messages.append({'role':'tool','content':text})
    event={'step':step,'messages':messages,'model_request':{'messages':messages}}
    ledger.record(event,bindings,acknowledged=ack,recipient=recipient);rows.append(event)
    (path/'steps.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    return ledger,rows


def test_fee_and_destination_are_independent_and_repeated_reads_do_not_inflate(tmp_path):
    source=capture(tmp_path)
    ledger,rows=delivery(tmp_path,[(source,0,5),(source,0,5)])
    result=extract(tmp_path,step=0); row=result['records'][0]
    assert row['status']=='partial' and row['parts']['fee']['status']=='complete'
    assert row['parts']['fee']['observed_utf16']==5
    assert row['parts']['postcode']['status']=='unknown'
    assert not result['inventory_complete'] and not result['producer_qualified']
    delivery(tmp_path,[(source,8,13)],step=1,ledger=ledger,rows=rows)
    assert extract(tmp_path,step=1)['records'][0]['status']=='complete'
    assert extract(tmp_path,step=0)['records'][0]['status']=='partial'


@pytest.mark.parametrize('control',['unacknowledged','different_recipient','stale_projection','missing_request'])
def test_unconfirmed_or_invalid_delivery_never_earns_coverage(tmp_path,control):
    source=capture(tmp_path)
    delivery(tmp_path,[(source,0,5)],ack=control!='unacknowledged',
             recipient='worker' if control=='different_recipient' else 'main',stale=control=='stale_projection')
    if control=='missing_request':
        (tmp_path/'steps.jsonl').unlink()
    assert extract(tmp_path,step=0)['records'][0]['status']=='unknown'


def test_same_state_equivalent_realizations_union_but_service_changes_do_not(tmp_path):
    first=capture(tmp_path)
    second=capture(tmp_path,index=1,step=1)
    third=capture(tmp_path,index=2,step=2,service='home-669')
    ledger,rows=delivery(tmp_path,[(first,0,3)])
    delivery(tmp_path,[(second,3,5),(second,8,13)],step=1,ledger=ledger,rows=rows)
    delivery(tmp_path,[(third,8,13)],step=2,ledger=ledger,rows=rows)
    assert extract(tmp_path,step=0)['records'][0]['parts']['fee']['observed_utf16']==3
    result=extract(tmp_path,step=2)
    assert len(result['records'])==2
    by_service={r['effective_state']['selected_service']:r for r in result['records']}
    assert by_service['home-719']['status']=='complete'
    assert by_service['home-669']['parts']['fee']['status']=='unknown'


def test_unknown_dom_ax_mapping_is_retained_without_false_absence(tmp_path):
    capture(tmp_path,mapped=False)
    result=extract(tmp_path,step=0)
    assert result['records'][0]['status']=='unknown'
    assert all(not p['source_mapping_complete'] for p in result['records'][0]['parts'].values())


def test_receipt_revalidated_against_retained_request(tmp_path):
    source=capture(tmp_path);delivery(tmp_path,[(source,0,5)])
    event=json.loads((tmp_path/'steps.jsonl').read_text())
    event['model_request']['messages'][0]['content']='replaced'
    (tmp_path/'steps.jsonl').write_text(json.dumps(event)+'\n')
    result=extract(tmp_path,step=0)
    assert result['records'][0]['status']=='unknown' and result['diagnostics']['invalid_receipt']==1
