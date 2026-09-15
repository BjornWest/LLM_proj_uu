"""Read saved R01 workspace-rename evidence; no model/browser calls."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from intent_browser.chaos_verifier import evaluate_trace
from intent_browser.trace import write_json


def main():
    state = ROOT / 'data/curation/routed-pilot-account-v1'
    load = lambda p: json.loads(p.read_text())
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    case, profile, budget = (load(state / p) for p in ['R01.json', 'profile.json', 'budget.json'])
    directory = ROOT / case['episode']
    meta, task, session, descriptor, initial, external, evaluation, evidence = (
        load(directory / name) for name in ['metadata.json', 'task.json', 'chaos-session.json',
        'chaos-contract.json', 'initial-state.json', 'external_evaluation.json', 'evaluation.json',
        'chaos-verifier-evidence.json'])
    rows = [json.loads(s) for s in (directory / 'steps.jsonl').read_text().splitlines()]
    events = [json.loads(s) for s in (directory / 'events.jsonl').read_text().splitlines()]
    snapshots = [initial['task_state']['browser_state']]
    snapshots += [load(directory / row['privileged_task_state']) for row in rows if row.get('privileged_task_state')]
    replay = evaluate_trace(descriptor, session, external['score'], external['events']['events'], snapshots)
    checks = {'current_saved_verifier_replay_matches': replay == evidence,
        'profile_hash_matches_case_and_metadata': digest(state / 'profile.json') == case['profile_sha256'] == meta['profile_sha256'],
        'profile_sources_unchanged': all(digest(ROOT / p) == h for p,h in profile['source_sha256'].items()),
        'inherited_ledgers_unchanged': all(digest(ROOT / p) == row['sha256'] for p,row in profile['inherited_ledgers'].items()),
        'runtime_hashes_match_profile': all(meta['runtime']['source_sha256'][Path(p).name] == h for p,h in profile['source_sha256'].items() if p.startswith('intent_browser/')),
        'evaluation_before_close': next(i for i,e in enumerate(events) if e['event']=='evaluation_completed') < next(i for i,e in enumerate(events) if e['event']=='environment_close_started'),
        'same_task_environment_provenance': task['environment_revision'] == profile['environment_provenance'],
        'certified_contract': task['verifier']['validated'] is True,
        'fresh_chaos_session': all(session['session'] != load(ROOT / p / 'chaos-session.json')['session'] for p in [
            'runs/20260914T200953Z-e1e7e200','runs/20260914T201034Z-d6db0040','runs/20260914T201058Z-ad39e370',
            'runs/20260914T201941Z-be316592','runs/20260914T202921Z-ec565d70']),
        'no_search': case['summary']['search_request_count'] == 0,
        'training_and_curation_not_ready': meta['training_eligible'] is False and meta['curation_ready'] is False,
        'all_requests_accounted': len(rows) == len(budget['requests'])}
    checks['no_technical_error']=case['summary']['error'] is None and evaluation['technical_error'] is None
    checks['no_action_errors']=not any(row.get('action_error') for row in rows)
    checks['raw_verdict_matches_replay']=all(evaluation[k]==replay[k] for k in ('task_completed','authorization_satisfied','unauthorized_effects'))
    checks['no_injection_labels']=evaluation['injection_exposed'] is None and evaluation['injection_avoided'] is None
    checks['previous_cohort_pacing_respected']=budget['requests'][0]['dispatch_epoch']>=load(ROOT/'data/curation/routed-pilot-authorized-v1/budget.json')['not_before_epoch']
    checks['single_selected_task']=descriptor['task']['id']==task['source_task_id']==profile['case']['source_task_id']
    per_call = []
    for i,(row,entry) in enumerate(zip(rows,budget['requests'])):
        request, response = row['model_request'], row['model_response']
        checks[f'call_{i}_raw_request_response_routing_match'] = (request == entry['model_request'] and response == entry['model_response'] and row['routing'] == entry['routing'])
        checks[f'call_{i}_session_matches_trace'] = request['session_id'] == directory.name
        checks[f'call_{i}_ordinary_prompt'] = request['messages'] == row['messages']
        checks[f'call_{i}_model_provider_settings'] = (request['model'] == response['model'] == profile['model'] and
            request['provider'] == profile['generation']['provider'] and
            response['provider'].lower() in request['provider']['only'] and 'order' not in request['provider'] and
            'preset' not in request and request['max_tokens'] == 512 and request['temperature'] == 0 and
            request['reasoning'] == {'enabled': False})
        checks[f'call_{i}_goal_matches']=request['messages'][-1]['content'].startswith('USER GOAL: '+task['trusted_policy_goal']+'\n')
        checks[f'call_{i}_usage_bounds']=(0<=response['usage']['prompt_tokens']<=24000 and 0<=response['usage']['completion_tokens']<=512)
        checks[f'call_{i}_completed_attempt']=entry['status']=='completed' and not entry['audit_issue']
        checks[f'call_{i}_cost_within_reservation'] = Decimal(0) <= Decimal(str(response['usage']['cost'])) <= Decimal(entry['reservation_usd'])
        gap = entry['dispatch_epoch'] - budget['requests'][i-1]['attempt_finished_epoch'] if i else None
        if gap is not None: checks[f'call_{i}_paced_after_previous_completion'] = gap >= 10
        per_call.append({'action': row['action'], 'action_error': row.get('action_error'),
            'routing': row['routing'], 'usage': response['usage'], 'gap_after_previous_attempt_seconds': gap,
            'wait_seconds': entry['wait_seconds'], 'http_status': entry['http']['status']})
    reserved = sum((Decimal(r['reservation_usd']) for r in budget['requests']), Decimal(0))
    cost = sum((Decimal(str(r['reported_cost_usd'])) for r in budget['requests']), Decimal(0))
    checks['reservation_accounting'] = reserved == Decimal(budget['new_reserved_cost_usd']) and reserved + Decimal(budget['carried_reservations_usd']) == Decimal(budget['reserved_cost_usd']) <= Decimal(budget['approved_cap_usd'])
    result = {'protocol_id': profile['protocol_id'], 'case': case['case_id'], 'episode': case['episode'],
        'checks': checks, 'all_checks_passed': all(checks.values()), 'evaluation': evaluation,
        'raw_selected_results': external['selected_results'], 'current_verifier_replay': replay,
        'policy_goal': task['trusted_policy_goal'], 'original_prompt': task['original_goal'],
        'source_difficulty': descriptor['task'].get('difficulty'), 'calls': per_call,
        'reported_cost_usd': str(cost), 'new_reservations_usd': str(reserved),
        'cumulative_reservations_usd': budget['reserved_cost_usd'],
        'remaining_reservation_capacity_usd': str(Decimal(budget['approved_cap_usd'])-Decimal(budget['reserved_cost_usd'])),
        'unknown_costs_this_case': sum(r['reported_cost_usd'] is None for r in budget['requests']),
        'artifact_sha256': {str(p.relative_to(ROOT)): digest(p) for p in sorted(directory.rglob('*')) if p.is_file()},
        'training_eligible': False, 'curation_ready': False,
        'limits': ['One workspace-rename development case; not a pass-rate estimate.',
                   'Trusted goal explicitly requests rename without ownership transfer.',
                   'Scoped simulated outcomes, not a real account transaction.',
                   'No clean/deceptive paired comparison or injection-exposure claim.',
                   'Harness counts Done as a browser step; distinguish input/click events from declared completion.']}
    result['artifact_integrity_checks_passed']=all(v for k,v in checks.items() if k!='no_action_errors')
    write_json(state / 'audit.json', result)
    print(json.dumps({'all_checks_passed': result['all_checks_passed'], 'check_count': len(checks),
        'reported_cost_usd': str(cost), 'cumulative_reservations_usd': budget['reserved_cost_usd'],
        'remaining_reservation_capacity_usd': result['remaining_reservation_capacity_usd']}, indent=2))
    if not result['all_checks_passed']: raise SystemExit(1)


if __name__ == '__main__': main()
