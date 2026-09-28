# FP8 trainer hybrids: feasibility and bounded probes

**Decision after review:** the user chose to retain NF4 training and pause this
custom integration. The recommendations/probes below document the investigation;
they are not active work or authorization for another GPU run. See the current
[training plan](../training-plan.md#precision-and-rollout-policy).

Reviewed 2026-09-16. **Neither hybrid is an existing supported recipe. Hybrid A
is the smaller next experiment for this project, but is not a drop-in Megatron
model replacement inside `AsyncGRPOTrainer`. Hybrid B preserves the mature
Megatron optimizer path but requires broader changes to generation semantics.**
Keep the tested NF4/TRL stack available. No production trainer was replaced and
no cloud resources were allocated during this investigation.

The objective remains policy alignment with adapter-only communication. Sharing
the label “FP8” does not establish numerical alignment, and neither hybrid fixes
the previously measured Hopper duplicate FP8 storage by itself.

## Source snapshots

Moving branches were resolved before inspection:

| Component | Inspected revision |
| --- | --- |
| NeMo-RL main | `1cef394359aeddf1eaf4f1d209208be7b6ec0b1a` |
| Megatron Bridge main | `6821931f8ed82f9d2f228a4dd537fab26775cdde` |
| TRL project pin | `a04ffd337108285002df29d9ae73ef7e855e03f1` |
| TRL main | `98dcd1876ece4659662b16472770d1ebd73884c5` |
| Open NeMo PR #3964 head | `5f42cb8b34c6a8d540ded74bd5a830172d632514` |
| Previously GPU-tested Bridge/container source | `151168f36372132c8fb8f926501f573019feb967` |

The two inspected TRL `async_grpo_trainer.py` files are byte-identical, SHA256
`15951bb122c4477ba82aeeb24ad85b35dd46fd8489f244364837dc958919af99`.
This is a source comparison, not a mutually compatible environment lock.

## Corrections to the handover

The main conclusion is supported: the Megatron worker exports full HF weights
for refit, with Bridge's adapter merge enabled by default. The adapter-only
exporter exists separately. See the
[worker export path](https://github.com/NVIDIA-NeMo/RL/blob/1cef394359aeddf1eaf4f1d209208be7b6ec0b1a/nemo_rl/models/policy/workers/megatron_policy_worker.py#L2980)
and [tested Bridge export defaults](https://github.com/NVIDIA-NeMo/Megatron-Bridge/blob/151168f36372132c8fb8f926501f573019feb967/src/megatron/bridge/models/conversion/auto_bridge.py#L504).

Two details matter:

- PRs [1748](https://github.com/NVIDIA-NeMo/RL/pull/1748),
  [1751](https://github.com/NVIDIA-NeMo/RL/pull/1751) and
  [1752](https://github.com/NVIDIA-NeMo/RL/pull/1752) were **still open/unmerged**
  at inspection. They are proposals, not evidence of a previously shipped native
  adapter path. [1797](https://github.com/NVIDIA-NeMo/RL/pull/1797) and
  [1889](https://github.com/NVIDIA-NeMo/RL/pull/1889) merged the full-weight paths.
- [PR 3964](https://github.com/NVIDIA-NeMo/RL/pull/3964) is still open. Its
  [validation](https://github.com/NVIDIA-NeMo/RL/blob/5f42cb8b34c6a8d540ded74bd5a830172d632514/nemo_rl/models/generation/vllm/config.py#L350)
  rejects Megatron, async engines, exposed HTTP serving, quantized rollout modes
  and speculative decoding; it requires DTensor v2/HF naming and matching
  supported policy/rollout precision. More importantly, its
  [installer](https://github.com/NVIDIA-NeMo/RL/blob/5f42cb8b34c6a8d540ded74bd5a830172d632514/nemo_rl/models/generation/vllm/vllm_backend.py#L870)
  removes and replaces **one stable adapter ID**. Increasing `max_loras` does not
  create version retention or episode leases.

## Comparison

These are engineering judgments from the call paths, not measured implementation
times. A narrow one-GPU experiment and a maintainable training system have very
different scope.

| Concern | A: existing rollout stack + Megatron training service | B: NeMo trainer + custom versioned generation |
| --- | --- | --- |
| GRPO loss | Can reuse pinned TRL loss; CPU boundary tested | Existing NeMo loss/training path retained |
| Backward/optimizer/checkpoint | New integration; HF Trainer cannot own a remote autograd graph | Existing Megatron machinery largely retained |
| Browser rollout and policy leases | Existing core logic retained; controller-specific helpers need adaptation | Must integrate browser bridge and leases into NeMo lifecycle |
| Adapter export | Bridge exporter qualification needed | Same prerequisite |
| Publication | Connect exporter to current immutable publication protocol | Replace full-policy refit plus add native versioned serving |
| Multi-turn/version metadata | Existing contract, still needs new-controller wiring | Carry adapter version through collector, turns, requests and replicas |
| Distributed training | Excluded from initial A probe | Existing NeMo advantage, but versioned serving still custom |
| First useful experiment | Smaller: single-rank loss/update/export | Larger before testing the required concurrent-episode behavior |

**Recommendation:** qualify the shared adapter exporter with the prepared tiny
probe, then assess a narrowly scoped A training service. Do not commit to a full
AsyncGRPOTrainer fork yet. B becomes more attractive if distributed training is
required, or upstream adds native Megatron adapter refit and version-aware async
generation. Neither production implementation is clearly a small patch.

## Hybrid A: actual integration boundary

`AsyncGRPOTrainer.__init__` creates an HF model from a model identifier, inspects
HF configuration, patches its LM head, applies PEFT, and delegates training to HF
Trainer/Accelerate. `_init_lora_sync`, `_sync_weight_lora` and checkpoint saving
also assume that model/PEFT ownership. `rollout_worker` and `weight_transfer`
injection points are not a pluggable training-backend interface. See the
[pinned trainer](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_grpo_trainer.py#L1041).

The reusable boundary is `compute_loss`: differentiable selected-token logprobs
and entropy, plus token-aligned masks, behavior logprobs and advantages. Reusing
that function avoids inventing another GRPO objective. It does not preserve the
entire trainer automatically. A service must own forward, backward, optimizer,
scheduler, checkpoint/resume and atomic adapter export in one process. Sending
detached logprobs back to HF Trainer would break backward.

Minimum batch contract:

- Full token history, positions, attention/padding mask and generated-token loss
  mask; browser observations remain input context but contribute no direct loss.
- Behavior logprobs aligned to token positions, already computed under the
  reserved episode policy. The loss drops position zero for next-token alignment.
- Per-token advantages from the existing complete-group reward processing;
  group/episode IDs, policy version and sampling configuration travel alongside.
- Effective token denominator and accumulation convention. The pinned loss
  already divides by gradient accumulation; do not divide twice.

The initial implementation must stay single trainer GPU, TP/PP/DP=1, one
trajectory per microbatch, no independent-sequence packing. Extending the full
vocabulary logprob wrapper to TP, pipeline schedules or chunked vocabulary
projection is separate work. The diagnostic named `kl` in this loss compares
behavior/current probabilities; it is not an SFT-reference KL penalty.

NeMo-RL itself is not required for this isolated model/loss/export calculation;
Core, TE and Bridge supply the model and export APIs. The already-tested NeMo
container is a convenient dependency package. Our TRL environment uses Python
3.12/PyTorch 2.13/Transformers 5.16.1; the tested NeMo policy environment uses
Python 3.13/PyTorch 2.11/Transformers 5.8.1. Combining those installations is
unqualified. A separate service avoids that dependency collision but adds a
batch/checkpoint/publication protocol. The present probes implement no service.

## Hybrid B: exact patch surfaces

The existing optimization implementation lives in `MegatronPolicyWorker.train`
and [Megatron training utilities](https://github.com/NVIDIA-NeMo/RL/blob/1cef394359aeddf1eaf4f1d209208be7b6ec0b1a/nemo_rl/models/megatron/train.py).
Its distributed scheduling, token normalization and optimizer handling are the
main reason to retain NeMo.

For Megatron policy → vLLM, inspect these layers:

1. `MegatronPolicyWorker.prepare_refit_info`, `_build_refit_conversion_tasks`,
   `_calculate_refit_param_info`, `_iter_params_with_optional_kv_scales` and
   `broadcast_weights_for_collective`: metadata and payload must both switch to
   adapters. Replacing just the tensor iterator leaves incompatible metadata.
2. `create_weight_synchronizer` selects `CollectiveWeightSynchronizer` for the
   default separate-GPU deployment, or `IPCWeightSynchronizer` when colocated.
   **`MegatronWeightSynchronizer` means a Megatron generation backend**, not the
   usual Megatron-trainer/vLLM path. See the
   [factory](https://github.com/NVIDIA-NeMo/RL/blob/1cef394359aeddf1eaf4f1d209208be7b6ec0b1a/nemo_rl/weight_sync/factory.py)
   and [collective synchronizer](https://github.com/NVIDIA-NeMo/RL/blob/1cef394359aeddf1eaf4f1d209208be7b6ec0b1a/nemo_rl/weight_sync/collective_weight_synchronizer.py).
3. `VllmGeneration.prepare_refit_info` and update methods lead into generation
   workers/backend weight installation. A native adapter manager needs immutable
   IDs, publication acknowledgments, capacity/backpressure and unload handling.
4. [Async worker `generate_async`](https://github.com/NVIDIA-NeMo/RL/blob/1cef394359aeddf1eaf4f1d209208be7b6ec0b1a/nemo_rl/models/generation/vllm/vllm_worker_async.py#L1411)
   currently calls `self.llm.generate` without `lora_request`. vLLM's request API
   is the appropriate underlying mechanism, but the inspected NeMo worker does
   not expose per-episode adapter selection. Add it through every turn, including
   text/multimodal request variants that the project actually uses.

`AsyncTrajectoryCollector` captures `generation_weight_version`, reserves target
training versions, and applies an age/lead window. `_process_batch`,
`_run_rollout_batch_worker`, `_collect_rollout_batch` and `_enqueue_rollout_group`
carry that bookkeeping. **Metadata is not a reservation on an inference
adapter.** `prepare_for_refit` either drains work or pauses requests while the
globally current policy is refitted. With in-flight updates, preserving a request
does not preserve its old policy. See the
[collector](https://github.com/NVIDIA-NeMo/RL/blob/1cef394359aeddf1eaf4f1d209208be7b6ec0b1a/nemo_rl/algorithms/async_utils/trajectory_collector.py).

Supporting concurrent v17/v18 browser episodes therefore also needs a lease at
group/episode start, explicit adapter IDs on each inference call, stale-episode
cancellation, request draining before unload, and failure/checkpoint recovery.
`VllmGeneration._async_generate_base` can distribute requests across DP shards:
all eligible replicas need the leased adapter, or routing must remain pinned.
See [generation routing](https://github.com/NVIDIA-NeMo/RL/blob/1cef394359aeddf1eaf4f1d209208be7b6ec0b1a/nemo_rl/models/generation/vllm/vllm_generation.py#L1023).
Our `PolicyRegistry` logic is reusable, but its trainer hooks are not a complete
NeMo integration. This is why B is larger than an exporter substitution.

## Shared export and alignment gates

Bridge's [adapter-only API](https://github.com/NVIDIA-NeMo/Megatron-Bridge/blob/151168f36372132c8fb8f926501f573019feb967/src/megatron/bridge/models/conversion/auto_bridge.py#L681)
reads the live adapter tensors. There is no required merged-base checkpoint
between optimizer updates. Finish the optimizer step before exporting; for
distributed models all participating ranks must enter the required gathers.

The [PEFT converter](https://github.com/NVIDIA-NeMo/Megatron-Bridge/blob/151168f36372132c8fb8f926501f573019feb967/src/megatron/bridge/models/conversion/peft_bridge.py)
splits fused QKV, gate/up and GDN adapter outputs, repeating the shared input
factor. This avoids the earlier raw-FP8 base merge failure in principle, but the
actual physical-FP8 model → adapter-only export is still untested on GPU.

Two less obvious compatibility points:

- The tested Bridge `save_hf_adapter` casts tensors to FP32; the
  [inspected current saver](https://github.com/NVIDIA-NeMo/Megatron-Bridge/blob/6821931f8ed82f9d2f228a4dd537fab26775cdde/src/megatron/bridge/models/conversion/auto_bridge.py#L982)
  preserves dtype. The prepared probe verifies BF16 raw export and explicitly
  restores BF16 serialization for the older saver, then checks exact equality.
  This does not change optimizer parameter dtype.
- Fused Megatron LoRA shares an input factor across split projections; separate
  HF adapters need not have that restriction. Our tiny probe also targets fused
  GDN `in_proj`, including `in_proj_a/b`, whereas the tested HF configuration
  excludes a/b. Equal rank does not imply equal parameterization. Do not silently
  drop exported projections. Resuming independently trained HF adapters into a
  shared-factor Megatron adapter may require higher rank or a different layout.

A persistent rollout base may need a **one-time** aligned export from the
trainer's frozen base. TE's effective weight/activation quantization and vLLM's
official checkpoint representation/kernels can differ. No per-update full-base
transfer is intended, but zero-adapter and nonzero-adapter comparisons on
identical token histories are required before claiming improved alignment.

## What was tested and what is prepared

Local **PASS**: [CPU probe](../../training/scripts/probe_grpo_loss_boundary.py)
extracts the unchanged, hash-checked upstream `compute_loss`, attaches a
synthetic frozen-BF16 model with BF16 trainable factors, and checks token alignment,
masking, accumulation, clipping, positive/negative advantage gradients, updates
and unchanged base. [Result](../../training/research/hybrid-loss-boundary-validation.json).
This proves a tensor interface, not an actual AsyncGRPOTrainer/Megatron run.

From repository root, using the existing RL environment:

```bash
training/envs/rl/.venv/bin/python training/scripts/probe_grpo_loss_boundary.py \
  --output training/outputs/hybrid-loss-boundary.json
```

It fetches only the 102 KB pinned official source, or accepts `--source` for an
offline cached copy. The workstation emitted a CUDA driver warning from the
installed PyTorch build, but all tensors and execution in this probe were CPU.

Prepared, **NOT executed on GPU**:
[Megatron probe](../../training/scripts/probe_megatron_grpo_adapter.py). It uses
the previously exercised tiny GDN/full-attention builder, the same upstream
loss, one SGD update and Bridge's adapter-only export/save APIs. It checks
physical frozen FP8 storage, BF16 gradients, nonzero adapter updates, QKV/GDN
export presence and BF16 file round-trip. It deliberately has no cloud launcher.
Both new scripts passed syntax/CLI checks locally.

After a separately authorized Hopper allocation, in the previously pinned
container and from a mounted repository root, the intended command is:

```bash
/opt/ray_venvs/nemo_rl.models.policy.workers.megatron_policy_worker.MegatronPolicyWorker/bin/python \
  training/scripts/probe_megatron_grpo_adapter.py \
  --source /path/to/pinned-async_grpo_trainer.py \
  --output /persistent/probes/hybrid-a-001/report.json
```

Use the source URL/hash from the CPU probe. The container digest and earlier
runtime inventory are in [Hopper evidence](../../training/research/nemo-fp8-modal-validation.json).
For Modal, a future bounded launcher must include both new scripts, the existing
`nemo_fp8_probe.py` and that source file; the existing Modal launcher has not been
silently expanded. Apply the usual external timeout and preserve failure output.

The prepared test is not yet the full requested proof: it needs a GPU execution
and then a native vLLM load/numerical comparison. Its random reduced Qwen3.5-family
model is an integration proxy, not Qwen3.8-27B qualification. Its SGD step does
not qualify production Adam state, scheduler, optimizer resume or GRPO learning.

Next gates, in order: tiny adapter-only export → vLLM adapter equivalence →
aligned frozen-base comparison → decide whether to build A's controller or B's
generation integration. Stop before that investment if alignment or memory
benefit is insufficient. No full hybrid solution has been built.
