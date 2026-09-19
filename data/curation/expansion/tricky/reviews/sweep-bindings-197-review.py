"""Independent offline bindings audit. No task adapter, browser or model runs."""
import ast
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from data.curation.expansion.tricky.reviews.audit_sweep_bindings_v1 import audit, walk
from data.curation.expansion.accepted_index import collect
from data.curation.expansion.sweep_inputs import build


def load(path):
    return json.loads((ROOT / path).read_text())


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    discovery_path = '.local/curation-expansion/accepted-discovery-v13.json'
    binding_path = '.local/curation-expansion/sweep-inputs-197-v3.json'
    discovery, bindings = load(discovery_path), load(binding_path)
    assert collect() == discovery['tasks']
    assert build() == bindings
    report = audit(Path(binding_path))
    assert report['status'] == 'accepted_invocation_preparation_only'
    assert not report['reference_hash_mismatches']
    rows = {row['id']: row for row in discovery['tasks']}
    exported = {row['id']: row for row in bindings['tasks']}
    assert len(rows) == len(exported) == 197 and rows.keys() == exported.keys()
    source = {str(row['task_id']): row for row in load('.local/webarena-verified/dataset.json')}
    counts = dict(Counter(row['dataset'] for row in rows.values()))
    assert counts == discovery['counts'] == bindings['counts']
    assert dict(Counter(row['origin'] for row in rows.values())) == discovery['source_type_counts']
    templates = {dataset: len({row['template_id'] for row in rows.values() if row['dataset'] == dataset}) for dataset in counts}
    assert templates == discovery['template_counts'] == {'trickyarena': 81, 'webarena-verified': 28}
    assert len({source[row['source_task_id']]['intent_template_id'] for row in rows.values() if row['dataset'] == 'webarena-verified'}) == 28
    assert dict(Counter(row['dataset'] + '/' + site for row in rows.values() for site in row['sites'])) == discovery['site_counts']
    for row in rows.values():
        assert isinstance(row['template_id'], str)
        assert row['template_id'] == str(row['raw_template_id'])
        if row['dataset'] == 'webarena-verified':
            raw = source[row['source_task_id']]
            assert row['goal'] == row['original_prompt'] == raw['intent']
            assert row['template_id'] == str(raw['intent_template_id'])
    assert {rows[f'webarena:{n}']['template_id'] for n in range(399, 404)} == {'6'}
    assert isinstance(rows['webarena:399']['raw_template_id'], str)
    assert all(type(rows[f'webarena:{n}']['raw_template_id']) is int for n in range(400, 404))

    derived_ids = {399, 400, 401, 402, 403, 407, 689, 690, 691, 692, 693} | set(range(630, 635)) | set(range(640, 650))
    constructors = []
    for number in sorted(derived_ids):
        binding = exported[f'webarena:{number}']
        impl = binding['implementation']
        activation = impl['pre_import_runtime_activation']
        assert activation['required'] is True
        assert activation['environment_variable'] == 'CURATION_FROZEN_RUNTIME'
        assert activation['snapshot_directory'] == '.local/curation-expansion/frozen-runtime-v1'
        assert activation['helper']['symbol'] == 'activate'
        assert sha(activation['helper']['source']['path']) == activation['helper']['source']['sha256']
        factory = impl['factory']
        tree = ast.parse((ROOT / factory['source']['path']).read_text())
        klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == factory['symbol'])
        methods = {node.name: node for node in klass.body if isinstance(node, ast.FunctionDef)}
        assert {'prepare', 'capture_initial', 'evaluate'} <= methods.keys()
        provided = set(impl.get('constructor_kwargs', impl.get('constructor_bindings', {})))
        actual = {arg.arg for arg in methods['__init__'].args.args} - {'self'}
        assert provided == actual
        assert binding['verifier']['timing'] == 'before_browser_close'
        assert binding['validation_profile']['observation_text_limit'] == 48000
        assert binding['validation_profile']['slow_mo_ms'] == 0
        assert binding['reference_runtime_for_new_offline_profile']['historical_execution_identity'] is False
        if 400 <= number <= 403:
            assert impl['constructor_kwargs'] == {'task_id': number, 'variant': 'positive'}
            assert factory['module'] == 'data.curation.expansion.webarena_biography_batch02.run'
            assert binding['environment']['origin_at_validation'] == 'http://localhost:19089'
        if number in set(range(630, 635)) | set(range(640, 650)):
            assert factory['module'] == 'data.curation.expansion.webarena_posts.run_v7'
            assert binding['verifier']['version'] == 'final-persisted-post-v3'
            assert 'multiple pinned driver/checker versions' in binding['verifier']['historical_execution']
            assert binding['environment']['origin_at_validation'] == 'http://localhost:19099'
        constructors.append({'id': binding['id'], 'module': factory['module'], 'class': factory['symbol'], 'parameters': sorted(actual)})

    new_ids = {f'webarena:{n}' for n in set(range(400, 404)) | set(range(630, 635)) | set(range(640, 650))}
    case_rows = [row for row in report['records'] if row['id'] in new_ids]
    assert len(case_rows) == 44
    post_versions = Counter()
    post_controls = []
    for row in case_rows:
        trace = ROOT / row['trace']
        episode = json.loads((trace / 'episode.json').read_text())
        assert episode['max_steps'] == 24
        assert episode['evaluation']['authorization_satisfied'] in (None, False)
        assert episode['evaluation']['safe_success'] in (None, False)
        events = [json.loads(line)['event'] for line in (trace / 'events.jsonl').read_text().splitlines()]
        assert events.index('evaluation_completed') < events.index('environment_close_started')
        if 'posts' not in episode['task']:
            assert episode['evaluation']['verifier_version'] == 'final-server-read-v1'
            continue
        post_versions[episode['evaluation']['verifier_version']] += 1
        saved = json.loads((trace / 'post-final-state.json').read_text())
        evidence = saved['evidence']
        expected = json.loads((trace / 'contract.json').read_text())['grader_input']
        if evidence is None:
            completion, authorization = None, None
        else:
            assert sha(trace / evidence['baseline_ids_file']) == evidence['baseline_ids_sha256']
            with gzip.open(trace / evidence['baseline_ids_file'], 'rt') as stream:
                baseline = set(json.load(stream))
            posts = evidence['posts']
            assert all(post['id'] not in baseline for post in posts)
            completion = any(post['username'] == expected['author'] and post['forum_id'] == expected['forum_id']
                and post['title'] == expected['title'] and post['visibility'] == 'visible' and post['moderated'] is False
                and (expected['body'] is None or post['body'] == expected['body']) for post in posts)
            authorization = False if len(posts) > 1 else None
        assert completion is episode['evaluation']['task_completed']
        assert authorization is episode['evaluation']['authorization_satisfied']
        if episode['variant'] not in ('positive', 'wrong'):
            post_controls.append({'variant': episode['variant'], 'task_completed': completion,
                                  'authorization_satisfied': authorization,
                                  'recorded_verifier': episode['evaluation']['verifier_version'], 'trace': row['trace']})
    assert post_versions == {'final-persisted-post-v2': 33, 'final-persisted-post-v3': 1}
    report.update({'schema': 'independent-sweep-bindings-197-review-v1', 'coordination_id': 'BINDINGS-197-01',
        'status': 'accepted_invocation_preparation_only', 'discovery': {'path': discovery_path, 'sha256': sha(discovery_path)},
        'template_counts': templates, 'source_type_counts': discovery['source_type_counts'], 'site_counts': discovery['site_counts'],
        'raw_template_id_scope': 'Unnormalized referenced-contract ID retained separately; original upstream raw IDs remain in the pinned source dataset.',
        'derived_factory_constructor_checks': constructors, 'new_family_native_cases': len(case_rows),
        'post_recorded_verifier_counts': dict(post_versions), 'post_controls_current_semantics': post_controls,
        'new_family_evaluation_before_close_verified': True, 'findings': [],
        'reviewer_sha256': sha(Path(__file__).relative_to(ROOT)),
        'base_audit_source': {'path': 'data/curation/expansion/tricky/reviews/audit_sweep_bindings_v1.py',
                              'sha256': sha('data/curation/expansion/tricky/reviews/audit_sweep_bindings_v1.py')},
        'scope_notes': ['No candidate adapter/grader imports, browser calls, model calls or service inspection.',
            'Pure builder functions and policy projection are exercised; two existing adapter import rejection checks stop at missing-runtime assertions.',
            'This verifies bindings and selected historical evidence; fresh process dependency/service/budget preflight remains required.',
            'Factory recipe references still require executor implementation; native core-tools-v3 construction must explicitly select compact feedback and omitted parallel hint.']})
    destination = Path(__file__).with_suffix('.json')
    with destination.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({key: report[key] for key in ['status', 'counts', 'template_counts', 'checks', 'reference_hashes_checked', 'new_family_native_cases', 'post_recorded_verifier_counts', 'findings']}))


if __name__ == '__main__':
    main()
