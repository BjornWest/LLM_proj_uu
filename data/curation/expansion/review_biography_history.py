"""Compare three real browser histories with upstream and final-read outcomes."""
import argparse
import hashlib
import json
from pathlib import Path
from data.curation.expansion.biography_outcome import check_biography

ROOT = Path(__file__).resolve().parents[3]
REPORTS = [
    '.local/expansion-webarena/native-closure-extra9-grade-v2/report.json',
    '.local/expansion-webarena/biography-history-native-grade-v1/report.json',
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review():
    rows = []
    for name in REPORTS:
        report = ROOT/name
        for case in json.loads(report.read_text())['cases']:
            if case['task_id'] != 399:
                continue
            trace = ROOT/case['trace']
            har = trace/'network.har'
            assert sha(har) == case['har_sha256']
            result = check_biography(json.loads(har.read_text()), origin='http://localhost:18999',
                                    username='MarvelsGrantMan136', expected='I am a robot')
            assert result['task_completed'] is case['intended_outcome']
            assert case['source_unchanged'] and case['scripted_path_completed']
            rows.append({'trace': case['trace'], 'variant': case['variant'],
                         'har_sha256': sha(har), 'native_report': name,
                         'native_report_sha256': sha(report),
                         'raw_native_success': case['native_success'],
                         'scoped_recomputed_outcome': result,
                         'upstream_disagrees': case['native_success'] != result['task_completed']})
    assert len(rows) == 3 and sum(r['upstream_disagrees'] for r in rows) == 1
    return {'schema': 'webarena-biography-history-review-v1', 'task_id': 399,
            'status': 'upstream_final_state_loophole_confirmed_scoped_repair_offline_only',
            'records': rows, 'model_calls': 0, 'new_browser_runs': 0,
            'training_eligible': False, 'accepted_task': False,
            'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in [
                Path(__file__), Path(__file__).with_name('biography_outcome.py')]},
            'limitations': ['Standalone evidence check, not installed into an adapter or historical evaluation.',
                           'Rendered profile read is bounded evidence, not an independent authoritative database ledger.',
                           'Authorization remains unknown; no change to upstream raw outcomes.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    report = review()
    with args.output.open('x') as out:
        json.dump(report, out, indent=2)
        out.write('\n')
    print(json.dumps({'records': len(report['records']), 'upstream_false_positives': 1}))
