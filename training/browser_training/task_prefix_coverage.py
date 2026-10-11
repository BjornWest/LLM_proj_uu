"""Scoped required-versus-delivered spans at acknowledged request boundaries.

An external source inventory identifies relevant spans. It is never policy
context and never earns exposure by itself. This reader checks the actual
Harness ledger, exact retained requests and frozen formatting projections.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
        separators=(',', ':'),allow_nan=False).encode()).hexdigest()


def require(condition, reason):
    if not condition:raise ValueError(reason)


def text_hash(value):return hashlib.sha256(value.encode()).hexdigest()


def slice16(text,start,end):
    raw=text.encode('utf-16-le')
    require(type(start) is int and type(end) is int and 0<=start<end<=len(raw)//2,'invalid_utf16_interval')
    return raw[2*start:2*end].decode('utf-16-le')


def length(intervals,start,end):
    selected=sorted((max(start,a),min(end,b)) for a,b in intervals if max(start,a)<min(end,b))
    total=0;last=start
    for a,b in selected:
        total+=max(0,b-max(last,a));last=max(last,b)
    return total


def artifact(trace,name):
    require(isinstance(name,str),'artifact_name_missing')
    path=(trace/name).resolve();require(path.is_relative_to(trace),'artifact_outside_trace')
    return json.loads(path.read_text())


def project(inventory, ranges, available, *, read_complete, urls=(), context_seen=(), errors=()):
    """No mixing parts between subjects, configurations or alternative captures."""
    rows=[]
    for target in inventory['targets']:
        alternatives=[];mapping_problem=False
        for witness in target.get('witnesses',[]):
            part_rows=[]
            for part in witness['parts']:
                require(part['spans'],'empty_required_part')
                seen=total=0;valid=True
                for span in part['spans']:
                    key=(witness['capture_sha256'],span['source_id'])
                    a,b=span['start'],span['end']
                    require(type(a) is int and type(b) is int and 0<=a<b,'invalid_required_span')
                    total+=b-a
                    seen+=length(ranges.get(key,()),a,b)
                    if key in available and available[key] is False:valid=False
                part_rows.append(dict(part=part['part'],seen_utf16=seen,total_utf16=total,mapping_available=valid))
            if not part_rows:continue
            complete=all(p['seen_utf16']==p['total_utf16'] for p in part_rows)
            partial=any(p['seen_utf16'] for p in part_rows)
            good=all(p['mapping_available'] for p in part_rows)
            mapping_problem|=not good
            alternatives.append(dict(status='complete' if complete else 'partial' if partial else 'not_observed',
                parts=part_rows,capture_sha256=witness['capture_sha256']))
        if target.get('urls'):
            alternatives.extend(dict(status='complete',channel='page_url',value=url)
                                for url in target['urls'] if url in urls)
        alternatives.extend(dict(status='complete',channel='task_context_memory',source_sha256=s['source_sha256'])
                            for s in target.get('context_spans',[]) if s['source_sha256'] in context_seen)
        statuses={a['status'] for a in alternatives}
        if 'complete' in statuses:status,reason='complete','all_required_parts_delivered'
        elif not target.get('witnesses') and not target.get('urls') and not target.get('context_spans'):
            status,reason='unknown',target.get('reason','relevant_source_unresolved')
        elif not read_complete or mapping_problem:
            status,reason='unknown','exposure_inventory_unresolved' if not read_complete else 'harness_source_mapping_rejected'
        elif 'partial' in statuses:status,reason='partial','some_required_parts_delivered'
        else:status,reason='not_observed','resolved_source_and_read_inventory_zero_exposure'
        rows.append(dict(id=target['id'],need_id=target['need_id'],field=target['field'],
            subject=deepcopy(target.get('subject',{})),status=status,reason=reason,
            alternatives=alternatives,known_exposure_lower_bound='partial' if 'partial' in statuses else None))
    return dict(rows=rows,counts=dict(Counter(r['status'] for r in rows)),
                unknown_reasons=dict(Counter(r['reason'] for r in rows if r['status']=='unknown')),
                read_inventory_complete=read_complete,diagnostics=list(errors))


def replay(trace, inventory):
    trace=Path(trace).resolve()
    require(inventory.get('schema')=='task-prefix-source-inventory-v1','unsupported_source_inventory')
    task_pin=inventory['task'];task_raw=Path(task_pin['path']).read_bytes()
    require(hashlib.sha256(task_raw).hexdigest()==task_pin['sha256'],'changed_task_source')
    task=json.loads(task_raw);require(digest(task)==inventory['task_sha256'],'task_inventory_hash_mismatch')
    for target in inventory['targets']:
        for span in target.get('context_spans',[]):
            original=task['memories'][span['memory_index']]
            require(text_hash(original)==span['source_sha256'],'context_source_task_mismatch')
            slice16(original,span['start'],span['end'])
    metadata=artifact(trace,'metadata.json')
    require(metadata.get('source')=='saved-AX-prefix-integration','unsupported_request_seam_protocol')
    require(metadata.get('task_sha256')==inventory['task_sha256'] and
            metadata.get('source_inventory_sha256')==digest(inventory),'trace_task_inventory_mismatch')
    steps={};starts={};capture_records={};capture_ordinals={}
    for row in (trace/'steps.jsonl').read_text().splitlines():
        step=json.loads(row);require(type(step['step']) is int and step['step'] not in steps,'duplicate_request_step')
        steps[step['step']]=step
    for ordinal,line in enumerate((trace/'events.jsonl').read_text().splitlines()):
        event=json.loads(line)
        if event['event']=='fact_capture_recorded':
            name=event['artifact'];require(name not in capture_records,'duplicate_capture_event')
            capture_records[name]=artifact(trace,name);capture_ordinals[name]=ordinal
        elif event['event']=='model_started':
            require(event['call_id'] not in starts,'ambiguous_request_boundary')
            starts[event['call_id']]=ordinal
    sources={};known_captures={}
    for name,capture in capture_records.items():
        require(capture['schema']=='ax-fact-provenance-v1','unsupported_native_capture')
        audit=capture['private_context']['scripted_source_capture']
        sha=audit['sha256'];known_captures[name]=sha
        original_pin=inventory['captures'][sha]['pin']
        require(audit==original_pin,'foreign_source_capture_pin')
        original_raw=Path(original_pin['path']).read_bytes()
        require(hashlib.sha256(original_raw).hexdigest()==sha,'changed_original_capture')
        original=json.loads(original_raw)
        require(capture['raw_ax_sha256']==digest(dict(nodes=original['raw_ax'])),'original_AX_capture_mismatch')
        approved={s['id']:s for s in original['normalized']['ax_sources']+inventory['captures'][sha].get('extra_sources',[])}
        for source in capture['sources']:
            require(source['id'] not in sources and text_hash(source['text'])==source['sha256'],'invalid_native_source')
            expected=approved[source['export_id']]
            binding=deepcopy(expected['binding']);binding['snapshot_id']=capture['snapshot_id']
            require(source['text']==expected['text'] and source['sha256']==expected['sha256'] and
                    source['binding']==binding and source['captured_step']==capture['step'],'changed_source_binding')
            sources[source['id']]=(source,name,(sha,source['export_id']))
    receipts=[json.loads(line) for line in (trace/'policy-delivery.jsonl').read_text().splitlines()]
    # Reject an incomplete, duplicated or reordered custom diagnostic before
    # accumulating any exposure. File order must agree with request events.
    require(set(steps)==set(range(len(receipts))),'incomplete_request_receipt_inventory')
    boundaries=[starts.get(f'model-{i:03d}') for i in range(len(receipts))]
    require(all(type(b) is int for b in boundaries) and boundaries==sorted(set(boundaries)),
            'unordered_request_boundaries')
    require(all(type(r.get('step')) is int and r['step']==i for i,r in enumerate(receipts)),
            'unordered_or_duplicate_request_receipts')
    deliveries={}
    for line in (trace/'fact-delivery.jsonl').read_text().splitlines():
        delivery=json.loads(line);key=(delivery['step'],delivery['recipient'])
        require(key not in deliveries,'duplicate_fact_delivery_receipt')
        deliveries[key]=delivery
    ranges=defaultdict(list);available={};urls=set();context_seen=set();prefixes=[];errors=[]
    for receipt_index,receipt in enumerate(receipts):
        step=receipt['step'];row=steps[step]
        require(receipt['recipient']=='main','unsupported_recipient')
        boundary=starts.get(f'model-{step:03d}')
        clean=(boundary is not None and receipt['scope']=='retained_request_completion' and
               receipt['backend_completion_returned'] is True)
        request=row['model_request']['messages']
        clean&=digest(request)==receipt['messages_sha256']
        # This diagnostic's actual EvidenceConversation appends one registered
        # observation per completion. Recheck that protocol independently of
        # the receipt's item list: omitting an item cannot manufacture zero
        # exposure while its output is still present in the retained request.
        try:
            delivery=deliveries.get((step,'main'))
            require(delivery is not None and delivery['policy_receipt_sha256']==digest(receipt) and
                    delivery['messages_sha256']==receipt['messages_sha256'] and delivery['scope']==receipt['scope'],
                    'fact_delivery_receipt_crosslink_mismatch')
            require(len(request)==step+3,'incomplete_append_only_request')
            ids=[item['content_id'] for item in receipt['items']]
            expected_ids=[f'content-{i:04d}' for i in range(step+1)]
            require(len(ids)==len(set(ids)) and set(ids)==set(expected_ids),'incomplete_delivery_item_inventory')
            for i,cid in enumerate(expected_ids):
                registered=artifact(trace,f'policy-{cid}.json')
                require(registered['id']==cid and registered['created_step']==i and
                    request[i+2]==dict(role='user',content='CURRENT BROWSER OBSERVATION\n'+registered['text']),
                    'registered_request_component_missing_or_changed')
        except (KeyError,TypeError,ValueError,OSError) as error:
            clean=False;errors.append(str(error))
        active={name for name,ordinal in capture_ordinals.items() if boundary is not None and ordinal<boundary}
        for name in active:
            wanted=[s for s in inventory['captures'][known_captures[name]]['source_ids']]
            retained={s['export_id'] for s in capture_records[name]['sources']}
            for source_id in wanted:
                key=(known_captures[name],source_id)
                available[key]=available.get(key,False) or source_id in retained
        if not clean:errors.append('unqualified_request_receipt_or_boundary')
        for item in receipt['items'] if clean else ():
            if not item['confirmed'] or not item['aligned']:
                clean=False;errors.append('unconfirmed_or_unaligned_content');continue
            try:
                content=artifact(trace,item['artifact']);span=item['message_span']
                selected=request[span['message_index']]['content']
                if isinstance(selected,list):selected=selected[0]['text']
                require(content['id']==item['content_id']==span['content_id'] and
                    content['sha256']==item['sha256']==text_hash(content['text']) and
                    selected[span['start']:span['end']]==content['text'],'retained_request_alignment_mismatch')
                require(content['created_step']<=step,'future_content')
                payload=json.loads(content['text'])
                if content['kind']=='page_observation' and isinstance(payload,dict) and isinstance(payload.get('url'),str):
                    urls.add(payload['url'])
                if content['kind']=='memory_result' and isinstance(payload,dict):
                    for memory in payload.get('memories',[]):
                        require(isinstance(memory,str) and memory in task.get('memories',[]),'foreign_memory_content')
                        context_seen.add(text_hash(memory))
                projection=artifact(trace,content['provenance']['fact_projection_artifact'])
                require(projection['content_id']==content['id'] and projection['text_sha256']==content['sha256'],
                        'projection_content_mismatch')
                output_name=projection.get('output_artifact')
                if output_name is not None:
                    output=artifact(trace,output_name)
                    require(output['schema']==projection['schema']=='ax-fact-provenance-v1' and
                            output['text_sha256']==projection['text_sha256'] and
                            output['projections']==projection['projections'] and
                            output['references']==projection['references'] and
                            output['diagnostics']==projection['diagnostics'],
                            'formatter_projection_inventory_mismatch')
                else:
                    require(content['kind']=='memory_result' or content['id']=='content-0000',
                            'selected_formatter_output_missing')
                    require(not projection['projections'] and not projection['references'],
                            'unexpected_non_AX_projection')
                delivered_item=next((x for x in delivery['items'] if x['content_id']==content['id']),None)
                require(delivered_item is not None and delivered_item['artifact']==content['provenance']['fact_projection_artifact']
                        and delivered_item['confirmed']==item['confirmed'] and
                        ((delivered_item.get('previously_confirmed') is True and not delivered_item['references']) or
                        [{k:r[k] for k in ('ref','historical_ref') if k in r} for r in delivered_item['references']]==
                        [{k:r[k] for k in ('ref','historical_ref') if k in r} for r in projection['references']]),
                        'fact_delivery_content_crosslink_mismatch')
                for p in projection['projections']:
                    source,name,key=sources[p['source_id']]
                    require(name in active and source['captured_step']<=step,'future_source_projection')
                    require(source['sha256']==p['source_sha256'] and digest(source['binding'])==p['binding_sha256'],
                            'source_binding_hash_mismatch')
                    text=payload
                    for component in p['output_path']:text=text[component]
                    actual=slice16(text,p['output_start'],p['output_end'])
                    if p['encoding']=='json_string':actual=json.loads('"'+actual+'"')
                    else:require(p['encoding']=='identity','unsupported_projection_encoding')
                    require(actual==slice16(source['text'],p['source_start'],p['source_end']),'projection_text_mismatch')
                    ranges[key].append((p['source_start'],p['source_end']))
            except (KeyError,IndexError,TypeError,ValueError,OSError) as error:
                clean=False;errors.append(str(error))
        # Once an acknowledged request has an unresolved evidence component,
        # later zero-exposure claims cannot silently become certain again.
        result=project(inventory,ranges,available,read_complete=clean and not errors,urls=urls,context_seen=context_seen,errors=errors)
        prefixes.append(dict(step=step,receipt_index=receipt_index,boundary_ordinal=boundary,
                             acknowledged=receipt['backend_completion_returned'],**result))
    return dict(schema='task-prefix-coverage-series-v1',metadata={'tags':['scripted']},
        task_sha256=inventory['task_sha256'],trace=str(trace),prefixes=prefixes,
        qualification='Scripted saved-AX request-seam integration; no live episode, model result, attention, candidate completeness or native action grade',
        model_calls=0,world_draws=0,browser_launches=0,historical_evidence_modified=False)
