#!/usr/bin/env python3
"""GPU-only real FP8/native-vLLM lifecycle qualification, no trainer."""
import argparse
import json
from pathlib import Path
import shutil
import time
from types import SimpleNamespace


def padded_adapter(source, target, rank, b_scale=1):
    """Zero-padding preserves B@A and alpha/r; this is not rank-32 training."""
    import torch
    from safetensors.torch import load_file, save_file
    target.mkdir(parents=True)
    cfg = json.loads((source / 'adapter_config.json').read_text())
    original = cfg['r']
    assert rank >= original and not cfg.get('rank_pattern') and not cfg.get('alpha_pattern')
    tensors = load_file(source / 'adapter_model.safetensors')
    for name, tensor in tensors.items():
        assert tensor.dtype == torch.bfloat16, (name, tensor.dtype)
        axis = 0 if '.lora_A.' in name else 1 if '.lora_B.' in name else None
        assert axis is not None, name
        shape = list(tensor.shape)
        assert shape[axis] == original
        shape[axis] = rank
        expanded = torch.zeros(shape, dtype=tensor.dtype)
        index = [slice(None)] * tensor.ndim
        index[axis] = slice(0, original)
        expanded[tuple(index)] = tensor
        if '.lora_B.' in name:
            expanded.mul_(b_scale)
        assert torch.isfinite(expanded).all(), name
        tensors[name] = expanded
    cfg.update(r=rank, lora_alpha=cfg['lora_alpha'] * rank / original)
    (target / 'adapter_config.json').write_text(json.dumps(cfg, indent=2))
    save_file(tensors, target / 'adapter_model.safetensors')


