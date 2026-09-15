"""Replay local preflight evidence and enable its exact build/task contracts.

This is an explicit developer operation, not a policy tool. No browser or API
requests. Supply reports from verify_chaos.py; failed cases remain in their
original reports and are excluded from certification.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from intent_browser.chaos_verifier import SUPPORTED, evaluate_trace, verifier_fingerprints
from intent_browser.trace import write_json


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT/'.local/preflight/chaos-verifier-validation.json')
    parser.add_argument('--certificate-output', type=Path, default=ROOT/'config/chaos_verifier.json',
                        help='Write a separate candidate certificate without changing the active build gate')
    args = parser.parse_args()
    selected = {}
    builds = []
    for path in args.reports:
        report = read(path)
        builds.append(report['provenance']['files_sha256'])
        for case in report['cases']:
            if case['passed']:
                selected[case['task'], case['scenario']] = case
    required = {(task, scenario) for task in SUPPORTED for scenario in ('positive', 'negative')}
    required |= {('confirmshaming', 'email-then-decline'), ('confirmshaming', 'skip')}
    if set(selected) != required or not builds or any(build != builds[0] for build in builds):
        raise ValueError('Need all 16 cases from one installed build')
    sessions = set()
    for (task, scenario), case in selected.items():
        directory = ROOT / case['episode']
        session = read(directory / 'chaos-session.json')
        descriptor = read(directory / 'chaos-contract.json')
        external = read(directory / 'external_evaluation.json')
        episode = read(directory / 'episode.json')
        # Replaying old labels cannot certify execution by today's runner.
        runtime = episode.get('runtime', {}).get('source_sha256', {})
        for name in ('runner.py', 'observation.py', 'trace.py', 'chaos.py', 'chaos_verifier.py'):
            current = hashlib.sha256((ROOT/'intent_browser'/name).read_bytes()).hexdigest()
            if runtime.get(name) != current:
                raise ValueError('Fresh current-runtime evidence required: '+case['episode']+' / '+name)
        snapshots = [read(directory / 'initial-state.json')['task_state']['browser_state']]
        snapshots += [read(p) for p in sorted(directory.glob('task-state-*.json'))]
        start_url = session['base_url'] + session['selected']['taskUrl']
        skipped = external['selected_results'][0].get('skipped') is True
        if any(s['url'] != start_url for s in snapshots) and not skipped:
            raise ValueError('Episode left its scoped URL')
        result = evaluate_trace(descriptor, session, external['score'], external['events']['events'],
                                [s for s in snapshots if s['url'] == start_url])
        expected = scenario in ('positive', 'email-then-decline')
        safe = result['task_completed'] and result['authorization_satisfied']
        if (safe is not expected or episode['error'] or descriptor['task']['id'] != task or
                episode.get('training_eligible') is not False or
                session['environment_revision']['files_sha256'] != builds[0] or
                session['session'] in sessions):
            raise ValueError('Case replay, provenance, or session isolation failed: ' + case['episode'])
        sessions.add(session['session'])
        case['replayed_contract'] = result
        case['artifact_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(directory.glob('*.json'))}
    validation = {'schema_version': 1, 'validated_at': datetime.now(timezone.utc).isoformat(),
                  'scope': 'Scripted local interaction contracts; not policy performance or transaction-ledger validation.',
                  'reports': [str(p) for p in args.reports], 'cases': list(selected.values()),
                  'files_sha256': builds[0], 'verifier_source_sha256': verifier_fingerprints()}
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, validation)
    config = {k: validation[k] for k in ('schema_version', 'validated_at', 'scope', 'files_sha256', 'verifier_source_sha256')}
    config.update(validated_task_ids=list(SUPPORTED), validation_report=str(output.relative_to(ROOT)),
                  validation_report_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    certificate = args.certificate_output.resolve()
    certificate.parent.mkdir(parents=True, exist_ok=True)
    write_json(certificate, config)
    print(f'Validated {len(selected)} cases in distinct sessions. Wrote {certificate}')


if __name__ == '__main__':
    main()
