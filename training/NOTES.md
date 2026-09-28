# Infrastructure research — 2026-09-15

**Current status (2026-09-19): actual 27B NF4/BF16-LoRA SFT and core AsyncGRPO learning both passed on L40S.** SFT held-out apple-format accuracy rose 0/16 → 16/16 after saved-adapter reload; eight RL updates improved the rewarded choice from 34/64 → 64/64 through the final natively synchronized FP8 vLLM policy. Monitored AsyncGRPO now also passes three updates → exact checkpoint restoration → three further updates on a two-turn synthetic task, with 24 applied rows. The test found and fixed PEFT's FP32 adapter promotion on resume; [details and source links](../docs/agents/training-gpu-acceptance.md). SFT intermediate-checkpoint resume, runtime adapter lifecycle/identity, and CPU BrowserGym/OpenEnv policy-session checks also passed. All test containers stopped. The first model-driven P11 browser/GRPO test now completed two optimizer steps, BF16 checkpointing and native adapter publication, but failed the final shutdown guard; a CPU-tested drain fix still needs GPU requalification. Its applied groups had zero reward variance, so it demonstrates no browser learning. [P11 evidence](research/modal-project-browser-grpo-validation.json). Sustained/long-context training, SM120 GPU execution, MTP and numerical parity remain unqualified.

