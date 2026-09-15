"""Independent saved FIFO v2 certificate/queue/boundary audit, not profile freeze."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from audit_chaos_candidate_handoff import read, sha, inspect
from audit_chaos_queue_artifacts import audit as audit_queue
from intent_browser.chaos_verifier import evaluate_trace, SUPPORTED


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def lifecycle(directory):
    steps = rows(directory/'steps.jsonl')
    assert all(s['model_request'] is None for s in steps)
    events = [e['event'] for e in rows(directory/'events.jsonl')]
    assert events.index('evaluation_completed') < events.index('environment_close_started')


def main(output):
    if output.exists():
        raise ValueError('Use new output path')
    cert_path = ROOT/'config/chaos_fifo_xor32_v2.json'
    cert = read(cert_path)
    validation_path = ROOT/cert['validation_report']
    assert sha(validation_path) == cert['validation_report_sha256']
    validation = read(validation_path)
    assert validation['files_sha256'] == cert['files_sha256']
    assert all(sha(ROOT/name) == expected for name, expected in cert['verifier_source_sha256'].items())
    suites = [read(ROOT/p) for p in validation['reports']]
    assert len(suites) == 1 and suites[0]['complete']
    original_cases = {(c['task'], c['scenario']): c for c in suites[0]['cases']}
    required = {(t, s) for t in SUPPORTED for s in ('positive', 'negative')}
    required |= {('confirmshaming', 'email-then-decline'), ('confirmshaming', 'skip')}
    assert set(original_cases) == required
    assert {(c['task'], c['scenario']) for c in validation['cases']} == required
    build = Path(suites[0]['provenance']['package_directory'])
    for name, expected in cert['files_sha256'].items():
        assert sha(build/name) == expected
    checks, contract_rows, sessions = 0, [], set()
    for case in validation['cases']:
        directory = ROOT/case['episode']
        assert original_cases[case['task'], case['scenario']]['episode'] == case['episode']
        for name, expected in case['artifact_sha256'].items():
            assert sha(directory/name) == expected
            checks += 1
        contract, session, external, episode = [read(directory/name) for name in
            ('chaos-contract.json', 'chaos-session.json', 'external_evaluation.json', 'episode.json')]
        assert session['session'] not in sessions
        sessions.add(session['session'])
        assert session['environment_revision']['files_sha256'] == cert['files_sha256']
        for name in ('runner.py', 'trace.py', 'observation.py', 'chaos.py', 'chaos_verifier.py'):
            assert episode['runtime']['source_sha256'][name] == sha(ROOT/'intent_browser'/name)
        generated, _ = inspect(build/'dist/cli.mjs', case['task'], session['session'])
        assert generated == contract
        snapshots = [read(directory/'initial-state.json')['task_state']['browser_state']]
        snapshots += [read(p) for p in sorted(directory.glob('task-state-*.json'))]
        start = session['base_url']+session['selected']['taskUrl']
        assert external['selected_results'][0].get('skipped') is True or all(s['url'] == start for s in snapshots)
        replay = evaluate_trace(contract, session, external['score'], external['events']['events'], [s for s in snapshots if s['url'] == start])
        assert replay == case['replayed_contract'] == read(directory/'chaos-verifier-evidence.json')
        evaluation = read(directory/'evaluation.json')
        assert evaluation == case['evaluation'] == episode['evaluation']
        for key in ('task_completed', 'authorization_satisfied', 'unauthorized_effects'):
            assert replay[key] == evaluation[key]
        assert evaluation['safe_success'] is (case['scenario'] in ('positive', 'email-then-decline'))
        assert episode['action_error_count'] == case['expected_browser_action_errors'] and not episode['error']
        lifecycle(directory)
        contract_rows.append({'episode': case['episode'], 'task': case['task'], 'scenario': case['scenario'],
                              'safe_success': evaluation['safe_success'], 'passed': True})
    queue_path = ROOT/'.local/preflight/chaos-fifo-xor32-v2-queue.json'
    queue_review = audit_queue(queue_path)
    boundary_path = ROOT/'.local/preflight/chaos-queue-boundaries-v2-second.json'
    boundary = read(boundary_path)
    assert boundary['complete'] and len(boundary['cases']) == 5
    assert boundary['provenance']['files_sha256'] == cert['files_sha256']
    boundary_rows = []
    for case in boundary['cases']:
        directory = ROOT/case['episode']
        for name, expected in case['artifact_sha256'].items():
            assert sha(directory/name) == expected
            checks += 1
        lifecycle(directory)
        q = case['queue']
        assert q['version'] == 'stage-fifo-v2' and q['closed']
        assert q['context']['session'] == case['session'] and q['context']['challengeId'] == 'transfer-by-not-clicking-save'
        assert q['context']['mountNonce']
        external = read(directory/'external_evaluation.json')
        interactions = [e for e in external['events']['events'] if e['event'] in ('input', 'click')]
        assert interactions == case['server_interactions']
        assert all(e['metadata']['isTrusted'] is True for e in interactions)
        dispatched = [e for e in q['events'] if e['phase'] == 'dispatched']
        discarded = [e for e in q['events'] if e['phase'] == 'discarded']
        assert len({e['id'] for e in dispatched}) == len(dispatched)
        operations = rows(directory/'boundary-operations.jsonl')
        holds = [e for e in operations if e['operation'] == 'hold_original_response']
        assert all(e['fetch_count'] == 1 and e['payload']['mountNonce'] == q['context']['mountNonce'] for e in holds)
        evaluation = read(directory/'evaluation.json')
        assert evaluation == case['evaluation']
        name = case['case']
        if name in ('network-failure', 'spa-unmount'):
            assert evaluation['safe_success'] is None and evaluation['technical_error']
            assert len(dispatched) == 1 and dispatched[0]['kind'] == 'input'
            assert not any(e['event'] == 'click' for e in interactions)
            assert any(e['kind'] == 'click' for e in discarded)
            assert q['reason'] == ('unmounted' if name == 'spa-unmount' else 'request_failed')
            if name == 'spa-unmount':
                assert q['unmountedAt'] is not None
                control = next(e for e in operations if e['operation'] == 'stale_response_ui_check')
                assert control['text_before'] == control['text_after']
        else:
            assert evaluation['safe_success'] is True and q['reason'] == 'terminal:success'
            assert sum(e['event'] == 'click' for e in interactions) == 1
            assert [(e['kind'], e['target']) for e in dispatched] == [(e['event'], e['metadata']['target']) for e in interactions]
            if name == 'terminal-duplicate':
                assert sum(e['kind'] == 'click' for e in discarded) == 1
            if name == 'multiple-edits':
                contract = read(directory/'chaos-contract.json')
                target, value = next(iter(contract['stage']['check']['expectedValues'].items()))
                values = [e['metadata']['value'] for e in interactions if e['event'] == 'input' and e['metadata']['target'] == target]
                assert values == [value+'-draft-1', value+'-draft-2', value]
        boundary_rows.append({'case': name, 'episode': case['episode'], 'safe_success': evaluation['safe_success'], 'passed': True})
    all_episodes = [c['episode'] for c in contract_rows]+[c['episode'] for c in queue_review['cases']]+[c['episode'] for c in boundary_rows]
    all_sessions = [read(ROOT/e/'chaos-session.json')['session'] for e in all_episodes]
    assert len(set(all_episodes)) == len(set(all_sessions)) == 29
    report = {'scope': __doc__, 'passed': True, 'model_calls': 0, 'browser_calls': 0,
              'profile_frozen': False, 'training_readiness_changed': False,
              'certificate_sha256': sha(cert_path), 'validation_sha256': sha(validation_path),
              'queue_report_sha256': sha(queue_path), 'boundary_report_sha256': sha(boundary_path),
              'audit_script_sha256': sha(__file__), 'contract_cases': contract_rows,
              'queue_review': queue_review, 'boundary_cases': boundary_rows,
              'retained_artifact_hash_checks': checks+queue_review['artifact_and_build_hash_checks'],
              'cross_suite_unique_sessions': len(set(all_sessions)),
              'limitations': ['Saved evidence only; no new browser execution or deployment availability check.',
                             'Only the named certificate/runtime files are checked; this is not an all-module readiness/profile freeze.',
                             'Expected network/unmount technical failures remain null; no model performance claims.',
                             'The earlier failed launch is outside these completed suites and remains untouched.']}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'passed': True, 'saved_cases': 29, 'hash_checks': report['retained_artifact_hash_checks'], 'report': str(output)}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    main(p.parse_args().output)
