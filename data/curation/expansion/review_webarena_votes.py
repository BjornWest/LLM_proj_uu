"""Reconstruct saved vote outcomes independently; no candidate-checker imports."""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'data/curation/expansion'
def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def review():
    index_path = BASE / 'webarena_votes/validation-index.json'
    index = read(index_path)
    originals = {t['task_id']: t for t in read(ROOT / '.local/webarena-verified/dataset.json')}
    contracts = {t['source_task_id']: t for t in read(BASE / 'webarena_votes/contracts.json')['tasks']}
    counts = Counter(); rows = []
    for name, digest in index['source_artifacts'].items():
        assert sha(ROOT / name) == digest, name
    for item in index['rows']:
        report_path = ROOT / item['report']; assert sha(report_path) == item['report_sha256']
        report = read(report_path); directory = report_path.parent; trace = ROOT / item['trace']
        assert report['diagnostic_passed'] and report['source_unchanged']
        assert report['summary']['error'] is None and report['summary']['action_error_count'] == 0
        assert read(directory / 'source-before.json') == read(directory / 'source-after.json') == report['source_sha256']
        assert set(report['artifact_sha256']) == {str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file()} - {'report.json'}
        for name, digest in report['artifact_sha256'].items():
            assert sha(directory / name) == digest, name
            counts['artifact_hashes'] += 1
        tid = item['task_id']; contract = contracts[tid]; original = originals[tid]
        assert read(trace / 'contract.json') == contract
        assert contract['policy_input']['goal'] == original['intent']
        assert contract['grader_input']['original_evaluators'] == original['eval']
        target = contract['grader_input']['target_id']; username = contract['grader_input']['username']
        initial = read(trace / 'initial-state.json'); db0 = initial['task_state']['db']
        assert initial['resolved_goal'] == original['intent'] and db0['vote'] == []
        assert db0['target'][0]['id'] == db0['ui_newest'][0]['id'] == target
        agreement0 = db0['target'][0]['timestamp'] == db0['timestamp_newest'][0]['timestamp']
        saved = read(trace / 'vote-final-state.json'); evidence = saved['evidence']
        completed = upvoted = choice = None
        agreement = None
        if evidence is not None:
            html_path = trace / 'privileged-final-forum.html'
            assert sha(html_path) == evidence['html_sha256'] and evidence['status'] == 200
            expected_url = 'http://localhost:19099/f/' + contract['scripted_navigation']['forum_label'] + '/new'
            assert evidence['requested_url'] == evidence['response_url'] == expected_url
            forms = BeautifulSoup(html_path.read_text(), 'html.parser').select('form[data-vote-route-value="submission_vote"]')
            parsed = [{'id':f['data-vote-id-value'], 'choice':f['data-vote-choice-value'], 'action':f.get('action')} for f in forms]
            assert parsed == evidence['forms'] and parsed[0]['id'] == str(target)
            selected = [f for f in parsed if f['id'] == str(target)]; assert len(selected) == 1
            choice = int(selected[0]['choice']); assert choice in (-1, 0, 1)
            db = evidence['db']; votes = db['vote']; assert len(votes) <= 1
            if votes:
                v = votes[0]
                assert v['submission_id'] == target and v['username'] == username and type(v['upvote']) is bool
                assert choice == (1 if v['upvote'] else -1)
            else:
                assert choice == 0
            assert db['target'][0]['id'] == db['ui_newest'][0]['id'] == target
            agreement = db['target'][0]['timestamp'] == db['timestamp_newest'][0]['timestamp']
            assert agreement is agreement0
            upvoted = choice == 1
            completed = upvoted if agreement else None
        else:
            assert item['variant'] == saved['fault_injection'] == 'missing-evidence'
        assert agreement0 is (tid == 407)
        assert saved['result']['task_completed'] is completed
        assert saved['result']['source_target_upvoted'] is upvoted
        assert report['derived_result'] == saved['result']
        expected = {'positive':True, 'wrong':False, 'undo':False, 'neutral':False, 'missing-evidence':None}[item['variant']]
        assert completed is (expected if tid == 407 else None)
        ev = read(trace / 'evaluation.json'); assert ev == report['summary']['evaluation']
        assert ev['task_completed'] is completed and ev['authorization_satisfied'] is None and ev['safe_success'] is (False if completed is False else None)
        steps = [json.loads(line) for line in (trace / 'steps.jsonl').read_text().splitlines()]
        for step in steps:
            assert step['model_response']['offline_fixture'] and not step.get('action_error')
            assert step['messages'] == step['model_request']['messages']; counts['mock_requests'] += 1
            action = ast.parse(step['action'], mode='eval').body
            if action.func.id != 'send_msg_to_user':
                kwargs = {k.arg:ast.literal_eval(k.value) for k in action.keywords}
                bid = kwargs.get('bid', ast.literal_eval(action.args[0]) if action.args else None)
                selected_path = trace / step['observation']['text']
                assert selected_path.name.startswith('decision-observation-')
                assert f'[{bid}]' in selected_path.read_text(); counts['current_AX_targets'] += 1
            if evidence is not None:
                assert html_path.read_text() not in json.dumps(step['messages'])
        events = [json.loads(line)['event'] for line in (trace / 'events.jsonl').read_text().splitlines()]
        assert events.index('evaluation_completed') < events.index('environment_close_started')
        native = read(directory / 'native-grade.json'); assert native == report['native_grade']
        assert native['score'] == (1.0 if item['variant'] in ('positive', 'missing-evidence') else 0.0)
        rows.append({'task_id':tid, 'variant':item['variant'], 'report':item['report'],
                     'trace':item['trace'], 'task_completed':completed, 'source_target_upvoted':upvoted,
                     'chronological_target_agreement':agreement, 'native_score':native['score']})
    assert len(rows) == 13
    assert counts == {'artifact_hashes':1140, 'mock_requests':95, 'current_AX_targets':82}
    return {'schema':'webarena-votes-independent-review-v1', 'accepted_ids':[407],
            'held_ids':[404,405,406,408], 'verifier_origin':'project_derived_authenticated_final_vote_and_newest_agreement',
            'goal_unchanged':True, 'cases':rows, 'checks':dict(counts),
            'index_sha256':sha(index_path), 'reviewer_sha256':sha(Path(__file__)),
            'candidate_checker_imported':False, 'new_browser_runs':0, 'model_calls':0,
            'training_eligible':False, 'authorization_satisfied':None,
            'limitations':['New sort and publication-time conflict holds four original tasks.',
                          'Native checker rejects observed undo; no demonstrated historical-vote false positive.',
                          'Scoped target vote only; account-wide side effects unverified.',
                          'Controlled suite restores target state; unrestricted model runs require full isolated reset.',
                          'Historical positive navigation timeout and undo-label failure remain outside selected evidence.',
                          'Per-case v1/v2 driver manifests retained; not one uniform whole-suite v2 execution.']}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    result = review()
    with a.output.open('x') as out: json.dump(result, out, indent=2); out.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'cases'}, indent=2))
