"""Compact, read-only queries over a saved browser-triage-v1 export."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


def repository():
    for base in (Path.cwd(), Path(__file__).resolve()):
        for root in (base, *base.parents):
            if (root/'data/curation/trace_triage/core.py').is_file():
                return root
    raise ValueError('Run from the browser-agent repository containing data/curation/trace_triage')


def load(path):
    if path.stat().st_size > 128*1024*1024:
        raise ValueError('Index exceeds 128 MiB; use a bounded cohort export')
    raw=path.read_bytes();report=json.loads(raw)
    if report.get('format')!='browser-triage-v1': raise ValueError('Unsupported triage format')
    ids=[e['episode_id'] for e in report['episodes']]
    if len(ids)!=len(set(ids)): raise ValueError('Ambiguous duplicate episode IDs')
    return report, hashlib.sha256(raw).hexdigest()


def total(e, field):
    return e.get('operational_metrics',{}).get('totals',{}).get(field,{}).get('known_sum')


def card(e, directory):
    metrics=e.get('operational_metrics',{})
    return {'episode_id':e['episode_id'],'task':e['task'],'source':e['source'],
            'condition':e.get('condition'),'driver':e.get('driver'),'model':e.get('model'),
            'providers':e.get('resolved_providers',[]),'outcome':e['outcome_group'],
            'task_completed':(e.get('recorded_evaluation') or {}).get('task_completed'),
            'authorization_satisfied':(e.get('recorded_evaluation') or {}).get('authorization_satisfied'),
            'steps':len(e['timeline']),'flags':sorted({f['code'] for f in e['flags']}),
            'usage':{k:metrics.get('totals',{}).get(k) for k in ('total_tokens','reasoning_tokens','cost_usd')},
            'cache_fraction_known_pairs':metrics.get('cache_fraction_known_pairs'),
            'packet':str(directory/'packets'/f"{e['key']}.md"),
            'template':str(directory/'diagnoses'/f"{e['key']}.json"),
            'step_records':str(directory/'step-records'/e['key']) if (directory/'step-records'/e['key']).is_dir() else None}


def select(report, args):
    queue={r['episode_id']:r for r in report['analysis'].get('review_queue',{}).get('items',[])}
    members=None
    if args.group_kind is not None:
        matches=[g for g in report['analysis']['groups'] if g['kind']==args.group_kind and g['key']==args.group_key]
        if len(matches)!=1:raise ValueError('Group must identify exactly one saved group')
        members=set(matches[0]['episodes'])
    rows=[]
    for e in report['episodes']:
        if members is not None and e['episode_id'] not in members:continue
        if args.outcome and e['outcome_group']!=args.outcome:continue
        if args.task and args.task.casefold() not in (e['task'] or '').casefold():continue
        if any(getattr(args,k) is not None and e.get(k)!=getattr(args,k) for k in ('source','condition','driver','model')):continue
        if args.provider and args.provider not in e.get('resolved_providers',[]):continue
        if not set(args.flag)<={f['code'] for f in e['flags']}:continue
        if args.min_tokens is not None and (total(e,'total_tokens') is None or total(e,'total_tokens')<args.min_tokens):continue
        q=queue.get(e['episode_id'])
        if args.queue=='suggested' and not q:continue
        if args.queue=='sampled' and (not q or 'sampled_apparent_success' not in q['reasons']):continue
        rows.append(e)
    def order(e):
        if args.sort=='priority':value=max((f['priority'] for f in e['flags']),default=0)
        elif args.sort=='cache':value=e.get('operational_metrics',{}).get('cache_fraction_known_pairs')
        else:value=total(e,'total_tokens' if args.sort=='tokens' else 'reasoning_tokens')
        return (value is None, value if args.sort=='cache' and value is not None else -value if value is not None else 0, e['episode_id'])
    return sorted(rows,key=order)


def page(rows,args):
    selected=rows[args.offset:args.offset+args.limit]
    return {'matched':len(rows),'offset':args.offset,'returned':len(selected),
            'omitted':len(rows)-len(selected),'items':selected}


def engine():
    root=repository();sys.path.insert(0,str(root))
    from data.curation.trace_triage.core import compare
    return compare, hashlib.sha256((root/'data/curation/trace_triage/core.py').read_bytes()).hexdigest()


def pair_result(a,b,directory):
    if not a['task'] or (a['source'],a['task'])!=(b['source'],b['task']):
        raise ValueError('Comparison requires the same known task and recorded source')
    if a['episode_id']==b['episode_id']:raise ValueError('Choose two distinct episodes')
    compare,code_hash=engine();pair=compare(a,b)
    pair['comparison_engine_sha256']=code_hash
    pair['source_identity_known']=bool(a['source'])
    pair['outcomes']=[a['outcome_group'],b['outcome_group']]
    pair.pop('alignment')  # Full alignment remains in the HTML or can be computed separately.
    difference=pair['first_action_divergence'] or {}
    focus=[]
    for episode,field in ((a,'left_steps'),(b,'right_steps')):
        selected=difference.get(field,[])[:1]
        prior=pair['prefix_evidence_differences'][:1]
        selected += [r['left_step' if field=='left_steps' else 'right_step'] for r in prior]
        for step in sorted(set(selected)):
            row=next(s for s in episode['timeline'] if s['step']==step)
            raw=row['action'].get('raw')
            focus.append({'episode_id':episode['episode_id'],'step':step,
                          'action_preview':raw[:240] if isinstance(raw,str) else raw,
                          'action_preview_truncated':isinstance(raw,str) and len(raw)>240,
                          'record':str(directory/'step-records'/episode['key']/f'{step}.json') if (directory/'step-records'/episode['key']/f'{step}.json').is_file() else None})
    pair['prefix_evidence_difference_count']=len(pair['prefix_evidence_differences'])
    pair['prefix_evidence_differences']=pair['prefix_evidence_differences'][:5]
    pair['focus']=focus
    return pair


def query(args):
    path=args.triage.resolve();report,sha=load(path);directory=path.parent
    selected=select(report,args);by_id={e['episode_id']:e for e in report['episodes']}
    result={'triage':str(path),'triage_sha256':sha,'selected_episodes':len(selected),
            'scope':'Read-only derived pointers; original outcomes unchanged; no automatic causal labels.'}
    if args.command=='summary':
        result.update(population=len(report['episodes']),outcomes=dict(Counter(e['outcome_group'] for e in selected)),
                      flags=dict(Counter(f['code'] for e in selected for f in e['flags']).most_common(15)),
                      flags_count_unit='occurrences, not distinct episodes',
                      tasks_top_10=dict(Counter(str(e['task']) for e in selected).most_common(10)),
                      distinct_tasks=len({e['task'] for e in selected}),
                      rejected_inputs=len(report.get('skipped',[])),
                      unfinished_suite_records=sum(r.get('disposition')=='not imported; unfinished case' for r in report.get('intake_notes',[])))
    elif args.command=='list':result.update(page([card(e,directory) for e in selected],args))
    elif args.command=='groups':
        ids={e['episode_id'] for e in selected};groups=[]
        for group in report['analysis']['groups']:
            if group['kind']!=args.kind:continue
            members=sorted(ids & set(group['episodes']))
            if not members:continue
            if args.kind=='trajectory_neighborhood' and group['key'] not in ids:continue
            representative=group['key'] if args.kind=='trajectory_neighborhood' else members[0]
            groups.append({'key':group['key'],'kind':group['kind'],'count':len(members),
                           'representative':representative,'member_sample':members[:5],
                           'member_sample_omitted':max(0,len(members)-5),
                           'outcomes':dict(Counter(by_id[x]['outcome_group'] for x in members))})
        groups.sort(key=lambda g:(-g['count'],g['key']))
        result.update(page(groups,args));result['overlap_warning']='Flag groups and neighborhoods overlap; counts are not additive or causal clusters.'
    elif args.command=='neighbors':
        if args.episode not in by_id:raise ValueError('Unknown episode')
        origin=by_id[args.episode]
        pairs=[pair_result(origin,e,directory) for e in selected if e['episode_id']!=origin['episode_id'] and origin['task'] and (origin['source'],origin['task'])==(e['source'],e['task'])]
        pairs.sort(key=lambda p:(-int(p['same_goal']),-p['similarity'],-p['common_action_prefix'],p['right']))
        result.update(page(pairs,args))
    else:
        if args.left not in by_id or args.right not in by_id:raise ValueError('Unknown episode')
        result['pair']=pair_result(by_id[args.left],by_id[args.right],directory)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['summary','list','groups','neighbors','compare'])
    parser.add_argument('--triage',type=Path,required=True)
    parser.add_argument('--outcome',choices=['success','failure','unknown'])
    for field in ('task','source','condition','driver','model','provider','episode','left','right'):parser.add_argument('--'+field)
    parser.add_argument('--flag',action='append',default=[])
    parser.add_argument('--queue',choices=['suggested','sampled'])
    parser.add_argument('--group-kind');parser.add_argument('--group-key')
    parser.add_argument('--sort',choices=['priority','tokens','reasoning','cache'],default='priority')
    parser.add_argument('--min-tokens',type=int)
    parser.add_argument('--kind',choices=['flag','trajectory','trajectory_neighborhood','task','outcome','driver','provider'],default='flag')
    parser.add_argument('--limit',type=int,default=10);parser.add_argument('--offset',type=int,default=0)
    args=parser.parse_args(argv)
    if not 1<=args.limit<=100 or args.offset<0 or args.min_tokens is not None and args.min_tokens<0:parser.error('Invalid count bound')
    if args.command=='neighbors' and not args.episode:parser.error('neighbors needs --episode')
    if args.command=='compare' and not (args.left and args.right):parser.error('compare needs --left and --right')
    if (args.group_kind is None)!=(args.group_key is None):parser.error('Group selection needs both --group-kind and --group-key')
    try:print(json.dumps(query(args),ensure_ascii=False,indent=2,allow_nan=False))
    except (ValueError,KeyError,OSError) as error:parser.error(str(error))


if __name__=='__main__':main()
