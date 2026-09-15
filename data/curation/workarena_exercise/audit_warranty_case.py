"""Audit one saved warranty development case without new browser/model calls."""
import argparse
import ast
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit('Refusing existing output')
    files = {}

    def load(path):
        raw = path.read_bytes()
        files[str(path.relative_to(ROOT))] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    case_path = args.case.resolve()
    case = load(case_path)
    trace = ROOT / case['trace']
    profile = load(case_path.parent / 'profile.json')
    ledger = load(ROOT / 'data/curation/sweeps/budget.json')
    rows = [r for r in ledger['requests'] if r['case_id'] == case_path.stem]
    steps = [json.loads(line) for line in (trace / 'steps.jsonl').read_text().splitlines()]
    sent = [s for s in steps if s.get('model_request') is not None]
    assert len(rows) == len(sent)
    for row, step in zip(rows, sent):
        assert row['model_request'] == step['model_request']
        assert row['model_response'] == step['model_response']
        assert row['session_id'] == row['model_request']['session_id'] == trace.name
        assert profile['reference_guidance'] in row['model_request']['messages'][0]['content']
    evaluation = load(trace / 'evaluation.json')
    assert evaluation == case['summary']['evaluation']
    evidence = load(trace / 'workarena-verifier-evidence.json')
    initial = load(trace / 'initial-state.json')
    cleanup = load(trace / 'workarena-cleanup.json')
    assert len(cleanup) == 3 and all(x['absent_after_teardown'] for x in cleanup)
    assert evidence['expected_date'] == initial['task_state']['expected_date']
    answer = evidence['answer']
    correct = isinstance(answer, str) and answer.strip() == evidence['expected_date']
    assert correct == evaluation['task_completed']
    actions = []
    for step in steps:
        code = step.get('action')
        autocomplete = None
        if code:
            node = ast.parse(code, mode='eval').body
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'fill':
                autocomplete = ast.literal_eval(node.args[2]) if len(node.args) > 2 else False
                for keyword in node.keywords:
                    if keyword.arg == 'enable_autocomplete_menu':
                        autocomplete = ast.literal_eval(keyword.value)
        request = step.get('model_request') or {}
        response = step.get('model_response') or {}
        actions.append({'step': step['step'], 'action': code, 'action_error': step.get('action_error'),
                        'autocomplete_enabled': autocomplete, 'provider': response.get('provider'),
                        'date_present_in_delivered_messages': evidence['expected_date'] in
                            '\n'.join(m['content'] for m in request.get('messages', []))})
    for path in trace.rglob('*'):
        if path.is_file():
            files[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    costs = [r.get('reported_cost_usd') for r in rows]
    result = {'schema': 'workarena-warranty-saved-case-audit-v1', 'case': str(case_path.relative_to(ROOT)),
              'trace': str(trace.relative_to(ROOT)), 'requests': len(rows),
              'exact_request_response_ledger_matches': True, 'actions': actions,
              'evaluation': evaluation, 'expected_date': evidence['expected_date'], 'answer': answer,
              'reported_cost_usd': str(sum((Decimal(str(c)) for c in costs if c is not None), Decimal(0))),
              'unknown_costs': sum(c is None for c in costs),
              'new_reserved_usd': str(sum((Decimal(r['reservation_usd']) for r in rows), Decimal(0))),
              'cumulative_reserved_usd': ledger['reserved_cost_usd'],
              'remaining_reservation_capacity_usd': str(Decimal(ledger['approved_cap_usd']) - Decimal(ledger['reserved_cost_usd'])),
              'all_three_temporary_records_removed': True,
              'scoped_records_unchanged': evidence['requirements']['scoped_records_unchanged'],
              'stop_reason': case['summary']['stop_reason'],
              'training_eligible': False, 'new_calls_by_audit': 0,
              'limitations': ['Guided single development case; no causal prompt comparison or benchmark pass rate.',
                             'Date occurrence in messages alone does not establish reading or the source of the answer.',
                             'Authorization checks cover scoped records only; broad authorization remains unknown.'],
              'files_sha256': files,
              'audit_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps({k: result[k] for k in ['requests', 'evaluation', 'reported_cost_usd', 'cumulative_reserved_usd']}))


if __name__ == '__main__':
    main()
