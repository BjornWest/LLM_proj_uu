"""Replay portable HTML/state collectors on saved accepted cases; no live requests.

This checks parsing/checker parity only, not host SQL/proxy/reset correctness.
Every new output is separate; source traces are read-only.
"""
import argparse
import gzip
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from .bindings import ROOT, digest, load_registry
from .context import RuntimeContext
from .tasks import make_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--registry', type=Path, default=ROOT / '.local/curation-expansion/worker-registry-v2.json')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    registry = {r['id']: r for r in load_registry(args.registry)['tasks']}
    results = []
    for family in ('biography', 'votes', 'wishlist', 'posts'):
        review = ROOT / ('data/curation/expansion/webarena-' + family + '-independent-review.json')
        cases = json.loads(review.read_text())['cases']
        for index, case in enumerate(cases):
            task_id = 'webarena:' + str(case.get('task_id', 399))
            if task_id not in registry:
                continue
            trace = ROOT / case['trace']
            filename = 'vote-final-state.json' if family == 'votes' else ('post-final-state.json' if family == 'posts' else family + '-final-state.json')
            if family == 'biography':
                entry_path = trace / 'privileged-final-profile-read.json'
                if not entry_path.exists():
                    continue
                saved = json.loads(entry_path.read_text())
                origin_parts = urlsplit(saved['request']['url'])
            else:
                saved = json.loads((trace / filename).read_text())
                evidence = saved['evidence']
                if evidence is None:
                    continue
                url = (evidence.get('response_url') if family == 'votes' else
                       evidence['page']['url'] if family == 'wishlist' else
                       evidence['reads'][0]['response_url'] if evidence['reads'] else None)
                if url is None:
                    continue
                origin_parts = urlsplit(url)
            origin = origin_parts.scheme + '://' + origin_parts.netloc
            context = RuntimeContext(args.registry, origins={'shopping': origin, 'reddit': origin})
            row = registry[task_id]
            task = make_task(task_id, runtime_context=context, revision=row['revision'])
            task.trace = SimpleNamespace(directory=trace)
            read_hashes = {}
            def read_html(path, name):
                file = trace / name
                read_hashes[name] = digest(file)
                return SimpleNamespace(url=origin + path, status=200), file.read_text(), digest(file)
            task.get_html = read_html
            if family == 'biography':
                text = saved['response']['content']['text']
                har = trace / 'network.har'
                if not har.exists():
                    har = trace.parents[1] / 'network.har'
                read_hashes[str(har)] = digest(har)
                task.requests = [{'method': e['request']['method'], 'url': e['request']['url']}
                                 for e in json.loads(har.read_text())['log']['entries']]
                task.get_html = lambda path, name: (SimpleNamespace(url=saved['request']['url'], status=saved['response']['status']), text, digest(entry_path))
                expected = case['recomputed_completion']
            elif family == 'wishlist':
                task.initial = json.loads((trace / 'baseline.json').read_text())
                task.read_state = lambda *a, **k: evidence['database']
                expected = case['task_completed']
            elif family == 'votes':
                task.read_state = lambda *a, **k: evidence['db']
                expected = case['task_completed']
            else:
                task.baseline_file = trace / 'post-baseline-ids.json.gz'
                with gzip.open(task.baseline_file, 'rt') as stream:
                    task.baseline = json.load(stream)
                task.read_state = lambda *a, **k: evidence['posts']
                expected = case['task_completed']
            value, _ = getattr(task, '_grade_' + family)(None)
            passed = value['task_completed'] is expected
            if 'authorization_satisfied' in case:
                passed &= value.get('authorization_satisfied') is case['authorization_satisfied']
            results.append({'task_id': task_id, 'family': family,
                'case': case.get('variant', case.get('case')), 'passed': passed,
                'trace': str(trace.relative_to(ROOT)), 'result': value, 'expected_completion': expected,
                'saved_HTML_sha256': read_hashes, 'review_sha256': digest(review)})
    report = {'schema': 'expanded-collector-saved-replay-v1', 'cases': results,
              'passed': bool(results) and all(r['passed'] for r in results), 'model_calls': 0,
              'new_browser_runs': 0, 'scope': 'Saved HTML/state parsing plus existing pure checker parity; not live state/proxy/reset acceptance',
              'source_sha256': {p.name: digest(p) for p in Path(__file__).parent.glob('*.py')}}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'cases': len(results), 'passed': report['passed'],
                      'failures': [(r['task_id'], r['case']) for r in results if not r['passed']]}))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
