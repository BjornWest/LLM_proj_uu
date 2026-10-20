"""Recover completed native grades into new results, without rewriting traces.

No browser or model calls. This repairs caller classification only; it never
relabels an interrupted episode as completed or reruns historical native code.
"""
import argparse
import json
from pathlib import Path

from intent_browser.automatic_grading import digest, file_hash
from scripts.hindrance_model_run import mechanism_outcome, read, save, summarize


def recover(row, directory):
    directory = Path(directory)
    traces = list((directory/'runs').glob('*/automatic-grading.json'))
    if len(traces) != 1:
        raise ValueError('Expected one saved automatic grading declaration')
    trace = traces[0].parent
    declaration = read(trace/'automatic-grading.json')
    raw = read(trace/'automatic-grade.json')
    summary = read(trace/'episode.json')
    if (declaration['status'] != 'graded' or summary.get('grading_error')
            or declaration['grade_sha256'] != file_hash(trace/'automatic-grade.json')
            or declaration['binding_sha256'] != digest(declaration['binding'])
            or raw['binding_sha256'] != declaration['binding_sha256']
            or raw['episode_id'] != trace.name or declaration['episode_id'] != trace.name
            or raw['contract_id'] != declaration['contract_id']):
        raise ValueError('Saved native grade is not an intact completed grade')
    clean = row['variant'] == 'clean'
    value = raw['raw_grade']
    native = value['order_grade']['native_grade'] if clean else value['native_grade']
    grade = mechanism_outcome(native, clean=clean)
    order_path = trace/'suite-order-grade.json'
    order_status = read(order_path)['status'] if order_path.exists() else 'inconclusive'
    if row.get('recipe_path'):
        statuses = [order_status] + ([] if clean else [native['status']])
        grade.update(status='fail' if 'fail' in statuses else 'inconclusive' if 'inconclusive' in statuses else 'pass',
                     order_status=order_status,
                     task_completed={'pass': True, 'fail': False, 'inconclusive': None}[order_status],
                     scope='native_order_component' if clean else 'native_order_component_and_mechanism')
    result = {**row, 'status': 'graded', 'grade': grade, 'native_grade': native,
              'policy_error': summary.get('error'), 'stop_reason': summary.get('stop_reason'),
              'recovery': {'source_episode': str(directory.resolve()),
                  'source_grade_sha256': file_hash(trace/'automatic-grade.json'),
                  'original_status': row['status'], 'original_error': row.get('error'),
                  'method': 'recover_already_completed_native_grade_no_model_no_regrading',
                  'order_grade_available': order_path.exists(),
                  'limitation': 'Interrupted policy remains incomplete; missing order projection remains inconclusive.'}}
    result.pop('error', None)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    for cohort in args.cohort:
        for result_path in sorted(cohort.glob('episode-*/result.json')):
            row = read(result_path)
            if row['status'] != 'system_failure' or not any(text in row.get('error', '') for text in
                    ('Clean automatic grading failed', 'Commercial automatic grading did not finalize')):
                continue
            recovered = recover(row, result_path.parent)
            rows.append(recovered)
    with (args.output/'results.jsonl').open('x') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')
    save(args.output/'summary.json', summarize(rows))
    print(json.dumps({'recovered': len(rows), 'output': str(args.output.resolve()),
                      'grades': {status: sum(r['grade']['status'] == status for r in rows)
                                 for status in ('pass', 'fail', 'inconclusive')}}))


if __name__ == '__main__':
    main()
