"""Independently summarize saved reference trials; no browser/API/model calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit('Refusing existing output')
    directory = args.report.parent
    report = json.loads(args.report.read_text())
    assert report['error_type'] is None and report['close_completed']
    assert report['model_calls'] == 0 and report['scoped_records_unchanged']
    assert len(report['cleanup']) == 3 and all(x['absent_after_close'] for x in report['cleanup'])
    hashes = json.loads((directory / 'artifact-hashes.json').read_text())
    for name, digest in hashes.items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    for name, digest in report['source_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    rows = []
    for trial in report['trials']:
        case = directory / f"{trial['round']}-{trial['method']}"
        assert json.loads((case / 'result.json').read_text()) == trial
        assert all(not action['error'] for action in trial['actions'])
        assert trial['settle_seconds'] >= 10
        visible = [x for x in trial['before_run_state'] if x['visible']]
        hidden = [x for x in trial['before_run_state'] if x['type'] == 'hidden']
        assert len(visible) == len(hidden) == 1
        assert visible[0]['value'] == report['target']['name']
        exact_query = trial['query'] == 'assigned_to=' + report['target']['owner_id']
        assert exact_query == trial['exact_target_query'] == bool(trial['native_filter_result'][0])
        if exact_query:
            assert trial['target_name_in_result_ax'] and trial['expected_date_in_result_ax']
        rows.append({'round': trial['round'], 'method': trial['method'],
                     'display_text_is_target': True,
                     'hidden_reference_is_target_before_run': hidden[0]['value'] == report['target']['owner_id'],
                     'hidden_reference_empty_before_run': hidden[0]['value'] == '',
                     'menu_expanded_before_run': visible[0]['expanded'],
                     'query': trial['query'], 'correct_target_filter': exact_query,
                     'expected_date_in_result_ax': trial['expected_date_in_result_ax'],
                     'browser_action_count': len(trial['actions'])})
    counts = Counter(x['method'] for x in rows)
    assert counts == {method: 2 for method in ['plain_fill', 'autocomplete_only', 'autocomplete_select', 'upstream_select']}
    # Known matched reproduction contract: plain fill fails and exact selection
    # succeeds. Keep autocomplete-without-selection empirical, not assumed.
    assert all(not x['correct_target_filter'] for x in rows if x['method'] == 'plain_fill')
    assert all(x['correct_target_filter'] for x in rows if x['method'] in ['autocomplete_select', 'upstream_select'])
    result = {'schema': 'workarena-reference-saved-audit-v1', 'report': str(args.report),
              'report_sha256': hashlib.sha256(args.report.read_bytes()).hexdigest(),
              'artifact_hashes_checked': len(hashes), 'source_hashes_checked': len(report['source_sha256']),
              'trials': rows, 'scoped_records_unchanged': True, 'cleanup_verified': True,
              'model_calls': 0, 'model_task_success': None, 'training_eligible': False,
              'limitations': report['limitations'],
              'audit_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps({'trials': len(rows), 'hashes_checked': len(hashes), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
