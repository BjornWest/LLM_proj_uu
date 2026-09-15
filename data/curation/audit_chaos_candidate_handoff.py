"""Read-only replay of the specified historical FIFO/xorshift v1 handoff."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from audit_chaos_queue_artifacts import audit
from intent_browser.chaos_verifier import SUPPORTED, evaluate_trace


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(bundle, task, session):
    text = subprocess.check_output(['node', 'scripts/inspect_chaos.mjs'], input=json.dumps(
        {'bundle': str(bundle), 'task': task, 'session': session}), text=True, cwd=ROOT)
    return json.loads(text), hashlib.sha256(json.dumps(json.loads(text), separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def main(output):
    if output.exists():
        raise ValueError('Use a new output path')
    queue_paths = ['.local/preflight/chaos-fifo-v1-validated.json', '.local/preflight/chaos-fifo-xor32-queue.json']
    queues = [audit(ROOT/p) for p in queue_paths]
    suite_path = ROOT/'runs/20260915T002523Z-6be0842f/chaos-preflight-suite.json'
    suite = read(suite_path)
    assert suite['complete'] and len(suite['cases']) == 16
    required = {(task, scenario) for task in SUPPORTED for scenario in ('positive', 'negative')}
    required |= {('confirmshaming', 'email-then-decline'), ('confirmshaming', 'skip')}
    assert {(c['task'], c['scenario']) for c in suite['cases']} == required
    bundle = Path(suite['provenance']['bundle'])
    build = Path(suite['provenance']['package_directory'])
    for name, expected in suite['provenance']['files_sha256'].items():
        assert sha(build/name) == expected
    sessions, contracts = set(), []
    for case in suite['cases']:
        directory = ROOT/case['episode']
        session, contract, external, episode, saved = [read(directory/name) for name in
            ('chaos-session.json', 'chaos-contract.json', 'external_evaluation.json', 'episode.json', 'chaos-verifier-evidence.json')]
        assert session['session'] not in sessions
        sessions.add(session['session'])
        assert session['environment_revision']['files_sha256'] == suite['provenance']['files_sha256']
        regenerated, _ = inspect(bundle, case['task'], session['session'])
        assert regenerated == contract
        snapshots = [read(directory/'initial-state.json')['task_state']['browser_state']]
        snapshots += [read(p) for p in sorted(directory.glob('task-state-*.json'))]
        start_url = session['base_url']+session['selected']['taskUrl']
        assert external['selected_results'][0].get('skipped') is True or all(s['url'] == start_url for s in snapshots)
        replay = evaluate_trace(contract, session, external['score'], external['events']['events'], [s for s in snapshots if s['url'] == start_url])
        assert replay == saved
        evaluation = read(directory/'evaluation.json')
        assert evaluation == case['evaluation']
        for field in ('task_completed', 'authorization_satisfied', 'unauthorized_effects'):
            assert evaluation[field] == replay[field]
        expected = case['scenario'] in ('positive', 'email-then-decline')
        assert evaluation['safe_success'] is expected and case['expected_safe_success'] is expected
        assert evaluation['injection_exposed'] is None and evaluation['injection_avoided'] is None
        assert episode['error'] is None and episode['training_eligible'] is False
        steps = [json.loads(s) for s in (directory/'steps.jsonl').read_text().splitlines()]
        assert all(s['model_request'] is None for s in steps)
        assert episode['action_error_count'] == case['expected_browser_action_errors']
        lifecycle = [json.loads(s)['event'] for s in (directory/'events.jsonl').read_text().splitlines()]
        assert lifecycle.index('evaluation_completed') < lifecycle.index('environment_close_started')
        contracts.append({'task': case['task'], 'scenario': case['scenario'], 'episode': case['episode'],
                          'session': session['session'], 'replay_matches_saved': True,
                          'descriptor_regenerated_matches': True, 'safe_success': evaluation['safe_success'],
                          'browser_action_errors': episode['action_error_count'],
                          'runtime_source_sha256_at_execution': episode['runtime']['source_sha256'],
                          'artifact_sha256_at_review': {p.name: sha(p) for p in directory.iterdir() if p.suffix in ('.json', '.jsonl', '.txt')}})
    rng_path = ROOT/'.local/preflight/chaos-rng-v2.json'
    rng = read(rng_path)
    assert sha(ROOT/'scripts/verify_chaos_rng.mjs') == rng['source_sha256']
    assert sha(ROOT/'scripts/inspect_chaos.mjs') == rng['inspector_sha256']
    rng_review = {}
    for identity in ('original', 'derived'):
        part = rng[identity]
        assert sha(part['bundle']) == part['bundle_sha256']
        for v in part['variants']:
            regenerated, digest = inspect(part['bundle'], 'revoke-current-only', v['session'])
            assert digest == v['descriptor_sha256']
            stage = regenerated['stage']
            index = next(i for i, row in enumerate(stage['data']['rows']) if row.get('target'))
            action = next(i for i, a in enumerate(stage['data']['actionsPerRow']) if a['kind'] == 'rotate')
            assert (index, action, stage['data']['rows'][index]['name']) == (v['target_index'], v['safe_action_index'], v['target_name'])
        counts = {k: dict(Counter(str(v[k]) for v in part['variants'])) for k in ('target_index', 'target_name', 'safe_action_index')}
        assert counts == part['diversity']
        joint = Counter(f"{v['target_index']}:{v['safe_action_index']}" for v in part['variants'])
        if identity == 'derived':
            assert len(joint) == 6 and len(counts['target_name']) == 4
        rng_review[identity] = {'regenerated_descriptors': len(part['variants']), 'descriptor_hash_matches': True,
                                'counts': counts, 'joint_counts': dict(joint), 'bundle_sha256': part['bundle_sha256']}
    result = {'scope': __doc__, 'passed': True, 'model_calls': 0, 'browser_calls': 0,
              'queue_reports': queues, 'contract_suite': str(suite_path.relative_to(ROOT)),
              'contract_suite_sha256': sha(suite_path), 'contract_cases': contracts,
              'rng_report': str(rng_path.relative_to(ROOT)), 'rng_report_sha256': sha(rng_path), 'rng_review': rng_review,
              'review_script_sha256': sha(__file__),
              'current_replay_verifier_sha256': sha(ROOT/'intent_browser/chaos_verifier.py'),
              'limitations': ['Replay with current verifier is not certification of current runner execution.',
                             'Newly recorded contract artifact hashes describe bytes at review, not an earlier immutable archive.',
                             'RNG author acceptance gate checks marginals and at least two names; independent review additionally checks all four names and six joint cells.',
                             'Earlier incomplete queue reports are excluded. V1 evidence does not certify v2.']}
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'passed': True, 'queue_cases': sum(len(q['cases']) for q in queues),
                      'contract_cases': len(contracts), 'rng_regenerated': 256,
                      'derived_joint': rng_review['derived']['joint_counts'], 'report': str(output)}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    main(p.parse_args().output)
