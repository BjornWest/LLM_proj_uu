"""Validate review structure/evidence references, never the truth of a diagnosis."""
import argparse
import json
from pathlib import Path

from .core import digest

TAXONOMY = "browser-failure-taxonomy-v1"
CAUSES = {
    "intent_misunderstanding", "hidden_information_failure", "semantic_ui_failure",
    "preselection_failure", "navigation_failure", "action_execution_failure",
    "state_observation_failure", "over_conservative_behavior", "memory_failure",
    "context_management_failure", "harness_environment_failure", "unknown_or_ambiguous",
}
INTEGRITY_STATUSES = {'unreviewed', 'no_issue_found_in_scope', 'suspected_issue',
                      'confirmed_issue', 'inconclusive'}


def validate(review, episode):
    if review.get('schema') != 'browser-failure-diagnosis-v1' or review.get('taxonomy_version') != TAXONOMY:
        raise ValueError('Unsupported diagnosis or taxonomy version')
    if review.get('episode_id') != episode['episode_id'] or review.get('source_evidence_sha256') != digest(episode['source_artifacts']):
        raise ValueError('Review identity/evidence snapshot mismatch')
    if review.get('recorded_outcomes_overridden') is not False:
        raise ValueError('A diagnosis cannot override recorded outcomes')
    forbidden = {'safe_success', 'reward', 'task_completed', 'authorization_satisfied', 'recorded_evaluation'}
    if forbidden & review.keys():
        raise ValueError('Outcome fields belong to original evidence, not the diagnosis')
    if review.get('status') not in ('unreviewed', 'reviewed', 'needs_more_evidence'):
        raise ValueError('Unknown review status')
    primary, secondary = review.get('primary_failure'), review.get('secondary_failures')
    if primary is not None and primary not in CAUSES:
        raise ValueError('Unknown primary cause')
    if not isinstance(secondary, list) or any(c not in CAUSES for c in secondary):
        raise ValueError('Unknown secondary cause')
    if review.get('support') not in (None, 'supported', 'plausible', 'unresolved'):
        raise ValueError('Unknown support status; numeric confidence is not calibrated')
    indices = {s['step'] for s in episode['timeline']}
    for field in ('first_suspicious_step', 'first_violation_step', 'irreversible_step'):
        value = review.get(field)
        if value is not None and (type(value) is not int or value not in indices):
            raise ValueError(f'Unknown/noninteger step: {field}')
    integrity = review.get('integrity_review')
    if integrity is not None:
        if not isinstance(integrity, dict) or set(integrity) != {'status','scope','findings','evidence'}:
            raise ValueError('Integrity review needs status, scope, findings and evidence only')
        if integrity['status'] not in INTEGRITY_STATUSES:
            raise ValueError('Unknown integrity status')
        if not isinstance(integrity['findings'], list) or any(not isinstance(x,str) or not x.strip() for x in integrity['findings']):
            raise ValueError('Integrity findings must be nonempty strings')
        if integrity['status'] == 'unreviewed':
            if integrity['scope'] is not None or integrity['findings'] or integrity['evidence']:
                raise ValueError('Unreviewed integrity template cannot assert findings')
        else:
            if review['status'] == 'unreviewed' or not isinstance(integrity['scope'], str) or not integrity['scope'].strip() or not integrity['evidence']:
                raise ValueError('Integrity assessment requires reviewed scope and evidence')
            if integrity['status'] in ('suspected_issue','confirmed_issue') and not integrity['findings']:
                raise ValueError('Integrity issue requires findings')
    references = [(field, review.get(field)) for field in ('evidence', 'contradicting_evidence')]
    if integrity is not None: references.append(('integrity_review.evidence', integrity['evidence']))
    for field, refs in references:
        if not isinstance(refs, list):
            raise ValueError(f'{field} must be a list')
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValueError('Evidence reference must be an object')
            source = episode['source_artifacts'].get(ref.get('artifact'))
            if not source or source['sha256'] != ref.get('sha256') or not ref.get('claim'):
                raise ValueError('Evidence artifact/hash/claim missing or mismatched')
            if ref.get('step') is not None and (type(ref['step']) is not int or ref['step'] not in indices):
                raise ValueError('Evidence step does not exist')
    if review['status'] == 'unreviewed':
        if primary is not None or secondary:
            raise ValueError('Unreviewed templates must not carry causal labels')
    else:
        if not review.get('reviewer') or not review.get('short_explanation') or review.get('support') is None:
            raise ValueError('Review needs reviewer, explanation and support status')
        if (primary not in (None, 'unknown_or_ambiguous') or secondary) and not review['evidence']:
            raise ValueError('Causal labels require cited evidence')
    return {'valid_structure': True, 'causal_correctness_verified': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--triage', type=Path, required=True)
    p.add_argument('--diagnosis', type=Path, required=True)
    a = p.parse_args()
    report, review = json.loads(a.triage.read_text()), json.loads(a.diagnosis.read_text())
    matches = [e for e in report['episodes'] if e['episode_id'] == review.get('episode_id')]
    if len(matches) != 1:
        raise ValueError('Review must identify exactly one episode')
    print(json.dumps(validate(review, matches[0])))


if __name__ == '__main__':
    main()
