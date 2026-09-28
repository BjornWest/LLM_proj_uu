"""Publish a completed extraction's display sidecar without changing recordings."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from scripts.trace_grades import BOUND_FILES, FILENAME, SCHEMA, sha


def publish(output):
    output = Path(output).resolve()
    read = lambda name: json.loads((output / name).read_text())
    plan, grade, completed = read('plan.json'), read('grade.json'), read('completed.json')
    if completed.get('status') != 'graded' or completed.get('source_hashes_unchanged') is not True:
        raise ValueError('Extraction not completed and verified')
    if plan.get('mode') != 'live': raise ValueError('Publish the live extraction, not a duplicate replay')
    trace = Path(plan['source_trace']).resolve()
    if grade.get('source_trace') != str(trace): raise ValueError('Grade/plan episode mismatch')
    source_hashes = read('source-hashes.json')
    for name, expected in source_hashes.items():
        if sha(name) != expected: raise ValueError('Extraction input changed: ' + name)
    if grade.get('safe_success') is not None or grade.get('full_response_evaluated') is not False:
        raise ValueError('This publisher supports scoped answer grades only')
    evidence = {name: sha(output / name) for name in
                ('plan.json', 'grade.json', 'claims.json', 'request.json', 'response.json',
                 'source-hashes.json', 'completed.json', 'usage.json')}
    usage = read('usage.json')
    value = {'schema': SCHEMA, 'episode_id': trace.name,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'structured_claims_correct': grade['structured_claims_correct'],
        'requirements': grade['oracle_grade']['requirements'],
        'additional_checks': grade['additional_checks'],
        'selected_candidate_assessment': grade.get('selected_candidate_assessment'),
        'oracle_answer': grade['oracle_answer'], 'claims': read('claims.json'),
        'derivations': grade['derivations'],
        'extractor': {'version': grade['extraction_version'], 'model': usage['model'],
                      'provider': usage['provider'], 'reported_cost_usd': usage['reported_cost_usd']},
        'full_response_evaluated': False, 'safe_success': None,
        'limitations': ['Derived after the episode; original recorded evaluation is unchanged.',
            'Checks concern extracted answer claims and covered host effects, not full prose or broad safety.',
            'Exact quotations do not by themselves prove correct semantic attribution.'],
        'source_directory': str(output), 'source_artifact_sha256': evidence,
        'episode_artifact_sha256': {name: sha(trace / name) for name in BOUND_FILES}}
    target = trace / FILENAME
    if target.exists() or target.is_symlink():
        existing = json.loads(target.read_text()) if not target.is_symlink() else {}
        if existing.get('source_artifact_sha256') == evidence and existing.get('episode_artifact_sha256') == value['episode_artifact_sha256']:
            return target
        raise ValueError('A different derived grade already exists; do not overwrite history')
    # Complete bytes become visible atomically; never replace an existing artifact.
    fd, temporary = tempfile.mkstemp(prefix='.derived-grade-', dir=trace)
    try:
        with os.fdopen(fd, 'w') as stream: json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        os.link(temporary, target)
    finally: Path(temporary).unlink(missing_ok=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    target = publish(args.output)
    from .details import publish_details
    print(target)
    print(publish_details(args.output, target))


if __name__ == '__main__': main()
