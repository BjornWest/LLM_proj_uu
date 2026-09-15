"""Local integrity and saved-evidence preflight; no browser or model calls."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from intent_browser.tricky_authorized import REV, load_contract
from scripts.verify_authorized_warranty import replay


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preflight():
    base = ROOT/'.local/tricky'
    build = json.loads((base/'build.json').read_text())
    validation = json.loads((ROOT/'config/authorized_warranty_validation.json').read_text())
    review = json.loads((ROOT/'data/curation/dev_w01_saved_artifact_review.json').read_text())
    contract = load_contract(ROOT/'config/authorized_warranty_contract.json')
    checks = {
        'source_revision': build['source']['revision'] == REV,
        'catalog': sha(base/'catalog.json') == build['catalog_sha256'],
        'build_script': sha(ROOT/'environments/tricky/build.mjs') == build['build_script_sha256'],
        'lockfile': sha(ROOT/'environments/tricky/package-lock.json') == build['package_lock_sha256'],
        'entry': sha(base/'site/main.jsx') == build['entry_sha256'],
        'assets': all(sha(base/'dist'/p) == h for p,h in build['dist_sha256'].items()),
        'verifier_sources': all(sha(ROOT/p) == h for p,h in validation['source_sha256'].items()),
        'report_parts': all(sha(ROOT/p) == h for p,h in validation['report_parts'].items()),
        'independent_review': review['all_passed'] and review['validation_sha256'] == sha(ROOT/'config/authorized_warranty_validation.json'),
        'development_only': contract['training_eligible'] is False and contract['curation_readiness'] is False,
    }
    raw_checks, patched_checks = [], []
    for name, record in build['source']['files'].items():
        raw = (base/'upstream'/name).read_bytes()
        raw_checks.append(hashlib.sha256(raw).hexdigest() == record['sha256'] and
            hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest() == record['git_blob'])
        changed = raw
        for patch in build['patches']:
            if patch['file'] == name:
                before, after = patch['before'].encode(), patch['after'].encode()
                if changed.count(before) != 1:
                    raise ValueError('Recorded patch anchor mismatch')
                changed = changed.replace(before, after)
        patched_checks.append(changed == (base/'site'/name).read_bytes())
    checks['raw_source'] = all(raw_checks)
    checks['derived_source'] = all(patched_checks)
    catalog = {str(p['id']):p for p in json.loads((base/'catalog.json').read_text())}
    cases = []
    for case in validation['cases']:
        directory = ROOT/case['episode']
        artifacts_match = all(sha(directory/p) == h for p,h in case['artifact_sha256'].items())
        replayed = replay(directory, catalog)
        metadata = json.loads((directory/'metadata.json').read_text())
        runtime_match = all(metadata['runtime']['source_sha256'].get(name) == sha(ROOT/'intent_browser'/name)
            for name in ('runner.py','backend.py','actions.py','trace.py','evaluation.py','tricky.py','tricky_authorized.py'))
        result = {'case':case['case'], 'episode':case['episode'],
            'artifacts_match':artifacts_match, 'executed_runtime_matches':runtime_match,
            'replay_matches':replayed == case['replay'],
            'build_matches':sha(directory/'tricky-build.json') == sha(base/'build.json'),
            'expected_outcomes_match':all(replayed['replayed_contract'][k] is v for k,v in case['expected'].items())}
        result['passed'] = all(v for k,v in result.items() if k not in ('case','episode'))
        cases.append(result)
    checks['six_cases'] = (len(cases) == 6 and {c['case'] for c in cases} ==
        {'keep','remove','abandon','wrong-product','duplicate-then-reload','suppressed'} and all(c['passed'] for c in cases))
    if not all(checks.values()):
        raise ValueError('Authorized fixture preflight failed: '+json.dumps(checks))
    return {'status':'passed','checks':checks,'cases':cases,'source_file_count':len(raw_checks),
        'asset_count':len(build['dist_sha256']),'source_revision':REV,
        'policy_input':contract['policy_input'],'contract_sha256':sha(ROOT/'config/authorized_warranty_contract.json'),
        'training_eligible':False,'curation_ready':False,'browser_calls':0,'model_calls':0,
        'scope':'Current fixture integrity and saved scripted replay; no new browser validation.'}


if __name__ == '__main__':
    print(json.dumps(preflight(), indent=2))
