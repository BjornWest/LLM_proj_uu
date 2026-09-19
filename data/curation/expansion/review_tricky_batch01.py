"""Independent saved-evidence review; does not import the candidate verifier.

Recomputes concise-answer outcomes and final-page requirements, checks exact
artifacts and delivered action/answer evidence. This is not a fresh browser run.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
INDEX = ROOT/'data/curation/expansion/tricky/validation-index.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value):
    return ' '.join(value.split()).casefold().rstrip('.')


def review():
    index = json.loads(INDEX.read_text())
    contracts_path = ROOT/'data/curation/expansion/tricky/contracts.json'
    contracts = {c['id']: c for c in json.loads(contracts_path.read_text())['tasks']}
    checks = {'artifact_hashes': 0, 'source_hashes': 0, 'action_targets': 0, 'browser_extractions': 0, 'independent_verdicts': 0}
    for mapping in [index['reports'], index['source_sha256']]:
        for path, digest in mapping.items():
            assert sha(ROOT/path) == digest, path
            checks['source_hashes'] += 1
    report_path = next(ROOT/p for p in index['reports'] if 'lookup-driver' in p)
    report = json.loads(report_path.read_text())
    cases = []
    for row in report['rows']:
        trace = ROOT/row['trace']
        assert {str(p.relative_to(trace)) for p in trace.rglob('*') if p.is_file()} == set(row['files'])
        for path, digest in row['files'].items():
            assert sha(trace/path) == digest, str(trace/path)
            checks['artifact_hashes'] += 1
        contract = contracts[row['task_id']]
        assert json.loads((trace/'lookup-contract.json').read_text()) == contract
        detail = json.loads((trace/'lookup-evaluation.json').read_text())
        raw_eval = json.loads((trace/'evaluation.json').read_text())
        assert raw_eval == row['evaluation']
        assert raw_eval['authorization_satisfied'] is None
        assert raw_eval['safe_success'] is (None if raw_eval['task_completed'] else False)
        assert raw_eval['technical_error'] is None
        answer_ok = norm(detail['final_answer']) in {norm(a) for a in contract['grader_input']['accepted_answers']}
        requested_path = contract['grader_input'].get('required_final_path')
        path_ok = requested_path is None or urlsplit(detail['final_state']['url']).path == requested_path
        expected = answer_ok and path_ok
        assert raw_eval['task_completed'] is expected
        assert expected is (row['case'] == 'positive')
        checks['independent_verdicts'] += 1
        steps = [json.loads(line) for line in (trace/'steps.jsonl').read_text().splitlines()]
        assert all(not s.get('action_error') for s in steps)
        for step in steps:
            parsed = ast.parse(step['action'], mode='eval').body
            if isinstance(parsed, ast.Call) and isinstance(parsed.func, ast.Name) and parsed.func.id != 'send_msg_to_user':
                bid = ast.literal_eval(parsed.args[0])
                assert f'[{bid}]' in step['messages'][-1]['content']
                checks['action_targets'] += 1
            assert step['model_request']['model'] is None
            assert step['model_request']['messages'] == step['messages']
        driver = json.loads((trace/'scripted-driver-evidence.json').read_text())
        assert driver['grader_reference_used_by_driver'] is False
        for extraction in driver['extractions']:
            matched = [s for s in steps if hashlib.sha256(json.dumps(s['messages'], sort_keys=True).encode()).hexdigest() == extraction['messages_sha256']]
            assert len(matched) == 1
            assert norm(extraction['value']) in norm(matched[0]['messages'][-1]['content'])
            assert any(norm(extraction['value']) in norm(json.loads(p.read_text())['body_text']) for p in trace.glob('lookup-state-*.json')) or contract['id'] == 'TX02'
            # TX02's accessible rating comes from an aria-label rather than body.innerText.
            checks['browser_extractions'] += 1
        event_names = [json.loads(line)['event'] for line in (trace/'events.jsonl').read_text().splitlines()]
        assert event_names.index('evaluation_completed') < event_names.index('environment_close_started')
        cases.append({'task_id': row['task_id'], 'case': row['case'], 'trace': str(trace.relative_to(ROOT)), 'outcome_recomputed': expected, 'accepted': True})
    assert len({r['task_id'] for r in cases if r['case'] == 'positive'}) == 10
    return {'schema_version': 1, 'reviewer': 'curation-parent-independent', 'candidate_index_sha256': sha(INDEX),
            'review_script_sha256': sha(Path(__file__)), 'status': 'accepted_for_scoped_general_browsing_development',
            'accepted_task_count': 10, 'site_count': len({c['site'] for c in contracts.values()}),
            'checks': checks, 'cases': cases, 'model_calls': 0, 'training_eligible': False,
            'limitations': ['Derived concise-answer protocol, not unrestricted semantic-answer grading.',
                           'No comprehensive authorization or side-effect verdict.',
                           'Saved-artifact review plus source inspection, not an independent browser replay.',
                           'Known health cancellation, missing PDF/audio defects remain outside these lookup contracts.',
                           'Current source reuse terms remain unspecified.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() or a.output.is_symlink():
        raise FileExistsError(a.output)
    result = review()
    with a.output.open('x') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
