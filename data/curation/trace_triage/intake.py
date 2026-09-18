"""Read old curation and current harness suite indexes without executing them."""
import json
from pathlib import Path


def suite_inputs(directory, root):
    directory = Path(directory).resolve()
    if not (directory / 'cases').is_dir():
        raise ValueError('Suite needs a cases directory: ' + str(directory))
    inputs, notes = [], []
    for path in sorted((directory / 'cases').glob('*.json')):
        case = json.loads(path.read_text())
        if case.get('status') not in ('completed', 'finished'):
            notes.append({'case_file': str(path), 'status': case.get('status'),
                          'disposition': 'not imported; unfinished case'})
            continue
        trace = case.get('episode') or case.get('trace')
        if not isinstance(trace, str) or not trace:
            raise ValueError('Finished case has no trace: ' + str(path))
        target = Path(trace)
        # Both current writers record repo-relative or absolute trace paths.
        if not target.is_absolute():
            target = Path(root) / target
        expected = case.get('artifact_sha256', case.get('artifacts_sha256'))
        if expected is not None and not isinstance(expected, dict):
            raise ValueError('Invalid suite artifact inventory')
        inputs.append((target, expected))
        notes.append({'case_file': str(path), 'status': case['status'],
                      'disposition': 'selected', 'has_artifact_inventory': expected is not None})
    return inputs, notes


def review_queue(episodes, seed='triage-mvp-2'):
    """Suggested work, including a deterministic control sample of apparent passes."""
    from .core import digest
    buckets = {}
    for e in episodes:
        if e.get('apparent_success'):
            key = (e['source'], e['task'], e.get('model'), e.get('driver'))
            buckets.setdefault(key, []).append(e)
    sampled = {min(es, key=lambda e: digest([seed, e['episode_id']]))['episode_id']
               for es in buckets.values()}
    items = []
    for e in episodes:
        reasons = []
        if e['outcome_group'] != 'success': reasons.append('failure_or_unknown')
        if e['flags']: reasons.append('detector_flags')
        if e['episode_id'] in sampled: reasons.append('sampled_apparent_success')
        if not reasons: continue
        items.append({'episode_id': e['episode_id'], 'reasons': reasons,
                      'recorded_outcome': e['outcome_group'],
                      'apparent_success': e.get('apparent_success', False),
                      'priority': max((f['priority'] for f in e['flags']), default=0)})
    items.sort(key=lambda x: (-x['priority'], x['episode_id']))
    return {'items': items, 'sampling_seed': seed, 'population_count': len(episodes),
            'apparent_success_population': sum(bool(e.get('apparent_success')) for e in episodes),
            'sampled_success_count': len(sampled),
            'sampling_rule': 'One apparent completion/pass per source/task/requested-model/driver bucket, chosen by deterministic hash; sampled even without flags. Review suggestions, not representative prevalence estimates.'}
