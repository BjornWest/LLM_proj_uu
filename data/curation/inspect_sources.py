"""Inspect cached, pinned source data without running upstream code or agents.

Usage: python3 data/curation/inspect_sources.py
Raw source cache: .research/dataset-audit (not a training dataset).
All emitted readiness/quality flags are static triage, not environment results.
"""

import argparse
import ast
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / '.research/dataset-audit'
OUT = Path(__file__).resolve().parent
SUS_REV = '814cf5f7a55cc2e683a0f75519a0a45cdf3791b0'
LITE_REV = '4ed5d744d8e9fb53abb7057ba7c5664feb2a67e4'
SITE_REV = '8201821fb64a5075f50b015f99653881ab09a030'


def norm(s):
    return ' '.join(s.split()).casefold()


def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def write_json(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def literal(node, names):
    """Resolve only literal strings, names and f-strings in enum declarations."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return names[node.id]
    if isinstance(node, ast.JoinedStr):
        return ''.join(str(literal(v.value, names)) if isinstance(v, ast.FormattedValue)
                       else v.value for v in node.values)
    raise ValueError(f'Unsupported static expression: {ast.dump(node)}')


def inspect_sus():
    raw = CACHE / 'susbench/task-list.csv'
    js = (CACHE / 'susbench/injection-mapping.js').read_text()
    # Pinned source uses exactly this top-level indentation/key spelling.
    keys = {m.group(1): js.count('\n', 0, m.start()) + 1
            for m in re.finditer(r'^  ["\']([^"\']+)["\']\s*:\s*\{', js, re.M)}
    mapping = {'false hierarachy': 'false_hierarchy', 'false hierarchy': 'false_hierarchy',
               'disguised ad': 'disguised_ad'}
    rows = []
    duplicate_groups = defaultdict(list)
    with raw.open() as f:
        for source in csv.DictReader(f):
            goal = source['task_description'].strip()
            flags = ['live_site_unvalidated', 'reuse_terms_unspecified', 'no_task_state_verifier']
            if re.search(r'\b(next|tomorrow|this week|today|latest|default shipping date)\b', goal, re.I):
                flags.append('time_or_version_dependent')
            if re.search(r'\b(pretty|best value|good reviews|around \$|learn more|biased)\b', goal, re.I):
                flags.append('subjective_or_underspecified')
            if re.search(r'\b(under|over|less than|cheapest|largest|highest|most|available)\b', goal, re.I):
                flags.append('requires_catalog_snapshot_or_comparison_rule')
            if re.search(r'\b(without|no protection|no beans|deselect|no preselected|without email)\b', goal, re.I):
                flags.append('explicit_negative_constraint')
            if source['injection_code'] not in keys:
                flags.append('injection_key_not_found_by_static_scan')
            if source['injection_code'] == 'ikea_preselect':
                flags.append('manual_label_mismatch_paid_plan_marked_avoided')
            if source['injection_code'] in {'ikea_preselect', 'amz_preselect', 'apple_preselect_final_cut_pro'}:
                flags.append('manual_susceptibility_callback_at_injection_time')
            if source['injection_code'] == 'amz_preselect':
                flags.append('manual_null_element_listener_risk')
            terminal = ('cart' if re.search(r'add.{0,45}(cart|bag)', goal, re.I)
                        else 'review_page' if 'review page' in goal
                        else 'purchase_or_booking_unspecified' if re.search(r'\b(buy|book|order|reserve)\b', goal, re.I)
                        else 'information_or_other')
            row = {'source': 'susbench', 'source_id': source['task_id'],
                   'raw_source': dict(source),
                   'record_id': 'susbench:' + source['task_id'], 'source_revision': SUS_REV,
                   'website': source['website'], 'original_goal': goal,
                   'injection_code': source['injection_code'],
                   'pattern_original': source['dark_pattern_type'],
                   'pattern': mapping.get(source['dark_pattern_type'].casefold(),
                                          source['dark_pattern_type'].casefold().replace(' ', '_').replace('-', '_')),
                   'terminal_scope_lexical': terminal, 'flags': flags,
                   'prompt_group': digest(norm(goal)),
                   'injection_group': source['injection_code'],
                   'upstream_completed_bookkeeping': source['completed'],
                   'injection_line': keys.get(source['injection_code']),
                   'source_url': f'https://github.com/SusBench-creator/SusBench/blob/{SUS_REV}/task-list.csv'}
            rows.append(row)
            duplicate_groups[norm(goal)].append(source['task_id'])
    assert len({r['source_id'] for r in rows}) == len(rows), 'Duplicate source IDs'
    return rows, {'rows': len(rows), 'websites': len({r['website'] for r in rows}),
                  'injection_codes_used': len({r['injection_code'] for r in rows}),
                  'mapping_keys_detected': len(keys),
                  'patterns_normalized': dict(Counter(r['pattern'] for r in rows)),
                  'exact_normalized_prompt_duplicate_groups': [v for v in duplicate_groups.values() if len(v) > 1],
                  'flags': dict(Counter(f for r in rows for f in r['flags']))}


def inspect_lite():
    base = CACHE / 'liteagent'
    names, enums = {}, {}
    for node in ast.parse((base / 'evaluation/enums.py').read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            names[node.targets[0].id] = literal(node.value, names)
        elif isinstance(node, ast.ClassDef) and node.name.endswith('Task'):
            for item in node.body:
                if isinstance(item, ast.Assign):
                    enums[node.name + '.' + item.targets[0].id] = literal(item.value, names)
    lookup = {norm(v): k for k, v in enums.items()}
    pattern_maps = {}
    for node in ast.parse((base / 'evaluation/consts.py').read_text()).body:
        if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call) and node.targets[0].id.endswith('_dark_patterns')):
            pattern_maps[node.targets[0].id] = {v: k for k, v in ast.literal_eval(node.value.args[0]).items()}
    domains = {'shopping': 'shop', 'news': 'news', 'spotify': 'spotify', 'health': 'health', 'linkedin': 'linkedin'}
    dp_coverage = defaultdict(set)
    for node in ast.walk(ast.parse((base / 'evaluation/dp_checks.py').read_text())):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if (isinstance(key, ast.Subscript) and isinstance(key.value, ast.Attribute)
                        and isinstance(key.value.value, ast.Name) and key.value.attr == 'inv'):
                    map_name = key.value.value.id
                    domain = domains[map_name.removesuffix('_dark_patterns')]
                    dp_coverage[domain].add(pattern_maps[map_name][ast.literal_eval(key.slice)])
    checks = {}
    for node in ast.walk(ast.parse((base / 'evaluation/task_checks.py').read_text())):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Attribute) and isinstance(key.value, ast.Name) and key.value.id.endswith('Task'):
                    checks[key.value.id + '.' + key.attr] = sorted({
                        n.attr for n in ast.walk(value) if isinstance(n, ast.Attribute)
                        and isinstance(n.value, ast.Name) and n.value.id == 'CheckTypes'})
    records = {}
    occurrences = 0
    files = sorted((base / 'data/prompts').rglob('*.txt'))
    for path in files:
        lines = path.read_text().splitlines()
        url = lines[0].strip()
        parsed = urlsplit(url if '://' in url else 'https://' + url)
        domain = parsed.path.strip('/').split('/')[0]
        patterns = sorted(filter(None, parse_qs(parsed.query).get('dp', [''])[0].split('_')))
        for lineno, goal in enumerate(lines[1:], 2):
            goal = goal.strip()
            if not goal:
                continue
            occurrences += 1
            stable = digest(parsed.path + '?' + '_'.join(patterns) + '\n' + norm(goal))
            member = lookup.get(norm(goal)) or lookup.get(norm(goal + ' ' + names['prompt_helper']))
            hint = 'none'
            if member:
                if '_SPECIFIC' in member:
                    hint = 'specific_constraint_or_solution_hint'
                elif re.search(r'_(GEN|INTER)\d', member):
                    hint = 'general_safety_warning'
            flags = ['site_not_run_in_this_audit', 'reuse_terms_unspecified', 'no_backend_state_verifier']
            if not member or member not in checks:
                flags.append('no_task_checker_static_match')
            if len(patterns) > 1:
                flags.append('multiple_patterns_confounded')
            missing_dp = [p for p in patterns if p not in dp_coverage[domain]]
            if missing_dp:
                flags.append('missing_pattern_checker_static_mapping')
            if domain == 'spotify' and 'ds' in patterns:
                flags.append('manual_privacy_click_label_mismatch')
            if domain == 'health' and 'cs' in patterns:
                flags.append('manual_privacy_checker_omits_location')
            if domain == 'spotify' and 'am' in patterns:
                flags.append('manual_wrong_plan_susceptibility_coverage_incomplete')
            if hint != 'none':
                flags.append('prompt_ablation_not_independent_task')
            if 'SCRATCHPAD_SUBSTRING_MATCH' in checks.get(member, []):
                flags.append('answer_substring_scoring')
            if 'download' in goal.casefold():
                flags.append('requires_download_outcome_support')
            if re.search(r'best value|biased', goal, re.I):
                flags.append('subjective_or_underspecified')
            if re.search(r'click.*more options|choosing|by removing|then click|toggle off', goal, re.I):
                flags.append('possible_procedural_hint')
            rel = str(path.relative_to(base))
            reference = {'path': rel, 'line': lineno,
                         'raw_prompt_line': lines[lineno - 1], 'raw_url_line': lines[0],
                         'url': f'https://github.com/LiteAgent/liteagent/blob/{LITE_REV}/{rel}#L{lineno}'}
            if stable in records:
                records[stable]['occurrences'].append(reference)
                continue
            family = re.sub(r'_(?:GEN|INTER|SPECIFIC)\d.*$', '', member or digest(norm(goal)))
            records[stable] = {'source': 'trickyarena', 'record_id': 'trickyarena:' + stable,
                'source_revision': LITE_REV, 'original_url': url, 'site': domain,
                'original_goal': goal, 'patterns': patterns, 'checker_enum': member,
                'task_family': family, 'prompt_group': digest(norm(goal)), 'hint_condition': hint,
                'task_check_types': checks.get(member, []), 'missing_pattern_checkers': missing_dp,
                'flags': flags, 'occurrences': [reference]}
    rows = list(records.values())
    return rows, {'prompt_files': len(files), 'prompt_occurrences': occurrences,
                  'unique_url_prompt_conditions': len(rows),
                  'unique_normalized_prompts': len({r['prompt_group'] for r in rows}),
                  'sites': dict(Counter(r['site'] for r in rows)),
                  'pattern_count_conditions': dict(Counter(len(r['patterns']) for r in rows)),
                  'hint_conditions': dict(Counter(r['hint_condition'] for r in rows)),
                  'missing_pattern_checkers': dict(Counter(p for r in rows for p in r['missing_pattern_checkers'])),
                  'flags': dict(Counter(f for r in rows for f in r['flags'])),
                  'coverage_method': 'Static enum match with collector helper suffix, whitespace normalized; does not execute evaluator parser.'}


def fetch_sources():
    """Restore the small ignored cache from pinned URLs and verified hashes."""
    hashes = json.loads((OUT / 'source_hashes.json').read_text())
    for name, expected in hashes.items():
        path = CACHE / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            continue
        dataset, rel = name.split('/', 1)
        if dataset == 'susbench':
            rel = rel if rel == 'task-list.csv' else 'dark-pattern-browser-extension/' + rel
            url = f'https://raw.githubusercontent.com/SusBench-creator/SusBench/{SUS_REV}/{rel}'
        elif dataset == 'liteagent':
            url = f'https://raw.githubusercontent.com/LiteAgent/liteagent/{LITE_REV}/{rel}'
        else:
            raise ValueError(f'Unknown source {dataset}')
        with urlopen(url, timeout=20) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f'Source size/hash mismatch: {name}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def build_pilot(rows):
    review = json.loads((OUT / 'pilot_review.json').read_text())
    by_id = {r['record_id']: r for r in rows}
    result = []
    policy_projection = []
    for candidate in review['candidates']:
        source = by_id[candidate['source_record']]
        enriched = {**candidate, 'source_revision': source['source_revision'],
                    'original_goal': source['original_goal'],
                    'source_flags': source['flags'], 'training_eligible': False,
                    'evaluation_ready': False, 'split': 'development_pilot'}
        enriched['pair_id'] = f'intent-pilot-v1:{candidate["id"]}'
        enriched['condition_ids'] = {
            condition: enriched['pair_id'] + ':' + condition for condition in review['protocol']['conditions']}
        enriched['source'] = source['source']
        enriched['source_task_id'] = source.get('source_id', source.get('checker_enum'))
        enriched['original_prompt'] = (source['raw_source']['task_description'] if source['source'] == 'susbench'
                                       else source['occurrences'][0]['raw_prompt_line'])
        enriched['family'] = source.get('task_family', source.get('injection_group'))
        enriched['split_group_tags'] = [source['source'] + ':prompt:' + source['prompt_group'],
                                         source['source'] + ':family:' + enriched['family']]
        if source['source'] == 'susbench':
            enriched['split_group_tags'].append('susbench:pattern:' + source['pattern'])
        enriched['policy_input'] = {'goal': candidate['proposed_goal']}
        enriched['authorization_constraints'] = {
            'explicitly_authorized_extras': candidate['explicitly_authorized_extras'],
            'forbidden_effects': candidate['forbidden_effects'],
            'interpretation_status': 'proposed project contract; see changes_from_source'}
        enriched['proposed_grader'] = {
            'status': 'requirements only; no grader implementation or runtime validation',
            'expected_state': enriched.pop('expected_state'),
            'additional_preconditions': enriched.pop('extra_preconditions'),
            'source_review': enriched.pop('source_review'),
            'defect_evidence_ids': candidate['defect_evidence_ids']}
        enriched['outcomes'] = dict.fromkeys([
            'task_complete', 'authorization_satisfied', 'injection_exposed', 'avoidance',
            'safe_success', 'technical_failure', 'raw_upstream_result', 'evidence'])
        enriched['execution_status'] = 'not_run'
        enriched['license'] = {
            'spdx': None, 'status': 'no root license found in inspected source release',
            'references': [f'https://github.com/{"SusBench-creator/SusBench" if source["source"] == "susbench" else "LiteAgent/liteagent"}/tree/{source["source_revision"]}']}
        if source['source'] == 'susbench':
            enriched['raw_source'] = source['raw_source']
            enriched['upstream_verifier'] = {
                'type': 'client_extension_avoidance_callbacks',
                'task_state_coverage': None,
                'coverage_status': 'reaction to injected pattern only; task/authorization not established',
                'references': [f'https://github.com/SusBench-creator/SusBench/blob/{SUS_REV}/dark-pattern-browser-extension/injection-mapping.js#L{source["injection_line"]}'],
                'raw_avoidance': None,
                'completed_bookkeeping': source['raw_source']['completed']}
            enriched['environment_revision'] = None
            enriched.update(source_url=source['source_url'], injection_code=source['injection_code'],
                            injection_line=source['injection_line'], website=source['website'],
                            split_group=source['injection_group'])
        else:
            assert len(source['patterns']) == 1, 'Pilot must isolate a single injected pattern'
            clean = [r for r in rows if r['source'] == 'trickyarena' and not r['patterns']
                     and r['checker_enum'] == source['checker_enum'] and r['site'] == source['site']]
            assert clean, f'No matched no-injection task for {candidate["id"]}'
            enriched['raw_source'] = {'prompt_occurrences': source['occurrences'],
                                      'clean_prompt_occurrences': [o for r in clean for o in r['occurrences']]}
            enriched['upstream_verifier'] = {
                'type': 'client_dom_event_log_and_optional_answer_substring',
                'task_check_types': source['task_check_types'],
                'pattern_checks_present': [p for p in source['patterns'] if p not in source['missing_pattern_checkers']],
                'pattern_checks_missing': source['missing_pattern_checkers'],
                'coverage_status': 'static mapping present does not establish semantic correctness',
                'references': [f'https://github.com/LiteAgent/liteagent/blob/{LITE_REV}/evaluation/{name}.py' for name in ['task_checks', 'dp_checks']],
                'raw_task_correct': None, 'raw_susceptibility': None}
            enriched['environment_revision'] = SITE_REV
            enriched['license']['references'].append(f'https://github.com/devinat1/agenttrickydps/tree/{SITE_REV}')
            enriched.update(source_url=source['occurrences'][0]['url'],
                            injected_url=source['original_url'],
                            clean_source_records=[r['record_id'] for r in clean],
                            clean_url=clean[0]['original_url'], checker_enum=source['checker_enum'],
                            patterns=source['patterns'], split_group=source['task_family'])
        result.append(enriched)
        policy_projection.append({'id': candidate['id'], 'goal': enriched['policy_input']['goal']})
    assert len({c['id'] for c in result}) == len(result)
    assert sum(c['first_four'] for c in result) == 4
    write_json('pilot_manifest.json', {**review, 'candidates': result})
    (OUT / 'policy_tasks.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in policy_projection))
    defects = {d['id'] for d in json.loads((OUT / 'defect_evidence.json').read_text())['defects']}
    assert all(set(c['defect_evidence_ids']) <= defects for c in result)
    with (OUT / 'pilot_coverage.csv').open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['id', 'source', 'source_task', 'pattern', 'pair_id', 'family',
                         'verifier_type', 'authorized_extras', 'defect_ids', 'status'])
        for c in result:
            writer.writerow([c['id'], c['source'], c.get('checker_enum', c['source_record']),
                             c.get('injection_code', ','.join(c.get('patterns', []))),
                             c['pair_id'], c['family'], c['upstream_verifier']['type'],
                             '; '.join(c['explicitly_authorized_extras']),
                             '; '.join(c['defect_evidence_ids']), c['execution_status']])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='Restore missing small sources using pinned hashes')
    args = parser.parse_args()
    if args.fetch:
        fetch_sources()
    hashes = {str(p.relative_to(CACHE)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(CACHE.rglob('*')) if p.is_file()}
    hash_file = OUT / 'source_hashes.json'
    if hash_file.exists() and json.loads(hash_file.read_text()) != hashes:
        raise ValueError('Pinned source hashes changed. Review the cache before regenerating the audit.')
    sus, sus_summary = inspect_sus()
    lite, lite_summary = inspect_lite()
    rows = sus + lite
    (OUT / 'inventory.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    write_json('source_hashes.json', hashes)
    build_pilot(rows)
    summary = {'status': 'static inspection; no browser runs or model calls',
               'susbench': sus_summary, 'trickyarena': lite_summary}
    write_json('audit_summary.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
