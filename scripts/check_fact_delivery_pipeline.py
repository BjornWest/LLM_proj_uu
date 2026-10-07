#!/usr/bin/env python3
"""Saved paired browser exports -> real AX formatting -> offline part features.

Retained delivery acknowledgments are scripted controls, never model results.
No runner, task grading, browser launch, world draw or shared Website mutation.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intent_browser.ax_context import AXContext
from intent_browser.ax_explorer import AXConfig
from intent_browser.fact_provenance import FactRecorder, encoded
from intent_browser.policy_delivery import PolicyDelivery
from training.browser_training.fact_exposure import digest, object_digest
from training.browser_training.fact_delivery_features import extract


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return digest(path.read_text())


def check(path, output, tokenizer):
    before = sha(path); data = read(path)
    packet = data['provider_packet']
    require_pair = packet['private_context']['pairing']
    assert require_pair['raw_ax_sha256'] == object_digest({'nodes': data['raw_ax']})
    assert require_pair['extra_ax_captures'] == 0
    assert require_pair['render_revision'] == data['commit']['revision']
    directory = output / path.parent.name / path.name.removesuffix('.capture.private.json')
    directory.mkdir(parents=True, exist_ok=False)
    trace = SimpleNamespace(directory=directory, event=lambda *args, **kwargs: None)
    context = AXContext(AXConfig(str(tokenizer), incremental=True))
    def provider(env, observation, metadata):
        result = deepcopy(packet)
        # The browser proof already brackets the exact raw AX. Reindex only
        # the host formatter snapshot label, preserving native node identities.
        for source in result['sources']:
            source['binding']['snapshot_id'] = metadata['snapshot_id']
        return result
    recorder = FactRecorder(trace, provider); recorder.attach(context)
    ledger = PolicyDelivery(trace); ledger.fact_recorder = recorder
    observation = {'url': data['commit']['meta']['url'], 'last_action_error': '',
                   'axtree_object': {'nodes': data['raw_ax']}}
    preview = context.prepare_observation(observation)
    assert preview == AXContext(context.config).prepare_observation(observation)
    ids = []
    def retain(value):
        selected = recorder.select(value)
        assert selected is not None
        ids.append(ledger.register('ax_result', value if isinstance(value, str) else encoded(value),
                                   step=0, fact_output=selected))
    retain(preview)
    for ref in recorder.current['fields']:
        retain(context.read(ref, view='node', repeat=True))
    messages = [{'role': 'tool', 'content': ledger.sources[cid]['text']} for cid in ids]
    bindings = [{'content_id': cid, 'message_index': i, 'start': 0, 'end': len(messages[i]['content'])}
                for i, cid in enumerate(ids)]
    event = {'step': 0, 'messages': messages, 'model_request': {'messages': messages}}
    (directory / 'steps.jsonl').write_text(json.dumps(event, ensure_ascii=False) + '\n')
    ledger.record(event, bindings, acknowledged=False)
    rejected = extract(directory, step=0)
    assert not rejected['features']['part_complete_count'] and not rejected['features']['part_partial_count']
    ledger.record(event, bindings, acknowledged=True)
    result = extract(directory, step=0)
    assert not result['diagnostics'], result['diagnostics']
    if packet['sources']:
        assert result['features']['part_complete_count'] > 0
    else:
        assert not result['features']['part_complete_count']
    helper = extract(directory, step=0, recipient='worker')
    assert not helper['features']['part_complete_count'] and not helper['features']['part_partial_count']
    (directory / 'features.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    recorder.close()
    assert sha(path) == before
    return {'input': str(path), 'input_sha256': before, 'features': result['features'],
            'public_text_parity': True, 'unacknowledged_and_recipient_controls': True,
            'paired_existing_ax': True, 'synthetic_delivery_only': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, default=ROOT/'training/.cache/qwen38-tokenizer/tokenizer.json')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    assert read(args.captures/'terminal.json')['passed'], 'Browser batch did not pass'
    paths = sorted(args.captures.glob('*/*.capture.private.json'))
    assert paths
    modules = ['scripts/check_fact_delivery_pipeline.py', 'intent_browser/fact_provenance.py',
               'intent_browser/ax_context.py', 'intent_browser/ax_explorer.py', 'intent_browser/policy_delivery.py',
               'training/browser_training/fact_delivery_features.py', 'training/browser_training/fact_exposure.py']
    pins = {name: sha(ROOT/name) for name in modules}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda path: check(path, args.output, args.tokenizer), paths))
    assert all(sha(ROOT/name) == pin for name, pin in pins.items()), 'Consumer source changed'
    result = {'passed': True, 'cases': results, 'source_sha256': pins,
              'scope': 'paired_saved_AX_real_formatter_and_scripted_retained_delivery',
              'browser_launches': 0, 'model_requests': 0, 'world_draws': 0, 'grader_calls': 0,
              'producer_qualified': False, 'live_website_adoption': False, 'case_workers': 2}
    (args.output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'passed': True, 'cases': len(results), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
