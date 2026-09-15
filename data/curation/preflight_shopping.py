"""Read-only P07 current-source/build checks and replay of saved scripted evidence."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from intent_browser.tricky import REV, TrickyTask, verify_p07


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preflight():
    build_dir = ROOT / '.local/tricky'
    build = json.loads((build_dir / 'build.json').read_text())
    config = json.loads((ROOT / 'config/tricky_p07_validation.json').read_text())
    checks = {
        'build_matches_scripted_validation': digest(build_dir/'build.json') == config['build_sha256'],
        'adapter_matches_scripted_validation': digest(ROOT/'intent_browser/tricky.py') == config['adapter_sha256'],
        'manifest_matches_scripted_validation': digest(ROOT/'data/curation/pilot_manifest.json') == config['manifest_sha256'],
        'source_revision_matches': build['source']['revision'] == REV,
        'catalog_matches': digest(build_dir/'catalog.json') == build['catalog_sha256'],
        'build_script_matches': digest(ROOT/'environments/tricky/build.mjs') == build['build_script_sha256'],
        'dependency_lock_matches': digest(ROOT/'environments/tricky/package-lock.json') == build['package_lock_sha256'],
        'entry_matches': digest(build_dir/'site/main.jsx') == build['entry_sha256'],
        'all_dist_assets_match': all(digest(build_dir/'dist'/p) == h for p,h in build['dist_sha256'].items()),
    }
    # Verify cached raw source and recorded instrumentation without rebuilding.
    source_checks, patched_checks = [], []
    for name,record in build['source']['files'].items():
        raw = (build_dir/'upstream'/name).read_bytes()
        source_checks.append(hashlib.sha256(raw).hexdigest() == record['sha256'] and
            hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest() == record['git_blob'])
        changed = raw
        for patch in build['patches']:
            if patch['file'] == name:
                before, after = patch['before'].encode(), patch['after'].encode()
                if changed.count(before) != 1:
                    raise ValueError('Recorded instrumentation anchor mismatch')
                changed = changed.replace(before, after)
        patched_checks.append(changed == (build_dir/'site'/name).read_bytes())
    checks['cached_raw_source_matches'] = all(source_checks)
    checks['derived_source_matches_recorded_patches'] = all(patched_checks)
    catalog = {str(p['id']):p for p in json.loads((build_dir/'catalog.json').read_text())}
    replay_path = ROOT / '.local/preflight/tricky-p07-validation.json'
    recorded_replays = {c['case']: c for c in json.loads(replay_path.read_text())['cases']}
    cases = []
    for case in config['cases']:
        directory = ROOT/case['episode']
        final = json.loads((directory/'tricky-final-state.json').read_text())
        saved = json.loads((directory/'tricky-verifier-evidence.json').read_text())
        evaluation = json.loads((directory/'evaluation.json').read_text())
        replay = verify_p07(final['orders'], final['browser']['cart'], catalog,
            exposed=final['browser']['warranty_inserted'] and final['browser']['warranty_delivered_before_commit'])
        ok = (digest(directory/'tricky-journal.jsonl') == case['journal_sha256'] and
              digest(directory/'tricky-final-state.json') == case['final_state_sha256'] and
              replay == recorded_replays[case['case']]['replayed_contract'] and
              all(replay[k] is v for k,v in case['expected'].items()) and
              evaluation['technical_error'] is None)
        differences = {k: {'raw':saved.get(k), 'current_replay':replay.get(k)}
                       for k in set(saved)|set(replay) if saved.get(k) != replay.get(k)}
        cases.append({'case':case['case'], 'episode':case['episode'], 'passed':ok,
                      'raw_vs_current_replay_differences':differences,
                      'current_replay_matches_recorded_replay':replay == recorded_replays[case['case']]['replayed_contract'],
                      'journal_sha256':case['journal_sha256'], 'final_state_sha256':case['final_state_sha256']})
    checks['all_12_scripted_cases_replay'] = len(cases) == 12 and all(c['passed'] for c in cases)
    tasks = [TrickyTask(condition=c) for c in ('no_added_injection','one_selected_injection')]
    checks['pair_same_policy_goal'] = tasks[0].policy_goal == tasks[1].policy_goal
    checks['curation_readiness_not_promoted'] = all(t.candidate.grader_input['evaluation_ready'] is False for t in tasks)
    result = {'status':'passed' if all(checks.values()) else 'failed', 'checks':checks, 'cases':cases,
        'recorded_replay_report_sha256':digest(replay_path),
        'historical_difference_note':'Two old negative traces additionally label an empty final cart unrequested_final_cart_items; current and recorded replay omit this redundant effect. All expected verdicts match; old evidence is not rewritten.',
        'build_sha256':digest(build_dir/'build.json'), 'manifest_sha256':config['manifest_sha256'],
        'adapter_sha256':config['adapter_sha256'], 'source_revision':REV,
        'source_file_count':len(source_checks), 'dist_asset_count':len(build['dist_sha256']),
        'policy_input':tasks[0].candidate.policy_input, 'source_key':list(tasks[0].candidate.source_key),
        'training_eligible':False, 'curation_ready':False, 'new_browser_calls':0, 'new_model_calls':0,
        'scope':'Saved scripted evidence replay and current disk/build integrity, not fresh scripted browser validation.'}
    if result['status'] != 'passed':
        raise ValueError(json.dumps(result))
    return result


if __name__ == '__main__':
    print(json.dumps(preflight(),indent=2))
