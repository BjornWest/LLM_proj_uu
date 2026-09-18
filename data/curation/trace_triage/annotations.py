"""Optional searchable annotations on immutable diagnosis records."""
import re
import argparse
import json
from pathlib import Path

from .review import CAUSES, validate

TAG = re.compile(r"^(behavior|evidence|outcome|context|procedure|review):[a-z0-9]+(?:-[a-z0-9]+)*$")

# These are reviewer boundaries, not automatic classifiers.
GUIDANCE = {
    'intent_misunderstanding': ('Evidence that the requested goal or constraint was interpreted incorrectly.', 'A violated constraint alone; execution or environment errors can produce the same outcome.', ['action_execution_failure','state_observation_failure']),
    'hidden_information_failure': ('Task-relevant available information was not discovered or incorporated.', 'Assuming that undelivered content was read; absence of information does not establish why navigation failed.', ['context_management_failure','navigation_failure']),
    'semantic_ui_failure': ('Evidence supports misunderstanding the meaning of a delivered UI label/control.', 'A wrong click without evidence distinguishing semantics from target/execution error.', ['action_execution_failure','intent_misunderstanding']),
    'preselection_failure': ('An unwanted default selection was left uncorrected and contributed to failure.', 'An explicitly authorized default or an automatic effect not represented as a selection.', ['hidden_information_failure','state_observation_failure']),
    'navigation_failure': ('Evidence supports a failure to reach or choose the needed page/path.', 'A loop describes behavior; its cause can still be unresolved.', ['hidden_information_failure','state_observation_failure']),
    'action_execution_failure': ('An incorrect action, argument, target or output format prevents execution.', 'Assuming the model reasoned correctly merely because the action errored.', ['semantic_ui_failure','harness_environment_failure']),
    'state_observation_failure': ('An observable decision/claim relies on a false or misread page state.', 'Missing feedback alone, especially when other state evidence remains available.', ['context_management_failure','harness_environment_failure']),
    'over_conservative_behavior': ('The agent refuses or unnecessarily asks despite sufficient explicit authorization.', 'Declining unauthorized extras or asking about a material unresolved ambiguity.', ['intent_misunderstanding']),
    'memory_failure': ('An actual memory mechanism retrieves, prioritizes, stores or deletes information incorrectly.', 'No memory subsystem evidence; repetition alone is not forgetting.', ['context_management_failure','intent_misunderstanding']),
    'context_management_failure': ('Relevant information is demonstrably lost or distorted in retained context/history.', 'A forgotten constraint inferred only from the final outcome.', ['memory_failure','harness_environment_failure']),
    'harness_environment_failure': ('Evidence establishes a task, tool, observation, verifier or infrastructure defect.', 'Any browser exception automatically blamed on infrastructure; valid interfaces can be misused.', ['action_execution_failure','context_management_failure']),
    'unknown_or_ambiguous': ('Observed behavior/outcome is clear but available evidence cannot distinguish causes.', 'Treating an unresolved case as a positive example of every alternative discussed.', []),
}
assert set(GUIDANCE) == CAUSES


def validate_annotation(review, episode):
    result = validate(review, episode)
    if review.get('annotation_version', 1) != 1:
        raise ValueError('Unsupported annotation version')
    # Do not introduce a competing copy of causal types alongside primary/secondary.
    if 'types' in review:
        raise ValueError('Use primary_failure/secondary_failures for taxonomy types')
    tags = review.get('tags', [])
    if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(t,str) or len(t)>96 or not TAG.fullmatch(t) for t in tags):
        raise ValueError('Tags must be <=20 namespaced lowercase slugs')
    if len(set(tags)) != len(tags):
        raise ValueError('Duplicate tags')
    refs = review.get('tag_evidence', {})
    if not isinstance(refs, dict) or set(refs) != set(tags):
        raise ValueError('Every tag needs an evidence entry, without orphan entries')
    for tag, artifacts in refs.items():
        if not isinstance(artifacts, list) or not artifacts or any(not isinstance(a,str) or a not in episode['source_artifacts'] for a in artifacts):
            raise ValueError(f'Tag evidence outside bound episode snapshot: {tag}')
    for key, limit in (('summary',1000),('classification_notes',2000)):
        value = review.get(key)
        if value is not None and (not isinstance(value,str) or not value.strip() or len(value)>limit):
            raise ValueError(f'{key} must be nonempty text <= {limit} characters')
    if tags and review['status']=='unreviewed':
        raise ValueError('Unreviewed templates cannot assert reviewer tags')
    return {**result,'annotation_structure_valid':True,'tag_truth_verified':False}


def assigned_types(review):
    return [x for x in [review.get('primary_failure'),*review.get('secondary_failures',[])] if x]


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--triage',type=Path,required=True);p.add_argument('--diagnosis',type=Path,required=True)
    a=p.parse_args();r=json.loads(a.diagnosis.read_text());t=json.loads(a.triage.read_text())
    matches=[e for e in t['episodes'] if e['episode_id']==r.get('episode_id')]
    if len(matches)!=1:raise ValueError('Review must identify one episode')
    print(json.dumps(validate_annotation(r,matches[0])))
