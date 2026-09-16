#!/usr/bin/env python3
"""CPU qualification of native packing and negative controls for the GPU probe."""
import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import torch
from browser_training.vllm_probe_worker import ProbeWorker, slot_fingerprint, check_kernel_metadata
from vllm.lora.layers.base_linear import BaseLinearLayerWithLoRA
from vllm.lora.layers.column_parallel_linear import MergedColumnParallelLinearWithLoRA
import vllm.lora.punica_wrapper.punica_gpu as punica


def rejected(call):
    try:
        call()
    except AssertionError:
        return
    raise AssertionError('Negative control was accepted')


def main():
    torch.set_num_threads(1)
    torch.manual_seed(42)
    def layer(cls, sizes):
        m = cls.__new__(cls)
        torch.nn.Module.__init__(m)
        m.tp_size = 1
        m.n_slices = len(sizes)
        m.output_sizes = sizes
        m.lora_a_stacked = tuple(torch.zeros(4, 1, 32, 8, dtype=torch.bfloat16) for _ in sizes)
        m.lora_b_stacked = tuple(torch.zeros(4, 1, n, 32, dtype=torch.bfloat16) for n in sizes)
        return m
    a = torch.randn(16, 8, dtype=torch.bfloat16)
    b = torch.randn(8, 16, dtype=torch.bfloat16)
    plain = layer(BaseLinearLayerWithLoRA, [8])
    packed = layer(MergedColumnParallelLinearWithLoRA, [2, 2, 2, 2])
    weights = {'plain': SimpleNamespace(lora_a=a, lora_b=b),
               'gdn': SimpleNamespace(lora_a=[a, a], lora_b=[b[:6], b[6:]])}
    modules = {'plain': plain, 'gdn': packed}
    for name, m in modules.items():
        m.set_lora(0, weights[name].lora_a, weights[name].lora_b)
    # Frozen conv1d storage is wrapped by vLLM but its forward bypasses LoRA.
    modules['frozen.conv1d'] = layer(BaseLinearLayerWithLoRA, [8])
    manager = SimpleNamespace(lora_index_to_id=[17, 18, None, None], modules=modules,
        get_adapter=lambda _: weights, _get_lora_layer_weights=lambda adapter, name: adapter.get(name))
    before = slot_fingerprint(manager, 17)
    assert before['buffer_count'] == 12
    assert slot_fingerprint(manager, 17)['sha256'] == before['sha256']
    plain.lora_b_stacked[0][0, 0, 0, 0] += 1
    rejected(lambda: slot_fingerprint(manager, 17))
    plain.set_lora(0, a, b)
    assert slot_fingerprint(manager, 17)['sha256'] == before['sha256']

    args = (torch.empty(2, 8), plain.lora_a_stacked, torch.empty(1, 2, 32),
        torch.tensor([0, 0]), torch.tensor([0, 1]), torch.tensor([2, 0, 0, 0, 0]),
        torch.tensor([0, 2, 2, 2, 2, 2]), torch.tensor([0, -1, -1, -1, -1]),
        torch.tensor(False), torch.tensor(5), 1.0)
    assert check_kernel_metadata(args, 0) == 2
    rejected(lambda: check_kernel_metadata(args, 1))
    bad_rows = list(args); bad_rows[4] = torch.tensor([0, 0])
    rejected(lambda: check_kernel_metadata(bad_rows, 0))
    bad_slots = list(args); bad_slots[7] = torch.tensor([1, -1, -1, -1, -1])
    rejected(lambda: check_kernel_metadata(bad_slots, 0))
    worker = ProbeWorker()
    worker.model_runner = SimpleNamespace(lora_manager=SimpleNamespace(_adapter_manager=manager))
    with patch.object(punica, 'lora_shrink', return_value=None) as shrink, patch.object(punica, 'lora_expand', return_value=None):
        worker.training_lora_trace(17)
        punica.lora_shrink(*args)
        shrink.assert_called_once()
        manager.lora_index_to_id[0] = 18
        rejected(lambda: punica.lora_shrink(*args))
        manager.lora_index_to_id[0] = 17
        trace = worker.training_lora_trace()
        assert trace['checked_token_rows'] == 2 and trace['missing_calls']
        assert trace['required_call_count'] == 4
        assert all('conv1d' not in s for s in trace['missing_calls'])
        assert punica.lora_shrink is shrink
        worker.training_lora_trace(17)
        for m in (plain, packed):
            for op, attr in [('lora_shrink', 'lora_a_stacked'), ('lora_expand', 'lora_b_stacked')]:
                call_args = list(args)
                call_args[1] = getattr(m, attr)
                getattr(punica, op)(*call_args)
        complete = worker.training_lora_trace()
        assert len(complete['calls']) == 4 and not complete['missing_calls']
    report = dict(status='PASS', gpu_used=False, buffer_count=12,
        native_plain_and_gdn_packing=True, detects_corrupted_weights=True,
        detects_wrong_slot_and_duplicate_token_rows=True, detects_slot_reassignment=True,
        missing_kernel_coverage_reported=True, original_functions_restored=True,
        untargeted_conv_buffers_verified_without_requiring_execution=True,
        scope='CPU native vLLM packing and diagnostic wrappers; GPU kernels mocked')
    (Path(__file__).resolve().parents[1]/'research/adapter-identity-local.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
