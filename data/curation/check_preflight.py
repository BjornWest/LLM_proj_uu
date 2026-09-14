"""Validate curation references and unknown labels; never run a grader or browser.

--fetch restores only missing pinned site sources (155,439 bytes in this catalog).
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).resolve().parent


def read(name):
    return json.loads((DATA / name).read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    catalog = read('preflight_source_hashes.json')['sources']
    sources = {r['path']: r for r in catalog}
    require(len(sources) == len(catalog), 'Duplicate source path')
    for record in catalog:
        path = ROOT / record['local_cache']
        require(path.resolve().is_relative_to(ROOT / '.research/tricky-preflight'),
                'Source cache path outside dedicated directory')
        if not path.exists() and args.fetch:
            expected_url = (f"https://raw.githubusercontent.com/{record['repository']}/"
                            f"{record['revision']}/{record['path']}")
            require(record['raw_url'] == expected_url, 'Unexpected source URL')
            with urlopen(expected_url, timeout=30) as response:
                raw = response.read(1_000_001)
            require(len(raw) <= 1_000_000 and len(raw) == record['bytes'], 'Source size mismatch')
            require(hashlib.sha256(raw).hexdigest() == record['sha256'], 'Fetched source hash mismatch')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        require(path.exists(), f'Missing {path}; use --fetch to restore small source files')
        require(sha(path) == record['sha256'], f'Source changed: {path}')

    manifest = read('pilot_manifest.json')
    candidates = {c['id']: c for c in manifest['candidates']}
    defects = {d['id']: d for d in read('defect_evidence.json')['defects']}
    spec = read('tricky_preflight.json')
    require(spec['provenance']['manifest_sha256'] == sha(DATA / 'pilot_manifest.json'),
            'Manifest changed: review preflight source identity and refresh its fingerprint')
    for family in spec['families']:
        candidate = candidates[family['candidate_id']]
        require(all(candidate[k] == v for k, v in family['source_key'].items()), 'Source identity mismatch')
        for key in ['environment_revision', 'pair_id', 'condition_ids']:
            require(candidate[key] == family[key], f'{key} mismatch')
        require(set(family['defect_evidence_ids']) <= defects.keys(), 'Unknown defect ID')
        for reference in family['source_facts']['source_refs']:
            source = sources[reference['path']]
            lines = (ROOT / source['local_cache']).read_text().splitlines()
            require(1 <= reference['line'] <= len(lines), 'Invalid source line')
    cards = spec['cases']
    by_id = {c['id']: c for c in cards}
    require(len(by_id) == len(cards), 'Duplicate case ID')
    for case in cards + spec['additional_regressions']:
        require(case['candidate_id'] in candidates, 'Unknown candidate')
        require(case['execution_status'] == 'not_run', 'Observed execution needs separate audit')
        require(all(v is None for v in case['observed_outcomes'].values()), 'Observed labels must remain unknown')
        if case.get('duplicate_of'):
            require(case['duplicate_of'] in by_id, 'Missing duplicate target')
        expected = case.get('proposed_expected', {})
        if case.get('status') == 'not_applicable':
            require(all(v is None for v in expected.values()), 'Inapplicable case has outcome assertions')
        if expected.get('safe_success') is True:
            require(expected['task_complete'] is True and expected['authorization_satisfied'] is True,
                    'Safe success lacks completion or authorization')
        if expected.get('injection_exposed') is False:
            require(expected['avoidance'] is None, 'Unexposed case falsely labeled avoided')
    for defect in defects.values():
        require(defect['browser_reproduction'] is None and defect['grader_validation'] is None,
                'This check covers source-only defects')
        for reference in defect['references']:
            if reference['local_cache']:
                path = ROOT / reference['local_cache']
                require(sha(path) == reference['sha256'], f'Evidence hash mismatch: {path}')
                require(1 <= reference['line'] <= len(path.read_text().splitlines()), 'Invalid defect line')
    for case in read('ikea_preflight.json')['cases']:
        require(case['execution_status'] == 'not_run', 'IKEA case unexpectedly run')
        for key in ['observed_callbacks', 'observed_selected_radio', 'observed_injection_exposed',
                    'task_complete', 'authorization_satisfied', 'actual_protection_charge', 'safe_success']:
            require(case[key] is None, f'IKEA observed {key} must remain unknown')
    require(all(c['evaluation_ready'] is False and c['training_eligible'] is False
                and all(v is None for v in c['outcomes'].values()) for c in candidates.values()),
            'Pilot outcome/readiness was promoted')
    print(f'Validated {len(catalog)} source hashes, {len(spec["families"])} family contracts, '
          f'{len(cards)} coverage cards, {len(spec["additional_regressions"])} extra regressions, '
          f'{len(read("ikea_preflight.json")["cases"])} IKEA cases and {len(defects)} defect records.')
    print('Static integrity only; no browser, grader, model or training validation.')


if __name__ == '__main__':
    main()
