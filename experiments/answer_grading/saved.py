"""Rebind saved connected-world evidence without starting sites or a browser."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_saved(cohort):
    # CLI must select this cohort's frozen source before importing its Episode.
    from environments.product_world.episode import Episode
    from intent_browser.connected_world_task import public_projection
    cohort = Path(cohort).resolve(); live = cohort / 'live'
    pins = read(cohort / 'snapshot.json')['files']
    for name, expected in pins.items():
        if sha(name) != expected: raise ValueError('Frozen source/input changed: ' + name)
    source = cohort / 'source'
    import inspect
    if not Path(inspect.getfile(Episode)).resolve().is_relative_to(source):
        raise ValueError('Oracle must be imported from the original cohort source')
    result = read(live / 'result.json'); trace = Path(result['trace']).resolve()
    if not trace.is_relative_to(live / 'runs'): raise ValueError('Trace is outside cohort')
    private = trace / 'manual-review-private'
    scenario = read(cohort / 'input/scenario.private.json')
    if scenario != read(private / 'scenario.private.json'): raise ValueError('Scenario attachments disagree')
    manifest = read(live / 'manifest.json')
    runtime = SimpleNamespace(public_manifest=manifest, index_origin=manifest['index_url'],
        provenance=read(live / 'provenance.json'), bindings=read(live / 'bindings.json'),
        comparison_coverage=read(cohort / 'input/coverage.public.json'),
        interaction_patterns=scenario.get('interaction_patterns'), storefront_content=scenario.get('storefront_content'),
        product_review_evidence=scenario.get('product_review_evidence'))
    episode = Episode.from_runtime(scenario, runtime)
    raw = episode.policy_input()
    public = public_projection({**raw, 'task_id': raw['episode_id']})
    if public != read(trace / 'policy-task.json') or public != read(live / 'policy-task.json'):
        raise ValueError('Reconstructed task differs from delivered task')
    reference = read(live / 'reference.private.json')
    if episode.reference() != reference['outcome'] or episode._candidates != reference['candidates']:
        raise ValueError('Original oracle/reference mismatch')
    answer = read(trace / 'natural-answer.json')
    if answer.get('technical_error') or result['summary'].get('error'):
        raise ValueError('Technical interruption: no automatic task verdict')
    initial = read(private / 'world-initial.json'); final = read(private / 'world-final.json')
    if final != read(live / 'journal.private.json'): raise ValueError('Final host journals disagree')
    # Source pins plus saved artifacts are recorded and checked again after inference.
    paths = [cohort/'snapshot.json', live/'result.json', live/'manifest.json', live/'provenance.json',
             live/'bindings.json', live/'reference.private.json', live/'journal.private.json',
             live/'policy-task.json', trace/'policy-task.json', trace/'natural-answer.json', trace/'steps.jsonl',
             private/'scenario.private.json', private/'world-initial.json', private/'world-final.json']
    hashes = {**pins, **{str(p): sha(p) for p in paths}}
    return SimpleNamespace(episode=episode, public=public, answer=answer['text'], initial=initial,
                           final=final, trace=trace, hashes=hashes)