def exercise(url, source, output, alternate_rank=32, identity=False):
    import requests
    from browser_training.policy_sessions import PolicyRegistry, PolicyCancelled, PolicyUnsafe, evict_idle
    session = requests.Session()
    registry = PolicyRegistry(max_staleness=2)
    registry.configure(2, str(output / 'policy-events.jsonl'))
    states = []
    ids = {}
    fingerprints = {}
    request_records = []
    identity_evidence = {'enabled': identity, 'diagnostic_b_scale': 128, 'traces': {}, 'fingerprints': {}}
    if identity:
        assert alternate_rank == 16
    def post(path, payload):
        response = session.post(url + path, json=payload, timeout=60)
        response.raise_for_status()
        return response
    def rpc(method, *args):
        return post('/collective_rpc', {'method': method, 'args': list(args), 'timeout': 30}).json()['results'][0]
    def fingerprint(name, label):
        result = rpc('training_lora_fingerprint', ids[name])
        if name in fingerprints:
            assert result['sha256'] == fingerprints[name], ('retained weights changed', name)
        fingerprints[name] = result['sha256']
        identity_evidence['fingerprints'][label] = result
        (output / 'identity-evidence.json').write_text(json.dumps(identity_evidence, indent=2))
        return result
    def state(label):
        value = post('/collective_rpc', {'method': 'training_lora_state', 'timeout': 30}).json()['results'][0]
        value.update(label=label, time=time.time(), names=[x['id'] for x in session.get(url+'/v1/models', timeout=10).json()['data']])
        states.append(value)
        (output / 'engine-states.json').write_text(json.dumps(states, indent=2))
        return value
    class Client:
        def unload_lora_adapter(self, name):
            post('/v1/unload_lora_adapter', {'lora_name': name})
            after = state('unloaded:' + name)
            assert name not in after['names'] and ids[name] not in after['registered'], after
            assert ids[name] not in after['active'], after
    trainer = SimpleNamespace(rollout_worker=SimpleNamespace(policy_registry=registry),
        vllm_client=Client(), _lora_name='probe', _lora_dir=str(output / 'adapters'))
    def publish(version, rank=16):
        evict_idle(trainer)
        registry.check_capacity()
        name = f'probe-v{version}'
        target = Path(trainer._lora_dir) / name
        # v1 uses an earlier trained checkpoint; later versions use checkpoint 2.
        earlier = source.parent / 'checkpoint-1'
        selected = earlier if not identity and version == 1 and earlier.is_dir() else source
        padded_adapter(selected, target, rank, b_scale=128 if identity and version % 2 == 0 else 1)
        before = state('before:' + name)
        post('/v1/load_lora_adapter', {'lora_name': name, 'lora_path': str(target)})
        after = state('loaded:' + name)
        added = set(after['registered']) - set(before['registered'])
        assert len(added) == 1, (before, after)
        ids[name] = added.pop()
        registry.publish(version)
        evict_idle(trainer)
    def generate(episode, trace_label=None):
        version = registry.begin_request(episode)
        try:
            if trace_label:
                rpc('training_lora_trace', ids[f'probe-v{version}'])
            data = post('/v1/completions', dict(model=f'probe-v{version}',
                prompt='The browser action to click button 7 is', max_tokens=12,
                temperature=0, seed=42, logprobs=1)).json()
            assert data['choices'][0]['logprobs']['token_logprobs']
            request_records.append(dict(version=version, trace_label=trace_label, choice=data['choices'][0]))
            (output / 'request-records.json').write_text(json.dumps(request_records, indent=2))
            return data['choices'][0]
        finally:
            if trace_label:
                trace = rpc('training_lora_trace')
                identity_evidence['traces'][trace_label] = trace
                (output / 'identity-evidence.json').write_text(json.dumps(identity_evidence, indent=2))
                assert trace['calls'] and not trace['missing_calls'], {'missing_calls': trace['missing_calls']}
            registry.end_request(episode)
    state('empty')
    publish(1)
    registry.acquire_group('slow'); registry.start_episode('slow', 'episode')
    first = generate('episode')
    control = generate('episode')
    comparisons = {'first': first, 'repeat_before_updates': control}
    if identity:
        fingerprint('probe-v1', 'a_before')
        comparisons['a_instrumented_before'] = generate('episode', 'a_before')
    (output / 'repeat-requests.json').write_text(json.dumps(comparisons, indent=2))
    publish(2, alternate_rank)
    if identity:
        fingerprint('probe-v2', 'b_before')
        assert fingerprints['probe-v1'] != fingerprints['probe-v2'], 'Diagnostic adapters are identical'
        registry.acquire_group('b-control'); registry.start_episode('b-control', 'b-control')
        comparisons['b_control'] = generate('b-control')
        comparisons['b_instrumented'] = generate('b-control', 'b_control')
        registry.finish_episode('b-control'); registry.release_group('b-control')
    publish(3)
    assert ids['probe-v1'] in state('v1-between-turns')['registered']
    second = generate('episode')
    if identity:
        fingerprint('probe-v1', 'a_after_publications')
        comparisons['a_instrumented_after'] = generate('episode', 'a_after')
        fingerprint('probe-v1', 'a_after_forward')
    comparisons['repeat_after_updates'] = second
    (output / 'repeat-requests.json').write_text(json.dumps(comparisons, indent=2))
    same_text = first['text'] == control['text'] == second['text']
    differences = [abs(a-b) for a,b in zip(first['logprobs']['token_logprobs'], second['logprobs']['token_logprobs'])]
    control_differences = [abs(a-b) for a,b in zip(first['logprobs']['token_logprobs'], control['logprobs']['token_logprobs'])]
    # Record the diagnostic before enforcing it so a failure remains reviewable.
    comparisons.update(before_update_max_difference=max(control_differences, default=0),
        after_update_max_difference=max(differences, default=0))
    (output / 'repeat-requests.json').write_text(json.dumps(comparisons, indent=2))
    repeatability_ok = same_text and max(differences + control_differences, default=0) < 0.01
    if identity:
        b = comparisons['b_control']
        # Only compare logprobs along the shared token prefix; different histories
        # cannot establish a numerical mismatch for the same conditional policy.
        common = []
        for ta, tb, pa, pb in zip(first['logprobs']['tokens'], b['logprobs']['tokens'],
                                  first['logprobs']['token_logprobs'], b['logprobs']['token_logprobs']):
            if ta != tb:
                break
            common.append(abs(pa-pb))
        distinct = first['text'] != b['text'] or max(common, default=0) > max(0.05, 5*max(differences + control_differences, default=0))
        identity_evidence.update(behaviorally_distinct=distinct,
            diagnostic_common_prefix_max_difference=max(common, default=0),
            adapter_a_weights_retained=True, kernel_inputs_verified=True,
            scope='All stored slot buffers match native CPU packing; actual shrink/expand weight pointers and grouped token-slot metadata audited. No GPU instruction-level proof.')
        identity_evidence['instrumentation_controls'] = {}
        for label, plain, traced in [('a_before', first, comparisons['a_instrumented_before']),
                                     ('a_after', second, comparisons['a_instrumented_after']),
                                     ('b', b, comparisons['b_instrumented'])]:
            equal = plain['logprobs']['tokens'] == traced['logprobs']['tokens']
            delta = max((abs(a-b) for a,b in zip(plain['logprobs']['token_logprobs'], traced['logprobs']['token_logprobs'])), default=0) if equal else None
            identity_evidence['instrumentation_controls'][label] = dict(same_tokens=equal, max_logprob_difference=delta)
        (output / 'identity-evidence.json').write_text(json.dumps(identity_evidence, indent=2))
        assert distinct, 'Diagnostic adapter signatures are not sufficiently separated'
    # Finish independent eviction checks even if this numerical diagnostic fails.
    # Keep an HTTP response undrained across a staleness tick. This proves lease
    # lifetime, not that the GPU remains busy throughout the client's delay.
    registry.begin_request('episode')
    response = session.post(url+'/v1/completions', json=dict(model='probe-v1', prompt='Count to ten:',
        max_tokens=32, temperature=0, stream=True), stream=True, timeout=60)
    response.raise_for_status()
    lines = response.iter_lines()
    assert next(lines)
    publish(4)
    assert ids['probe-v1'] in state('stale-but-response-undrained')['registered']
    try:
        registry.finish_episode('episode')
    except PolicyUnsafe:
        pass
    else:
        raise AssertionError('Outstanding request released early')
    for _ in lines:
        pass
    response.close(); registry.end_request('episode')
    try:
        registry.begin_request('episode')
    except PolicyCancelled:
        pass
    else:
        raise AssertionError('Stale episode allowed another model call')
    registry.finish_episode('episode')
    assert registry.release_group('slow') == 'staleness'
    evict_idle(trainer)
    # Error completion releases leases; version still ages normally.
    registry.acquire_group('error'); registry.start_episode('error', 'failed')
    registry.cancel_group('error', 'mock_environment_error')
    registry.finish_episode('failed'); registry.release_group('error')
    for version in range(5, 11):
        publish(version, rank=alternate_rank if version % 2 == 0 else 16)
        group = f'g{version}'
        registry.acquire_group(group); registry.start_episode(group, group)
        generate(group, f'churn-{version}' if identity and version in (5, 10) else None)
        registry.finish_episode(group); registry.release_group(group)
        assert len(state(f'churn-{version}')['registered']) <= 3
    final = registry.snapshot()
    assert not final['groups'] and not final['episodes'] and not final['fault']
    assert set(final['versions']) == {8, 9, 10}
    assert len(list(Path(trainer._lora_dir).iterdir())) == 3
    # Explicit shutdown unloads the retained current/staleness window too.
    for version in list(final['versions']):
        Client().unload_lora_adapter(f'probe-v{version}')
        shutil.rmtree(Path(trainer._lora_dir) / f'probe-v{version}')
    assert not state('shutdown-empty')['registered']
    report = dict(status='PASS' if repeatability_ok else 'LIFECYCLE_PASS_LOGPROBS_NEED_REVIEW',
        lifecycle_pass=True, repeatability_ok=repeatability_ok, same_text=same_text, versions_loaded=10, ranks=sorted({16, alternate_rank}), adapter_dtype='bfloat16',
        rank32='zero-padded rank16; loading/layout qualification only' if alternate_rank==32 else 'not tested',
        session_adapter_name_pinned=True, staleness_cancels_next_call=True, response_drained_before_release=True,
        engine_removal_verified=True, shutdown_registered_adapters=0,
        same_policy_logprob_max_difference=max(differences, default=0),
        before_update_logprob_max_difference=max(control_differences, default=0),
        distinct_trained_policy_weights=not identity and (source.parent / 'checkpoint-1').is_dir(),
        identity=identity_evidence,
        scope='real FP8 inference + native load/unload + production registry; no TRL optimizer or MTP',
        final_registry=final, states=states)
    (output / 'inference-report.json').write_text(json.dumps(report, indent=2))
    return report


def main():
    p=argparse.ArgumentParser(); p.add_argument('--url',default='http://127.0.0.1:8000')
    p.add_argument('--source',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--alternate-rank', type=int, choices=[16,32], default=32)
    p.add_argument('--identity', action='store_true', help='Same-rank diagnostic adapters and GPU kernel input audit')
    a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    print(json.dumps(exercise(a.url,a.source,a.output,a.alternate_rank,a.identity),indent=2))

if __name__=='__main__': main()
