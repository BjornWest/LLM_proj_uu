# Training infrastructure: findings, evidence and next deployment

**Status at 16 September 2026: both SFT and the core asynchronous RL loop have demonstrated learning with the real 27B model on rented L40S GPUs.** Model-driven, multi-turn browser training is the next integration milestone. The remaining work is primarily task design, harness reliability and realistic-context validation; this is not yet a qualified sustained browser-training system.

This is the consolidated project write-up. The [research notebook](../training/NOTES.md) retains upstream sources and the investigation history. The [operational handoff](agents/training-modal-preflight.md#ssh-deployment-handoff) contains the SSH migration commands and caveats. All completed test containers were stopped. No further GPU runs or recurring cloud work are scheduled by this handoff.

## What we have actually demonstrated

| Check | Result | What it does not establish |
| --- | --- | --- |
| 27B NF4 Axolotl SFT | Real updates, BF16 adapters, FP32 optimizer moments, intermediate-checkpoint resume with a nonzero adapter change; tested examples up to 1,907 tokens | Long-context fit, sustained training or tuned throughput |
| SFT behavior learning | 64 examples, 32 updates; held-out exact matches **0/16 → 16/16** after reloading the saved adapter | Browser competence, unseen vocabulary or arbitrary sentence lengths |
| Two-GPU AsyncGRPO learning | Eight updates; rewarded answers **34/64 → 64/64** through the final natively synchronized vLLM policy | Multi-turn browser learning, broad generalization or numerical parity |
| Runtime LoRA lifecycle | Load, retain, replace and evict versions; same-rank identity checks; worker-cache removal | An exhaustive proof against every long-run leak or race |
| BrowserGym/OpenEnv integration | Real local browser sessions, task rewards, official tokenizer/parser, native harness and spawned rollout worker, policy-session tests | Model-generated browser actions and trainer gradients in one combined run |
| SM120 preparation | Attention source audit, optional FA2 wheel compilation/import and CPU configuration checks | Actual SM120 training kernels or MIG execution |

Evidence: [SFT execution/resume](../training/research/modal-l40s-validation.json), [SFT learning](../training/research/modal-sft-learning-validation.json), [RL learning](../training/research/modal-e2e-validation.json), [adapter identity](../training/research/adapter-identity-validation.json), [browser integration](../training/research/browser-validation.json), [spawned harness](../training/research/spawned-harness-validation.json), [policy sessions](../training/research/policy-session-validation.json).

### SFT: the apple test

The prompt says `Repeat: red boat`. Training supplies `red apple boat apple` as the assistant answer; the input never explains the apple rule. We generated 64 unique color/noun pairs and held out 16 different combinations of the same vocabulary. Eight training examples were also checked separately.

Before training, none of the 16 held-out answers had the target format. After one pass through the training examples, all 16 did; the eight training examples also improved from zero to eight exact matches. For example:

```text
Input:   Repeat: red boat
Before:  red boat
After:   red apple boat apple
```

We erased every in-memory LoRA tensor, reloaded the checkpoint, checked exact equality of all 800 saved adapter tensors, and only then ran the final generation evaluation. This establishes that the saved artifact carries the learned behavior. The frozen base stayed in memory; this was not a cold model reload. All final answers terminated with EOS, and training loss fell from 6.05 to approximately 0.000004 across training batches. No held-out loss was measured.

The run used one L40S for **271.32 seconds of GPU-function execution (4m31s)**, after a separate allocation wait. This is measured execution time, not a provider invoice. The intentionally easy task establishes SFT plumbing and a small amount of compositional generalization, not task-solving quality.

### RL: the choice test

The model was asked to choose A or B. Calibration selected B as the rewarded answer; that target went to a deterministic reward callback, not into the prompt. Separate 64-sample evaluations measured 53.125% before training and 100% afterward. Their descriptive Wilson 95% intervals were approximately 41.1–64.8% and 94.3–100%.

This ran the actual pinned, patched `AsyncGRPOTrainer.train()`, its spawned rollout worker, real FP8 vLLM generations, computed rewards/advantages and eight optimizer updates. It used no synthetic behavior logprobs or advantages. Native synchronization published policies v1–v9, and the final evaluation queried **v9 directly**, rather than manually loading a trained adapter under a separate name.

The run took **392.91 seconds per GPU (6m33s)** on two L40S GPUs, or 13.10 aggregate GPU-function minutes. Adapter, optimizer, trainer and rollout state were saved. Event replay covered 57 groups / 228 episodes and six old-policy evictions, with no active session at eviction and no remaining session leases at shutdown.

The first forward/backward was slow (121 seconds versus roughly 4–6 seconds later). The resulting backlog caused **119 stale samples to be discarded**; accepted samples had recorded staleness at most two. This is a throughput-tuning concern, not evidence that stale samples were silently trained. The experiment does not resolve the effect of NF4/FP8 numerical differences on harder RL tasks.

## The configuration to carry forward

```text
Teacher trajectories → Axolotl SFT → BF16 LoRA adapter
                                      ↓
                              future browser RL

Trainer: frozen NF4 27B base + BF16 LoRA → TRL AsyncGRPO updates
                                              ↓
                           versioned adapter directories + HTTP registration
                                              ↓
Rollout: official FP8 27B base + BF16 LoRA → vLLM → browser harness
```

The SFT and RL learning tests used fresh adapters independently. Starting browser RL from the SFT adapter is the intended workflow, but that complete chain has not been demonstrated with real browser trajectories.

### Precision and model identity

The tested trainer checkpoint is `greghavens/Qwen3.8-27B-bnb-4bit`, revision `26157380225e427827263c34df23018a1e28dff5`. It is a community prequantized NF4 checkpoint: all seven shards were checksum-audited, the actual quantization state was inspected, and 496 NF4 linears were verified. This does not constitute an independent full-quality evaluation of the checkpoint.

The rollout checkpoint is official `Qwen/Qwen3.8-27B-FP8`, revision `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`. The original BF16 checkpoint remains a fallback, pinned at `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`.

Three different FP8 concepts must remain separate:

1. **Prequantized weight storage:** an FP8 checkpoint saves base-weight memory, but its layer implementation still needs a supported input-gradient path for adapter training.
2. **FP8 mixed-precision training:** enabling Axolotl's `fp8: true` is a compute strategy and can retain higher-precision master weights; it is not equivalent to loading an FP8 frozen base.
3. **Frozen quantized base with BF16 adapters:** this is our desired memory strategy. NF4 currently provides the GPU-tested training path; FP8 is the tested serving path.

Frozen weights still participate in backpropagation: gradients must pass through their operations to reach earlier adapters. Plain Transformers' pinned fine-grained FP8 quantizer marks its path non-trainable. Axolotl has a separate FP8/fused-kernel candidate, but we did not qualify it on a GPU. **NF4 was chosen for the demonstrated implementation and lower trainer memory, not because it is universally better than FP8.** No new calibration was needed to use the NF4 checkpoint. [Pinned FP8 quantizer](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/quantizers/quantizer_finegrained_fp8.py), [Axolotl FP8/LoRA support](https://github.com/axolotl-ai-cloud/axolotl/blob/v0.19.0/docs/support-matrix.qmd).

Trainable LoRA parameters and gradients are explicitly BF16. We disable PEFT's automatic adapter promotion where supported, enforce adapter storage dtype, and assert it during training and in saved files. The bitsandbytes AdamW32bit optimizer maintains FP32 moments. Merely setting `bf16: true` would not guarantee BF16 adapter storage.

### Architecture, adapter targets and conservative defaults

Despite the checkpoint name, the Transformers architecture is `Qwen3_5ForConditionalGeneration`: 64 text layers, comprising 48 Gated DeltaNet and 16 full-attention layers. Our adapters cover 400 projections / 800 tensors, with **108,789,760 parameters at rank 16**.

| Block | LoRA targets |
| --- | --- |
| Full attention | `self_attn.q_proj`, `k_proj`, `v_proj`, `o_proj` |
| MLP | `mlp.gate_proj`, `up_proj`, `down_proj` |
| Gated DeltaNet | `linear_attn.in_proj_qkv`, `in_proj_z`, `out_proj` |

Vision, embeddings, `lm_head`, MTP, convolution, a/b projections, decay parameters and norms remain unadapted. Some unadapted base projections are nevertheless quantized; “not a LoRA target” does not mean “stored in BF16.” Text-only training bypasses vision computation but still loads frozen vision weights. vLLM uses `--language-model-only`.

The validated baseline is rank 16, alpha 32, no dropout, non-reentrant gradient checkpointing, microbatch one, SDPA full attention, and no sequence packing. Rank 32 is an exposed option, not a measured result. Cut Cross Entropy, fused LoRA optimization kernels, FP8 KV cache and MTP are not part of the successful baseline.

### Reproducible environments

Keep SFT, RL/serving and browser-service environments separate. Axolotl's TRL dependency differs from the experimental AsyncGRPO revision we need; the OpenEnv distributions also cannot be casually mixed in one namespace.

| Component | Pinned setup |
| --- | --- |
| Python / uv | 3.12.12 / 0.10.8 |
| PyTorch / torchvision | 2.13.0 / 0.28.0, CUDA 13 stack |
| Transformers / PEFT / Accelerate | 5.16.1 / 0.20.0 / 1.13.0 |
| Axolotl | 0.19.0 in SFT; its TRL dependency is 1.9.0 |
| AsyncGRPO TRL | source commit `a04ffd337108285002df29d9ae73ef7e855e03f1` |
| vLLM | 0.28.0 in RL/serving |
| FLA / bitsandbytes | 0.5.2 / 0.50.2 |
| OpenEnv / BrowserGym | 0.4.2 / core and MiniWoB 0.14.3; browser Playwright 1.44.0 |
| Optional SM120 FA2 | 2.8.3, compiled/imported but not GPU-qualified |

The authoritative dependency graphs are the [SFT](../training/envs/sft/uv.lock), [RL](../training/envs/rl/uv.lock) and [browser](../training/envs/browser/uv.lock) lockfiles. Keep model revisions, source patches, actual package versions, seeds, resolved configs and per-run source hashes with each result. W&B is optional; the successful probes used local JSON/JSONL logs.

## Important discoveries and fixes

**Policy retention required more than keeping several adapter versions loaded.** The upstream rollout loop could reread the latest model name between turns, mixing policies within one episode. Pinning a name alone would still allow its adapter to be evicted while the episode was active. Our orchestration patch reserves a version per GRPO group, tracks episode/request leases, stops stale groups, and unloads only after leases drain. We retain TRL's native disk/HTTP synchronization rather than implementing a replacement transport. [Implementation and CPU/GPU evidence](../training/browser_training/policy_sessions.py).

**vLLM HTTP unload did not remove the cached engine adapter in the pinned implementation.** The audited patch calls the engine removal path as well. Physical worker-cache removal was checked in the lifecycle probe. These version-specific patches must be re-audited before any package upgrade; patch tools fail closed on unknown source.

**Quantized AsyncGRPO initialization needed small compatibility changes.** The tested candidate avoids an incompatible VLM unfreeze operation, prepares the quantized model for adapter training, disables adapter dtype promotion and permits the selected attention backend. This is an isolated, source-hash-checked adaptation of TRL, not a new RL algorithm. It is also not an unmodified upstream guarantee.

**Hybrid sequence packing is not qualified.** Resetting position IDs is insufficient to reset DeltaNet recurrence and convolution state between samples; a CPU reproduction found cross-sequence contamination. The RL probe therefore enforces `per_device_train_batch_size=1` and `token_budget=0`. Increase effective batch with accumulation first. Enabling FA2 alone does not fix recurrent boundaries. [Packing evidence](../training/research/hybrid-packing-validation.json).

**OpenEnv's existing harness is useful, but needed narrow adapters.** We map TRL's conversation-shaped task to the BrowserGym task identifier and normalize serialized tool arguments back to dictionaries for Qwen's template. The harness preserves token IDs, behavior logprobs and masks observations/tool outputs. A completed episode is one reward unit, but reconciliation may yield multiple training rows. Keep reasoning disabled in this path until `reasoning_content` survives the OpenEnv round trip. Bound session creation and cleanup; a native synchronous tool loop can otherwise block other episodes. [Harness bridge](../training/browser_training/harness_bridge.py).

**The dataset/action contract is still a project decision.** The converter supports successful-only trajectories, action versus reasoning+action, and whole-trajectory versus state/action layouts. Current plain-action SFT targets still need alignment with the harness's structured tool-call output. Reward should come from deterministic environment state, including constraints and unwanted side effects. Scripted browser tests are explicitly local fixtures, not full upstream benchmarks or final project tasks.

**Numerical variation remains unresolved, but is not evidence of the wrong adapter.** Same-rank tests verified adapter slot buffers and kernel inputs with distinguishable adapters. Observed maximum logprob differences were roughly 0.075–0.112 in instrumented repeated requests, including before a second adapter was published. Instrumentation perturbs execution; these maxima on a short prompt are not a task-quality or KL estimate. We have not isolated the mechanism or demonstrated trainer/rollout parity. General batch-dependent floating-point effects can occur without LoRA. The user paused further numerical investigations; the RL learning result shows that this easy task learns despite the current stack, not that all mismatch is harmless. [Identity evidence](../training/research/adapter-identity-validation.json), [Thinking Machines write-up](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/).

**Failures improved preflight coverage.** Earlier attempts stopped on request serialization (`BatchEncoding` rather than integer IDs) and a provenance logger that assumed the complete local directory layout existed remotely. Actual tokenizer payload serialization and provenance capture now run in the Modal CPU image before GPU submission. Queue time is separate from execution time, committed run markers prevent replay, and each bounded probe explicitly stops its containers. The historical reports preserve failures rather than counting them as successful training.

## Moving from Modal to an SSH-accessible host

SSH changes provisioning and process management, not the training algorithms. The tested inner programs—`sft_learning_probe.py` and `e2e_learning_probe.py`—can be invoked directly. Modal currently supplies the image build, GPU allocation, volume mounts, invocation deadlines and cleanup around them.

| Modal responsibility | SSH-host equivalent |
| --- | --- |
| CPU image build and locked installation | Prebuild an image or install the same separate uv locks on a prepared disk before GPU rental |
| GPU function / device allocation | A supervised process with explicit `CUDA_VISIBLE_DEVICES` |
| Model-cache volume | Persistent SSD/NVMe mount and explicit `HF_HOME` / `HF_HUB_CACHE` |
| Result volume and commits | Durable run directory, checkpoint retention and backups |
| Function timeout and cancellation | Process-group deadlines plus supervisor cleanup; separately stop the rented instance |
| SDK logs and app identity | Files, process logs, GPU telemetry, host identity and manifests |

Our recommendation is **one host with separate rollout and trainer GPUs for the first migration**. It closely matches the successful two-L40S container and uses a normal shared filesystem. SFT can use one GPU. A mixed-GPU host is reasonable if the trainer has sufficient memory and suitable kernels, but buying capacity solely from the tiny-task measurements would be premature.

The known inner programs are portable; there is not yet a qualified all-purpose production launcher or published standalone Docker image. In particular, the older `run_async_grpo.py` follows the earlier BF16/FA3 path, and `preflight.sh all` is not the exact successful NF4/SDPA test. Start with the direct probe commands in the [SSH handoff](agents/training-modal-preflight.md#ssh-deployment-handoff), then integrate the proven configuration into the eventual browser-training entry point. Do not install every package into one environment or silently upgrade around source-hash failures.

### Host prerequisites and storage

For the pinned CUDA 13 stack, NVIDIA lists Linux driver family **580 or newer** as the compatibility baseline. For this 13.0.3 stack, prefer 580.126.20 or newer, matching the [toolkit release recommendation](https://docs.nvidia.com/cuda/archive/13.0.3/cuda-toolkit-release-notes/index.html). A working wheel import is not a kernel test; PTX/JIT paths and the actual device still need validation. Docker GPU access additionally requires a working host driver and NVIDIA Container Toolkit. SSH access alone does not imply root access or permission to reconfigure GPUs. [CUDA compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html), [container prerequisites](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

Weights are about 19.4 GB for the NF4 checkpoint and 30.9 GB for FP8, before environments, compile caches and checkpoints. Keep full revision-pinned snapshots, including tokenizer/config metadata. Prefer downloading on a CPU host or attaching a populated persistent disk. Modal's cache volumes are not automatically local disks on another provider; transfer verified snapshots/checkpoints or download the same revisions there. Local diagnostics do not include all trained weights: the learned adapters and optimizer state remain in the Modal result volume. Retain those volumes until intentionally backed up or discarded.

The training source, lockfiles, tests, documentation and reviewed JSON evidence are included in the training infrastructure commit. A clone of that commit provides the code; environments, cached models, raw logs and generated checkpoints remain separate artifacts. Make sure the commit is available on the remote before cloning on a rental host. See the [artifact policy](../training/research/README.md), and keep archived source hashes with the recorded experiments.

### Separate trainer and rollout machines

This is plausible, but it adds a storage-consistency requirement as well as network latency. Native adapter sync writes versioned directories and asks vLLM to load an **absolute path**. Both machines must see complete files at the same path, with visibility and deletion semantics verified. A simple shared-filesystem mount is the first candidate; asynchronous object-store copying is not a drop-in replacement. Modal volumes also have explicit commit/reload semantics, unlike a single host's ordinary directory. [Modal volume semantics](https://modal.com/docs/guide/volumes).

The tested adapter-only path transfers files through shared storage and uses HTTP control calls; **it does not send adapter tensors through NCCL**. NCCL becomes relevant for tensor-parallel inference, distributed trainers or a different full-weight-transfer path. Do not add NCCL multi-node infrastructure just to serve these adapters.

Benchmark actual topology before committing: HTTP RTT, sustained private-link throughput, shared-directory visibility, adapter publish-to-first-use latency and inference stalls. Rank-16 BF16 adapter tensor payload is approximately **218 MB**; rank 32 roughly doubles it. Rank can therefore affect synchronization time as well as memory. The serving rank limit must accommodate it, and changing rank later still deserves a smoke test. Trainer/rollout traffic within a deployment is often called *east–west*; provider egress is an additional routing/billing question.

Keep runtime adapter-management endpoints private. On one host use loopback; between hosts use a private network/tunnel and deliberately scoped access. Supervise both processes and release session leases on failures. An SSH terminal or `tmux` session alone is not an execution budget, and killing Python does not stop instance billing.

### Hardware and MIG

L40S is the only GPU on which this exact combined learning path has passed. Its useful short-test fit does not establish that it is the best sustained-training choice. RTX PRO 6000 Blackwell remains attractive for memory, but actual SM120 kernels must pass on the selected host. Hopper is a sensible alternative to evaluate; it is not a GPU result we have already obtained.

The Modal RTX PRO probe found no usable MIG slices, so it aborted without training. That is a provider-access result, not proof of missing hardware capability. NVIDIA lists RTX PRO 6000 Blackwell Server, Workstation and Max-Q variants as MIG-capable. An SSH rental would still need exposed management controls, suitable profiles and enough memory per slice. A physical GPU split also divides compute and memory resources; it is not equivalent to two full GPUs. Recheck permissions and profiles before planning a MIG test. [NVIDIA MIG support](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/supported-gpus.html).

### Memory measurements to use cautiously

| Successful workload | Sampled device-memory peak | Allocated tensor peak |
| --- | --- | --- |
| SFT, apple task | 27,951 MiB | 19.63 GiB |
| RL trainer, choice task | 31,975 MiB | 25.28 GiB |
| RL FP8 rollout server | 38,767 MiB | Not separately measured |

Device memory includes reservations and runtime allocations; the two columns are not interchangeable. The probes have tiny sequences, and vLLM reserves a configured fraction of the GPU. Real browser contexts, longer completions and more concurrent episodes can change fit substantially. Rank affects adapter/optimizer state, while context and concurrency affect activations and KV/recurrent caches. Measure representative 2K/4K/8K workloads before promising a 48 GB or MIG-slice deployment; no larger-context VRAM estimate has been GPU-validated here.

## What to do when work resumes

1. **Settle the task/reward and action contract.** Specify success, constraint adherence, unauthorized side effects, timeouts and invalid actions. Align teacher logs, SFT targets and the harness parser. Keep training and evaluation tasks/site variants distinct.
2. **Make the harness dependable on CPU.** Test reset isolation, parallel sessions, slow tools, failed creation, cancellation, stale groups and cleanup. Preserve observations, action tokens, behavior logprobs, reward and policy version per trajectory.
3. **Run one bounded model-driven BrowserGym learning iteration.** Combine the already-tested browser and GPU paths on a trivial local task before moving to project tasks. This is the main missing end-to-end integration.
4. **Test actual AsyncGRPO resume.** Check restored optimizer/trainer/rollout state and a subsequent nonzero update. Checkpoint files alone are not proof of correct asynchronous restart.
5. **Reproduce on the chosen SSH host, then benchmark realistic workloads.** Increase browser concurrency independently of optimizer batch size. Measure generation, environment, update and synchronization time, staleness/discards and both GPUs' utilization. Tune the bottleneck observed there.

MTP with FP8/runtime LoRA, FP8 trainer storage, deterministic kernels, packing, multi-node orchestration and hyperparameter tuning remain optional later investigations. No NVFP4/QeRL, custom RL algorithm, preference reward model, final browser task suite or extended training run was added. We have enough evidence to pause infrastructure work and focus next on objectives and harness quality.