Start with the [consolidated findings and forward plan](../docs/training-findings.md) and [SSH deployment handoff](../docs/agents/training-modal-preflight.md#ssh-deployment-handoff). Latest evidence: [SFT learning](research/modal-sft-learning-validation.json), [RL learning](research/modal-e2e-validation.json).

**Updated experiment decisions:** [training plan](../docs/training-plan.md). The desired representation is now explicitly FP8 frozen base + BF16 LoRA throughout, conditional on a supported training path. The [FP8 recheck below](#fp8-trainer-recheck--16-september-2026) still finds a native trainer blocker; NF4 remains the demonstrated fallback. Proposed 16k contexts, ranks and learning rates are experimental settings, not new validated defaults.

**Historical scope:** the numbered answers below record the initial FP8/BF16 investigation. Their candidate/fallback choices and CPU-only status statements are superseded where indicated by the dated follow-ups and current summary. The GPU-tested trainer now uses NF4, not the original BF16 fallback or unqualified FP8 trainer candidate. Numerical investigations remain paused; no extended experiment or published deployment image exists.

**NeMo alternative:** [isolated Hopper experiments](#hopper-experiment-results--16-september-2026) now pass FP8-base/BF16-LoRA backward checks in native TE/Megatron linear layers and a reduced Qwen hybrid model, including checkpointing. They also show two distinct FP8 weight orientations occupying approximately BF16-sized GPU storage. The hybrid assertions completed before a process-exit timeout; full 27B NeMo GRPO/export remains unqualified.

## 1. Cleanest supported BF16 LoRA on a frozen FP8 base?

There is no GPU-qualified, stock end-to-end path for this exact stack in this repository yet. Axolotl advertises frozen `FineGrainedFP8Config` + LoRA, separately from `fp8: true`. Its fused LoRA implementation can dequantize FP8 blocks to BF16 inside autograd-capable operations. That is the SFT candidate we prepared: official FP8 checkpoint, `adapter: lora`, explicit text projection targets, BF16 adapter storage, fused QKV/O/MLP kernels, FLA/packing patch, BF16 activations and FP32 Adam moments. It does **not** promise FP8 GEMMs during training. [Axolotl precision matrix](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/docs/support-matrix.qmd), [block dequantization implementation](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/src/axolotl/kernels/quantize.py), [fused LoRA autograd](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/src/axolotl/kernels/lora.py).

Plain Transformers' fine-grained FP8 quantizer reports `is_trainable=False`; successfully loading it or wrapping it in PEFT does not establish a supported backward path through frozen quantized layers. Freezing parameters does not eliminate the need for input gradients through those layers. Consequently, the RL configuration uses a **BF16 frozen trainer base** with FP8 inference and does not try to copy Axolotl's monkeypatches into TRL. [Pinned quantizer](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/quantizers/quantizer_finegrained_fp8.py), [FP8 linear implementation](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/integrations/finegrained_fp8.py).

## 2. Official FP8 checkpoint or BF16 + Axolotl FP8 mixed precision?

For serving and experimenting with reduced **weight storage**, choose the official FP8 checkpoint. Its config specifies dynamic fine-grained E4M3 quantization with 128×128 blocks and explicit unquantized exclusions. Many norms, vision weights, decay parameters and embeddings are not FP8; the correct invariant is “quantized frozen linears + higher-precision frozen exceptions,” not “every base parameter is FP8.” [Official config at the pinned revision](https://huggingface.co/Qwen/Qwen3.8-27B-FP8/blob/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a/config.json).

`fp8: true` selects torchao mixed-precision compute and retains higher-precision master weights; it does not implement the desired memory layout. We leave it off. Given a 96 GB training GPU, an initial BF16-base LoRA run at 2K context is a practical fallback with fewer integration dependencies. [Axolotl mixed precision](https://docs.axolotl.ai/docs/mixed_precision.html), [FP8 configuration source](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/src/axolotl/core/fp8.py).

## 3. Which modules should LoRA target?

The model's architecture is **`Qwen3_5ForConditionalGeneration`**, with 64 text layers: 48 Gated DeltaNet layers and 16 full-attention layers. It is dense, so MoE expert/router targeting is irrelevant. [Pinned model config](https://huggingface.co/Qwen/Qwen3.8-27B/blob/1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0/config.json).

Our conservative qualified-suffix list:

| Block | Targets |
|---|---|
| Full attention | `self_attn.q_proj`, `k_proj`, `v_proj`, `o_proj` |
| Dense MLP | `mlp.gate_proj`, `up_proj`, `down_proj` |
| Gated DeltaNet | `linear_attn.in_proj_qkv`, `in_proj_z`, `out_proj` |

Do not target convolution, `A_log`, `dt_bias`, `in_proj_a/b`, norms, vision, embeddings, `lm_head`, or MTP initially. The full-attention Q projection includes an output gate; it is not an ordinary ungated Qwen2 attention block. These names follow the model implementation and Axolotl's architecture guide. The optimal subset is an experiment, not an upstream guarantee. [Transformers model implementation](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/models/qwen3_5/modeling_qwen3_5.py), [Axolotl Qwen3.5 guide](https://docs.axolotl.ai/docs/models/qwen3.5.html).

Rank 16 / alpha 32 / dropout 0 is the baseline; rank 32 / alpha 64 is an exposed alternative. All three MLP projections are included because the fused MLP path requires adapters on all three. Axolotl's fused DeltaNet input operation also includes the frozen a/b projections without requiring LoRA on them. [Kernel attachment logic](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/src/axolotl/monkeypatch/lora_kernels.py).

## 4. Can the vision tower be frozen or ignored?

Yes for text-only observations/actions: no image inputs enter the vision forward, and PEFT freezes all base parameters. Our target names exclude vision. Assert that all trainable names are LoRA and inspect the resulting count. A loaded-but-unused tower still occupies memory; avoid treating “frozen” as “removed.” The pinned TRL implementation also freezes non-text components for VLM training. [TRL model initialization](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_grpo_trainer.py#L1082).

vLLM has `--language-model-only` for the text-serving use case; our FP8 preset uses it. Do not rewrite the training checkpoint's nested config into a causal-LM model or strip weights manually just to save the vision allocation. Screenshots can later be added as a separate multimodal experiment; current AsyncGRPO's text-only VLM handling does not provide multimodal GRPO. [Qwen3.8 serving recipe](https://recipes.vllm.ai/Qwen/Qwen3.8-27B).

## 5. Does Axolotl fully support this exact FP8 LoRA SFT combination?

**Architecture support exists; this precise combination is a GPU-unverified candidate.** Qwen3.8-27B reuses the supported Qwen3.5 architecture. Axolotl's tagged source has gated-Q attention rewrite patterns, Gated DeltaNet fused projection operations and packing-boundary resets. Do not interpret a generic support-matrix checkmark as a successful run of this checkpoint, version, quantizer and GPU combination. [Gated attention/LoRA patch](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/src/axolotl/monkeypatch/lora_kernels.py), [DeltaNet forward/packing patch](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/src/axolotl/monkeypatch/models/qwen3_5/modeling.py).

The implementation choices are:

| Feature | Prepared choice and reason |
|---|---|
| BF16 fallback attention | SDPA, unpacked; no external attention build |
| FP8 candidate attention | FA2 + packing; requires optional `flash-attn==2.8.3` |
| Packing | FLA 0.5.2; Axolotl's patch passes boundaries to recurrent attention |
| Fused LoRA kernels | Enabled only on FP8 candidate; required to avoid relying on plain FP8 inference backward |
| Checkpointing | Non-reentrant gradient checkpointing; no CPU/disk activation offload initially |
| CCE | Architecture supported, not enabled in baseline |

The DeltaNet patched forward is installed behind `sample_packing` in this Axolotl release. Enabling only the LoRA kernel flags in an unpacked FP8 config is insufficient to ensure that its attached DeltaNet operations are actually called. This is why the FP8 config uses packing while the simpler fallback does not. [Patch-manager conditions](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/src/axolotl/loaders/patch_manager.py).

CCE's integration lists Qwen3.5 and recommends Axolotl's fork at commit `4dfa52212d0552805aec5a6a2176c0abbea277d2`. It is a useful second experiment for the 248,320-token vocabulary. Add it as a locked optional source dependency and enable `axolotl.integrations.cut_cross_entropy.CutCrossEntropyPlugin` only after the baseline passes. It is not currently installed by our locks; do not combine an unpinned `pip install -U` with a claimed reproducible experiment. [CCE integration](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/src/axolotl/integrations/cut_cross_entropy/README.md).

## 6. How are BF16 adapters guaranteed?

Axolotl supports **`peft_autocast_adapter_dtype: false`** and passes it to both `get_peft_model` and `PeftModel.from_pretrained`. The default PEFT behavior otherwise promotes adapters. FP8-inherited adapter tensors also need conversion to a usable compute/storage dtype; Axolotl explicitly handles that case. [Axolotl adapter loader](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/src/axolotl/loaders/adapter.py), [PEFT factory parameter](https://github.com/huggingface/peft/blob/v0.20.0/src/peft/mapping_func.py).

Our public Axolotl plugin additionally casts **only trainable LoRA A/B parameters** to BF16, checks that every other parameter is frozen, and writes counts/dtypes. A callback re-enforces BF16 after checkpoint resume and checks finite gradients before every optimizer step. Serialized adapter headers can be checked without loading torch or the base. CPU tests reproduced FP32→BF16 conversion and rejection of dtype drift; full PEFT+27B checks are remote-only.

AsyncGRPO does not expose `autocast_adapter_dtype`; the launcher casts `trainer.model`'s LoRA parameters after construction and before optimizer creation/first sync. This uses ordinary parameter conversion, not a replacement trainer. Both paths use **bitsandbytes AdamW32bit**: BF16 parameter/gradient storage, FP32 first/second moments. The callback checks actual initialized moment tensors after updates. BF16 gradients are higher precision than the FP8 base; they are not falsely advertised as FP32. [AdamW32bit API](https://huggingface.co/docs/bitsandbytes/reference/optim/adamw).

## 7. Exact compatible versions?

There is **no single mutually compatible released environment** for all components. We resolved independent Linux x86-64/Python 3.12 locks against published dependency metadata:

| Component | SFT | RL + vLLM |
|---|---|---|
| Python | 3.12.12 | 3.12.12 |
| PyTorch / torchvision | 2.13.0 / 0.28.0 | 2.13.0 / 0.28.0 |
| Transformers | 5.16.1 | 5.16.1 |
| PEFT | 0.20.0 | 0.20.0 |
| Accelerate | 1.13.0 | 1.13.0 |
| Axolotl | 0.19.0 | absent |
| TRL | 1.9.0, required by Axolotl | commit `a04ffd337108285002df29d9ae73ef7e855e03f1` (1.14.0.dev0) |
| vLLM | absent | 0.28.0 |
| FLA | 0.5.2 | 0.5.2 |
| bitsandbytes | 0.50.2 | 0.50.2 |
| FlashAttention | optional FA2 2.8.3 build | default kernel-hub FA3; opt-in FA2 2.8.3 + audited loader patch |
| kernel-hub loader | 0.16.1, resolved | 0.16.0, explicit |
| OpenEnv | openenv-core 0.1.0, unused Axolotl dependency | openenv 0.4.2 |

The environment-service lock pins **openenv 0.4.2** and BrowserGym core/MiniWoB 0.14.3, whose Playwright dependency resolves to 1.44.0. Runtime validation exposed and corrected the previous openenv-core 0.3.0 pin: its StepResult rejects the current client’s metadata argument. The two OpenEnv distributions own the same Python namespace and must not be co-installed. The environment team owns the actual BrowserGym OpenEnv service package and task assets; our bridge imports neither Chromium nor tasks into the trainer.

Axolotl 0.19.0 pins TRL 1.9.0, Transformers 5.16.1 and Accelerate 1.13.0. Current released TRL **1.13.0 lacks the `peft_config` argument** in AsyncGRPO; main has it. vLLM 0.29.0 is newer, but the researched TRL dependency range stops at 0.28.0. We choose 0.28.0 rather than mixing latest packages. The old docs' Transformers conflict workaround (`--no-deps`) is unnecessary for these resolved versions. [Axolotl release metadata](https://pypi.org/pypi/axolotl/0.19.0/json), [TRL released constructor](https://github.com/huggingface/trl/blob/v1.13.0/trl/experimental/async_grpo/async_grpo_trainer.py), [TRL source dependency range](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/pyproject.toml), [vLLM release dependencies](https://pypi.org/pypi/vllm/0.28.0/json).

The locks first established consistent declared constraints; both installed environments now also pass CPU import/config/adapter tests. This still does not establish CUDA ABI/kernel compatibility. In particular the hardcoded FA3 artifact is fetched at runtime, outside the Python wheel lock, and is not Blackwell-qualified. There is no honest fully reproducible Blackwell AsyncGRPO image to claim until that is addressed.

## 8. Native AsyncGRPO BF16-LoRA → vLLM runtime sync?

**Adapter synchronization: yes in the pinned source commit. Desired whole-episode policy pinning: requires our locally tested patch.** The trainer detects `--enable-lora`, saves versioned PEFT directories and registers new names. It validates maximum rank and adapter capacity and rejects unsupported PEFT variations. Our launcher refuses the full-weight fallback and excludes `lm_head`, which this trainer's chunked loss cannot adapt correctly. [Adapter synchronization implementation](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_grpo_trainer.py#L1740).

The worker's `_generate_one_turn` reads `_request_model` anew. That property reads the shared current version. Its multi-turn loop does not snapshot an episode policy. Our initial two-method probe has now been strengthened: the complete upstream worker class, generation loop, HTTP method, scoring and token reconciler ran unchanged against a local scripted HTTP endpoint. Both episodes requested v1 on turn 0 and v2 on turns 1–2 after a forced version update. The reward group still carries a group-level version, which cannot truthfully describe mixed-policy turns. This contradicts the documentation's broader retention claim. [Pinned worker](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_rollout_worker.py#L854), [full-loop CPU evidence](research/rollout-validation.json), [documentation claim](https://huggingface.co/docs/trl/main/en/async_grpo_trainer#lora).

The subsequently authorized project patch now reserves a policy per GRPO group, preserves it across each episode’s model calls, and prevents eviction until reservations drain. Stale groups stop requesting inference and are discarded in full. Native adapter save/load/unload remains unchanged as a transport; there is no new vLLM server or weight-transfer implementation. This is a local orchestration fix, not yet a GPU correctness certification. See the policy-reservation validation below.

## 9. Required hardware/filesystem/NCCL topology?

Two distinct GPUs are the documented baseline. A single host substantially simplifies shared paths, process management and networking. Start ordinary `vllm serve` with:

```bash
CUDA_VISIBLE_DEVICES=0 VLLM_SERVER_DEV_MODE=1 \
VLLM_ALLOW_RUNTIME_LORA_UPDATING=1 VLLM_WORKER_MULTIPROC_METHOD=spawn \
vllm serve Qwen/Qwen3.8-27B-FP8 \
  --enable-lora --lora-dtype bfloat16 --max-lora-rank 32 --max-loras 4 \
  --max-model-len 4096 --max-num-seqs 8 \
  --logprobs-mode processed_logprobs \
  --weight-transfer-config '{"backend":"nccl"}'
```

The executable launcher adds the exact model revision and other conservative flags. These environment names/CLI options exist in vLLM 0.28.0. The canonical NCCL configuration remains present, but **adapter-only payloads are loaded from shared disk** under `output_dir/.vllm_lora/`. One trainer GPU needs no training all-reduce; the NCCL smoke separately validates peer communication for later TP/FSDP use. Server data parallelism is unsupported by this adapter-registration implementation. [vLLM LoRA config](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/config/lora.py), [vLLM environment flags](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/envs.py), [TRL sync-mode selection](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_grpo_trainer.py#L836).

Separate machines need the same absolute shared adapter path and private HTTP reachability. NCCL transport setup is required only when actually using a distributed collective/full-weight transfer path. Persistent checkpoint storage is separate from the rotating serving cache; save real checkpoints, not just `.vllm_lora` directories.

## 10. Is OpenEnv's BrowserGym integration mature enough to use?

It is a sensible integration to adapt, not proof that this exact asynchronous training combination is production-ready. OpenEnv has a BrowserGym client/action/observation schema and a harness tutorial; TRL has a BrowserGym GRPO example. The published BrowserGym tutorial uses the trainer-owned `generate_rollout_completions` / `build_harness_rollout_func` path, which should not be mislabeled a ready-made AsyncGRPO example. [OpenEnv BrowserGym tutorial](https://github.com/meta-pytorch/OpenEnv/blob/da5929566e99c8eb376a47042b316cb13c0aae29/docs/source/tutorials/browsergym-harness.md), [TRL BrowserGym example](https://github.com/huggingface/trl/blob/v1.13.0/examples/grpo_browsergym/grpo_browsergym.py).

Prefer AsyncGRPO's native **`environment_factory`** when the trainer owns each tool-generation turn: reset provides an observation, public methods expose browser actions, and subsequent observations become tool context. In this pinned worker the environment-owned reward API is **`get_reward()`**, called on the final environment state before reuse. Do not copy a synchronous `reward_func(environments=...)` callback unchanged: AsyncGRPO's ordinary reward callbacks receive completions/prompts/dataset columns, while stateful rewards are collected through `get_reward`. Factories/callbacks must be picklable and live in importable modules. [Worker environment discovery and scoring](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_rollout_worker.py#L400).

Token mechanics: each model call records prompt IDs, output IDs and behavior logprobs. The native reconciler tracks chat-template retokenization drift, masks tool/observation tokens from the loss and may fork a conversation into several training sequences. One completed browser episode is one rollout/reward unit, **not necessarily one tensor row**; its group's advantage is attached to the resulting sequences. Do not flatten a trajectory to text and discard logprobs. [Native reconciliation code](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_rollout_worker.py#L65).

The native `HarnessRolloutWorker` loop and `BrowserGymSessionFactory` now pass CPU browser integration with the small task-selection/tool-argument adapters described below; use that existing loop. Browser service concurrency must be configured for the episode count: OpenEnv's default one session is insufficient. Each rollout needs isolated browser state. [TRL harness integration](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/openenv_harness.py), [OpenEnv concurrency guidance](https://huggingface.co/docs/trl/main/en/openenv#environment-server-concurrency).

The supplied OpenEnv bridge explicitly uses `client.sync()` because AsyncGRPO calls environment reset synchronously inside an active event loop. It maps the project's `task` to BrowserGym server's actual `task_name` argument. A real Chromium/BrowserGym/OpenEnv round-trip now checks both contracts, with two overlapping sessions, success/failure rewards, observation masks and aligned logprobs. The bridge also preserves the separately supplied task goal, URL and action errors. [OpenEnv client execution modes](https://github.com/meta-pytorch/OpenEnv/blob/da5929566e99c8eb376a47042b316cb13c0aae29/src/openenv/core/env_client.py), [BrowserGym reset signature](https://github.com/meta-pytorch/OpenEnv/blob/da5929566e99c8eb376a47042b316cb13c0aae29/envs/browsergym_env/server/browsergym_environment.py#L237).

## 11. Does MTP work with FP8 + runtime LoRA, and are RL logprobs correct?

The official vLLM recipe reports native Qwen3.8 MTP working with FP8, including SM120 measurements, using `--speculative-config '{"method":"mtp","num_speculative_tokens":3}'`. That supports testing FP8+MTP; it is **not a test of runtime-changing LoRA + FP8 + MTP**. vLLM has Qwen3.5 LoRA tests and separate speculative-LoRA tests, but no combined test for this exact trio was found in the inspected tagged source. The `lora-mtp` preset is therefore an optional inference experiment, disabled in RL. [Recipe](https://recipes.vllm.ai/Qwen/Qwen3.8-27B), [Qwen3.5 LoRA test](https://github.com/vllm-project/vllm/blob/v0.28.0/tests/lora/test_qwen35_densemodel_lora.py), [speculative-LoRA tests](https://github.com/vllm-project/vllm/blob/v0.28.0/tests/v1/e2e/spec_decode/draft_model/test_lora.py).

Standard speculative rejection sampling is designed to preserve the **target** sampling distribution; vLLM's rejection sampler derives accepted-token logprobs from target logits, not draft probabilities. We request `processed_logprobs` and use temperature 1, top-p 1, top-k 0 in TRL to align behavior logprobs with its temperature-scaled training loss. This source-level property does not establish numerical equivalence for every quantized LoRA kernel. Do not use approximate acceptance modes as a shortcut. [Pinned rejection sampler](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/v1/sample/rejection_sampler.py), [speculative decoding guarantees](https://docs.vllm.ai/en/v0.28.0/features/speculative_decoding/).

The supplied adapters do not target/train MTP. As the target policy changes, a frozen draft's acceptance can decline; that affects speed, not the theoretical target distribution under correct rejection sampling. Shared model components and runtime kernel behavior still need empirical verification. Compare baseline vs MTP before/after at least two distinct adapters, old-adapter stability, finite token logprobs, seeded greedy outputs and repeated sampled distributions. Record accepted/draft counters and high-concurrency throughput; a lower per-request latency is not evidence of higher saturated throughput. The current scripts exercise registration/logprob shape and collect counters, but do not claim a statistical distribution-equivalence test.

## 12. Easiest reproducible deployment?

Prebuild the separate **uv environments on a CPU image builder**, keep them in an image/persistent volume, and preload revision-pinned Hugging Face snapshots. A known provider CUDA 13.0 devel base is useful when building FA2; no custom Dockerfile is needed to duplicate provider driver/container setup. Python dependencies and major CUDA libraries are locked. Run dependency/import checks there, then the GPU preflight immediately after allocation. [PyTorch release metadata](https://pypi.org/pypi/torch/2.13.0/json), [CUDA 13.0.3 driver requirement](https://docs.nvidia.com/cuda/archive/13.0.3/cuda-toolkit-release-notes/index.html).

Kernel-hub artifacts fetched by the trainer are a remaining reproducibility hole. The pinned AsyncGRPO source hardcodes `kernels-community/flash-attn3`; that kernel's current build manifest lists SM80/SM90a, **not SM120**. `model_init_kwargs` cannot simply override it because the trainer supplies an explicit `attn_implementation` argument. Installing FA2 does not make the trainer choose FA2. We prepared a hash-guarded, one-line opt-in loader patch to let model_init_kwargs select FA2 while preserving the FA3 default. This changes argument forwarding only, not training or synchronization. The FA2 build/import checks now pass on CPU; varlen forward/backward still needs an SM120 GPU test. The artifact and dispatch findings below are stronger than inferring failure from a missing architecture entry alone. [Hardcoded trainer backend](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_grpo_trainer.py#L1074), [kernel build manifest](https://github.com/huggingface/kernels-community/blob/555c2e89f4afb8b03c65ec619251db7b6806c287/flash-attn3/build.toml), [FA2 SM120 build support](https://github.com/Dao-AILab/flash-attention/blob/v2.8.3/setup.py).

## 13. Likely VRAM at useful contexts?

These are **planning envelopes, not measurements**. Assumptions: one training GPU, microbatch 1, non-reentrant checkpointing, no full-model optimizer state, text-only input, no reference model, no retained cache during training. Activations, temporary dequantization, logits, padding and kernel workspaces dominate uncertainty. Start at 2K and measure before extending.

The actual pinned Transformers/PEFT model instantiated on the meta device confirms **108,789,760 LoRA parameters at r16** (800 tensors), or **217,579,520 at r32**. All ten target suffixes match text projections; no vision or MTP parameters are trainable. This validates structure, not hybrid forward/backward execution. [Installed CPU/meta evidence](research/sft-cpu-validation.json). BF16 parameters + BF16 gradients + two FP32 Adam moments cost approximately **1.22 / 2.43 GiB**, excluding bookkeeping/workspaces. The rank increase is relatively small compared with base and activations. A 27B checkpoint is not simply 27 GB total runtime memory: large embeddings/head and unquantized exceptions matter. [Model dimensions](research/bf16-config.json), [quantization exclusions](research/fp8-config.json).

| Per-GPU path, rank 16 | 2K context | 4K | 8K |
|---|---:|---:|---:|
| SFT FP8 storage candidate, packed FA2 | 42–58 GiB | 52–72 GiB | 70–96+ GiB |
| SFT BF16 base fallback, SDPA | 64–80 GiB | 72–92 GiB | 88–112+ GiB |
| RL BF16 trainer, chunked head, one sequence/row | 60–80 GiB | 64–88 GiB | 78–104+ GiB |

Add about 1.2 GiB for r32 over r16, plus possible kernel workspace changes. Actual residency may fall outside these estimates. The FP8 server's weights are roughly 29–32 GiB before KV/recurrent cache, graph capture and adapter slots; the official recipe's two-GPU figure is 14.28 GiB weights per GPU. With our `gpu_memory_utilization=0.85`, vLLM deliberately reserves most of its GPU for caching. Rank/version count also adds adapter residency. [Measured serving reference](https://recipes.vllm.ai/Qwen/Qwen3.8-27B).

The 16 full-attention layers alone use approximately **64 KiB/token with BF16 KV** (16 × 2 × 4 KV heads × 256 head dimension × 2 bytes), or 32 KiB/token in FP8. Eight 4K sequences therefore need roughly 2 GiB of attention KV, **plus** DeltaNet recurrent state, cache block overhead and scheduling buffers. This is a sizing calculation, not a vLLM allocation prediction. Use the engine's startup cache report and measured peak VRAM. Gradient accumulation changes effective batch more cheaply than increasing microbatch; increasing context can be much more expensive than doubling LoRA rank.

## 14. Important blockers and experimental features?

1. **Locally fixed, GPU-unverified:** our hash-guarded patch fixes group/episode policy pinning and retention in CPU regressions. Qualify real vLLM request/eviction behavior before enabling production browser RL.
2. **Source mismatch:** main-doc AsyncGRPO LoRA APIs are absent from released TRL 1.13.0. Use the pinned commit; upgrade it deliberately and rerun the source audit.
3. **Blackwell attention prerequisite:** default FA3 selects Hopper kernels for SM100/103/120. The opt-in FA2 build/loader patch enables a qualification attempt; GPU execution remains unverified. SFT/serving checks remain available.
4. **FP8 SFT composition:** requires fused autograd and DeltaNet packing integration, not just a successful FP8 load. GPU probe and BF16 fallback are prepared; no unsupported quantizer flags are patched away.
5. **Hybrid RL packing correctness:** the trainer resets position IDs but does not reset DeltaNet state between packed samples. `token_budget=0`, microbatch 1 and one trainer process avoid multi-sample rows. This is a configuration workaround, not an implementation of custom packing. [AsyncGRPO hybrid-model warning](https://huggingface.co/docs/trl/main/en/async_grpo_trainer#vision-language-models).
6. **FP8 serving vs BF16 trainer:** the frozen bases have quantization differences. Behavior logprobs must be retained and training/serving ratio diagnostics monitored; do not assume exact equality. No full merged sync is allowed against the FP8 server.
7. **MTP combination unqualified:** no default RL MTP; measure runtime adapter changes, acceptance and logprobs first.
8. **Environment integration:** real CPU browser round-trips pass after updating OpenEnv to 0.4.2 and selecting Uvicorn’s websockets backend. Native TRL tools execute synchronously and stall the event loop. Its OpenEnv harness has a session thread pool. Our patch adds reservations and closes sessions created after stop; both have CPU regressions. Final tasks, bounded operation deadlines and production throughput remain to validate.
9. **Resume semantics:** checkpoints preserve trained prompt position/model version, not in-flight episodes. Checkpoint-and-resume needs a real GPU smoke before relying on recovery. [Checkpoint implementation](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_grpo_trainer.py#L1799).

The next useful GPU session starts with the **seconds-long SM120 FA2 kernel probe**, then short SFT/serving and one-turn RL qualification if prerequisites pass. Multi-turn browser RL remains gated until the local reservation fix passes actual vLLM GPU qualification and the production harness/action contract is supplied.

## Follow-up validation: BrowserGym and SM120

### What actually ran locally

The installed browser stack is now `openenv==0.4.2`, BrowserGym 0.14.3 and Playwright 1.44.0, using cached Chromium 125.0.6422.26. `scripts/smoke_browser.sh` ran two overlapping successful browser episodes and two subscription-failure episodes through the **unmodified upstream BrowserGym client/server**, real OpenEnv WebSocket transport, our bridge and the complete upstream `_AsyncRolloutLoop` class. The fixture uses a local HTML page with a button/input, no external task data. Success was 1, failure was 0, prompt/tool observations were masked, and generated tokens retained their aligned logprobs. Sessions closed and were replaced successfully for the next group. Two additional sessions exercise the official OpenEnv BrowserGymSessionFactory and MCPHarnessAdapter, stopping at environment completion after two model calls for success or one for failure. The measured ~9 seconds for all six episodes is smoke-test wall time, not a browser throughput benchmark. [Recorded result](research/browser-validation.json).

Heavy TRL imports and tokenizer/schema helpers are replaced in this CPU harness. The generation loop, tool dispatch, HTTP request code, scoring and token reconciler execute from the hash-checked upstream file unchanged. Inference is a real local HTTP endpoint returning scripted tokens/logprobs, and the tokenizer is synthetic. This does **not** establish Qwen chat-template correctness, vLLM behavior, model gradients, spawned-worker behavior or training success. The separate forced-update test demonstrates v1→v2 within each episode while both scored samples remain labeled v1. [Full-loop test](scripts/validate_rollout_worker.py), [recorded policy defect](research/rollout-validation.json).

Three integration issues were fixed before GPU allocation:

1. `openenv-core==0.3.0` imported successfully but rejected the current BrowserGym client's `StepResult(metadata=...)` at runtime. The renamed distribution `openenv==0.4.2` provides that field and the harness interfaces TRL imports. Both browser/RL locks now use it; verification rejects co-installing the old distribution. [Release](https://pypi.org/project/openenv/0.4.2/), [client construction](https://github.com/meta-pytorch/OpenEnv/blob/da5929566e99c8eb376a47042b316cb13c0aae29/envs/browsergym_env/client.py#L105), [StepResult schema](https://github.com/meta-pytorch/OpenEnv/blob/da5929566e99c8eb376a47042b316cb13c0aae29/src/openenv/core/client_types.py).
2. Our bridge previously discarded the separate task goal; it now includes goal, URL, page text and action errors. Reset failures also release the client. These have local regression tests.
3. Uvicorn's default `websockets-sansio` transport logged disconnect exceptions on every normal client close. Explicit `ws="websockets"` removed those errors in the rerun. This is a tested server option, not a server patch. The only missing Chromium OS library was libasound; the local test used a private extraction of Ubuntu's package rather than altering system libraries.

### SM120: stronger evidence and a practical path

The published FA3 CUDA-13 stable-ABI artifact also declares only `8.0` and `9.0a`; this is not merely a stale documentation table. The dispatch macro sends architecture values >=90, including SM100/103/120, into its `Arch=90` specialization. NVIDIA explicitly says `compute_90a` PTX is not forward-compatible with Blackwell. We therefore have a concrete source/artifact reason to avoid this FA3 path. We have **not** downloaded/disassembled the binary or demonstrated its failure on a GPU. [Pinned artifact metadata](https://huggingface.co/kernels-community/flash-attn3/raw/e29f138fc363b396e5d2706c8a5f6fa7d36f41e0/build/torch-stable-abi210-cu130-x86_64-linux/metadata.json), [dispatch macro](https://github.com/huggingface/kernels-community/blob/555c2e89f4afb8b03c65ec619251db7b6806c287/flash-attn3/flash-attn/static_switch.h#L138), [NVIDIA compatibility rules](https://docs.nvidia.com/cuda/blackwell-compatibility-guide/index.html#application-compatibility-on-blackwell-architecture).

FA2 2.8.3 explicitly builds `compute_120/sm_120` with CUDA >=12.8. The optional `rl-sm120` bootstrap builds it and applies **one local compatibility line** to TRL's loader, allowing the existing `model_init_kwargs` to choose FA2 without a duplicate keyword. The full upstream file hash must match before/after patching; unknown modifications fail. CPU validation reproduces the original TypeError, checks default FA3 and explicit FA2 selection, checks revision/dtype forwarding and idempotence, and records the patched source hash. No RL or synchronization logic is changed. [FA2 setup](https://github.com/Dao-AILab/flash-attention/blob/v2.8.3/setup.py#L189), [patch and artifact evidence](research/sm120-validation.json).

The first GPU test is `verify_attention.py`: BF16 causal varlen attention with Qwen's actual 24 query heads, 4 KV heads and head dimension 256; compare output and all Q/K/V gradients to separate-sequence FP32 math references; perturb one sequence to detect cross-sequence leakage. Then test the tiny model, then the hybrid 27B model. Passing FA2 alone cannot certify DeltaNet kernels or end-to-end training. Keep the actual RL microbatch=1 restriction even if this primitive's packing test passes.

Hardware fallback: RTX PRO 6000 is SM120; B200/GB200 are SM100; B300/GB300 are SM103; H100/H200/GH200 are SM90. NVIDIA's current table does not list SM102 for those rental candidates. SM100/103 do **not** solve this particular hardcoded Hopper-FA3 path automatically. Hopper is the direct match for the audited FA3 artifact, but the episode-policy bug is hardware-independent. Prefer testing the prepared FA2 route on SM120 before changing the hardware plan. [NVIDIA GPU capability table](https://developer.nvidia.com/cuda/gpus).

### Native harness, tokenization and shutdown validation

The native worker executes synchronous browser tools directly on its event loop, so one slow browser step delays other episodes. `max_inflight_tasks` is not a guarantee of parallel tool execution. TRL's existing `HarnessRolloutWorker` runs sessions in a thread pool and cleans up live sessions on stop; it is the better existing interface to evaluate for browser throughput. Its white-box `_sample_turn` still calls the same `_generate_one_turn`, so it does not solve policy pinning. The full upstream `_HarnessRolloutLoop` now executes against real OpenEnv/BrowserGym sessions, including its thread pool, model callback and token reconciler. This qualifies the tested CPU loop; it does not execute the spawned worker process or trainer gradients. [Native tool dispatch](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_rollout_worker.py#L921), [native harness session pool](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/openenv_harness.py#L145).

The retention probe also executes the upstream sync and queue-consumption methods with a mock transport: at max_staleness=2, publishing v4 unloads v1, keeps v2–v4, drops queue samples with lag 3 and accepts lag 2. Sync has no active-episode reference check. Merely pinning the name inside each episode would therefore expose a subsequent unloaded-adapter failure; retention or explicit episode cancellation must accompany that fix. This is a source-method test, not a live vLLM eviction test.

The harness probe runs two stable-policy browser episodes, two forced-update episodes, and two episodes using the **actual Qwen3.8 tokenizer and TRL response parser**. Prompt and tool tokens stay masked; generated tokens retain aligned logprobs. The forced-update case reproduces mixed versions through the harness too. Two additional shutdown probes use bounded mock sessions. Existing sessions close promptly, but stop during `session_factory.create()` misses the not-yet-registered session; the worker waits for its deadline. Ensure bounded factory creation and session/request deadlines before real tasks. [Harness evidence](research/harness-validation.json), [probe](scripts/validate_harness_worker.py).

Two small interface fixes were necessary: TRL passes the conversation as the factory’s `task`, whereas BrowserGymSessionFactory expects a task name; `TaskSelectingSessionFactory` performs that mapping. OpenEnv serializes tool arguments to JSON strings, but Qwen3.8’s template expects a dictionary; `MappingArgumentsHarnessAdapter` normalizes that representation without replacing OpenEnv’s agent loop. The unadapted cases are reproduced in the test. OpenEnv’s `LLMResponse` conversion also drops `reasoning_content`; keep thinking disabled for harness rollouts until reasoning survives this round trip. [Project adapters](browser_training/harness_bridge.py), [upstream conversion and lifecycle](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/openenv_harness.py).

Actual tokenizer validation caught a separate SFT issue: inline `<think>` content creates duplicate reasoning blocks with the official template, while Axolotl’s older `qwen3_5` override removes earlier reasoning. The converter now emits `reasoning_content`; real-model configs use `tokenizer_default` with `preserve_thinking: true`. Enable reasoning with `run_sft.sh --enable-thinking`. Six examples cover action/reasoning-action × trajectory/state-action: actual Axolotl prompter/labeling classes supervise all intended actions/reasoning and mask task/observations. This is source-class execution with lightweight import replacements, not an installed Trainer run. The official template also matches TRL’s known Qwen3.8 template, and its real response parser decodes browser tool calls. [Tokenization evidence](research/tokenization-validation.json), [official template](https://huggingface.co/Qwen/Qwen3.8-27B/blob/1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0/chat_template.jinja), [Axolotl labeling](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/src/axolotl/prompt_strategies/chat_template.py).

The pinned BF16 and FP8 checkpoints have identical Hugging Face Git blob IDs for `tokenizer.json`, `tokenizer_config.json`, and `chat_template.jinja`; the tokenizer checks apply to both checkpoints.

The converter’s current plain-action targets and the harness’s structured tool-call output must be aligned before production SFT→RL. The converter remains modular rather than inventing the final project action format.

GPU time is needed for FA2 kernel execution, hybrid forward/backward and training/sync qualification. Browser integration, tokenizer correctness and dependency import checks can be tested first on CPU. The workstation’s GTX 1070 cannot qualify BF16/FP8 or SM120 kernels.


### Installed SFT/RL environments

The approved wheel installations use the existing locks in isolated environments. Both environments pass `uv pip check` and package imports, including AsyncGRPOTrainer’s PEFT interface. All three actual Axolotl config schemas and both AsyncGRPO config schemas pass. A tiny randomly initialized Qwen3 model completes two CPU updates with PEFT 0.20.0: LoRA parameters and gradients are BF16, bitsandbytes Adam moments are FP32, and saved/reloaded adapters remain BF16. A separate meta-device construction validates the actual Qwen3.8 architecture and adapter targets without allocating model weights. [SFT CPU report](research/sft-cpu-validation.json), [RL CPU report](research/rl-cpu-validation.json). All six SFT tokenizer cases also pass using installed Axolotl classes without import substitutions. [Installed tokenization report](research/sft-tokenization-validation.json). The installed vLLM CLI accepts all three presets, with and without optional tools/FP8-KV/eager flags; no engine is created.

The installed Torch 2.13 wheel reports CUDA 13.0 and compiled targets `sm_75 sm_80 sm_86 sm_90 sm_100 sm_120`. This confirms native SM120 inclusion in PyTorch itself, not FA2/DeltaNet/vLLM execution. The workstation driver exposes CUDA 12.6 and the GTX 1070 is SM61, so these wheels cannot execute locally on that GPU. FLA imports on CPU with a warning; bitsandbytes’ optional 4-bit CPU GEMM emits a kernel-hub warning, but the tested AdamW32bit CPU updates succeed. GPU optimizer kernels remain untested.


A compiler smoke found an additional **real dependency incompatibility** despite `uv pip check` passing: CUDA NVCC 13.0.88 depended on unconstrained `nvidia-nvvm`, which resolved to 13.4.59. The front end generated PTX 9.4; the 13.0 assembler rejected it with `Unsupported .version 9.4; current version is 9.0`. The RL lock now also pins **nvidia-nvvm 13.0.88**. With that correction, the wheel-provided compiler/headers/libraries compile and disassemble a 5,840-byte SM120 cubin containing BF16/FP8 conversion types. This checks compilation only; no CUDA kernel executes. `rl-sm120` automatically uses this bundled toolkit when neither CUDA_HOME nor system NVCC is available, and checks it before the FA2 build. [Failure evidence](research/cuda-toolchain-before-fix.json), [passing compiler evidence](research/cuda-toolchain-validation.json), [NVIDIA’s published NVVM 13.0.88 wheel](https://pypi.org/project/nvidia-nvvm/13.0.88/).


A further tiny Qwen3.5 hybrid forward probe reached FLA’s Triton kernel and failed with `0 active drivers`. The Transformers decorator selects installed FLA ahead of its Torch reference function, even for a CPU tensor; the FLA import warning does not imply its training kernels run on CPU. We did not monkeypatch that path to claim qualification. Real hybrid forward/backward remains a GPU check. [Pinned fallback selection](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/integrations/hub_kernels.py).


The installed `HarnessRolloutWorker` now also runs through its **actual spawn controller and child process**, without source/import substitutions. One successful episode and one subscription-failure episode produce rewards 1/0 and native group advantages approximately +1/−1. The browser service stays in the separate browser environment. A module-level task selector, upstream BrowserGym factory and our argument-normalizing adapter survive pickling. Actual Qwen tokenization, HTTP turn generation, environment scoring, rollout queue transport, heartbeat and clean exit are covered; trainer gradients and live vLLM synchronization are not. [Spawned-worker probe](scripts/validate_spawned_harness.py), [result](research/spawned-harness-validation.json).


The installed CPU probe also calls native `AsyncGRPOTrainer._sync_weight_lora` and `save_lora_adapter` with a real tiny PEFT model and CPU Accelerator. Four distinct BF16 snapshots are atomically published, older files retain their hashes, and the native HTTP client sends requests accepted by vLLM’s real load/unload schemas. Registration precedes publication of the new policy version; v4 unloads v1 at max_staleness=2. The receiver is a local mock, so this does **not** establish engine-side adapter application, FP8 inference correctness or NCCL behavior. [Native-publication evidence](research/rl-cpu-validation.json).


The complete pinned FA2 2.8.3 build subsequently compiled **all 73 units for SM120** and exposed a final-link issue: the CUDA Python runtime wheel omits the unversioned `libcudart.so` development name, and NVCC’s default layout does not find the flattened wheel’s library directory. Bootstrap now creates a private linker symlink under `.cache/cuda-devel-link-libs` and supplies the proper library search path; it changes no system/toolkit library. The compiler probe now tests host linking too, so these errors fail before a lengthy FA2 compile. [Failed link](research/cuda-toolchain-link-before-fix.json), [passing compile/link](research/cuda-toolchain-validation.json).

The resulting ~66 MB wheel imports successfully against Torch 2.13.0+cu130. Its installed extension matches the wheel byte-for-byte; build flags contain only `compute_120/sm_120`. The manifest includes the original sdist hash, wheel/extension hashes, Python/toolchain versions and required GLIBC/GLIBCXX symbols. This is **build and import qualification only**. No FA2 forward/backward, FP8 model load or 27B training has run. Both SFT and RL bootstrap variants accept `FA2_WHEEL` plus `FA2_WHEEL_SHA256` to avoid compiling on a rental. Keep the artifact in persistent storage; it is deliberately outside Git. [Build manifest](research/flash-attn-build.json).

Both prebuilt bootstrap variants now pass: `sft-packing` and `rl-sm120` install the verified wheel, import its extension and pass dependency checks. The RL variant applies the expected hash-guarded TRL loader patch. No recompilation or GPU execution is required for this install path. Training manifests now include environment-lock hashes and the FA2 extension hash. The locally tested uv version is 0.10.8, which is also the bootstrap fallback pin.


## Policy-reservation implementation and CPU validation

The project patch is in [policy_compat.py](browser_training/policy_compat.py), with the lifecycle implementation in [policy_sessions.py](browser_training/policy_sessions.py). `scripts/patch_trl_policy.py --apply` verifies all three upstream file hashes, refuses unknown or partially patched source, and composes with the FA2 attention patch in either order. RL bootstrap applies it automatically, including after the optional kernel build's package synchronization. The original source audit remains unchanged and intentionally reproduces the upstream bug.

A local multiprocessing manager owns the registry on the trainer host. Group acquisition and version publication are serialized. Every episode has an ID and a fixed group-policy version; context explicitly crosses the OpenEnv thread pool. Reservations last through browser waits and outstanding HTTP calls, including cancellation. New groups use the latest published policy. Late-starting siblings use their group's original policy.

When publication exceeds `max_staleness`, the group is marked cancelled. Further model calls are rejected; existing requests drain. Failed or cancelled groups produce no training rows, including previously successful siblings. Retired adapters can be unloaded and their files removed only after all group/session references release. The trainer uses the existing native PEFT save and vLLM HTTP registration/unload calls.

The CPU integration test executes **installed patched TRL**, its real spawned worker, real OpenEnv/BrowserGym sessions, the actual Qwen tokenizer/parser and native adapter publication with tiny random BF16 PEFT files. The HTTP model server is scripted and validates native vLLM load/unload schemas; it also refuses unknown adapter names and eviction during outstanding requests. In the pinning scenario, v2 is published during two v1 requests; the successful episode's second turn remains v1 and both samples retain v1 metadata. In the staleness scenario, v4 is published while two v1 requests are held; v1 remains registered, its stale group is discarded, then v1 unloads after draining. Fresh v4 episodes yield rewards 1/0, advantages approximately +1/-1, masked observations and aligned token logprobs. Both workers exit normally. [Integration evidence](research/policy-session-validation.json).

Local regression tests additionally cover publication/acquisition races, late-starting siblings, repeated cancellation while HTTP is outstanding, ambiguous timeout quarantine, capacity exhaustion, complete-group rejection on factory failure, delayed session creation during shutdown, durable episode/version events and source-patch drift/composition. Run `envs/browser/.venv/bin/python -m pytest -q tests/test_policy_sessions.py tests/test_policy_harness.py` from `training/`; run `bash training/scripts/smoke_browser.sh --policy-sessions` from the repository root for the installed/spawned browser regression.

Limits are deliberate: one trainer process; white-box harness only; cooperative cancellation waits for browser/factory deadlines; `max_staleness + 2` registered-version capacity. If stale sessions cannot drain before that capacity is needed, synchronization stops safely rather than evicting active adapters. Inference timeout/transport errors are not retried because the remote request may still be running; the registry prohibits eviction and the run must restart vLLM before checkpoint resume. A killed worker likewise quarantines its reservations. No custom distributed transport, real model rollout, GPU kernel, or optimizer training was introduced for this fix. `policy-events.jsonl` provides run/group/episode/version and request/eviction lifecycle provenance; runtime reservations are not checkpointed.

Next GPU test: on the small smoke model, hold an actual vLLM generation across adapter publication, verify the old name remains usable through later turns, cancel a stale group, and confirm unload only follows request/session drain. Repeat with FP8 Qwen on qualified hardware afterward. Browser fixtures and scripted inference establish orchestration behavior, not the GPU engine's request-cancellation or adapter-residency semantics.


## NF4 QLoRA trainer investigation — 48 GB L40S / RTX A6000

**Conclusion:** an NF4 trainer plus BF16 LoRA is a credible next candidate for 48 GB hardware. It is not yet a qualified AsyncGRPO configuration. Keep the existing BF16 fallback until the loader/preparation and GPU tests below pass. The rollout server can remain FP8, subject to quantization-mismatch measurements.

### What ran locally

`PYTHONPATH=. envs/rl/.venv/bin/python scripts/validate_qlora_cpu.py` (from `training/`) uses tiny randomly initialized checkpoints and the installed pinned environment, with CUDA and Hub access disabled. [Recorded evidence](research/qlora-cpu-validation.json).

- Ordinary Qwen3: 14 genuine bitsandbytes NF4 linears, double quantization, uint8 packed storage and BF16 compute. Two CPU forward/backward/Adam updates pass with BF16 LoRA parameters and gradients, FP32 optimizer moments, unchanged frozen base parameters, and adapter save/reload verification. Loss on the fixed random batch moves from 4.16853 to 4.14362; this demonstrates plumbing, not learning quality.
- Tiny Qwen3.8 architecture (`Qwen3_5ForConditionalGeneration`): the hybrid model loads with 13 NF4 text projections; vision, output head and DeltaNet `in_proj_a`/`in_proj_b` remain unquantized. The real pinned AsyncGRPO constructor, with only its model loader substituted to return the already-loaded CPU model, fails at the VLM text-model unfreeze: `only Tensors of floating point dtype can require gradients`. This happens before adapter attachment or a trainer update.
- Manual standard k-bit preparation followed by PEFT wrapping succeeds on that hybrid model and keeps the selected adapters BF16. Its forward reaches FLA/Triton and stops because there is no supported accelerator driver. No hybrid backward or GPU kernel is certified by the ordinary-Qwen CPU test.
- Native `Qwen3_5ForCausalLM.from_pretrained` loads the text-only model from the same tiny multimodal checkpoint with zero missing/unexpected keys and no vision allocation. Its packed text weights match the multimodal model. This avoids the VLM constructor branch, but routing this loader through AsyncGRPO and checking the changed adapter prefixes against vLLM remain outstanding.

### Supported candidate and integration work

The original on-load candidate uses the **BF16 source checkpoint** `Qwen/Qwen3.8-27B`, quantized with bitsandbytes; do not feed the existing FP8 checkpoint to an NF4 loader. A prequantized NF4 checkpoint is an alternative and is now the SFT candidate below. Neither route needs representative calibration data. Earlier on-load settings, exercised by the probe:

```python
BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
    bnb_4bit_compute_dtype=torch.bfloat16,
    llm_int8_skip_modules=["lm_head", "model.visual", "in_proj_a", "in_proj_b"],
)
```

Despite the option's name, the pinned 4-bit quantizer uses `llm_int8_skip_modules` too. Use the qualified `model.visual` prefix: the short string `visual` does not exclude descendants such as `model.visual.blocks.0.attn.qkv` in this Transformers version. Preserve the existing explicit text LoRA targets and BF16 dtype assertions. [Pinned quantizer](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/quantizers/quantizer_bnb_4bit.py), [module matching](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/quantizers/quantizers_utils.py), [official QLoRA preparation](https://huggingface.co/docs/peft/developer_guides/quantization).

The pinned AsyncGRPO loader forwards `model_init_kwargs`, so a bitsandbytes config can reach `from_pretrained`. However, its VLM branch enables gradients on the entire text model before adding PEFT, including integer-packed base weights. It also omits `prepare_model_for_kbit_training`. The smallest conservative integration is to skip base unfreezing for quantized PEFT training and prepare the frozen k-bit model **before** adding adapters; calling that helper after LoRA attachment freezes the adapters too. Alternatively qualify the native text-only loader, its configuration routing and exported adapter-name mapping. Neither change is installed as a production QLoRA path in this investigation. [Pinned trainer](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_grpo_trainer.py), [PEFT preparation implementation](https://github.com/huggingface/peft/blob/v0.20.0/src/peft/utils/other.py), [text-only architecture](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/models/qwen3_5/modeling_qwen3_5.py), [native prefix conversion](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/conversion_mapping.py).

Unlike the fine-grained FP8 inference loader, bitsandbytes implements input gradients through frozen NF4 linears. Standard PEFT preparation promotes **all non-quantized BF16/FP16 parameters to FP32**, not only norms. This includes large embeddings/output heads and retained vision parameters, so memory arithmetic must include them. Do not globally cast the packed model back to BF16; preserve packed weights and explicitly control adapter storage. The probe uses standard preparation plus `autocast_adapter_dtype=False` and our BF16 adapter check. [bitsandbytes backward](https://github.com/bitsandbytes-foundation/bitsandbytes/blob/0.50.2/bitsandbytes/autograd/_functions.py), [adapter dtype controls](https://huggingface.co/docs/peft/developer_guides/troubleshooting).

### Memory and hardware assessment

Metadata-only sizing for the full conditional-generation architecture, retaining vision and excluding the above sensitive projections from quantization:

| Component | Estimated GiB |
| --- | ---: |
| Frozen NF4 base, BF16 exceptions | 17.33 |
| Frozen NF4 base after standard PEFT FP32 promotion | 22.97 |
| Rank-16 BF16 adapters + BF16 gradients + FP32 Adam moments | 1.22 |
| Rank-32 BF16 adapters + BF16 gradients + FP32 Adam moments | 2.43 |

The two base rows are alternatives, not additive. The BF16-exception row is a storage scenario, not an implemented alternative preparation policy. Counts: 24,326,963,200 quantizable text-linear elements and 3,029,765,360 unquantized elements. Packed-scale storage assumes NF4 blocks of 64 and nested scale blocks of 256, omitting small alignment/codebook terms. Activations, temporary dequantized matrices, FLA/attention workspaces, allocator overhead and loading peaks are **not included**. Standard preparation plus rank 16 is about 24.2 GiB before these costs, making a 48 GB card plausible at short contexts with checkpointing and microbatch 1. No supported maximum context length is claimed; test 2K, then 4K and 8K. Text-only loading may save further memory.

L40S is Ada SM89 with 48 GB; RTX A6000 is Ampere SM86 with 48 GB (distinct from RTX 6000 Ada). Both fit the hardware requirements for BF16 FlashAttention-2 and bitsandbytes QLoRA. Prefer benchmarking L40S first if rental rates are close; consider A6000 if its measured cost per useful trainer update is lower. Published peak FLOPS are not a measured QLoRA speed ratio. [NVIDIA capabilities](https://developer.nvidia.com/cuda/gpus), [L40S specifications](https://www.nvidia.com/en-us/data-center/l40s/), [RTX A6000](https://www.nvidia.com/en-us/products/workstations/rtx-a6000/), [FA2 support](https://github.com/Dao-AILab/flash-attention#nvidia-cuda-support).

The current cached FA2 wheel is **SM120-only** and cannot qualify either trainer card. Prepare a separate FA2 artifact including the SM80 build target used for Ampere/Ada support; pinned FA2 2.8.3's build selector recognizes `80`, `90`, `100`, `120`, so do not assume `FLASH_ATTN_CUDA_ARCHS=86` or `89` generates the desired binary. Keep the existing attention-loader override and qualify head dimension 256 forward/backward with no dropout, then the model's DeltaNet kernels. This research did not start another kernel build. [Pinned FA2 build targets](https://github.com/Dao-AILab/flash-attention/blob/v2.8.3/setup.py).

### Matching trainer and rollout resources

Different GPU architectures are acceptable in principle: the one-process trainer and the rollout server exchange adapters through files/HTTP, not a cross-node NCCL training group. A shared host is easier. Separate hosts require a fast shared filesystem mounted at the same absolute adapter path. Rank 16 writes about **208 MiB of adapter tensors per publication**; rank 32 about **415 MiB**. At 1 Gbit/s, rank-16 payload transmission alone has an ideal lower bound of about 1.7 seconds, before filesystem and server-loading overhead. Do not assume separate cheap instances save money if synchronization dominates.

A smaller trainer is sensible only if it keeps pace with accepted rollout groups. NF4 saves memory but incurs dequantization and backward work; it is not a guaranteed throughput improvement. Measure trainer update time, rollout production/consumption rates, queue depth, staleness/discards and synchronization time. A slow trainer can make an expensive rollout GPU generate trajectories that are later discarded.

The NF4 trainer and FP8 rollout base define different numerical policies even at the same LoRA version. Native AsyncGRPO retains behavior logprobs and computes probability ratios, but this does not establish that large quantization differences are harmless. Before a real run, compare identical token sequences with the same adapter across trainer/server: logprob deltas, ratio distribution, clipping fraction and KL diagnostics at initialization and after updates. Preserve the behavior logprobs. If mismatch is excessive, align base precision/quantization or retain the BF16 fallback; no new RL correction algorithm is proposed here.

The subsequent local initialization/SFT tests are recorded below. Next hardware work: short NF4 hybrid forward/backward and checkpoint tests on a 48 GB trainer, then one async iteration against the FP8 rollout server. This also makes a 48+48 GB MIG partition worth revisiting for full-model qualification once the trainer path is ready; simultaneous fit and vLLM behavior remain unverified.

## Pretrained NF4 SFT and TRL initialization validation — September 15

**Recommendation:** qualify NF4 QLoRA for both SFT and the RL trainer. SFT has no separate behavior-policy sampler, so NF4 SFT does not introduce the trainer/rollout probability mismatch discussed above. Reusing the exact same frozen NF4 base for SFT and RL avoids changing the base underneath the SFT adapter. FP8 inference remains an independent choice and still needs probability/quality measurements with that adapter. Lower memory does not guarantee faster updates or equal downstream reward.

The new `configs/sft_qwen38_27b_nf4_qlora.yml` pins `greghavens/Qwen3.8-27B-bnb-4bit` revision `26157380225e427827263c34df23018a1e28dff5`. Its actual config specifies NF4, double quantization, uint8 storage and BF16 compute, excluding `model.visual`, `lm_head` and `mtp` from quantization. Unlike our earlier on-load skip list, its DeltaNet `in_proj_a` and `in_proj_b` are quantized. LoRA targets still exclude those gates. The checkpoint revision restores MTP tensors omitted by an earlier conversion; inspecting names/configs is therefore essential. This is a community conversion, not an official Qwen checkpoint. [Pinned checkpoint config](https://huggingface.co/greghavens/Qwen3.8-27B-bnb-4bit/blob/26157380225e427827263c34df23018a1e28dff5/config.json), [conversion script](https://huggingface.co/greghavens/Qwen3.8-27B-bnb-4bit/blob/26157380225e427827263c34df23018a1e28dff5/quantize.py).

`unsloth/Qwen3.8-27B-unsloth-bnb-4bit` is another candidate, but the inspected config uses FP16 compute and additionally skips `in_proj_qkv` as well as `in_proj_a/b`. It is not interchangeable for memory estimates or base-policy matching. Other FP8 conversions also exist; for example `huginnfork/Qwen3.8-27B-FP8` uses compressed-tensors. A different FP8 format does not by itself provide backward kernels: pinned Transformers explicitly makes its compressed-tensors FP8 kernel path inference-only unless dequantized. [Alternative NF4 config](https://huggingface.co/unsloth/Qwen3.8-27B-unsloth-bnb-4bit/blob/main/config.json), [compressed-tensors trainability](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/quantizers/quantizer_compressed_tensors.py).

**Actual pretrained SFT test:** `scripts/validate_qlora_sft.py` runs the pinned Axolotl stack on cached Qwen3-0.6B using CPU only. Four converted synthetic browser examples pass the real dataset/tokenizer path, with both supervised action tokens and masked context present. The model loads 196 NF4 linears and rank-16 BF16 adapters. Two SFT steps produce `checkpoint-1` and `checkpoint-2`; optimizer, scheduler, RNG and Trainer state files are checked. A new Trainer resumes to step three. Finally the adapters are removed without merging, the NF4 base is saved, and a fresh one-step SFT run exercises Axolotl's prequantized loading branch. Both branches and resume pass BF16 adapter/gradient and FP32 optimizer-moment checks. This tests plumbing, not browser-agent quality or hybrid attention. [Script](scripts/validate_qlora_sft.py), [evidence](research/qlora-sft-validation.json).

Axolotl 0.19's configuration builder does not forward a plain `use_cpu` field to Transformers. Our existing precision plugin now declares that input and forwards it through the public `get_training_args` hook for explicit CPU tests. The plugin also verifies actual NF4 quantization states, BF16 compute and frozen quantized weights. Remote configurations leave `use_cpu` false. Axolotl reads an existing checkpoint's quantization config directly; `bnb_config_kwargs` applies to the on-load conversion branch, so it is not a reliable way to override a prequantized checkpoint's compute dtype or exclusions. The chosen checkpoint already has BF16 compute. [Pinned Axolotl loader](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/src/axolotl/loaders/model.py), [plugin](browser_training/axolotl_plugin.py).

**Actual TRL constructor test:** `scripts/validate_qlora_trl_init.py` loads a saved random tiny hybrid model through the real model loader, with the checkpoint candidate's quantization exclusions. Unmodified initialization reproduces the integer-weight unfreeze failure. An isolated copy of the hash-checked trainer source then skips base unfreezing for 4-bit models, calls PEFT k-bit preparation before adapter attachment, and disables adapter dtype promotion. The constructor completes, vision stays frozen, BF16 adapters export correctly, and TrainingArguments serialize. The probe additionally exercises native `compute_loss` and two FP32-Adam updates on an ordinary tiny Qwen3 with NF4 weights; all 28 adapter-gradient tensors are finite BF16 and base parameters remain unchanged. Inputs/advantages are synthetic and behavior logprobs come from that local model. This is not a generated rollout or a full GRPO training iteration. [Evidence and exact candidate edits](research/qlora-trl-init-validation.json).

Installed TRL is unchanged by this probe; the initialization candidate is not yet a production NF4 RL patch. Production FLA/attention backward still requires suitable GPU hardware, and live FP8-vLLM adapter application remains unqualified. On this workstation the GTX 1070 and CUDA 12.6 driver cannot execute the pinned CUDA 13 stack; available RAM also makes a full 27B trainer load inappropriate. `scripts/validate_nf4_checkpoint.py` instead checks complete cached shard hashes/headers and runs two CPU adapter updates on each of four isolated real projections (DeltaNet QKV and Z, full-attention Q, MLP down). It does not exercise the DeltaNet recurrence or allocate the complete model.

**Further CPU validation:** the TRL probe now also executes the tiny hybrid model's native GRPO loss and two adapter updates using Transformers' own PyTorch DeltaNet and causal-convolution reference functions. The probe disables Hub dispatch (`USE_HUB_KERNELS=NO`) and explicitly selects the unwrapped reference functions within a temporary context; merely disabling Hub kernels would still prefer installed FLA. All 26 hybrid adapter-gradient tensors are finite BF16 and the frozen parameters remain unchanged. This is a complete tiny hybrid reference backward pass, not a test of FLA/Triton, FlashAttention, the full 27B model or a generated rollout. Production dispatch is untouched. [Reference implementations](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/models/qwen3_5/modeling_qwen3_5.py), [dispatch priority](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/integrations/hub_kernels.py).

The SFT probe also passes a separate actual Axolotl `ModelLoader` test on a saved prequantized tiny hybrid checkpoint, using the same quantization exclusions and LoRA targets as the 27B candidate. All 15 quantized projections have BF16 compute, all 26 adapter tensors save as BF16, and vision stays frozen. This validates architecture-specific initialization without executing hybrid attention. The four isolated real checkpoint projections additionally compare outputs and input gradients against explicitly dequantized BF16 linear references; both errors were exactly zero in the CPU checks (assertion tolerances are recorded).

Use the same `HF_HOME` for downloads and launches. Current workstation weight caching uses `$HOME/.cache/huggingface`; shell wrappers default to `training/.cache/huggingface` unless overridden. Export the desired persistent cache path before invoking either. No credentials are embedded. Inter-instance trainer/server traffic is normally called **east–west**; measure adapter-directory visibility and end-to-end publication/loading time as well as bandwidth and HTTP latency.

**Download audit completed:** all seven NF4 weight shards are cached, totaling 19,424,559,530 bytes including headers. SHA256 checks match each Hub content-addressed blob, every indexed tensor is present, and the header audit finds 496 NF4 linears and 15 restored MTP tensors. Tensor payloads comprise 6,861,743,584 BF16 bytes, 6,484,608 FP32 bytes and 12,555,841,098 uint8 bytes. These are on-disk quantities, not trainer VRAM estimates; loaders can omit MTP and cast nonquantized parameters. All four selected real projections pass two adapter updates and the dequantized-reference checks. [Complete shard hashes and projection results](research/nf4-checkpoint-validation.json).

## Modal L40S hardware qualification — September 15

The initial real 27B NF4 Axolotl test passed on one Modal L40S (SM89), driver
580.95.05, Torch 2.13.0+cu130, 44.39 GiB device memory. Two SFT steps exercised
496 frozen NF4 linears, 108,789,760 BF16 adapter parameters (800 tensors), and
1,600 finite FP32 optimizer-moment tensors. The existing callback required every
trainable adapter gradient to exist, be finite and be BF16. Vision remained frozen.
Checkpoint adapter headers, optimizer, scheduler, Trainer and RNG files passed.
This used SDPA and installed hybrid GPU kernels, without CPU reference overrides.
The dataset contained eight synthetic browser conversations, 395 tokens each
(padded training batches reported 448), rank 16 and accumulation 1. It is an
infrastructure test, not evidence of browser-agent quality.

Maximum *logged* allocated memory was about 20.73 GiB. One-second `nvidia-smi`
samples reached 27,992 MiB (27.34 GiB), including allocator reservations/runtime
memory. Do not interpret the lower final `torch.cuda.max_memory_allocated()`
snapshot as a whole-run peak: Axolotl resets peak counters during logging.
The two-step training timer included cold work and reported 83.02 seconds;
this is not a steady-state benchmark. Full SFT subprocess time was 144.85 seconds;
GPU telemetry covered about 155 seconds including hardware checks and cleanup.

Reviewing the initial resume exposed a test limitation: increasing `max_steps`
after resuming the terminal checkpoint leaves its already-completed scheduler at
zero learning rate. Backward/state loading/checkpoint saving passed, but that
third step did not prove an adapter update. The follow-up probe resumes checkpoint
one within the original two-step schedule and compares a saved LoRA-B tensor to
confirm a nonzero update. It also tests approximately 2K-token conversations.
The built-in throughput counter went negative across same-process resume, so
retain raw metrics and exclude that counter from throughput conclusions.

The first CPU-only image build rejected the existing uv lock under Modal's default
index settings. Explicit `--default-index https://pypi.org/simple` made the unchanged
lock install and `uv pip check` passed. CPU preparation then cached the complete
19,424,559,530-byte checkpoint and verified offline snapshot/tokenizer resolution
before GPU allocation. The short run's container list was empty after completion.
See the [operational runbook](../docs/agents/training-modal-preflight.md) and local
artifacts under `outputs/modal/l40s-20260915-212004-9690ddfc/`.

Remaining qualification is distinct: longer contexts, rank 32, L40S FA2 for the
pinned AsyncGRPO attention path, production integration of the audited NF4 TRL
constructor fix, live FP8 vLLM publication/session retention, and NF4/FP8 logprob
mismatch. L40S results do not qualify SM120. Modal also lists RTX PRO 6000, so a
future separately authorized Blackwell test can exercise the existing SM120 wheel.
[Modal GPU support](https://modal.com/docs/guide/gpu),
[driver environment](https://modal.com/docs/guide/cuda).

**Longer-context follow-up passed:** the actual tokenized length was **1,907**,
padded to 1,920 (the configured cap was 2,048). Maximum logged allocated memory
was **25.74 GiB**, while one-second device samples reached **27.39 GiB**.
Resuming intermediate checkpoint one repeated the remaining scheduled update
at learning rate 0.00005; a saved LoRA-B tensor changed by a maximum absolute
0.0000500679. Thus this follow-up verifies an actual resumed update, not just a
zero-learning-rate step. All BF16 adapter/gradient, FP32 optimizer and frozen-base
checks passed again. The first sample included cold compilation/loading; three
updates are too few for a stable throughput estimate.

The two invocations used about **5.3 minutes** covered by GPU telemetry; both
apps had zero containers afterward. GPU-only list-price estimate is approximately
**$0.17**, excluding CPU/RAM, image/download work, storage and any time outside
the telemetry window. The paid authorization was up to 20 L40S minutes.
[Consolidated evidence](research/modal-l40s-validation.json).

The audit callback and benchmark summarizer now preserve Axolotl's captured
pre-reset allocation peak. Benchmark summaries suppress token-rate conclusions
when counters reset across resume and identify runs without post-warmup samples.
New local regressions cover the observed records. The Modal launcher also streams
subprocess diagnostics during execution and tests timeout termination locally.
These post-run reporting changes were tested locally; the exact GPU-tested sources
are archived with the follow-up run.

## RTX PRO / MIG availability gate — September 15

User requested RTX PRO with MIG, aborting if MIG was unavailable. A read-only
Modal probe allocated one **RTX PRO 6000 Blackwell Server Edition**, driver
580.95.05. `nvidia-smi` reported **MIG Disabled**; `nvidia-smi -L` exposed only
the full physical GPU, and `nvidia-smi mig -lgi` reported no MIG-enabled devices.
The effective process capabilities did not contain `CAP_SYS_ADMIN`. The test
therefore returned `ABORT_MIG_UNAVAILABLE`, without changing GPU configuration,
downloading/loading a model, or starting SFT/RL. The command probe took 0.214
seconds; that excludes GPU provisioning/teardown and is not a billing duration.
The app completed, and a subsequent container-list check was empty.

This establishes lack of usable MIG in **the allocated Modal container**, not
lack of MIG support in the GPU hardware. NVIDIA lists two `2g.48gb` instances
for RTX PRO 6000 Blackwell and requires `CAP_SYS_ADMIN` to toggle MIG mode.
A provider must expose preconfigured slices or permit host-level configuration.
Do not try to bypass a managed provider's device isolation.
[Supported profiles](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/supported-mig-profiles.html),
[MIG management and application constraints](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/deployment-considerations.html).

The proposed one-allocation sequence remains reasonable on such a host: create
both slices before model startup, run inference and trainer qualification in
independent processes pinned to their respective MIG UUIDs, then retain the server
and start the integrated mock-environment run. Use one shared local adapter path.
Keep the native PEFT disk/HTTP synchronization path: NVIDIA currently documents
NCCL as unsupported with MIG. SFT memory results are not proof of the TRL trainer's
memory requirement or SM120 kernel compatibility. Those tests remain outstanding.

Probe script: `scripts/modal_mig_probe.py` (`--dry-run` makes no cloud calls).
Evidence: `outputs/modal/rtx-mig-20260915-222151/`; cloud app
`ap-sjrpA9Q3LgjmnSEZsDYJA0`. No further GPU work was started after the failed gate.

## Independent L40S qualification — new local controls (September 15)

The pinned vLLM 0.28 unload endpoint removes the public adapter name without
calling engine removal. An absent `/v1/models` entry therefore does not establish
that the adapter weights were removed. `scripts/patch_vllm_unload.py` backports the
engine-removal part of upstream PR #54939, guarded by the exact source hash. It
retains the name when engine removal throws and accepts `False` when the worker
LRU has already removed the adapter. The actual endpoint passes CPU checks with a
simulated engine; this is distinct from a real GPU lifecycle test.
[Upstream endpoint](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/entrypoints/openai/models/serving.py),
[upstream fix](https://github.com/vllm-project/vllm/pull/54939),
[CPU evidence](research/vllm-unload-validation.json).

`validate_hybrid_packing.py` now reproduces the previously documented packing
limitation numerically. In a tiny actual Qwen text model with one linear-attention
layer and CPU reference kernels, changing only the preceding packed sample changes
the next sample's hidden states by a maximum 0.203. DeltaNet receives no cumulative
sequence lengths. This is not a GPU kernel result; it confirms that resetting
position IDs alone does not supply recurrent/convolution boundaries. The existing
microbatch-one, `token_budget=0`, single-trainer baseline avoids multi-sample rows.
The isolated GPU loss probe additionally rejects non-contiguous position IDs.
Do not enable dynamic packing merely after installing FlashAttention.
[Reproduction](research/hybrid-packing-validation.json),
[Transformers implementation](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/models/qwen3_5/modeling_qwen3_5.py),
[TRL collator and loss](https://github.com/huggingface/trl/blob/a04ffd337108285002df29d9ae73ef7e855e03f1/trl/experimental/async_grpo/async_grpo_trainer.py).

The new independent Modal probes are `scripts/modal_inference.py` and
`scripts/modal_grpo.py`. Both support `--dry-run` and CPU-only `--prepare-only`;
each GPU invocation has a six-minute absolute caller window, fixed replay guard,
no ordinary retries, bounded subprocesses and forced container termination.
The shared RL lock builds on CPU. The complete pinned official FP8 snapshot is
cached on the project's Modal volume (30,866,866,928 weight bytes); the NF4 snapshot
was already cached. The inference probe checks worker adapter IDs through a
read-only vLLM extension using native collective RPC, alongside public adapter
names and the production session registry. These diagnostics do not replace
vLLM's loader or synchronization. Development endpoints bind to localhost only.

Rank 32 in this probe is a zero-padded copy of the trained rank-16 adapter, with
alpha scaled to preserve alpha/r and B@A. It qualifies the rank-32 loading layout,
not rank-32 training or quality. Most vLLM GPU LoRA storage is preallocated;
correct unload means adapter IDs leave the caches, not that `nvidia-smi` returns
to its pre-server memory level. Finite churn cannot prove the absence of every
long-run leak; in particular, per-name frontend resolver-lock metadata is not
reclaimed by the upstream endpoint/backport.

### Actual isolated GRPO GPU result

`l40s-grpo-20260915-224453-0600f35a` passed on one L40S: native AsyncGRPO
constructor and loss, 353-token input, two BF16 rank-16 adapter updates, all 800
adapter gradients checked, 1600 FP32 Adam moments, and unchanged frozen-parameter
samples. Peak allocated/reserved VRAM was 25.788/29.566 GiB. Steps took 57.411 and
1.038 seconds; the former includes first-use compilation. The adapter checkpoint
was written and its BF16 tensor headers verified; optimizer-state reload passed.
This is **not** `Trainer.train()`, a real rollout, full trainer resume, or a
throughput benchmark. It establishes the native loss/backward path fits an L40S
under these small single-trajectory conditions. The candidate NF4 initializer
remains separate from the production runner. [Evidence](research/modal-rl-validation.json).

### Actual FP8 adapter lifecycle GPU result

`l40s-inference-20260915-225017-1f8ab0e0` completed ten native adapter publications,
rank 16 and zero-padded rank 32, with the real official FP8 base and BF16 adapters.
The production registry kept an old version through multiple turns and a stale,
undrained streaming response. Staleness prevented its next request; release then
removed its public name, worker registered/active IDs and adapter directory.
Environment-error release and repeated churn passed. Shutdown left zero adapter
IDs in either worker cache. GPU allocation stayed approximately 37.212 GiB
through churn; final allocation exceeded the pre-adapter value by only 0.368 MiB.
Preallocated LoRA/KV buffers remain; CPU RSS is not expected to fall immediately.
The GPU container was terminated and an empty container list recorded.

The overall report deliberately says `LIFECYCLE_PASS_LOGPROBS_NEED_REVIEW`.
A repeat before adapter publications matched exactly, while repeating the old
policy after loading newer adapters changed one selected-token logprob by at most
0.019604 (generated text unchanged). Prefix caching was disabled in this run.
The first, prefix-enabled attempt had a 0.144 difference and stopped too early
to test eviction. Neither result establishes a wrong adapter selection or proves
that reported sampling probabilities are incorrect. The 0.01 threshold is a
probe diagnostic, not an upstream guarantee or RL acceptance criterion.
Mixed adapter ranks, kernel numerical paths and policy-weight integrity need a
controlled comparison before interpreting the drift. Normal training retains
one rank throughout a run. Full responses and engine states are archived with
the run; do not silently relax the threshold to convert this into an all-clear.

The rank-16-only control (`l40s-inference-20260915-225630-cf46ab66`) exhausted its
shorter startup allowance after loading weights, during cold kernel warmup. It
was terminated by the fixed guard; **no fixed-rank comparison ran**. The original
budget was not extended. All four new GPU invocations have empty post-run
container lists. Their recorded function runtime totals 652.58 seconds; including
the earlier SFT telemetry gives about 16.2 minutes, excluding unsampled container
startup/teardown. These are execution observations, not an invoice total.

Next test: keep rank 16 throughout, repeat the same old adapter before/after
publishing same-rank new weights, and fingerprint its CPU tensors, GPU slots and
adapter-ID mapping before publication. Compare that with the mixed-rank case.
The archived report's `session_policy_stable` means name/ID routing was pinned;
it does not establish identical numerical outputs. Future reports use the more
precise field `session_adapter_name_pinned`. Resolve or characterize the drift
before treating the two-GPU pipeline as qualified. The subsequent two-L40S test
should use one container and a shared adapter directory, then exercise actual
`Trainer.train()`, native disk/HTTP sync and one mock GRPO iteration.

After the paid tests, both launchers were updated to preserve Triton and vLLM
compile caches under `/model-cache/compiled/rl-vllm028-torch213-sm89/`, committing
them after subprocess shutdown. This should avoid repeating part of the expensive
cold compilation, but **reuse has not been GPU-tested and the earlier runs did not
populate this new location**. It is separate from model downloads and cannot make
the next cold run warm retroactively. The source archive for each result preserves
the code actually executed; these cache/report-label edits are subsequent changes.
Local suite: 56 passed, two optional-dependency skips; native CPU endpoint, NF4
constructor/loss, hybrid boundary and mocked inference-control probes also ran.

### Upstream comparisons and limits of adapter identification

A subsequent online review found measured logprob variation in the same general
range. These are primary reporter observations, not reproductions on our stack:

- [vLLM #51187](https://github.com/vllm-project/vllm/issues/51187), August 2026:
  maximum chosen-token logprob differences 0.04685 and 0.03906 across repeated
  concurrent workloads; emitted token IDs unchanged. vLLM 0.26, Qwen3-0.6B FP16,
  SM89 RTX 4060 Laptop, batch invariance enabled. It persists with eager execution
  and prefix caching disabled. Sequential requests were reproducible in that
  report, so its concurrency trigger does not explain our sequential case.
- [vLLM #25194](https://github.com/vllm-project/vllm/issues/25194), September 2025:
  published values differ by 0.03524 and 0.09485 on the first two common generated
  tokens, before text diverges. Reporter localized it to Triton autotuning of a
  Mamba kernel, without batching, prefix caching or chunked prefill. That specific
  issue was fixed; it demonstrates a numerical mechanism, not an identified bug
  in our pinned version or Qwen DeltaNet implementation.
- An older [comment on #3251](https://github.com/vllm-project/vllm/issues/3251#issuecomment-2448963097)
  reports an average difference of 0.02 with/without prefix caching, but explicitly
  questions the correctness of its experimental fix. It is weak evidence for a
  benign numerical explanation and is not our cache-disabled configuration.

The size 0.0196 cannot rule out wrong-adapter application. The improved test uses
SFT checkpoints one and two: only one optimizer update separates them. The saved
resume probe measured a maximum 0.00005007 change in one sampled LoRA-B tensor;
this is not a full adapter-distance measurement or a bound on output differences.
A misrouted adjacent checkpoint can produce similar logprobs and identical text.
The original first inference attempt used functionally equivalent adapter copies,
including rank padding, and was not a behavioral adapter-identity test at all.

Existing evidence verifies the requested adapter name, continued engine registry
membership and eviction, but not the GPU slot selected for every token. The next
identity test should use two deliberately distinguishable same-rank diagnostic
adapters, establish each one's output signature, and then check per-request
adapter-ID-to-slot/token mapping and actual adapter tensors while publishing other
versions. Correct stored weights alone do not prove the forward pass used them.
No new GPU invocation was made for this literature/source review.

### Thinking Machines kernels and Qwen GDN batch invariance

Reviewed 2026-09-15. **Do not enable `VLLM_BATCH_INVARIANT=1` on our current
27B launch: pinned vLLM 0.28.0 rejects its GDN backend.** This is a software
capability boundary, independent of renting L40S, Hopper or RTX PRO Blackwell.

[Thinking Machines' original work](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
fixes arithmetic reduction order across different batch shapes. Its Qwen examples
already cover deterministic inference and RL; it is not limited to another model
family. Deterministic sampling still requires controlling the random seed.
Their prototype should not be installed over our pinned stack as a generic fix.

[vLLM 0.28's built-in mode](https://docs.vllm.ai/en/v0.28.0/features/batch_invariance/)
is beta, documents a compute-capability floor of 8.0, and lists dense Qwen3,
Qwen3-Next and a Qwen FP8 model among tested configurations. This list does not
qualify Qwen3.8-27B-FP8 plus runtime LoRA. Our checkpoint uses
`Qwen3_5ForConditionalGeneration`, with 48 linear-attention and 16 full-attention
layers, according to the cached pinned config.

Local source inspection and an actual CPU call to
`get_mamba_attn_backend(MambaAttentionBackendEnum.GDN_ATTN)` reproduced:

```text
RuntimeError: VLLM batch_invariant mode is not supported for GDN_ATTN.
```

No model, GPU or cloud allocation was needed. `GDNAttentionBackend` inherits
`supports_batch_invariance() == False`; the selector enforces it. Sources:
[backend](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/v1/attention/backends/gdn_attn.py),
[selector](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/v1/attention/selector.py),
and [upstream issue #48613](https://github.com/vllm-project/vllm/issues/48613).
The generic tested-model list is insufficient evidence against this actual guard.

There are relevant existing adaptations:

- [vLLM PR #49827](https://github.com/vllm-project/vllm/pull/49827) is **open,
  unmerged**, API-checked at head `debb4ba43485a3efa41e6c81180e004b81be6a16`.
  It aligns GDN decode kernels and prefill partitions. Its gate requires CUDA
  SM90+, excluding L40S SM89. H100 validation covers unquantized TP1, without
  prefix caching or speculative decoding. Quantization is explicitly outside
  scope. RTX PRO SM120 clears the numeric gate but has no demonstrated validation
  in that report. It does not establish our runtime-LoRA combination.
- [TorchTitan's Qwen3.5 unified-path PR #3957](https://github.com/pytorch/torchtitan/pull/3957)
  is **merged**, API-checked separately. A
  [research snapshot](https://github.com/yichuan-w/torchtitan-batch-invarient-GDN)
  combines Thinking Machines kernels with a shared trainer/generator model and
  GDN-specific forward handling. It documents H100/CUDA13 testing. This is a
  different training integration, not a TRL plugin or evidence for NF4/FP8 parity.

The [associated August 2026 experiments](https://yichuan-w.github.io/blog/GDN-train-inference-mismatch-asyncRL/)
are especially relevant to browser agents: exact initial logprob parity was
achieved, but downstream gains depended on the workload and staleness window.
The reported trainer throughput penalty was roughly 2–3× on math/search and 5×
on the terminal agent. Mostly single-seed results do not establish a general
accuracy benefit. Those costs describe that implementation, not a forecast for
our vLLM server. Adjusting episode timeouts matters when measuring a slower path.

LoRA is not categorically excluded: our installed
[LoRA Triton configuration](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/lora/ops/triton_ops/utils.py)
disables tuned configurations and sets shrink `split_k=1` under batch invariance.
It still chooses `block_k` by token batch size; source hooks alone are not a
proof of all-rank/all-batch numerical invariance. Likewise, the
[FP8 implementation](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/model_executor/layers/quantization/fp8.py)
keeps blockwise FP8 on its selected FP8 kernel. Its separate per-tensor BF16
dequantization fallback must not be mistaken for our 128×128-block checkpoint.

Three independent differences need separate measurements: serving numerics for
one fixed policy; NF4 trainer versus FP8 rollout numerics; and genuinely older
rollout policy versions. Our quantizers represent different base weights, so
deterministic kernels cannot guarantee exact trainer/rollout equality. Async
staleness remains even with perfectly matched kernels. Neither determinism nor a
small logprob difference proves the right adapter was selected.

Recommended next validation: finish the same-rank adapter identity/mapping control
on the current serving stack first. If investigating strict GDN invariance, use an
isolated pinned copy of the upstream patch with a small unquantized Qwen3.5 model
on H100 to reproduce its documented case. Then add distinct BF16 LoRAs and runtime
publication, followed by blockwise FP8 and target hardware qualification. Compare
identical token histories under solo, concurrent and mixed prefill/decode traffic;
record logprob distributions, adapter identity and throughput. Do not bypass the
GDN capability guard or claim a stock A/B flag test is currently runnable.

No packages, model weights or GPU time were used for this investigation beyond
the already installed environment and small public source/document requests.

### Same-rank adapter identity GPU result — follow-up analyzed 2026-09-16

**Identity/lifecycle passed; numerical repeatability remains unresolved.**
Evidence: [summary](research/adapter-identity-validation.json) and
`outputs/modal/l40s-inference-20260915-235431-53cc5a53/`.
The run used official FP8 weights, L40S, eager TP1, prefix caching off, all
adapters rank 16/BF16, and the existing production policy registry. A is the
unchanged SFT checkpoint 2. B multiplies its LoRA-B tensors by 128 to create a
distinct diagnostic signature; it is not another trained policy or a quality
benchmark. The serving allocation retains `max_lora_rank=32` as in earlier tests.

- All 1,280 stored slot buffers matched a CPU reconstruction with native vLLM
  packing. A's complete fingerprint remained identical after publication and
  another forward. This checks transfer and retention, not independent correctness
  of upstream packing math.
- Five instrumented requests checked 36,480 shrink/expand calls and 60,800 token
  rows. Every one of the 512 required call sites across actual adapter targets
  executed. Weight-buffer pointers and the grouped token-to-slot metadata supplied
  to the kernels matched the requested adapter. GPU instruction execution and the
  kernels' internal pointer caches were not independently audited.
- A and B generated different text. A stayed on adapter ID 1 / slot 0 across
  publication. Later slot reuse reproduced A's fingerprint for version 5 and B's
  for version 10. Ten publications, stale-stream retention, error release and
  eviction completed; shutdown had no registered/active IDs and four empty slots.
  GPU allocation was flat at 37.262 GiB during churn and returned to within
  0.368 MiB of its pre-adapter value. Finite churn is not an unlimited leak test.

The important numerical controls were:

| Comparison for the same adapter | Maximum absolute selected-token logprob difference | Text |
| --- | ---: | --- |
| First two normal A requests, before audit/publication | 0 | Identical |
| Normal A vs instrumented A, **before B exists** | 0.083283 | Identical |
| First normal A vs normal A after B/C publication | 0.083283 | Identical |
| Normal A vs instrumented A after publication | 0.075736 | Identical |
| Normal B vs instrumented B | 0.111689 | Identical |

The pre-publication instrumented A response's entire logprob structure exactly
matches the later normal A response after publication. Thus loading B/C is not
necessary for this observed change, and switching to B cannot explain the
pre-publication change. The worst A token in the first/last normal comparison
changed from -1.604671 to -1.687954 (about 8% lower conditional probability).
These are twelve-token observations, not a full-distribution KL estimate.

Instrumentation synchronizes GPU metadata and copies slot tensors to CPU. This
perturbs execution, so the run does not isolate a causal instrumentation effect
from call ordering, allocation history or kernel arithmetic. The earlier 0.0196
mixed-rank result used a different A checkpoint and sequence of operations; a
direct causal rank comparison is not available. What this run establishes is
that variation can also occur with one rank and checked adapter identity.

A concrete next numerical hypothesis is LoRA shrink's split-K reduction: the
pinned default selects `split_k=64` below 128 token rows and its
[kernel uses relaxed atomic additions](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/lora/ops/triton_ops/kernel_utils.py).
This is source evidence for a candidate, not localization of our observed error.
A future isolated control could compare ordinary repeats, fingerprints alone,
hooks alone and a narrowly scoped shrink split-K=1 configuration. Full
`VLLM_BATCH_INVARIANT=1` remains blocked by GDN; no such kernel change was applied.

Operationally, one submission was cancelled while pending with no task assigned.
The first actual GPU run stopped at an overstrict probe assertion requiring
execution of frozen conv1d storage wrappers. This was corrected to require actual
adapter targets while still checking all buffers and observed calls. Both GPU
attempts are preserved: 199.10 and 199.69 seconds of recorded function runtime,
398.79 seconds total, excluding unsampled startup/teardown and CPU preparation.
All three app container lists were verified empty. The successful run deliberately
returns `LIFECYCLE_PASS_LOGPROBS_NEED_REVIEW` / CLI exit 1; do not turn that into a
numerical all-clear. Local native diagnostic tests and the 56-test suite pass
(two optional-dependency skips).

### Assessing the RL impact, rather than requiring exact reproducibility

The phenomenon is not inherently LoRA-specific: stock Qwen serving has reported
logprob variation without runtime adapters (for example the reproduction in
[vLLM #51187](https://github.com/vllm-project/vllm/issues/51187)). Our particular
mechanism has not been localized by a base-only ablation.

For the twelve identical A tokens in the last test, normal-before versus
normal-after had mean absolute logprob difference 0.046960 and probability ratios
from 0.920091 to 1.072142. This is roughly -8.0% to +7.2% relative probability,
not an accuracy change. It is rollout-versus-rollout evidence, with intervening
instrumentation; it is not a measured NF4-trainer/FP8-rollout gap or a KL estimate.

The pinned AsyncGRPO loss computes per-token
`r = exp(trainer_logprob - behavior_logprob)` and clips the surrogate with default
epsilon 0.2 (ratio interval 0.8–1.2). If a mismatch of the measured size occurred
between trainer and behavior logprobs, it would perturb these importance weights
by several percent. Being inside the clip interval does not remove that
perturbation; genuine policy updates/staleness can also place a ratio near a clip
boundary. Neither gradient-direction error nor reward degradation follows from
the scalar logprob difference alone. Source: pinned
`trl/experimental/async_grpo/{async_grpo_trainer,async_grpo_config}.py`.

Prioritize a bounded impact qualification over a blanket bitwise-equality gate:
freeze the policy (no optimizer updates), score the same sampled token histories
with repeated ordinary vLLM requests and the actual NF4 trainer, and vary context
length and serving concurrency. Measure signed bias, the error distribution and
tails, importance ratios and clipping decisions. Then compare fixed-advantage
losses/gradients on the same trajectories and a small controlled learning run.
This includes intentional quantization mismatch as well as serving variability.
Do not assume the observed differences are independent, zero-mean noise.
No further GPU run was started for this analysis.

## Priority change: minimal end-to-end learning test (2026-09-16)

The user requested pausing numerical investigation and conserving weekly credits.
The earlier frozen-policy diagnostic proposal is deferred. Identical token
histories means evaluating the same conditional probabilities; teacher-forced
prefill does not reproduce the execution path of sequential rollout decoding.
Actual sampled rollout logprobs remain the behavior-policy reference for GRPO.

Public evidence is sufficient to motivate a bounded learning test now:

- [Thinking Machines' write-up](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
  explains batch-dependent numerics and an RL example where mismatch matters.
- [GDN training/inference experiments](https://yichuan-w.github.io/blog/GDN-train-inference-mismatch-asyncRL/)
  report configuration-dependent learning benefits from invariance, with substantial
  throughput costs. Most comparisons use one seed and a different training stack;
  they neither establish safety nor predict degradation for our NF4/FP8 setup.
- [TRL's reward API and examples](https://huggingface.co/docs/trl/grpo_trainer)
  support simple deterministic completion rewards and an IncrementEnv tool example.
  Our A/B bandit is a deliberately smaller project smoke task using that API,
  not a claimed upstream benchmark recipe or evidence of browser learning.

`scripts/modal_e2e.py` prepares one two-L40S allocation: GPU 0 serves FP8, GPU 1
trains NF4 with BF16 rank-16/alpha-32 adapters and FP32 Adam moments. It reuses
the existing pinned image/cache; missing snapshots cause failure rather than a
new weight download. CPU preparation is separate. No allocation has run yet.

The real `AsyncGRPOTrainer.train()` executes 16 optimizer steps, four generations
per group, four in-flight episodes, microbatch one/accumulation four, maximum
staleness two, one native adapter sync per step, SDPA and no sequence packing.
The trainer constructor uses the previously audited NF4 candidate and policy
patches. There is no synthetic rollout worker, old logprob or advantage override.
Learning rate 1e-4 is deliberately for a tiny learning demonstration, not a
recommended browser-agent hyperparameter. Responses are limited to eight tokens.

The task asks for A or B. A separate 32-sample calibration requires each answer
in at least 12.5% of responses, selects the less common answer as the fixed reward
target, and aborts before training if the task lacks diversity. The target is
not included in the model prompt. Malformed/verbose responses receive zero.
The existing `OneTurnMockEnv` cannot demonstrate learning because its reward is
independent of the response and constant within each GRPO group.

There are independent 64-sample before/after evaluations with disjoint seed
ranges. The final evaluation uses the last policy published by native trainer
synchronization, not a manually substituted adapter. Evidence requires changed
adapter weights, checked BF16 gradients/FP32 moments, an optimizer+adapter+
rollout-state checkpoint, all expected sync versions and actual rollouts under
at least two versions. Clear learning additionally requires nonoverlapping
95% Wilson intervals for the binary reward rate. An inconclusive learning result
is labeled `PIPELINE_PASS_LEARNING_INCONCLUSIVE`, never silently promoted to PASS.
One prompt/seed does not qualify generalization or numerical correctness.

Budget proposal: up to ten minutes per L40S (20 GPU-minutes total), including a
60-second startup allowance and a 540-second function timeout. Work has a tighter
510-second deadline to leave cleanup time. Queue allowance is ten minutes;
timeouts/failures cancel the call and terminate its containers. No automatic
retry. These are execution limits, not a guarantee about provider billing or
teardown accounting. The browser environment/multi-turn harness is outside this
minimal probe; the existing scripted BrowserGym checks remain separate evidence.

```bash
cd training
.venv/bin/python scripts/modal_e2e.py --dry-run  # local only
# After cloud authorization:
.venv/bin/python scripts/modal_e2e.py
```

Local validation: 29 relevant tests passed (choice reward/statistics/pickling,
policy reservations, configs and subprocess/allocation deadlines). The pinned
TRL config instantiates on CPU and the audited NF4 candidate imports. These are
not GPU results; local GTX1070/driver cannot execute this CUDA13 stack. No new
weights or GPU job were started. Approval for the new allocation is pending.

### First authorized two-GPU attempt: stopped before calibration

The user authorized the 20 GPU-minute budget, with no automatic retries.
`l40s-e2e-20260916-002725-92d7ebe9` timed out in CPU preparation after 160 seconds;
no GPU call was submitted. Its original captured output did not identify the
stall. Preparation was changed to stream stages/periodic stack diagnostics and
enforce `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `USE_HUB_KERNELS=NO`.
That CPU check passed; the log shows an optional bitsandbytes CPU-kernel lookup
failing promptly offline. The earlier stall's precise location was not captured.

`l40s-e2e-20260916-003126-4dfaa455` ran on two L40S GPUs for 143.72 function
seconds each (4.79 aggregate GPU-function minutes, excluding startup/teardown
and other billing). FP8 vLLM loaded; the NF4 trainer constructed successfully,
passed explicit BF16/NF4 checks and selected adapter-only sync. Its initial
adapter was saved, loaded by vLLM and unloaded. Peak device memory was
38,755 MiB on GPU 0 and 29,328 MiB on GPU 1. These are setup peaks, not training
VRAM measurements.

The evaluation helper then failed before its first completion request: pinned
Transformers returns a `BatchEncoding` from `apply_chat_template` by default,
which `requests` cannot serialize as JSON. This was a project probe bug.
`render_prompt_ids()` now explicitly sets `return_dict=False` and validates
flat integer IDs; CPU preparation checks actual HTTP payload serialization and
token-ID agreement for both cached tokenizers before GPU allocation.

Local correction checks: 30 relevant tests passed, plus 32 real HTTP requests
through the actual evaluation helper to a local stub using the cached Qwen
tokenizer. This verifies transport, not model generation. Both Modal apps have
empty final container lists. Logs and source archives are retained; see
`research/modal-e2e-validation.json` and `research/e2e-request-validation.json`.

No calibration, GRPO update, native scheduled policy publication, training
checkpoint or learning comparison was reached. Full RL remains unqualified.
In accordance with the no-automatic-retry request, a second GPU attempt was
not started. Asked whether to use the remaining budget for eight updates with
`--gpu-seconds 360 --steps 8` (six minutes per GPU, including startup allowance).
The first attempt's recorded function time plus a conservative 60s startup
allowance plus that proposed follow-up allowance totals 18.79 GPU-minutes;
this is execution-budget accounting, not a provider invoice guarantee.

### Corrected shorter attempt: GPU capacity unavailable

The user approved the eight-update, six-minute-per-GPU follow-up.
`l40s-e2e-20260916-093959-9984fa35`, app `ap-agnPvQAHbnG89K8ufHIYiM`, passed remote
CPU preparation, including actual tokenizer request serialization and agreement
between trainer/rollout prompt IDs. Its GPU call remained `PENDING` with an empty
`task_id` throughout the ten-minute queue window. It was explicitly cancelled
after that window; no GPU function started and the final container list is empty.
The local client waiting on the cancelled call was then interrupted to close
the app. No automatic retry or extended queue wait was started.

This attempt adds zero GPU-function time and no learning evidence. Aggregate
recorded GPU-function usage for the two authorized attempts remains 4.79 minutes
(the earlier 143.72s on each of two GPUs), excluding provider overhead/billing.
The corrected probe remains ready, but full RL is still unqualified. Source
archive, plan, call-graph cancellation evidence and final container listing are
in the run's local output directory; the summary is updated in
`research/modal-e2e-validation.json`.

### Ten-minute follow-up: baseline passed, provenance path bug blocked training

The user approved ten minutes per GPU for the corrected eight-update test.
`l40s-e2e-20260916-100055-1b0d7b07` obtained two L40S GPUs promptly. Both models
loaded, the initial BF16 adapter served successfully, and all 96 pre-training
generations completed. Calibration was A=23/B=9, selecting B as reward target.
The independent baseline was A=30/B=34, reward 0.53125. There is sufficient
answer diversity for a learning probe; this is not evidence of learning.

Before `trainer.train()`, our provenance logger raised `FileNotFoundError` for
`/opt/training/envs`. The Modal image mounts selected sources and installs its
locked environment in `/opt/rl`, rather than copying the complete repository.
This was another project packaging bug that should have been checked on CPU.
No optimizer update, native scheduled policy publication, training checkpoint
or final evaluation was reached. GPU function runtime was 262.76 seconds per
GPU (8.76 aggregate GPU-function minutes, not invoice duration). All containers
were stopped; no automatic GPU retry was launched.

The logger now discovers existing lockfiles plus those beside the active virtual
environment (`sys.prefix`), instead of requiring the local repository layout.
New tests cover a separately installed environment and missing optional paths.
The full local suite passes: 63 passed, 2 skipped. CPU preparation now executes
the real provenance capture and requires hashes for `/opt/rl/pyproject.toml`
and `/opt/rl/uv.lock` before submitting a GPU call. This revised preparation was
also run successfully in the actual Modal CPU image, with no GPU submission
(app `ap-4vE7Ne5ghd1rr2GdfNISFt`). Its final container list is empty.

The evidence summary retains all attempts in `research/modal-e2e-validation.json`.
Recorded aggregate E2E GPU-function usage so far is 13.55 GPU-minutes, excluding
provider overhead and unrelated earlier SFT/inference probes. Full RL and reward
improvement remain unverified. The next GPU test still requires authorization.


### Two-GPU learning smoke passed (2026-09-16)

The explicitly authorized retry `l40s-e2e-20260916-120628-0cf5f142`
(app `ap-cHCbJh36CUemOmQlgEnsSd`) completed on 2×L40S using
`--gpu-seconds 600 --queue-seconds 1800 --steps 8`. No automatic retry occurred.
Following roughly eight minutes queued, GPU function execution took 392.91s
per GPU: 13.10 aggregate GPU-function minutes, not invoice duration. All
containers are confirmed stopped. Historical E2E GPU-function time across the
executed attempts is 26.65 aggregate minutes under separately approved runs.

This executes the patched, pinned `AsyncGRPOTrainer.train()` with its actual
spawned rollout worker, real FP8 generations and native runtime LoRA sync.
There are no synthetic behavior logprobs or advantages in this run. The frozen
NF4 trainer has 496 quantized linears; all 108,789,760 trainable adapter elements
are BF16. It uses rank 16/alpha 32, microbatch 1, accumulation 4, group size 4,
maximum four inflight rollouts, staleness 2 and no sequence packing.

The task asks for a single A or B. Calibration selected B as the rewarded answer;
that target is supplied to the reward callback, not disclosed in the prompt.
Independent evaluations of 64 samples each gave:

| Evaluation | Rewarded answers | Mean reward | Wilson 95% interval |
| --- | --- | --- | --- |
| Initial adapter | 34/64 | 0.53125 | 0.4107–0.6482 |
| Final native-served policy v9 | 64/64 | 1.0 | 0.9434–1.0 |

Eight optimizer updates increased reward by 46.875 percentage points. A checked
LoRA-B tensor changed by a maximum absolute 0.00070953. This is evidence that
updates affect the served policy and improve this task; it is not a browser,
generalization, long-run stability or numerical-parity result.

Native publication produced v1–v9. Event replay checked 57 groups / 228 episodes
and requests, with matching episode/request policy versions and no active group
or episode at any of the six evictions (v1–v6). All groups, episodes and requests
drained. These short single-turn sessions complement the earlier lifecycle test;
they do not alone qualify long browser episodes. Remaining versions v7–v9 were
retained until server shutdown.

`checkpoint-8` contains 800 BF16 adapter tensors, optimizer state with 1,600
FP32 moment tensors, trainer state and rollout state (`model_version=9`).
Per-step gradient assertions passed. The report's initial dtype snapshot has
`gradient_tensors_checked=0` because it precedes training. Actual AsyncGRPO
resume has not been exercised. We downloaded only diagnostics/configs; weights
and optimizer state remain in Modal volume `browser-training-results` under
this run's `learning/checkpoint-8` directory.

Native training took 197.87s. The first forward/backward took 121.44s, versus
about 4.3–6.2s subsequently; cold compilation/warmup is a plausible contributor,
not an isolated diagnosis. First-step delay allowed a rollout backlog, and the
trainer discarded 119 stale samples (71+24+24 across logging windows); accepted
samples never exceeded recorded staleness 2. Native sync timing ranged about
0.9–4.7s per update including its orchestration overhead. This task's two-token
completions and tiny concurrency do not measure rollout saturation.

Peak device memory was 38,767 MiB on rollout GPU0 and 31,975 MiB on trainer GPU1;
trainer peak allocated tensor memory was 25.28 GiB. These are very short-context
measurements, not a browser-context capacity estimate. Logs, metrics, config,
source and environment provenance are saved with the run. See
`research/modal-e2e-validation.json` and the local output directory's
`report.json`, `policy-event-audit.json` and `learning/metrics.jsonl`.

The next functional integration test is model-driven multi-turn BrowserGym
using the already CPU-validated harness, followed by actual AsyncGRPO resume.
No further GPU run was started. Numerical investigations remain paused.


### SFT behavior learning passed (2026-09-16)

`l40s-sft-learning-20260916-123908-dbbb7ea3` (app `ap-uq5BepmM8yhoHkdGRkQuzS`) passed the
bounded one-L40S apple-formatting test. GPU function time was 271.32s (4m31s),
within the ten-minute cap; allocation waited roughly eight minutes separately.
No automatic GPU retry occurred. An initial app initialization failed before any
function submission because Modal disallows an image build step after runtime
mounts; moving offline flags into subprocess environments fixed it without GPU use.
All final containers are stopped.

The model receives `Repeat: red boat` with a neutral system prompt. Training
examples provide `red apple boat apple`; the apple rule is not stated in the
input. A seeded split uses 64 unique color/noun pairs for training and 16 disjoint
pairs for evaluation. Held-out words occur individually in training, so this
checks new combinations, not new vocabulary or arbitrary sentence lengths.
The actual Axolotl chat-template path verifies the exact supervised assistant
payload and EOS for all examples and matches the masked prefix to generation.

| Evaluation | Before | After saved-adapter reload |
| --- | --- | --- |
| Held-out exact matches | 0/16 | 16/16 |
| Training-example exact matches | 0/8 | 8/8 |

All final generations placed apple correctly, kept the original words in their
expected alternating positions, and ended with EOS before the 20-token cap.
The raw `word_preservation` metric checks those alternating positions; it scores
plain baseline repetition zero even though baseline answers usually preserve
the original words. Do not interpret it as an independent baseline copy score.
One baseline training-example response refused `black hat`; after training it
correctly generated `black apple hat apple`. No safety or robustness conclusion
is drawn from that isolated response.

The run used the same frozen 27B NF4 base, BF16 rank-16/alpha-32 LoRA targets,
SDPA and no packing. It performed 32 optimizer updates, batch 1 × accumulation 2,
one pass over 64 examples, constant learning rate 1e-4. Training loss fell from
6.05119 to 0.000003958 on successive training batches; this is not held-out loss.
Each example has 33 unpadded tokens and five supervised tokens including EOS.
The first update took about 51.55s; subsequent updates roughly 2–3s. The Trainer's
179.57s runtime includes the baseline evaluation callback; the progress-bar
training/checkpoint interval was about 129s, so do not treat 179.57s as pure update
time. This tiny task is not a representative throughput benchmark.

After checkpoint creation, the probe zeroed every in-memory LoRA tensor and
loaded `checkpoint-32` into the same frozen base. All 800 reloaded adapter tensors
matched the checkpoint exactly and remained BF16; optimizer checks found 1,600
FP32 moment tensors. Per-step gradient checks passed. The checkpoint also
contains optimizer, scheduler, RNG and trainer state. This tests adapter reload,
not a cold base reload or a new resume test (SFT resume was qualified earlier).
Peak sampled device memory was 27,951 MiB; peak logged allocated tensor memory
was 19.63 GiB. These short sequences do not establish browser-context capacity.

27 small diagnostic files were downloaded; weights/optimizer remain in Modal
volume `browser-training-results/l40s-sft-learning-20260916-123908-dbbb7ea3/learning/checkpoint-32`.
See `research/modal-sft-learning-validation.json`, `scripts/modal_sft_learning.py`
and `scripts/sft_learning_probe.py`. Local tests: 65 passed, 2 skipped. This adds
actual learned-generation evidence for SFT; browser task quality, arbitrary
format generalization and FP8 serving of this particular adapter remain untested.
No further GPU work was started.

## FP8 trainer recheck — 16 September 2026

**Conclusion: the official checkpoint is already qualified for vLLM inference,
but there is still no clean stock Transformers/PEFT/AsyncGRPO route that keeps its base in
FP8 and provides a supported training backward.** More VRAM does not remove
this software blocker. Retain FP8 as the desired representation and NF4 as the
working fallback; do not change the successful dependency locks on the basis of
source inspection alone.

Checked the installed Transformers 5.16.1 / PEFT 0.20.0 / pinned TRL stack,
Transformers **5.17.0** source, PEFT **0.21.0** source, and current upstream main
revisions. Transformers main was `b22fe4624c55416fc0f122cd531695e03fc93561`,
PEFT main `db7d68a2dc4f734ba692a8b6b039da8eb25939ba`, TRL main
`b7df6a8f0562a26d25ac4324848a07f1bc40617d`. Newer packages were not installed.
[Source revisions and hashes](research/fp8-upstream-audit.json),
[actual CPU/meta probe](research/fp8-training-cpu-validation.json).

### 1. Can the official FP8 checkpoint be the trainer policy directly?

Its `quant_method: fp8`, E4M3, dynamic activations and 128×128 weight blocks
select Transformers' **FineGrainedFP8HfQuantizer / FP8Linear**, not
compressed-tensors or Transformer Engine. The pinned version, 5.17.0 and inspected
main all return `is_trainable=False`. The Transformers training validator rejects
the PEFT-wrapped quantized model; AsyncGRPO calls that parent Trainer initializer.
The CPU probe reproduces this exact validation error without loading 27B weights.
[Checkpoint config](https://huggingface.co/Qwen/Qwen3.8-27B-FP8/blob/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a/config.json),
[5.17 quantizer](https://github.com/huggingface/transformers/blob/v5.17.0/src/transformers/quantizers/quantizer_finegrained_fp8.py),
[training validator](https://github.com/huggingface/transformers/blob/v5.17.0/src/transformers/trainer_utils.py).

On CPU/unsupported hardware the loader may request BF16 dequantization. Our probe
confirms that CPU fallback; a successful CPU forward after it would not establish
FP8 storage or FP8 training. `dequantize=True` is a different, higher-memory path.

A tiny synthetic Qwen hybrid checkpoint additionally exposes a **5.16.1 loader
bug**: with only hardware validation bypassed to inspect the FP8 load path on
CPU, `update_tp_plan` raises an AttributeError from an absent expert-override
mapping before weights load. The 5.17.0/main source adds a default empty mapping
and addresses that particular error. We did not patch around it or install a
new stack. This version-specific loader fix does not change `is_trainable=False`.

### 2. Why does freezing the base not fix its backward?

For `y = W x + B A x`, freezing W removes its parameter gradient, but earlier
adapters still need the input-gradient contribution through W. LoRA's own branch
can have gradients while the frozen-base branch lacks a supported backward.
Even nonzero adapter gradients or one decreasing loss are insufficient proof
of a correct multilayer gradient path.

The native FP8 forward dispatches to DeepGEMM on eligible hardware/formats or
the finegrained Triton kernel. This is an inference implementation, not a
registered training backend. Changing the validator flag or using an adapter API
that bypasses it does not supply missing gradient support. We did not execute
these kernels locally. [Native linear dispatch](https://github.com/huggingface/transformers/blob/b22fe4624c55416fc0f122cd531695e03fc93561/src/transformers/integrations/finegrained_fp8.py),
[upstream training request](https://github.com/huggingface/transformers/issues/46295),
[LoRA-specific report](https://github.com/huggingface/transformers/issues/46736).

### 3. Does AsyncGRPO make this work without custom modifications?

No. The inspected upstream trainer loads the model, calls
`get_peft_model(model, peft_config)` and then initializes Transformers Trainer.
It supplies no native FP8 backward integration, and its PEFT call uses default
adapter promotion. Our existing BF16 enforcement and policy-session patches
serve other purposes; they do not make FP8 training supported. The VLM text-only
initialization and attention override also remain relevant if introducing a new
quantization backend. [Audited AsyncGRPO source](https://github.com/huggingface/trl/blob/b7df6a8f0562a26d25ac4324848a07f1bc40617d/trl/experimental/async_grpo/async_grpo_trainer.py).

### 4. Can PEFT insert BF16 adapters in the right Qwen modules?

**Insertion is possible; BF16 storage needs explicit handling.** FP8Linear is an
`nn.Linear` subclass, so PEFT's ordinary dispatcher matches it. The CPU test uses
an actual FP8Linear and the native PEFT wrapper, with these results:

| Operation | Actual trainable parameter dtype |
| --- | --- |
| Default PEFT autocast | FP32 |
| `autocast_adapter_dtype=False` alone | FP8, inherited from the base layer |
| Explicit cast of trainable LoRA parameters | BF16; frozen FP8 bytes unchanged |

The metadata-only full Qwen architecture probe also checks native FP8 replacement
and all 400 targeted text projections: full attention q/k/v/o, MLP gate/up/down,
Gated DeltaNet in_proj_qkv/in_proj_z/out_proj. Rank 16 yields 108,789,760 BF16
trainable parameters. Vision/head/MTP remain untargeted. No model weights or
hybrid forward/backward are involved in this structural check.

**Additional loader concern:** with the official exclusion list, native replacement
produces 336 targeted FP8Linear modules and 64 ordinary BF16 `mlp.gate_proj`
modules. The list includes names ending in `mlp.gate`; Transformers' unanchored
regex matching also matches `mlp.gate_proj`. The official weight index contains
64 corresponding `gate_proj.weight_scale_inv` entries. This is a concrete
configuration/replacement mismatch, not yet a demonstrated numerical failure:
actual tensor loading must verify scale application, unexpected keys and module
dtypes. Do not blindly delete exclusions, which also protect vision and GDN
components. The same matching expression remains in 5.17.0 and inspected main.
[Matching helper](https://github.com/huggingface/transformers/blob/v5.17.0/src/transformers/quantizers/quantizers_utils.py),
[official weight index](https://huggingface.co/Qwen/Qwen3.8-27B-FP8/blob/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a/model.safetensors.index.json).

Continue using `enforce_bf16_lora` **before constructing the optimizer**, then
verify parameters, gradients, FP32 optimizer moments and saved/reloaded tensors.
Do not call `.to(bfloat16)` on the entire quantized model. The dtype fix does not
change the native FP8 training rejection. [Precision helper](browser_training/precision.py),
[PEFT dtype movement](https://github.com/huggingface/peft/blob/v0.21.0/src/peft/tuners/tuners_utils.py).

Reproduce the local audit, with existing dependencies and no network/weights/GPU:

```bash
cd training
PYTHONPATH=. envs/rl/.venv/bin/python scripts/validate_fp8_training_cpu.py
```

The explicit BF16-dequantized tiny control has finite input/adapter gradients.
It is labelled separately; it is not a persistent-FP8 backward result. The
synthetic checkpoint-loading diagnostic bypasses only the hardware availability
check and records the native loader failure, with no FP8 forward executed.

### 5. Would FP8 trainer and rollout logprobs be sufficiently consistent?

**Not established.** Identical checkpoint/adapter values remove one source of
NF4/FP8 mismatch, but activation scaling, dequantization, GEMM/attention/GDN
kernels, accumulation, batching and sampling processors can still differ.
Axolotl's FP8-storage/BF16-compute route is not numerically identical to vLLM's
FP8 activation/weight execution merely because both load the same checkpoint.

After a candidate passes backward qualification, compare selected-token logprobs
on identical token histories under zero and trained adapters. Fix model/adapter
revisions, tokenizer, chat template and sampling/logprob convention. Record
median/tails/max differences, repeated-serving noise, sequence log-ratio drift,
importance-weight tails/clipping and actual held-out learning behaviour. There
is no universal scalar tolerance that certifies RL stability. The previous
identity/noise experiments did not establish this parity. No new GPU numerical
run was performed; the user's pause on that investigation remains respected.

### 6. Attention, checkpointing, Gated DeltaNet and serving limits

Gradient checkpointing recomputes forward operations; it cannot repair a missing
backward. Retain non-reentrant checkpointing and `use_cache=False`, with a test
that reaches early-layer adapters. Full-attention FlashAttention does not supply
Gated DeltaNet kernels or guarantee packed-sequence state isolation. Keep the
qualified unpacked microbatch-one / `token_budget=0` path until both attention
and recurrent boundaries are validated. L40S/SM89, Hopper/SM90 and Blackwell/SM120
kernel combinations require separate checks; SM100 support is not proof of SM120
support. The earlier FA2 wheel build remains only build/import evidence.

vLLM adapter synchronization transfers adapter snapshots, not the trainer's
frozen base or its backward implementation. It can remain unchanged if a new
backend preserves adapter names, shapes, scaling and checkpoint format. Existing
runtime version leases still apply. Test old and new policy versions explicitly
before declaring a converted backend compatible. SFT r32 → RL r16 also requires
a policy-preserving handoff; our current loader refuses rank/target mismatch.

### 7. Are compressed-tensors or Transformer Engine cleaner alternatives?

| Route | What is supported | Consequence for this project |
| --- | --- | --- |
| Native official FP8 | FP8 inference; training guard rejects | Not a stock trainer solution |
| Axolotl frozen FP8 + fused LoRA | SFT-specific FP8 storage, dequantized BF16 autograd kernels | Existing unqualified candidate; not an AsyncGRPO integration |
| compressed-tensors regular training | Decompressed weights / quantization-aware paths | PEFT support does not guarantee persistent 8-bit base storage |
| compressed-tensors optimized FP8 | FP8 kernel inference, `is_trainable=False` | Does not solve the desired backward |
| Transformer Engine | Training-aware FP8 compute and PEFT TE-layer adapters | Most credible FP8-backward building blocks, but a new integration to qualify |
| Proven NF4/BF16-LoRA | Actual SFT and AsyncGRPO learning | Preserve as fallback |

**compressed-tensors:** the current Transformers quantizer documents eager
decompression or decompression on first forward for its regular path. Its
`use_optimized_inference=True` FP8 path returns non-trainable. An FP8 checkpoint
that can be fine-tuned after decompression does not meet the frozen-FP8-memory
requirement. The official Qwen checkpoint is not in this backend's format;
renaming `quant_method` is not a conversion. [Current quantizer source](https://github.com/huggingface/transformers/blob/b22fe4624c55416fc0f122cd531695e03fc93561/src/transformers/quantizers/quantizer_compressed_tensors.py),
[compressed-tensors documentation](https://huggingface.co/docs/transformers/main/quantization/compressed_tensors).

**Transformer Engine:** PEFT has native adapters for TE Linear/LayerNormLinear/
LayerNormMLP. TE's experimental `quantized_model_init` can retain only quantized
parameters and explicitly names frozen-base LoRA as a use case. This is stronger
than simply setting mixed precision to FP8, which can retain higher-precision
weights. However, the official 128×128 checkpoint scales are not automatically
imported into TE by Accelerate's generic layer conversion. Starting from BF16
and quantizing to TE's recipe is also not necessarily the same frozen base as
the official serving checkpoint. Adapter conversion order, keeping LoRA BF16,
Qwen's hybrid projections, checkpoint recomputation, train/eval precision and
export names all need validation. PEFT TE adapter merge/unmerge is unsupported.
No clean Qwen3.8 official-FP8 → TE → AsyncGRPO example was established in this
audit. [PEFT TE source](https://github.com/huggingface/peft/blob/v0.21.0/src/peft/tuners/lora/te.py),
[TE quantized initialization](https://docs.nvidia.com/deeplearning/transformer-engine/user-guide/api/pytorch.html#transformer_engine.pytorch.quantized_model_init),
[Accelerate precision guide](https://huggingface.co/docs/accelerate/en/usage_guides/low_precision_training),
[Accelerate converter](https://github.com/huggingface/accelerate/blob/v1.13.0/src/accelerate/utils/transformer_engine.py).

Axolotl explicitly limits its fused LoRA kernels to SFT/FSDP2, not RLHF; using
them inside TRL would be integration work, not a supported configuration toggle.
[Support matrix](https://docs.axolotl.ai/docs/support-matrix.html).

### Next decision, before renting hardware

Keep the successful NF4 stack intact. If FP8 investigation is prioritized, first
choose an upstream training backend and a supported import/conversion route.
Resolve the exclusion-list/load mapping concern as part of that route.
Then qualify a tiny two-layer frozen-FP8 + BF16-LoRA input-gradient test against
a dequantized reference, with checkpointing on/off; require early-adapter
gradients, finite updates and unchanged base storage. Only then progress to Qwen
hybrid forward/backward, native AsyncGRPO construction, adapter sync and matched
logprobs. A native-loader rental now would mostly reproduce a rejection we can
already demonstrate on CPU. No dependencies, training defaults or cloud resources
were changed by this recheck.

## NeMo-RL / Megatron alternative — 16 September 2026

**Decision: worth a bounded feasibility test, not yet a replacement for the
validated NF4 trainer.** The preceding audit established a stock HF/TRL loading
and backward limitation; it did not exhaustively evaluate NeMo-RL's Megatron
backend. NVIDIA now documents Qwen3.8-27B text-only GRPO with Megatron Bridge and
vLLM, including loading, refit, logprobs and optimizer updates. That makes this
a substantially stronger candidate than assembling a custom TE integration.
[Qwen3.8 support](https://docs.nvidia.com/nemo/rl/nightly/guides/models/qwen/qwen3-8.html).

The key distinctions from a demonstrated exact recipe are:

- MCore's `fp8_param=true` genuinely requests FP8 parameter storage for eligible
  GEMM weights; biases and other excluded parameters stay in higher precision.
  It is distinct from FP8 compute. This flag alone does not establish total
  residency: inspect TE storage, retained copies and optimizer membership.
  [MCore configuration](https://docs.nvidia.com/megatron-core/developer-guide/latest/apidocs/core/core.transformer.transformer_config.html#core.transformer.transformer_config.TransformerConfig.fp8_param).
- Bridge exposes an independent `lora_dtype`, and NeMo documents Megatron LoRA
  SFT/GRPO. Still verify actual adapter storage and gradients: the inspected
  Bridge LoRA transform passes `lora_dtype` to the ordinary Linear adapter,
  whereas its parallel adapter branch receives the model configuration.
  A dtype setting in documentation is not a substitute for checking the
  modules used by Qwen. [LoRA guide](https://docs.nvidia.com/nemo/rl/nightly/guides/lora.html),
  [Bridge transform source](https://github.com/NVIDIA-NeMo/Megatron-Bridge/blob/6821931f8ed82f9d2f228a4dd537fab26775cdde/src/megatron/bridge/peft/lora.py).
- The documented Qwen3.5 FP8 training/rollout recipes use **`fp8_param=false`**.
  Bridge's verified Qwen3.8 LoRA/SFT configurations are BF16. Neither establishes
  Qwen3.8 + physically FP8 frozen weights + BF16 LoRA + GRPO end to end.
  [Qwen3.5 FP8 details](https://docs.nvidia.com/nemo/rl/nightly/guides/models/qwen/qwen3-5.html#fp8-rollout-and-training),
  [Qwen3.8 Bridge guide](https://docs.nvidia.com/nemo/megatron-bridge/nightly/models/qwen/qwen3.8-27b.html).
- NeMo's FP8 guidance recommends Hopper for its DeepSeek-style training recipe;
  it explicitly cautions that this recipe with FP32 scales is unsupported for
  Blackwell training. This is a recipe-specific limitation, not a statement
  that Blackwell cannot train in FP8. Prefer Hopper for the first qualification.
  [FP8 guidance](https://docs.nvidia.com/nemo/rl/nightly/fp8.html).

**Refit and browser episodes need their own qualification.** The inspected
Megatron worker calls Bridge's HF export, whose default merges adapters, and
has a separate physical FP8 weight/scale export path. Correct composition of
those paths is still unverified; adapter-only runtime synchronization must not
be assumed. Export a deliberately nonzero adapter and compare the refitted
policy before trusting learning results. Starting from BF16 and converting to
TE also need not recreate the official FP8 checkpoint's effective weights.
Matched FP8 names do not guarantee matched logprobs.
[Worker source](https://github.com/NVIDIA-NeMo/RL/blob/1cef394359aeddf1eaf4f1d209208be7b6ec0b1a/nemo_rl/models/policy/workers/megatron_policy_worker.py),
[Bridge export source](https://github.com/NVIDIA-NeMo/Megatron-Bridge/blob/6821931f8ed82f9d2f228a4dd537fab26775cdde/src/megatron/bridge/models/conversion/model_bridge.py).

NeMo supports trajectory-age tracking and draining pending generation before
refit with `in_flight_weight_updates=false`. Its optional in-flight update mode
can pause and resume requests across a weight change; it does not provide our
desired unchanged policy throughout an episode. Start with draining and verify
that the unit drained is the entire browser episode, including all tool calls.
Our TRL session leases cannot be assumed to transfer to this orchestration.
[Async guide](https://docs.nvidia.com/nemo/rl/nightly/guides/async-grpo.html),
[Collector source](https://github.com/NVIDIA-NeMo/RL/blob/1cef394359aeddf1eaf4f1d209208be7b6ec0b1a/nemo_rl/algorithms/async_utils/trajectory_collector.py).

Next test sequence: select one NeMo checkout/container with its own matching
Bridge/MCore/TE dependencies; qualify a small Qwen hybrid model with physical
FP8 base storage, BF16 adapters, frozen-base checks and nonzero early-layer
gradients; repeat with checkpointing; validate nonzero-adapter export/refit and
fixed-history logprobs; then attempt a short 27B update and a mock multi-turn
episode spanning a requested refit. Measure peak memory and synchronization
cost before choosing hardware or migrating BrowserGym. The shipped 27B recipe
uses 16 GPUs; that is a tested topology, not an established minimum.

This was a documentation/source review, not a NeMo runtime test. Source snapshots
were NeMo-RL `1cef394359aeddf1eaf4f1d209208be7b6ec0b1a` and Bridge
`6821931f8ed82f9d2f228a4dd537fab26775cdde`; they were inspected independently,
not validated as a compatible installation. No paid compute or large dependency
downloads were started, and the working training configurations are unchanged.

### Hopper experiment results — 16 September 2026

**The isolated FP8/BF16-LoRA backward tests passed, including a reduced Qwen
hybrid model. FP8 parameter storage did not halve resident GEMM-weight memory in
this configuration.** Evidence is in
[`research/nemo-fp8-modal-validation.json`](research/nemo-fp8-modal-validation.json).
This advances the NeMo alternative beyond a documentation-only hypothesis;
it does not yet qualify a production trainer or the exact 27B checkpoint.

We used the NVIDIA NeMo-RL v0.7.0 amd64 container pinned by digest, on an H100
80GB (SM90). Its actual policy-worker environment contained PyTorch
2.11.0+cu130, TE 2.15.0+42b84005, MCore 0.19.0+7b8495881 and Transformers 5.8.1.
The source identities matter more than editable package version strings:
NeMo-RL `19244a0949fb363326f71675223da75e09d14866`, Bridge
`151168f36372132c8fb8f926501f573019feb967`, MCore
`7b8495881dee1689db9d5ed636d8b6b48eacf260`. The image's NeMo distribution metadata
reports `0.6.0+19244a094` despite the release tag; we did not substitute packages.
Modal supplied driver 580.95.05, running the CUDA 13.2 base image in minor
compatibility mode. The exercised kernels worked in that combination.

| Isolated check | Result |
| --- | --- |
| Two MCore/TE linear layers + Bridge BF16 LoRA, BF16 base control | Passed |
| Same module types with physical blockwise FP8 base storage | Passed |
| FP8 linear test with TE activation checkpointing | Passed |
| Four-layer dense GDN/full-attention model, FP8 base + BF16 LoRA | Assertions passed |
| Same reduced hybrid architecture with full activation checkpointing | Assertions passed |

Each case performed three stateless SGD updates against a synthetic squared-error
objective. Adapter parameters and gradients stayed BF16; early adapter gradients
were finite/nonzero; frozen parameters acquired no gradients; frozen dense
weights and FP8 rowwise weights/scales were unchanged. The linear test also
verified input gradients through the frozen layers. The hybrid model had
5,174,960 parameters, 16 adapted modules and 32 adapter matrices. Loss fell from
0.2138 to 0.2095 without checkpointing and 0.2145 to 0.2119 with checkpointing.
These are plumbing measurements, not task-learning or convergence evidence.
The cases use separate random initializations, so they are not a numerical
equivalence comparison between precision/checkpointing settings. Production
optimizer state/master-weight handling remains untested here.

**Memory surprise:** the hybrid's 4,665,344 FP8 GEMM-weight elements occupied
9,334,256 bytes of distinct quantized GPU allocations, including scales. TE
retained separate rowwise and columnwise uint8 storage; storage pointers proved
these were not aliases. Bridge/MCore also retained 9,330,688 bytes of BF16
initialization values on CPU. Thus `fp8_param=true` was real, but the two FP8
orientations together cost approximately BF16-sized GPU weight storage. This
does not support a ~27 GB base-residency estimate for a 27B trainer. Full-model
peak memory, workspaces and supported ways to avoid unnecessary retained copies
need a separate check before selecting a smaller training GPU.

**Supervisor qualification:** the first GPU launch stopped on a test-configuration
mistake in the hybrid case (generic GPT GELU instead of Qwen SiLU). The corrected
hybrid run wrote its complete PASS report at 206.9 seconds, but had not exited at
the 210-second subprocess deadline. The supervisor killed it and correctly
recorded FAIL. We recovered the complete report from the result volume; its
assertions passed, but this was not a clean process-exit test. The launcher now
preserves completed JSON evidence even when process exit times out, and allows
more subprocess headroom for an isolated stage within the same outer cap; those
launcher changes were checked locally, not rerun on GPU.

The two GPU calls together took 388 seconds from submission to local report,
including queue/startup, within the authorized ten-minute envelope. This is not
an invoice measurement. All six preparation/test apps were verified stopped with
zero tasks afterward. The large first container import and one repeated CPU
import timeout consumed preparation time, not GPU allocations. Successful import
inventories can now be reused only for the exact same container digest and policy
worker. No pretrained weights were downloaded and no 27B training ran.

Next gates remain memory residency and nonzero-adapter export/refit, then an
actual NeMo GRPO update and multi-turn policy consistency. The hybrid probe uses
Bridge's fused GDN `in_proj` (including b/a projections), rather than exactly
our existing HF adapter target subset; target mapping and adapter handoff remain
part of export qualification. Keep the validated NF4/TRL setup unchanged.

### Follow-up: residency and export qualification

**Synchronization architecture clarification:** the intended project design is
an unchanged FP8 rollout base plus versioned BF16 adapters, transferring only
adapters after updates. The existing TRL runtime path follows that design. The
NeMo probes instead inspected its native merged-weight export/refit path; no
actual full-model transfer was run. Failures in that path are not blockers for
adapter-only synchronization in principle. Before further merged-refit GPU
tests, determine whether the chosen NeMo version can natively export and publish
adapter versions while preserving episode leases. Bridge's
`export_adapter_weights` API exists, but an adapter checkpoint exporter alone is
not an integrated asynchronous synchronization mechanism. Also verify that
Megatron's fused projection adapters map to supported vLLM targets and that the
two engines start from compatible effective base weights. Do not silently replace
the requested synchronization design with full-model refit or implement a custom
synchronization system as part of this qualification.

**Experiment provenance and objective:** policy alignment is the primary reason
to investigate FP8 on both sides; memory fit remains a constraint. We did not run
an upstream end-to-end RL recipe unchanged. We used the pinned NVIDIA container
and native TE/MCore/Bridge APIs in custom small probes, combining physical FP8
parameters (`fp8_param=true`) with frozen-base BF16 LoRA. The documented Qwen3.5
FP8 GRPO recipes use `fp8_param=false`, while Qwen3.8 has a separate functional
GRPO recipe. No validated exact Qwen3.8 + physical-FP8-base + BF16-LoRA + GRPO
recipe was found. The export failures therefore do not establish failure of an
as-shipped end-to-end recipe. Nor do our weight checks establish policy/logprob
alignment. FP8 storage, FP8 compute and inference quantization remain separate
choices.

The duplicate layout is an intentional TE implementation choice, documented
explicitly in its blockwise-scaling guide: Hopper requires a physical transpose
for columnwise access. With 2D weight scaling, this is another layout of the same
quantized values and scales, not a separately learned backward policy. The
guide distinguishes this from 1D scaling, where the two orientations can have
different quantization error. TE's performance documentation also explains that
layout sharing depends on the hardware and quantization recipe; the observed
duplication must not be generalized to all FP8 implementations or Blackwell.
These are current TE 2.19 explanatory docs; our runtime remains pinned to TE
2.15, whose source and measured storage confirm the Hopper behavior.
[TE transpose handling](https://docs.nvidia.com/deeplearning/transformer-engine/features/low_precision_training/fp8_blockwise_scaling/fp8_blockwise_scaling.html#handling-transposes),
[TE performance considerations](https://docs.nvidia.com/deeplearning/transformer-engine/features/low_precision_training/performance_considerations/performance_considerations.html).

The runtime image and the newer upstream source review have different refit
paths. In the pinned NeMo `19244a094` worker, `_calculate_refit_param_info` builds
ordinary Bridge conversion tasks, then `_iter_params_with_optional_kv_scales`
passes those tasks to `export_hf_weights`. It does **not** contain the newer
`_is_fp8_export`/physical-FP8 refit selection inspected above. Test the pinned
path separately from explicit Bridge FP8 export; support in newer source is not
evidence that the container uses it.
[Pinned worker](https://github.com/NVIDIA-NeMo/RL/blob/19244a0949fb363326f71675223da75e09d14866/nemo_rl/models/policy/workers/megatron_policy_worker.py),
[pinned Bridge exporter](https://github.com/NVIDIA-NeMo/Megatron-Bridge/blob/151168f36372132c8fb8f926501f573019feb967/src/megatron/bridge/models/conversion/auto_bridge.py).

The duplicate GPU orientations have a purpose: TE's backward explicitly requests
columnwise weight storage for input gradients. Earlier LoRA layers need those
gradients even when the intervening base weights are frozen. The blockwise tensor
API can discard an orientation with `update_usage`, and for 2D scaling recreate
the columnwise form from the rowwise form. Discarding it between steps therefore
does not establish a lower training peak; no custom memory scheduler is being
implemented. CPU initialization copies have a documented
`clear_high_precision_init_val()` API. They exist to initialize higher-precision
optimizer master weights and can be released when no longer needed; the prior
probe did not clear them. This is a source finding, not a new measured memory
improvement.
[TE backward](https://github.com/NVIDIA/TransformerEngine/blob/42b84005/transformer_engine/pytorch/module/linear.py),
[orientation storage](https://github.com/NVIDIA/TransformerEngine/blob/42b84005/transformer_engine/pytorch/tensor/storage/float8_blockwise_tensor_storage.py),
[initialization-copy API](https://github.com/NVIDIA/TransformerEngine/blob/42b84005/transformer_engine/pytorch/quantization.py).

**Hopper follow-up outcome:** ordinary BF16 export preserved the nonzero adapter;
explicit physical-FP8 export failed. The final probe completed and deliberately
returned `BLOCKED`/exit 1, rather than timing out. See
[`research/nemo-fp8-export-validation.json`](research/nemo-fp8-export-validation.json).

The same random 5.17M-parameter hybrid received deliberately nonzero rank-16 BF16
adapter matrices. Independent `W + 2BA` calculations before fused-projection
splitting agreed with Bridge's logical merge across all 16 adapted projections.
The GDN merge multiplies adapters in BF16, whereas other branches promote to
FP32; the reference explicitly matches that arithmetic and records its deviation
from FP32. This was not another learning run.

| Export check | Measured result |
| --- | --- |
| Ordinary conversion tasks, as selected by the pinned worker | 16 adapted tasks, 31 HF tensors, no exceptions; all outputs BF16 |
| Ordinary export versus logical higher-precision merge | Worst relative L2 weight error 0.2202%; max element error 0.000628 |
| Explicit physical-FP8 tasks + default LoRA merge | 19 exceptions among 32 weight/scale tasks |
| Frozen base rowwise data and scales | Unchanged after export checks |
| Actual vLLM refit / inference / logprobs | Not run |

The physical export failures included trying to combine full-sized adapter
updates with block-scale matrices, invalid GDN scale reshaping, and unsupported
FP8/BF16 promotion in GDN merges. An additional isolated test fed actual TE raw
FP8 values into the upstream merge helper and reconstructed the receiver's
scaled values. The intended update norm was 5.168; the received update norm was
0.0000372, with 99.99995% relative update error. The helper added a logical update
to raw quantized-number units. This is an explicit-physical-export/helper result,
**not** a claim that the pinned ordinary worker silently loses its updates.

One comparison control reused the original weight scales after a deliberately
large update and produced nonfinite values. That GPU control is invalid and is
preserved as such in the evidence; it does not quantify normal FP8 rounding.
The probe now recomputes control scales, checked locally for increased ranges,
zero blocks and partial blocks, but that amended control was not rerun on GPU.
The two earlier attempts stopped on probe issues: a config-only wrapper API
restriction and an FP32 reference that did not match GDN's BF16 multiplication.

**Promising supported route to test next:** the pinned NeMo inference loader
already quantizes ordinary merged weights with fresh scales before calling
vLLM's `model.load_weights`. Thus the tested BF16 export can potentially feed an
FP8 inference policy without using the broken direct physical-FP8 export.
BF16 here describes transient export/transfer tensors; it does not change the
trainer's persistent TE base representation. This is full merged-weight refit,
not our TRL runtime adapter-version synchronization. It still requires a live
receiver test, matched-history logprobs and episode-safe update scheduling.
[Pinned native receiver](https://github.com/NVIDIA-NeMo/RL/blob/19244a0949fb363326f71675223da75e09d14866/nemo_rl/models/generation/vllm/quantization/fp8.py).

The small CPU reproducer `scripts/nemo_fp8_export_cpu.py` extracts the pinned
upstream merge and receiver-quantization functions without importing the GPU
frameworks. It distinguishes incorrect raw-unit merging from BF16 merged-weight
transfer followed by native requantization. This is arithmetic evidence, not
live vLLM refit qualification.

That CPU check passed: an intended update of 0.0801563 became 0.0800781 after
BF16 export and native requantization (0.0976% relative update error), whereas
raw-unit merging delivered zero. This constant-matrix example establishes the
arithmetic distinction; it is not a model-wide error estimate.

The three attempts consumed 413 seconds in total from submission to report,
including startup/queue time, and 228 seconds inside GPU functions. Both figures
are timing measurements, not invoices. All three apps were verified stopped
with zero tasks. No further GPU runs were started. Retain the tested NF4/TRL
configuration while qualifying the ordinary-export path; the failed physical
export composition does not rule out NeMo as a whole.

### Adapter-only hybrid feasibility follow-up (2026-09-16)

The next experiment is now **adapter-only export**, not more merged full-base
refit testing. See the [source-level comparison of hybrids A/B](../docs/agents/training-fp8-hybrid-feasibility.md)
for exact revisions, call paths, version-lifetime requirements and probe commands.

Neither proposal is an existing recipe. A has the smaller next isolated probe
and preserves our rollout/session work, but TRL has no Megatron training-backend
plug-in: a service/controller would own backward, optimizer and checkpoints.
B preserves NeMo's Megatron training machinery but needs changes through refit,
request routing and episode lifetimes. PR #3964 replaces one fixed adapter ID;
it does not supply the required simultaneous immutable policy versions.

Local validation reused pinned TRL's unchanged loss with a synthetic BF16 model
and BF16 adapters: masking, clipping, accumulation and gradients passed. This
does not establish Megatron/FP8 integration. A tiny real Megatron update/export
probe is prepared and syntax-checked, **not GPU-executed**. No rental was started.
The tested older Bridge saver promotes exported adapters to FP32, while inspected
current Bridge preserves dtype; the probe explicitly verifies BF16 export and
serialization. Frozen-base numerical alignment remains an independent gate.

**Subsequent decision:** retain NF4 training + BF16 adapters + FP8 vLLM rollouts;
pause the custom Megatron integration and its proposed GPU probe. The user judged
the maintenance/correctness burden unjustified given the timeline and unresolved
FP8 numerical mismatch. Research remains available for a future upstream-supported
path. The [training plan](../docs/training-plan.md) records this decision and the
next proposed work on task-level observability and curriculum sampling.
