#!/usr/bin/env python3
"""Saved-browser source -> actual AX formatter -> synthetic delivery acceptance.

No browser, runtime, network, model, producer qualification or task grading. Native
export identities stay private; only host snapshot labels are reindexed from the
same pinned raw AX. Output directory must be new.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),os.environ.get('FACT_PROVENANCE_CONSUMER_ROOT',str(ROOT/'training'))]
from browser_training.fact_render_capture import harness_source_packet
from browser_training.fact_exposure import projected_text
from browser_training import fact_render_capture, fact_exposure, website_projection
from intent_browser.ax_context import AXContext
from intent_browser.ax_explorer import AXConfig
from intent_browser.fact_provenance import FactRecorder, encoded, object_digest, slice16
from intent_browser.policy_delivery import PolicyDelivery


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_case(path,output,tokenizer):
    data=json.loads(path.read_text());normalized=data['normalized']
    directory=output/path.parent.name/path.name.removesuffix('.capture.private.json')
    directory.mkdir(parents=True)
    trace=SimpleNamespace(directory=directory,event=lambda *a,**k:None)
    packet=harness_source_packet(normalized)
    obs={'url':data['commit']['meta']['url'],'last_action_error':'','axtree_object':{'nodes':data['raw_ax']}}
    x=AXContext(AXConfig(str(tokenizer),incremental=True))
    def provider(env,observation,context):
        result=deepcopy(packet)
        for source in result['sources']:
            source['binding']['snapshot_id']=context['snapshot_id']
        return result
    r=FactRecorder(trace,provider);r.attach(x)
    ledger=PolicyDelivery(trace);ledger.fact_recorder=r
    original=AXContext(x.config)
    preview=x.prepare_observation(obs)
    assert preview==original.prepare_observation(obs),'Recording changed public text'
    assert not normalized['inventory_complete'] and not normalized['delivery_evidence']
    capture=json.loads((directory/r.current['artifact']).read_text())
    sources={s['id']:s for s in capture['sources']}
    exports={s['id']:s for s in packet['sources']}
    for source in sources.values():
        incoming=exports[source['export_id']]
        assert source['text']==incoming['text'] and source['sha256']==incoming['sha256']
        assert source['opaque_binding']==incoming['opaque_binding']
        for key in ('document_id','frame_id','node_id','field'):
            assert source['binding'][key]==incoming['binding'][key]
    projection_count=0;content_ids=[]
    def select(value):
        nonlocal projection_count
        selected=r.select(value)
        assert selected is not None,'Lost emitted generation'
        cid=ledger.register('ax_result',value if isinstance(value,str) else encoded(value),step=0,fact_output=selected)
        record=json.loads((directory/ledger.sources[cid]['provenance']['fact_projection_artifact']).read_text())
        for p in record['projections']:
            source=sources[p['source_id']]
            fragment=slice16(projected_text(ledger.sources[cid]['text'],p['output_path']),p['output_start'],p['output_end'])
            if p['encoding']=='json_string':fragment=json.loads('"'+fragment+'"')
            assert fragment==slice16(source['text'],p['source_start'],p['source_end'])
            assert p['binding_sha256']==object_digest(source['binding'])
            projection_count+=1
        content_ids.append(cid)
    # Bind each generation immediately, as the runner does. Holding an entire
    # corpus before registration would exceed the deliberately bounded cache.
    select(preview)
    for ref,fields in r.current['fields'].items():
        select(x.read(ref,view='node',repeat=True))
        name=x.nodes[x.resolve(ref)]['name']
        if name:select(x.search(name,repeat=True))
    assert sources and projection_count,'Released source slice has no supported projection'
    messages=[{'role':'tool','content':ledger.sources[cid]['text']} for cid in content_ids]
    bindings=[{'content_id':cid,'message_index':i,'start':0,'end':len(messages[i]['content'])} for i,cid in enumerate(content_ids)]
    event={'step':0,'messages':messages,'model_request':{'messages':messages}}
    # Explicit synthetic acknowledgment control: there is no model invocation.
    ledger.record(event,bindings,acknowledged=False)
    failed=json.loads((directory/'fact-delivery.jsonl').read_text().splitlines()[-1])
    assert not any(i['confirmed'] for i in failed['items'])
    ledger.record(event,bindings,acknowledged=True)
    accepted=json.loads((directory/'fact-delivery.jsonl').read_text().splitlines()[-1])
    assert all(i['confirmed'] for i in accepted['items'])
    (directory/'steps.jsonl').write_text(json.dumps(event,ensure_ascii=False)+'\n')
    assert capture['mapping_inventory_complete'] is False
    r.close()
    result={'input':str(path),'sha256':sha(path),'passed':True,'exported_sources':len(exports),
            'supported_indexed_sources':len(sources),'projection_runs':projection_count,'selected_outputs':len(content_ids),
            'unsupported_sources':capture['diagnostics'],'input_ax_unknowns':normalized['ax_diagnostics'],
            'native_identity_and_parts_preserved':True,'public_text_parity':True,'synthetic_ack_controls':True,
            'browser_started':False,'model_requests':0,'producer_qualified':False,'exposure_status':'unknown',
            'snapshot_reindexing':'Host AX snapshot label only; pinned native document/frame/node/run/part identities unchanged'}
    (directory/'review.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-receipt',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tokenizer',type=Path,default=ROOT/'training/.cache/qwen38-tokenizer/tokenizer.json')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    receipt=json.loads(args.input_receipt.read_text());pins=receipt['evidence_pins']
    assert pins and all(sha(Path(p))==pin for p,pin in pins.items()),'Input evidence pin changed'
    paths=sorted(Path(p) for p in pins if p.endswith('.capture.private.json'))
    assert len(paths)==receipt['recording_captures'],'Incomplete capture set'
    before={str(path):sha(path) for path in paths}
    sources=[ROOT/p for p in ('intent_browser/fact_provenance.py','intent_browser/ax_context.py',
        'intent_browser/policy_delivery.py','scripts/verify_fact_provenance_exports.py')]
    sources += [Path(m.__file__) for m in (fact_render_capture,fact_exposure,website_projection)]
    source_pins={str(p.resolve()):sha(p) for p in sources}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda p:verify_case(p,args.output,args.tokenizer),paths))
    assert all(sha(Path(p))==pin for p,pin in pins.items()),'Inputs changed during acceptance'
    assert all(sha(Path(p))==pin for p,pin in source_pins.items()),'Source changed during acceptance'
    result={'passed':True,'scope':'Saved browser captures / real formatter / synthetic delivery only',
        'cases':results,'input_sha256':before,'source_sha256':source_pins,'case_workers':2,
        'browser_launches':0,'network_calls':0,'model_requests':0,'website_edits':0,
        'producer_qualification':'pending','quote_acceptance':False,'live_website_adoption':False}
    (args.output/'validation.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'passed':True,'cases':len(results),'projection_runs':sum(c['projection_runs'] for c in results),
        'output':str(args.output)}))

if __name__=='__main__':main()
