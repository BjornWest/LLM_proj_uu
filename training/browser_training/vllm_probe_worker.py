"""Bounded diagnostics through native RPC. Instrumentation is opt-in, eager/TP1 only."""
import copy
import hashlib


def as_tuple(value):
    return value if isinstance(value, (tuple, list)) else (value,)


def tensor_digest(tensor):
    import torch
    data = tensor.detach().contiguous().cpu()
    return hashlib.sha256(data.view(torch.uint8).numpy().tobytes()).hexdigest()


def slot_fingerprint(manager, adapter_id):
    """Compare all device slot bytes with a CPU reconstruction using native packing.

    Only shadow buffers are written. This checks transfer/retention, not whether
    the upstream packing algorithm itself is mathematically correct.
    """
    import torch
    slot = manager.lora_index_to_id.index(adapter_id)
    adapter = manager.get_adapter(adapter_id)
    result = {}
    for name, module in manager.modules.items():
        assert module.tp_size == 1, 'Identity probe supports TP1 only'
        shadow = copy.copy(module)
        for attr in ('lora_a_stacked', 'lora_b_stacked'):
            original = getattr(module, attr)
            buffers = tuple(torch.zeros_like(t[:1], device='cpu') for t in as_tuple(original))
            setattr(shadow, attr, buffers if isinstance(original, (tuple, list)) else buffers[0])
        weights = manager._get_lora_layer_weights(adapter, name)
        def cpu(value):
            if isinstance(value, list):
                return [cpu(t) for t in value]
            return None if value is None else value.detach().cpu()
        if weights is not None:
            shadow.set_lora(0, cpu(weights.lora_a), cpu(weights.lora_b))
        for attr in ('lora_a_stacked', 'lora_b_stacked'):
            for index, (actual, expected) in enumerate(zip(as_tuple(getattr(module, attr)), as_tuple(getattr(shadow, attr)))):
                assert actual.dtype == torch.bfloat16
                observed = tensor_digest(actual[slot])
                assert observed == tensor_digest(expected[0]), (name, attr, index, 'GPU slot differs from CPU adapter')
                result[f'{name}/{attr}/{index}'] = observed
    assert result, 'No adapter buffers inspected'
    digest = hashlib.sha256(repr(sorted(result.items())).encode()).hexdigest()
    return dict(adapter_id=adapter_id, slot=slot, buffer_count=len(result), sha256=digest,
                buffers=result, cpu_reconstruction_matches=True)


def check_kernel_metadata(args, expected_slot):
    """Inspect the exact grouped row/slot metadata supplied to shrink/expand."""
    mapping, rows, counts, starts, slots, no_lora, active_count = args[3:10]
    mapping = mapping.cpu().tolist()
    rows = rows.cpu().tolist()
    counts = counts.cpu().tolist()
    starts = starts.cpu().tolist()
    slots = slots.cpu().tolist()
    assert mapping and not bool(no_lora.item())
    assert all(s == expected_slot for s in mapping), ('token mapping', mapping, expected_slot)
    covered = []
    for i in range(int(active_count.item())):
        if slots[i] == -1:
            continue
        assert slots[i] == expected_slot, ('active slot', slots, expected_slot)
        assert starts[i + 1] - starts[i] == counts[i]
        covered.extend(rows[starts[i]:starts[i + 1]])
    assert sorted(covered) == list(range(len(mapping))), ('grouped token rows', covered)
    return len(mapping)


class ProbeWorker:
    def training_lora_state(self):
        import os
        import psutil
        import torch
        manager = self.model_runner.lora_manager._adapter_manager
        active = manager._active_adapters
        active = active.cache if hasattr(active, 'cache') else active
        return dict(registered=sorted(manager.list_adapters()), active=sorted(active),
                    slot_to_adapter=list(manager.lora_index_to_id),
                    capacity=manager.capacity, slots=manager.lora_slots,
                    allocated=torch.cuda.memory_allocated(), reserved=torch.cuda.memory_reserved(),
                    rss=psutil.Process(os.getpid()).memory_info().rss)

    def training_lora_fingerprint(self, adapter_id):
        return slot_fingerprint(self.model_runner.lora_manager._adapter_manager, adapter_id)

    def training_lora_trace(self, adapter_id=None):
        """Arm for one sequential request, or disarm and return aggregate evidence.

        No changes to kernels/weights. Wrappers inspect their actual input tensors;
        this is not an instruction-level audit of Triton GPU execution.
        """
        import vllm.lora.punica_wrapper.punica_gpu as punica
        if adapter_id is None:
            evidence = self._identity_trace
            self._identity_trace = None
            for name, original in self._identity_originals.items():
                setattr(punica, name, original)
            evidence['missing_calls'] = sorted(set(evidence.pop('expected_calls')) - set(evidence['calls']))
            return evidence
        assert not getattr(self, '_identity_trace', None), 'Trace already armed'
        manager = self.model_runner.lora_manager._adapter_manager
        fingerprint = slot_fingerprint(manager, adapter_id)
        expected = {}
        required = set()
        adapter = manager.get_adapter(adapter_id)
        for name, module in manager.modules.items():
            for op, attr in [('lora_shrink', 'lora_a_stacked'), ('lora_expand', 'lora_b_stacked')]:
                expected[(op, tuple(t.data_ptr() for t in as_tuple(getattr(module, attr))))] = name
                # vLLM also wraps untargeted linears, including conv1d storage
                # accessed directly by GDN. Require execution only for weights
                # actually present in this adapter; still inspect every observed
                # kernel call and fingerprint every allocated slot buffer.
                if manager._get_lora_layer_weights(adapter, name) is not None:
                    required.add(name + '/' + op)
        assert required, 'Adapter has no targeted modules'
        self._identity_trace = dict(adapter_id=adapter_id, slot=fingerprint['slot'],
                                    fingerprint=fingerprint['sha256'], calls={}, checked_token_rows=0,
                                    required_call_count=len(required), expected_calls=sorted(required))
        self._identity_originals = {op: getattr(punica, op) for op in ('lora_shrink', 'lora_expand')}
        def wrap(op, original):
            def checked(*args, **kwargs):
                trace = self._identity_trace
                assert manager.lora_index_to_id[trace['slot']] == trace['adapter_id']
                count = check_kernel_metadata(args, trace['slot'])
                key = (op, tuple(t.data_ptr() for t in args[1]))
                assert key in expected, ('unexpected weight buffers', op)
                label = expected[key] + '/' + op
                trace['calls'][label] = trace['calls'].get(label, 0) + 1
                trace['checked_token_rows'] += count
                return original(*args, **kwargs)
            return checked
        for op, original in self._identity_originals.items():
            setattr(punica, op, wrap(op, original))
        return dict(armed=True, adapter_id=adapter_id, slot=fingerprint['slot'])
