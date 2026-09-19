"""Independently re-evaluate retained WebArena browser positives with native code.

Run in the isolated WebArena-Verified venv. No browser/model calls. This does not
promote the native scorer to an independent final-state or authorization oracle.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
from importlib.metadata import version

from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig

ROOT = Path(__file__).resolve().parents[3]
INDEX = ROOT/'.local/expansion-webarena/first-batch-review-v1/report.json'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def review():
    index = json.loads(INDEX.read_text())
    checks = {'artifact_hashes': 0, 'index_hashes': 0, 'current_AX_targets': 0, 'native_positive_replays': 0}
    for mapping in [index['artifact_sha256'], index['acceptance_indexes']]:
        for path, digest in mapping.items():
            assert sha(ROOT/path) == digest, path
            checks['artifact_hashes' if mapping is index['artifact_sha256'] else 'index_hashes'] += 1
    api = WebArenaVerified(config=WebArenaVerifiedConfig(environments={
        '__SHOPPING__': {'urls': ['http://localhost:7770']},
        '__REDDIT__': {'urls': ['http://localhost:9999']}}))
    records = []
    for row in index['tasks']:
        tid = int(row['source_task_id'])
        trace = ROOT/row['trace']
        native_report = json.loads((ROOT/row['evidence']['native_report']).read_text())
        native = next(t for t in native_report['tasks'] if t['task_id'] == tid)
        result = api.evaluate_task(task_id=tid, agent_response=native['positive_response'], network_trace=trace/'network.har').model_dump(mode='json')
        assert result['score'] == 1 and result['status'] == 'success'
        checks['native_positive_replays'] += 1
        steps = [json.loads(s) for s in (trace/'steps.jsonl').read_text().splitlines()]
        assert all(not s.get('action_error') for s in steps)
        for step in steps:
            action = ast.parse(step['action'], mode='eval').body
            if isinstance(action, ast.Call) and action.func.id != 'send_msg_to_user':
                bid = ast.literal_eval(action.args[0])
                assert f'[{bid}]' in step['messages'][-1]['content']
                checks['current_AX_targets'] += 1
        original = json.loads((trace/'evaluation.json').read_text())
        assert original['task_completed'] is None and original['safe_success'] is None
        records.append({'source_task_id': str(tid), 'template_id': row['template_id'],
                        'trace': row['trace'], 'native_positive_recomputed': result,
                        'browser_positive_reviewed': True, 'original_unknown_evaluation_preserved': True,
                        'fully_accepted': False,
                        'pending': ['Actual browser negative-path review', 'New native-tool profile adoption', 'Task-specific data/reset closure']})
    return {'schema_version': 1, 'reviewer': 'curation-parent-independent', 'candidate_index_sha256': sha(INDEX),
            'review_script_sha256': sha(Path(__file__)), 'native_package_version': version('webarena-verified'),
            'status': 'positive_feasibility_verified_acceptance_incomplete', 'checks': checks,
            'source_task_count': len(records), 'site_count': 2, 'records': records,
            'model_calls': 0, 'new_browser_runs': 0, 'training_eligible': False,
            'limitations': ['Native grader replay is not independent implementation of grader semantics.',
                           'HAR navigation success may mean a page was visited, not the correct final page.',
                           'Legacy 120000-character AX profile; no current teacher-profile compatibility claim.',
                           'Source fixtures vary in runtime; retained first-attempt hang is not overwritten.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(args.output)
    report = review()
    with args.output.open('x') as out:
        json.dump(report, out, indent=2)
        out.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}, indent=2))
