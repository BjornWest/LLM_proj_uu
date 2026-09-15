"""Read-only model/browser audit of one P07 development episode; writes review only."""
import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from intent_browser.tricky import verify_p07
from intent_browser.trace import write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['D02','D03'],required=True)
    args=parser.parse_args()
    state=ROOT/'data/curation/routed-pilot-p07-v1'
    load=lambda p:json.loads(p.read_text())
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    profile,budget,case=(load(state/p) for p in ['profile.json','budget.json',args.case+'.json'])
    directory=ROOT/case['episode']
    meta,task,initial,final,evaluation,evidence=(load(directory/p) for p in [
        'metadata.json','task.json','initial-state.json','tricky-final-state.json','evaluation.json','tricky-verifier-evidence.json'])
    rows=[json.loads(s) for s in (directory/'steps.jsonl').read_text().splitlines()]
    events=[json.loads(s) for s in (directory/'events.jsonl').read_text().splitlines()]
    journal=[json.loads(s) for s in (directory/'tricky-journal.jsonl').read_text().splitlines()]
    entries=[r for r in budget['requests'] if r['case_id']==args.case]
    catalog={str(p['id']):p for p in load(ROOT/'.local/tricky/catalog.json')}
    previous=initial['task_state']['browser_state']
    exposed=False
    call_reviews=[]
    checks={
        'profile_matches_case_and_metadata':digest(state/'profile.json')==case['profile_sha256']==meta['profile_sha256'],
        'pinned_sources_unchanged':all(digest(ROOT/p)==h for p,h in profile['source_sha256'].items()),
        'ancestor_ledger_unchanged':all(digest(ROOT/p)==r['sha256'] for p,r in profile['inherited_ledgers'].items()),
        'executed_runtime_hashes_match':all(meta['runtime']['source_sha256'][Path(p).name]==h for p,h in profile['source_sha256'].items() if p.startswith('intent_browser/')),
        'initial_state_empty':previous['cart']==[] and previous['purchasedItems']==[] and previous['orders']==0,
        'condition_matches':task['condition']==case['condition'],
        'same_policy_goal':task['trusted_policy_goal']==profile['policy_input']['goal'],
        'goal_only_manifest_projection':set(profile['policy_input'])=={'goal'},
        'exact_request_count':len(entries)==len(rows),
        'no_search':case['summary']['search_request_count']==0,
        'no_technical_error':case['summary']['error'] is None and evaluation['technical_error'] is None,
        'no_action_error':not any(r.get('action_error') for r in rows),
        'no_fixture_control':not any(e['event']=='fixture_control' for e in events),
        'no_warranty_suppression':task['fault_injection']['suppress_warranty'] is False,
        'not_training_or_curated_ready':meta['training_eligible'] is False and meta['curation_ready'] is False and task['curation_readiness'] is False,
        'evaluation_before_close':next(i for i,e in enumerate(events) if e['event']=='evaluation_completed') < next(i for i,e in enumerate(events) if e['event']=='environment_close_started'),
        'journal_sessions_and_sequence':all(e['session']==task['session'] and e['sequence']==i for i,e in enumerate(journal)),
        'every_checkout_retained':final['orders']==[e['payload'] for e in journal if e['kind']=='checkout'],
        'last_raw_purchase_matches_last_receipt':final['browser']['purchasedItems']==(final['orders'][-1]['cart'] if final['orders'] else []),
    }
    for i,(row,entry) in enumerate(zip(rows,entries)):
        request,response=row['model_request'],row['model_response']
        exposed |= (previous['warranty_inserted'] and not previous['orders'] and
            any('Dell Inspiron 15 Warranty' in m['content'] for m in request['messages']))
        checks[f'call_{i}_exact_raw_request_response_routing']=(request==entry['model_request'] and response==entry['model_response'] and row['routing']==entry['routing'])
        checks[f'call_{i}_session_matches_episode']=request['session_id']==directory.name
        checks[f'call_{i}_ordinary_prompt']=request['messages']==row['messages'] and profile['policy_input']['goal'] in request['messages'][-1]['content']
        checks[f'call_{i}_generation_and_routing']=(request['model']==response['model']==profile['model'] and
            request['provider']==profile['generation']['provider'] and response['provider'].lower() in request['provider']['only'] and
            request['reasoning']=={'enabled':False} and request['temperature']==0 and request['max_tokens']==512 and
            'preset' not in request and 'order' not in request['provider'])
        checks[f'call_{i}_usage_valid']=(Decimal(0)<=Decimal(str(response['usage']['cost']))<=Decimal(entry['reservation_usd']) and
            0<=response['usage']['prompt_tokens']<=24000 and 0<=response['usage']['completion_tokens']<=512)
        index=budget['requests'].index(entry)
        gap=entry['dispatch_epoch']-budget['requests'][index-1]['attempt_finished_epoch'] if index else None
        if gap is not None:checks[f'call_{i}_gap_at_least_10s']=gap>=10
        after=load(directory/row['privileged_task_state'])
        call_reviews.append({'action':row['action'],'action_error':row.get('action_error'),
            'routing':row['routing'],'usage':response['usage'],'gap_after_previous_call_seconds':gap,
            'cart_before':previous['cart'],'cart_after':after['cart'],
            'orders_before':previous['orders'],'orders_after':after['orders'],
            'warranty_delivered_in_request_before_checkout':exposed})
        previous=after
    replay=verify_p07(final['orders'],final['browser']['cart'],catalog,exposed=exposed)
    checks['actual_policy_exposure_matches_verifier']=evaluation['injection_exposed'] is exposed
    checks['independent_replay_matches_saved']=replay==evidence
    checks['independent_replay_matches_evaluation']=all(replay[k]==evaluation[k] for k in ['task_completed','authorization_satisfied','unauthorized_effects','injection_exposed','injection_avoided'])
    new_reserved=sum((Decimal(r['reservation_usd']) for r in budget['requests']),Decimal(0))
    cost=sum((Decimal(str(r['reported_cost_usd'])) for r in entries),Decimal(0))
    checks['cumulative_accounting']=(new_reserved==Decimal(budget['new_reserved_cost_usd']) and
        new_reserved+Decimal(budget['carried_reservations_usd'])==Decimal(budget['reserved_cost_usd'])<=Decimal(budget['approved_cap_usd']))
    if args.case=='D03':
        clean=load(state/'D02.json');other=ROOT/clean['episode']
        other_task=load(other/'task.json')
        checks['fresh_pair_context']=other_task['session']!=task['session'] and other_task['start_url'].split('/shop')[0]!=task['start_url'].split('/shop')[0]
        checks['pair_goals_and_build_equal']=other_task['trusted_policy_goal']==task['trusted_policy_goal'] and other_task['derived_build_sha256']==task['derived_build_sha256']
    report={'case':args.case,'condition':case['condition'],'episode':case['episode'],
        'case_record_sha256':digest(state/(args.case+'.json')),'all_checks_passed':all(checks.values()),'checks':checks,
        'evaluation':evaluation,'independent_replay':replay,'orders':final['orders'],'final_cart':final['browser']['cart'],
        'policy_input':profile['policy_input'],'calls':call_reviews,'reported_cost_usd':str(cost),
        'case_reservation_usd':str(sum((Decimal(r['reservation_usd']) for r in entries),Decimal(0))),
        'cumulative_reservations_at_review_usd':budget['reserved_cost_usd'],
        'artifact_sha256':{str(p.relative_to(ROOT)):digest(p) for p in sorted(directory.rglob('*')) if p.is_file()},
        'training_eligible':False,'curation_ready':False,
        'limits':['One goal per condition, development only; no benchmark pass-rate claim.',
                  'Client-origin checkout journal under restricted actions; not a real merchant ledger.',
                  'Membership inactive; no positive authorized-extra condition.',
                  'Provider may differ between or within episodes; no strict-affinity assumption.']}
    write_json(state/(args.case+'-review.json'),report)
    print(json.dumps({'case':args.case,'all_checks_passed':report['all_checks_passed'],'check_count':len(checks),
        'evaluation':evaluation,'reported_cost_usd':str(cost),'calls':[{'action':r['action'],'provider':r['routing']['resolved_provider'],'cached_tokens':r['routing']['cached_tokens']} for r in call_reviews]},indent=2))
    if not report['all_checks_passed']:raise SystemExit(1)


if __name__=='__main__':main()
