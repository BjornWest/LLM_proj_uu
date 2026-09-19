"""Audit the frozen 14-task native adoption cohort without importing its graders."""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def review(path):
    suite = json.loads(path.read_text())
    assert len(suite['cases']) == 28 and suite['passed']
    source = None
    counts = {'artifact_hashes': 0, 'current_observation_targets': 0, 'native_requests': 0, 'verdicts': 0}
    rows = []
    normalize = lambda v: ' '.join(v.split()).casefold().rstrip('.')
    for case in suite['cases']:
        report_path = ROOT/case['report']
        r = json.loads(report_path.read_text())
        assert r['passed'] and r['source_unchanged'] and r['profile'] == 'core-tools-v3'
        assert case['execution']['returncode'] == 0 and not case['execution']['timed_out']
        if source is None: source = r['source_sha256']
        assert source == r['source_sha256'], 'Mixed source cohort'
        trace = ROOT/r['trace']
        for f, digest in r['files_sha256'].items():
            assert sha(trace/f) == digest
            counts['artifact_hashes'] += 1
        ev = json.loads((trace/'evaluation.json').read_text())
        assert ev == r['summary']['evaluation']
        if case['task_id'].startswith('TX'):
            contract = json.loads((trace/'lookup-contract.json').read_text())
            detail = json.loads((trace/'lookup-evaluation.json').read_text())
            complete = normalize(detail['final_answer']) in {normalize(a) for a in contract['grader_input']['accepted_answers']}
            expected_path = contract['grader_input'].get('required_final_path')
            complete &= expected_path is None or urlsplit(detail['final_state']['url']).path == expected_path
        else:
            contract = json.loads((trace/'action-contract.json').read_text())
            detail = json.loads((trace/'action-evaluation.json').read_text())
            quantities = Counter()
            carts = [detail['state']['cart']] if contract['kind'] == 'cart' else [e['payload']['cart'] for e in detail['journal'] if e['kind'] == 'shop:checkout']
            for cart in carts:
                for item in cart:
                    assert type(item['quantity']) is int and item['quantity'] > 0
                    quantities[str(item['id'])] += item['quantity']
            complete = all(quantities[k] == n for k,n in contract['grader_input']['target_quantities'].items())
        assert ev['task_completed'] is bool(complete)
        assert bool(complete) is (not case['negative'])
        assert ev['authorization_satisfied'] in (None, False) and ev['technical_error'] is None
        assert ev['safe_success'] is not True
        counts['verdicts'] += 1
        for line in (trace/'steps.jsonl').read_text().splitlines():
            step = json.loads(line)
            assert not step.get('action_error')
            assert step['model_response']['offline_fixture'] is True
            assert step['model_request']['messages'] == step['messages']
            assert step['model_request']['tools']
            counts['native_requests'] += 1
            action = ast.parse(step['action'], mode='eval').body
            if action.func.id != 'send_msg_to_user':
                kwargs = {x.arg: ast.literal_eval(x.value) for x in action.keywords}
                bid = kwargs.get('bid', ast.literal_eval(action.args[0]) if action.args else None)
                selected = trace/step['observation']['text']
                assert selected.name.startswith('decision-observation-')
                assert f'[{bid}]' in selected.read_text(), 'Target only in history, not current observation'
                counts['current_observation_targets'] += 1
        events = [json.loads(s)['event'] for s in (trace/'events.jsonl').read_text().splitlines()]
        assert events.index('evaluation_completed') < events.index('environment_close_started')
        rows.append({'task_id': case['task_id'], 'negative': case['negative'], 'trace': r['trace'],
                     'report': case['report'], 'report_sha256': sha(report_path), 'task_completed': bool(complete)})
    return {'schema_version': 1, 'status': 'scripted_native_profile_validated', 'profile': 'core-tools-v3',
            'source_sha256': source, 'suite_report': str(path.relative_to(ROOT)), 'suite_sha256': sha(path),
            'review_script_sha256': sha(Path(__file__)), 'task_count': 14, 'case_count': 28,
            'checks': counts, 'cases': rows, 'model_calls': 0, 'training_eligible': False,
            'scope': 'Same original contracts, new native requests/tool parsing/current observation delivery. No paid/model capability evidence or comprehensive authorization claim.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suite', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists() or args.output.is_symlink(): raise FileExistsError(args.output)
    report = review(args.suite.resolve())
    with args.output.open('x') as out: json.dump(report, out, indent=2); out.write('\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['cases','source_sha256']}, indent=2))
