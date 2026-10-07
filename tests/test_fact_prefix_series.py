"""Request chronology controls over exact saved receipts; no browser/provider."""
import json

import pytest

from training.browser_training.fact_prefix_series import extract_prefixes
from test_fact_delivery_features import capture, delivery


def lifecycle(path, events):
    (path/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))


def start(step):
    return {'event':'model_started','call_id':f'model-{step:03d}'}


def completed(row):
    return {'event':'model_completed','call_id':f'model-{row["step"]:03d}',
            'model_request':row['model_request']}


def recorded(index):
    return {'event':'fact_capture_recorded','step':0,
            'artifact':f'fact-capture-{index:04d}.json'}


def test_future_same_step_capture_cannot_enter_earlier_inventory(tmp_path):
    first=capture(tmp_path)
    later=capture(tmp_path,index=1,step=0,service='home-669')
    ledger,rows=delivery(tmp_path,[(first,0,5)])
    delivery(tmp_path,[(later,0,5),(later,8,13)],step=1,ledger=ledger,rows=rows)
    lifecycle(tmp_path,[recorded(0),start(0),completed(rows[0]),recorded(1),start(1),completed(rows[1])])
    result=extract_prefixes(tmp_path)
    prefixes=result['prefixes']
    assert len(prefixes)==2 and all(p['capture_boundary_status']=='joined' for p in prefixes)
    early=prefixes[0]['native_coverage']['records']
    assert len(early)==1 and early[0]['effective_state']['selected_service']=='home-719'
    assert early[0]['parts']['postcode']['status']=='unknown'
    late=prefixes[1]['native_coverage']['records']
    assert len(late)==2 and sum(r['status']=='complete' for r in late)==1


def test_future_same_step_projection_fails_closed(tmp_path):
    first=capture(tmp_path);later=capture(tmp_path,index=1,step=0,service='home-669')
    _,rows=delivery(tmp_path,[(later,0,5)])
    lifecycle(tmp_path,[recorded(0),start(0),completed(rows[0]),recorded(1)])
    result=extract_prefixes(tmp_path)['prefixes'][0]['native_coverage']
    assert len(result['records'])==1 and result['records'][0]['status']=='unknown'
    assert result['diagnostics']['invalid_projection']==1


@pytest.mark.parametrize('fault',['missing','hash','duplicate_start','duplicate_completion'])
def test_missing_or_ambiguous_boundary_never_uses_step_fallback(tmp_path,fault):
    source=capture(tmp_path);_,rows=delivery(tmp_path,[(source,0,5)])
    events=[recorded(0),start(0),completed(rows[0])]
    if fault=='hash':events[-1]['model_request']={'messages':[]}
    elif fault=='duplicate_start':events.insert(2,start(0))
    elif fault=='duplicate_completion':events.append(completed(rows[0]))
    if fault!='missing':lifecycle(tmp_path,events)
    prefix=extract_prefixes(tmp_path)['prefixes'][0]
    assert prefix['capture_boundary_status']=='unknown'
    assert prefix['native_coverage']['records']==[]
    assert prefix['native_coverage']['diagnostics']['request_capture_boundary_unknown']==1


def test_receipt_ordinals_keep_later_same_step_delivery_out_of_first_prefix(tmp_path):
    source=capture(tmp_path)
    ledger,rows=delivery(tmp_path,[(source,0,5)])
    # Re-delivery of the identical retained request is distinguishable by ledger
    # ordinal. The first attempt is unacknowledged, the later one confirmed.
    path=tmp_path/'policy-delivery.jsonl'
    confirmed=json.loads(path.read_text());unknown=json.loads(path.read_text())
    unknown['backend_completion_returned']=False
    unknown['scope']='attempted_request_unconfirmed'
    for item in unknown['items']:item['confirmed']=False
    path.write_text(json.dumps(unknown)+'\n'+json.dumps(confirmed)+'\n')
    lifecycle(tmp_path,[recorded(0),start(0),completed(rows[0])])
    prefixes=extract_prefixes(tmp_path)['prefixes']
    assert len(prefixes)==2
    assert prefixes[0]['native_coverage']['records'][0]['status']=='unknown'
    assert prefixes[1]['native_coverage']['records'][0]['parts']['fee']['status']=='complete'


def test_worker_does_not_borrow_main_capture_boundary(tmp_path):
    source=capture(tmp_path);_,rows=delivery(tmp_path,[(source,0,5)],recipient='worker')
    lifecycle(tmp_path,[recorded(0),start(0),completed(rows[0])])
    assert extract_prefixes(tmp_path)['prefixes']==[]
    worker=extract_prefixes(tmp_path,recipient='worker')['prefixes'][0]
    assert worker['capture_boundary_status']=='unknown' and worker['native_coverage']['records']==[]
