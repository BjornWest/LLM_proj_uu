# Browser-agent training preparation

Open the [W&B training dashboard](https://wandb.ai/bjorn-westerlund-3326-uppsala-universitet/browser-training/reports/Browser-training-%E2%80%94-progress-and-health--VmlldzoxNzk2ODA0Ng==)
for explained charts of browser outcomes, GRPO signal and infrastructure health.
It currently shows the P11 infrastructure test; model-quality panels exclude
synthetic tests. The [reading guide](../docs/training-monitoring.md) explains
missing measurements and how to interpret the results.

Start with the [consolidated findings and next-deployment plan](../docs/training-findings.md). The [SSH handoff](../docs/agents/training-modal-preflight.md#ssh-deployment-handoff) maps the successful Modal probes to direct commands; older generic launchers below are not yet a unified NF4 browser-training entry point.

The [training experiment plan](../docs/training-plan.md) records the current data
splits, frozen-harness workflow, curriculum, evaluation and hyperparameter
candidates. **The selected working baseline is NF4 training + BF16 LoRA + FP8
vLLM rollouts. Custom FP8 trainer integration is paused.**
See the [source and CPU recheck](NOTES.md#fp8-trainer-recheck--16-september-2026).

**The two-GPU RL learning smoke passed: eight real AsyncGRPO updates raised the rewarded answer from 34/64 to 64/64 on a simple choice task.** The trainer used a frozen 27B NF4 base with BF16 adapters, synchronized through TRL's native LoRA publication path to FP8 vLLM. Checkpoints and safe session eviction were verified. See [learning evidence](research/modal-e2e-validation.json), [research answers and limits](NOTES.md), and [remote validation status](#remote-preflight).

The [SFT behavior test](research/modal-sft-learning-validation.json) also learned a simple apple-insertion rule: 0/16 → 16/16 exact held-out answers after reloading the saved adapter. Earlier L40S tests qualify NF4 SFT with BF16 adapters, FP32 optimizer moments and intermediate-checkpoint resume. The first real-model P11 browser/GRPO test completed two optimizer steps and checkpointing, but failed its shutdown safety check; details below. The SM120 FA2 wheel compiles and imports locally, but its GPU kernels remain unqualified; Modal exposed no usable MIG slices. Sustained RL and exact trainer/rollout numerical parity remain unqualified.

**19 September: monitored GRPO checkpoint resume also passed.** A real two-turn
synthetic task completed three updates, restored the exact adapter/optimizer/
scheduler state in a fresh process, then completed three more. The test caught
and fixed PEFT promoting BF16 adapters to FP32 on resume. Applied-row accounting,
policy retention and separate GPU resource measurements passed. See the
[acceptance record](../docs/agents/training-gpu-acceptance.md). This is still a
synthetic infrastructure check, not model-driven browser training.

**P11 browser follow-up: partial qualification.** Real model actions, native
rewards, eight applied rows, BF16 checkpointing and LoRA publication v1–v3 worked.
The applied reward groups were all successful, giving zero gradients; this does
not demonstrate browser learning. Shutdown exceeded TRL's 15-second wait and
correctly triggered the unsafe-worker guard. A bounded drain fix passes a
22-second delayed-response CPU test; GPU requalification remains pending.
All containers stopped. [Evidence](research/modal-project-browser-grpo-validation.json)
and [details](../docs/agents/training-gpu-acceptance.md#real-p11-gpu-outcome-partial-qualification-shutdown-failure).

Evidence: [SFT GPU](research/modal-l40s-validation.json), [browser](research/browser-validation.json), [tokenization](research/tokenization-validation.json), [deployment runbook](../docs/agents/training-modal-preflight.md).

The [same-rank identity test](research/adapter-identity-validation.json) now passes
slot-weight, kernel-input and ten-version eviction checks with distinguishable
BF16 rank-16 adapters. Logprob variation persists, including before any second
adapter was loaded during an instrumented request. This supports investigating
numerical execution and instrumentation effects; it does not qualify exact
reproducibility or trainer/rollout parity.

The bounded [end-to-end learning probe](scripts/modal_e2e.py) completed on two
L40S GPUs in 6m33s of function time per GPU. It published policies v1–v9,
evaluated v9, and saved the BF16 adapter and FP32 optimizer state. Recorded
evictions of v1–v6 occurred with no active sessions, and all sessions drained.
The slow first update caused a backlog; 119 stale samples were discarded.
All containers stopped. This is a single-prompt learning check, not a browser
benchmark or a throughput result. Numerical diagnostics remain paused.

## Small SFT learning check

**Passed on L40S:** 32 updates, 0/16 → 16/16 held-out exact matches, with the saved adapter reloaded. Function time 4m31s; all containers stopped. [Evidence](research/modal-sft-learning-validation.json).

`scripts/modal_sft_learning.py` tests a deliberately artificial rule: turn
`Repeat: red boat` into `red apple boat apple`. It uses 64 training examples,
16 held-out combinations of familiar words, and 8 training examples for a
memorization check. Before/after greedy generation is scored for exact matches,
apple placement and word preservation. The final evaluation erases and reloads
the saved adapter on the same frozen NF4 base. The predeclared learning threshold
is at least 75% held-out exact matches and an improvement of 50 percentage points.
This does not test browser skills, unseen vocabulary or FP8 serving.

```bash
cd training
.venv/bin/python scripts/modal_sft_learning.py --dry-run
# Paid run: requires authorization. Existing cached weights only, one L40S,
# maximum 10 minutes including startup, 32 updates, no automatic retries.
.venv/bin/python scripts/modal_sft_learning.py --gpu-seconds 600 --steps 32
```

The launcher validates the actual Axolotl dataset and provenance in a CPU
container before requesting a GPU. It saves the generated data, resolved config,
source/lock hashes, raw generations, checkpoints and metrics in the result
volume. A successful pipeline without sufficient learning is explicitly marked
`PIPELINE_PASS_LEARNING_INCONCLUSIVE`.

## Local checks

From the repository root:

```bash
bash training/scripts/bootstrap_remote.sh local
bash training/scripts/preflight.sh static
cd training
.venv/bin/python scripts/audit_upstream.py  # small official source files only
```

The training project has its own virtual environments; the existing browser project's `.venv`, dependencies and recordings are untouched. `scripts/common.sh` changes to `training/`, so relative dataset/output paths in launch commands are relative to that directory.

### Real browser validation without a GPU or training data

```bash
bash training/scripts/bootstrap_remote.sh browser-validation
# On a fresh CPU builder only: installs Chromium and its Linux libraries.
# Skip when the pinned Playwright browser is already cached.
training/envs/browser/.venv/bin/python -m playwright install --with-deps chromium
bash training/scripts/smoke_browser.sh
bash training/scripts/smoke_browser.sh --harness
# After installing the RL stack: actual spawned TRL worker, no import substitutes.
bash training/scripts/smoke_browser.sh --spawned
# Patched worker: force updates during real browser episodes, then test stale eviction.
bash training/scripts/smoke_browser.sh --policy-sessions
cd training
PYTHONPATH=. envs/browser/.venv/bin/python scripts/validate_tokenization.py
PYTHONPATH=. envs/browser/.venv/bin/python scripts/validate_rollout_worker.py
PYTHONPATH=. .venv/bin/python scripts/validate_attention_source.py
```

`smoke_browser.sh` starts and cleans up its own local OpenEnv server and browser processes. It registers a tiny HTML fixture with BrowserGym; no MiniWoB assets, project tasks or model weights are needed. The pinned upstream BrowserGym client/server files are hash-checked and cached (~33 KB). Two episodes run with overlapping lifetimes. A successful click/fill trajectory earns 1; a subscription action earns 0. Both pass through the actual upstream worker's generation/scoring/token-reconciliation code. Two additional browser sessions validate the official OpenEnv BrowserGymSessionFactory and MCPHarnessAdapter; the harness stops as soon as the environment finishes. The tokenizer and HTTP model replies are scripted, so this is browser/rollout plumbing validation, not a model-training test.

`--harness` additionally executes the native TRL harness loop with threaded OpenEnv sessions, including two episodes using Qwen’s real tokenizer and TRL’s response parser. It checks task selection, JSON tool-argument normalization, token/logprob reconciliation, policy mixing and shutdown behavior. Inference replies are scripted; no model is loaded. The first tokenization check downloads about 13 MB of tokenizer/config assets, plus small pinned source files.

`--spawned` uses the installed RL environment for TRL’s actual child-process controller and keeps the browser service in its own browser environment. It checks factory/tokenizer serialization, real OpenEnv sessions, scoring, queue transport, heartbeat and clean child shutdown; no Trainer or vLLM engine is created.

Reports: `research/spawned-harness-validation.json`, `research/browser-validation.json`, `research/harness-validation.json`, `research/tokenization-validation.json`, `research/rollout-validation.json`, `research/sm120-validation.json`. The policy audit deliberately reproduces the known defect and records `rl_ready: false`; successful script execution does not mean RL is ready. Network is only required to fetch missing small source files or refresh the attention audit.

### Policy reservations in the patched RL stack

`bootstrap_remote.sh rl` and `rl-sm120` apply a hash-checked patch to the pinned TRL worker, harness and trainer. It composes with the attention patch. For an already installed environment:

```bash
cd training
PYTHONPATH=. envs/rl/.venv/bin/python scripts/patch_trl_policy.py --diff  # inspect
PYTHONPATH=. envs/rl/.venv/bin/python scripts/patch_trl_policy.py --apply
envs/browser/.venv/bin/python -m pytest -q tests/test_policy_sessions.py tests/test_policy_harness.py
cd ..
bash training/scripts/smoke_browser.sh --policy-sessions
```

The tracker lives in a local manager process on the trainer host. It reserves a policy for an entire GRPO group, maps each episode ID to that version, and retains the adapter between browser turns. Threads and the spawned rollout worker share these reservations. vLLM still uses the native versioned adapter names and disk/HTTP load/unload API; no inference-server modification is required.

Publishing a version beyond `max_staleness` cancels the old group cooperatively: no more model requests are admitted, outstanding HTTP calls drain, and the whole group is discarded. Adapter files and registration are removed only after all its episode/group reservations release. A slow browser operation must return or reach its own deadline before its session can drain. Adapter residency is left to vLLM.

The patch conservatively stops on ambiguous inference failures, forced worker termination, or exhaustion of the `max_staleness + 2` adapter slots while old sessions drain. It does not retry timed-out inference or forcibly unload active adapters. Restart vLLM and resume from a checkpoint after an uncertain request/worker failure. This first implementation supports **one trainer process and the white-box OpenEnv harness**; it rejects loop-owning external agents and multi-process trainer synchronization. The production launcher remains gated pending GPU qualification and a project harness factory/action-format contract.

`policy-events.jsonl` in the training output records run/episode/group IDs, policy versions, request starts/ends, cancellations and eviction decisions. In-memory diagnostic history is bounded; the file keeps the complete event stream. [Implementation](browser_training/policy_sessions.py), [audited source edits](browser_training/policy_compat.py), [CPU integration evidence](research/policy-session-validation.json). The historical audit scripts continue testing **unmodified** upstream source so the original defect remains reproducible.

On this WSL installation, Chromium 125 was already cached but `libasound.so.2` was missing. We downloaded Ubuntu's 391 KB `libasound2` package and extracted it under `training/.cache/browser-libs/root`; the wrapper adds that private library directory. No system library was changed. Fresh remote images should use Playwright's OS dependency installer instead. The test server explicitly selects Uvicorn's `websockets` backend: its default `websockets-sansio` backend produced disconnect exceptions during normal session cleanup with this package set.

### Installed training packages on CPU

```bash
# Downloads several GB of wheels; no model weights or GPU training.
bash training/scripts/bootstrap_remote.sh sft
bash training/scripts/bootstrap_remote.sh rl
cd training
PYTHONPATH=. envs/sft/.venv/bin/python scripts/validate_training_cpu.py --role sft
CUDA_VISIBLE_DEVICES='' HF_HUB_OFFLINE=1 AXOLOTL_DO_NOT_TRACK=1 PYTHONPATH=. \
  envs/sft/.venv/bin/python scripts/validate_tokenization.py --installed-axolotl \
  --output research/sft-tokenization-validation.json
PYTHONPATH=. envs/rl/.venv/bin/python scripts/validate_training_cpu.py --role rl
```

The probe disables CUDA and Hub downloads. It validates framework config schemas, then uses a 24K-parameter randomly initialized Qwen3 model for two CPU LoRA updates and adapter save/reload. It asserts BF16 adapter parameters/gradients and FP32 bitsandbytes Adam moments. If the Qwen3.8 config was cached by the tokenizer probe, it also builds the full architecture as **metadata only**, verifies the target modules and counts 108,789,760 adapter parameters at rank 16. This allocates no 27B weight tensors and executes no hybrid-model forward pass. The RL probe also parses all six vLLM preset/optional-flag combinations through the installed server parser. It executes native TRL adapter publication with real BF16 snapshots and its actual HTTP client against a mock receiver that validates vLLM request schemas; it checks immutable files and registration-before-version-publication. No vLLM engine is created. Reports go to `research/{sft,rl}-cpu-validation.json`. The installed Axolotl labeling check separately confirms all six tokenizer cases without import substitutions.

The workstation driver reports CUDA 12.6, too old for these CUDA 13 wheels; the GTX 1070 is also outside their supported GPU targets. CPU probes still run. FLA warns that no supported accelerator is available, and bitsandbytes warns that its optional CPU 4-bit GEMM cannot find a compatible kernel-hub build. Our AdamW32bit CPU probe succeeds without that unrelated 4-bit kernel. No local driver change is needed for these checks. A tiny hybrid-model forward does reach FLA/Triton and fails without an active accelerator driver; the passing CPU update probe uses ordinary Qwen3 attention, not the hybrid kernels.

### Quantized trainer research for 48 GB GPUs

NF4 QLoRA now passes a tiny ordinary-Qwen CPU update/save/reload probe with BF16 adapters and gradients. The same hybrid architecture loads in NF4, but the pinned AsyncGRPO VLM constructor tries to unfreeze integer-packed weights and fails. A native text-only loading alternative also passes its loading checks. The older generic RL configuration still uses the BF16 fallback. The source-audited NF4 candidate has since passed actual two-GPU learning through `scripts/e2e_learning_probe.py`; use that tested path for reproduction. See [the NF4 investigation, memory estimates and L40S/A6000 assessment](NOTES.md#nf4-qlora-trainer-investigation--48-gb-l40s--rtx-a6000) and [probe evidence](research/qlora-cpu-validation.json).

```bash
cd training
PYTHONPATH=. envs/rl/.venv/bin/python scripts/validate_qlora_cpu.py
```

### NF4 SFT candidate and pretrained CPU validation

The additional [NF4 SFT config](configs/sft_qwen38_27b_nf4_qlora.yml) pins `greghavens/Qwen3.8-27B-bnb-4bit` at `26157380225e427827263c34df23018a1e28dff5`. Its base uses NF4 with double quantization and BF16 compute. Adapters and gradients are explicitly checked as BF16, optimizer moments as FP32. Vision, MTP and the output head are excluded from adapter targets. Start unpacked, without fused LoRA kernels; qualify packing separately on GPU. This NF4 path has since passed L40S SFT updates, resume and behavior learning; it is the tested training baseline. The original FP8-storage config remains a separate candidate.

```bash
cd training
# Keep this variable set for download AND launch. The shell wrappers otherwise
# default to training/.cache/huggingface. This workstation's weights use this cache:
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
bash scripts/download_models.sh smoke nf4  # ~1.5 GB + 19.4 GB, reusable on persistent disk
# Offline after download; four CPU steps on the small pretrained model only.
PYTHONPATH=. envs/sft/.venv/bin/python scripts/validate_qlora_sft.py
# Tiny hybrid initialization: proposed edits in an isolated module, no package mutation.
PYTHONPATH=. envs/rl/.venv/bin/python scripts/patch_trl_attention.py --apply
PYTHONPATH=. envs/rl/.venv/bin/python scripts/validate_qlora_trl_init.py
# All shard checksums + isolated real 27B projection backward passes, never a full-model load.
PYTHONPATH=. envs/rl/.venv/bin/python scripts/validate_nf4_checkpoint.py
# REMOTE GPU only, after suitable kernel/driver preflight and dataset conversion:
bash scripts/run_sft.sh --config configs/sft_qwen38_27b_nf4_qlora.yml \
  --steps 3 --save-steps 1 --output outputs/nf4-gpu-preflight
```

The SFT probe runs the actual Axolotl converter/tokenizer, model loader, trainer, optimizer and checkpoint path. It trains two steps, resumes to step three, then trains one step from a saved prequantized base. It preserves run outputs and emits [a report](research/qlora-sft-validation.json). CPU execution uses a public plugin hook to forward `use_cpu`; no upstream SFT source is patched. The separate [TRL initialization probe](research/qlora-trl-init-validation.json) reproduces the integer-weight failure, then validates a minimal proposed initialization fix without replacing the model loader. It additionally passes native GRPO-loss updates on ordinary Qwen3 and a tiny hybrid model using explicitly selected upstream PyTorch reference functions. It does not enable production NF4 RL or qualify GPU kernels.

This uses tiny random checkpoints and cached configuration metadata; no pretrained model weights, GPU execution or new dependency downloads are needed. The 27B storage estimate is about 23 GiB after standard k-bit preparation, plus adapter/gradient/optimizer storage and unmeasured activation/workspace costs. A 48 GB trainer is a candidate, not a measured fit guarantee.

### Experimental SM120 RL attention path

The compiled artifact is `.cache/wheels/sm120-cu130-torch213/flash_attn-2.8.3-cp312-cp312-linux_x86_64.whl` (~66 MB), with a companion `.sha256` file. It is **not stored in Git**: copy it to your persistent volume/image builder before rental. [Build manifest](research/flash-attn-build.json) records source/wheel/extension hashes and symbol requirements. The wheel is for Linux x86-64, Python 3.12, Torch 2.13/CUDA 13.0 and **SM120 only**. Use Ubuntu 22.04 or newer (the extension requires GLIBC >=2.32); still run the GPU preflight.

Install the prebuilt wheel without compiling:

```bash
# Absolute path to the transferred artifact; run from the repository root.
export FA2_WHEEL=/workspace/wheels/flash_attn-2.8.3-cp312-cp312-linux_x86_64.whl
export FA2_WHEEL_SHA256=77123edbbfda4e1da8c463a7c9701e45c7d80c71960355a0d06aeaa4645b0b57
bash training/scripts/bootstrap_remote.sh rl-sm120
bash training/scripts/bootstrap_remote.sh sft-packing
```

The bootstrap verifies SHA-256, installs the artifact without changing dependencies, checks imports and applies the TRL loader patch for RL. A later `uv sync` can remove this direct-file installation or replace it with a registry build; rerun the same prebuilt bootstrap afterward. Do not use this SM120 wheel on Hopper or SM100/103. To build from source instead, unset `FA2_WHEEL`/`FA2_WHEEL_SHA256` and use:

```bash
# CPU builder with g++/ninja and sufficient RAM; potentially a long compile.
# The RL wheels supply CUDA 13.0 when no system toolkit/CUDA_HOME is selected.
FLASH_ATTN_CUDA_ARCHS=120 MAX_JOBS=4 \
  bash training/scripts/bootstrap_remote.sh rl-sm120

# On the rented GPU, before loading a model:
cd training
CUDA_VISIBLE_DEVICES=1 PYTHONPATH=. envs/rl/.venv/bin/python scripts/verify_attention.py
RL_ATTENTION=flash_attention_2 bash scripts/preflight.sh tiny
```

`rl-sm120` installs the locked FA2 2.8.3 extra and applies one explicit compatibility change to TRL: `model_init_kwargs.pop("attn_implementation", default)` replaces the hardcoded attention argument. The patch refuses any unknown upstream file, is idempotent, and the training manifest records the resulting trainer source hash. Review it in `browser_training/attention_compat.py`. It is **a local compatibility patch, not unmodified upstream support**. `validate_attention_source.py` reproduces the original duplicate-keyword error and checks the patched call preserves revision/dtype/default behavior.

For source builds, preserve the extra with `uv sync --project training/envs/rl --extra sm120 --locked`; for the transferred wheel, rerun the prebuilt bootstrap instead. A reinstall of TRL can remove the patch; reapply it using `PYTHONPATH=. envs/rl/.venv/bin/python scripts/patch_trl_attention.py --apply` from `training/`. The launcher refuses FA2 unless the audited patch is present. The kernel probe compares BF16 output and Q/K/V gradients with an FP32 reference for Qwen's 24 Q heads / 4 KV heads / head dimension 256, and checks that one packed sequence cannot affect another. A pass qualifies that attention primitive, not the complete DeltaNet model, optimizer or RL pipeline. The FA2 build and CPU extension imports pass locally. No GPU kernel execution has been performed.

`rl-sm120` can use the compiler bundled in the locked RL wheels, and first runs `verify_cuda_toolchain.py` to compile/disassemble an SM120 cubin without executing it. This caught a real resolver issue: NVCC 13.0 with unconstrained NVVM 13.4 emitted unsupported PTX 9.4. Pinning NVVM 13.0.88 fixes that compile failure. The probe also checks shared-library linking. With the wheel toolkit, bootstrap creates a private `libcudart.so` linker name under `.cache/cuda-devel-link-libs`, and supplies that directory plus the toolkit’s `lib` via `LIBRARY_PATH`. For an independent rerun after bootstrap, use `LIBRARY_PATH="$PWD/.cache/cuda-devel-link-libs:$PWD/envs/rl/.venv/lib/python3.12/site-packages/nvidia/cu13/lib" envs/rl/.venv/bin/python scripts/verify_cuda_toolchain.py` from `training/`. A host C++ compiler is required. [Before](research/cuda-toolchain-before-fix.json) / [after](research/cuda-toolchain-validation.json).

The build sets `FLASH_ATTENTION_FORCE_BUILD=TRUE` to prevent setup.py fetching a different prebuilt wheel. If reusing an image/cache previously built for another architecture, remove its installed `flash-attn` and run `uv cache clean flash-attn` before rebuilding, or use a fresh builder/cache. The Python package version alone does not identify its compiled GPU targets.

## Before allocating GPUs

Use Linux x86-64, Python 3.12.12, adequate CPU RAM (128–192 GB recommended for loading/builds), and persistent disk. Allow roughly 150 GB for both 27B checkpoints, the smoke model, multiple package environments and outputs; allow more if retaining merged models/wheel caches. A CPU image builder can install packages and download weights ahead of allocation:

```bash
git clone <this-repository-url>
cd LLM_proj_uu
export HF_HOME=/workspace/persistent/huggingface
bash training/scripts/bootstrap_remote.sh all
bash training/scripts/download_models.sh fp8 bf16 smoke
```

`bootstrap_remote.sh` installs pinned environments, checks dependency consistency/imports, runs the installed CPU config/adapter probes for SFT/RL, and runs local tests. It does not install a driver, modify system CUDA, download model weights or install Chromium. Requires `git`, a usable `python3 -m pip`, and outbound PyPI/Hugging Face access. A preinstalled `uv` is reused; the fallback installs the locally tested `uv==0.10.8`. On externally managed system Python, provision uv through the image builder rather than bypassing that protection.

The resolved PyTorch runtime is CUDA 13.0.3. Use an NVIDIA driver at least **580.126.20**, preferably a current vendor-supported driver. The RL lock constrains NVCC/CRT/CCCL/NVVM to the 13.0 line to avoid silently generating newer PTX. NVIDIA Container Toolkit / `--gpus all` is needed if these environments are put into a container. WSL's GTX 1070 is unsuitable for these remote probes.

Do not run a training environment's `uv sync` from the repository root. Reproduce with `uv sync --project training/envs/sft --locked` (or `rl` / `browser`). The three locks intentionally differ; Axolotl's TRL 1.9.0 and the AsyncGRPO development commit cannot occupy one environment.

For the FP8 SFT candidate, install the prebuilt wheel above or build the optional FlashAttention 2 dependency **before** renting:

```bash
# CPU builder with CUDA 13.0 devel toolkit, nvcc, g++, ninja and sufficient RAM.
# This can take tens of minutes. It compiles kernels, not training.
FLASH_ATTN_CUDA_ARCHS=120 MAX_JOBS=4 \
  bash training/scripts/bootstrap_remote.sh sft-packing
```

Use `90` for Hopper, or a semicolon-separated architecture list for a reusable image. Packing is a locked optional extra. A subsequent plain `uv sync` drops extras; preserve it with `--extra packing`. FlashAttention's build prerequisites are installed before its non-isolated build. The lock's supplied dependency metadata matches the pinned upstream `setup.py` (`torch`, `einops`).

Reuse `$HF_HOME/hub` on a persistent volume. Preserve its blobs, snapshots **and symlinks** when copying (`rsync -a`), or archive/extract it intact in object storage. Mount at the same path in each container. Public models require no embedded credential. If a provider only exposes persistent storage on GPU instances, populate it on a cheap CPU host and transfer the archive; account for transfer time before buying compute. After caching, set `HF_HUB_OFFLINE=1` for fail-fast model loading; kernel-hub artifacts must also be warmed first.

## Dataset conversion

Input is JSONL, one normalized trajectory per line. This is an intentionally small interchange format, **not** a new repository-wide trace standard. Existing `runs/` logs have separate verifier evidence; normalize those explicitly before conversion. `success: null`, string `"true"`, and integer `1` are excluded by default. Success must mean independently verified task/constraint success, not the agent saying it is done.

```bash
cd training
.venv/bin/python scripts/prepare_sft_dataset.py teacher.jsonl data/sft.jsonl \
  --target action --layout trajectory
# Alternatives: --target reasoning-action; --layout state-action
```

The converter emits `messages` with system/user/assistant roles. Axolotl applies loss only to assistant turns and their turn terminators. Observation text is context. `reasoning-action` puts supplied reasoning in the assistant’s `reasoning_content` field; the official Qwen3.8 tokenizer template adds the tags. Use `run_sft.sh --enable-thinking` for that dataset. The real-model configs set `preserve_thinking: true`, and CPU validation with the actual Axolotl labeling classes confirms that every reasoning/action turn is supervised while observations stay masked. Inline `<think>` content and the older Axolotl `qwen3_5` template both produced incorrect reasoning handling in this test. State/action examples include task + current observation, not prior history; use full trajectories for partially observable tasks. Split train/eval by task/trajectory before converting, not after splitting into individual steps. No validation dataset is invented by these configs.

## SFT launch and resume

Start with the conservative BF16 base, BF16 rank-16 adapters and FP32 Adam moments:

```bash
bash training/scripts/run_sft.sh --dry-run
bash training/scripts/benchmark_sft.sh --steps 20 --output outputs/sft-bench-bf16
bash training/scripts/run_sft.sh --output outputs/sft-experiment-001
```

To probe the desired FP8 storage path after installing the packing extra:

```bash
bash training/scripts/run_sft.sh \
  --config configs/sft_qwen38_27b_fp8_lora.yml \
  --steps 3 --grad-accum 1 --output outputs/sft-fp8-probe
```

The FP8 config retains checkpoint quantization and enables Axolotl's fused LoRA kernels, including Gated DeltaNet projection handling. Its packing patch is required to wire the DeltaNet fused forward. This path dequantizes blocks for BF16 math; it is not native FP8 forward training. It remains a GPU validation candidate. The BF16 fallback uses ordinary PEFT/SDPA without those kernels.

Adjust `--sequence-len 4096`, `--grad-accum 8`, `--rank 32` (alpha follows rank), `--dataset`, and `--output`. Microbatch stays 1. Optional `--packing` enables packing/FA2 on the BF16 configuration too. Do not pass `--packing` before installing the extra. No CCE, compile, offload or mixed-precision FP8 compute is enabled by default.

```bash
bash training/scripts/run_sft.sh --output outputs/sft-experiment-001 \
  --resume outputs/sft-experiment-001/checkpoint-50
```

Use the same model revision, rank, dataset, context and optimizer settings when resuming. The CLI will not silently overwrite an existing run. Checkpoints retain Trainer/optimizer/RNG state and adapter weights. An adapter-only directory is not a resumable optimizer checkpoint. BF16 checks run after resume as well as before optimizer updates; a non-LoRA trainable weight or dtype drift aborts the run.

## vLLM presets and adapter export

```bash
# GPU 0; 4096-token context, 8 concurrent sequences, BF16 KV cache by default.
bash training/scripts/run_vllm_rl.sh --preset baseline
bash training/scripts/run_vllm_rl.sh --preset lora
# Experimental inference benchmark only; stop the preceding server first.
bash training/scripts/run_vllm_rl.sh --preset lora-mtp
```

`--kv-dtype fp8` is a separate benchmark switch. `--tools` enables the Qwen3 Coder tool-call parser for chat clients. TRL's native worker uses token-level `/v1/completions` and parses responses itself; a server parser is not a substitute for correct trainer tokenization. The baseline disables MTP and uses unrestricted sampling defaults (`--generation-config vllm`) so checkpoint top-k/top-p defaults do not silently change the policy. Qwen thinking/parser behavior and model revisions are recorded in launch arguments.

Preferred export is the **unmerged adapter** on its frozen serving base:

```bash
cd training
.venv/bin/python scripts/check_adapter_dtypes.py outputs/sft-experiment-001/checkpoint-50
.venv/bin/python scripts/check_vllm.py \
  --adapter outputs/sft-experiment-001/checkpoint-50 \
  --next-adapter outputs/sft-experiment-001/checkpoint-100
```

This registers two immutable names, checks generation/logprobs, verifies the older name still serves, then unloads just its test adapters. Paths are resolved locally and must be identical/readable on the server. It validates serving plumbing, not output quality or a full model-distribution equivalence proof.

For a permanent BF16 merged export, use Axolotl's native command in the SFT environment after training:

```bash
cd training
source scripts/common.sh
envs/sft/.venv/bin/axolotl merge-lora \
  outputs/sft-experiment-001/resolved.yml \
  --lora-model-dir outputs/sft-experiment-001/checkpoint-50
```

Axolotl writes the merged model under `output_dir/merged`. Its native merge path supports quantized formats and a `--dequant` flag, but **do not assume an FP8 merge equals base+adapter serving**. Validate its saved `quantization_config`, scale tensors and vLLM load independently. For an FP8-trained adapter, `--dequant` explicitly makes the merged checkpoint BF16; a new FP8 deployment requires a separate supported PTQ/export step and numerical evaluation. Keep the original adapter and base revision regardless. No merge/requantization pipeline is part of RL synchronization.

## RL topology and interface

Use one host with GPU 0 for vLLM and GPU 1 for the trainer. Set `SFT_GPU` / `TRAIN_GPU` or vLLM's `--gpu` to change assignments. One trainer process is the baseline. Tensor parallel rollout serving may be increased later with `--tp`; vLLM data-parallel replicas are rejected by the pinned adapter synchronization path.

`output_dir/.vllm_lora/` must be a persistent, writable trainer directory that vLLM can read at the **same absolute path**. Updated adapters travel via disk + HTTP registration, not NCCL. The launch retains the canonical NCCL weight-transfer flag, but adapter mode does not instantiate that full-weight transport. The trainer refuses a fallback to merged/full-weight synchronization.

On separate machines, add a shared filesystem mounted identically and a private reachable vLLM address; start vLLM with `--host <private-interface>` and pass trainer `--server http://<private-ip>:8000`. HTTP/dev endpoints can load adapters and pause generation: keep them on a trusted network. NCCL network interfaces/firewall/RDMA matter for multi-GPU training, tensor parallel serving, or full-weight fallback; they are not an adapter-file transport. No multi-node provisioning is implemented here.

`BrowserToolEnv` is the project-facing adapter. Its backend returns observation, terminal flag and a deterministic `Outcome`; `get_reward()` calls the environment verifier and closes resources. All public tool methods have typed arguments/docstrings; lifecycle methods stay private so TRL doesn't expose them to the model. `OpenEnvBackend` accepts the upstream BrowserGym client and action model from the environment team's service package. A fake client tests that exact shape locally. It does not assume BrowserGym's scalar success reward proves the absence of unauthorized side effects.

For the native OpenEnv harness, `TaskSelectingSessionFactory` maps TRL’s conversation-valued task to the service task ID. `MappingArgumentsHarnessAdapter` converts OpenEnv’s JSON-string tool arguments to dictionaries before Qwen template rendering; the official MCP harness still owns the agent loop. The current OpenEnv response conversion drops `reasoning_content`, so keep harness thinking disabled until that round trip is fixed. The policy patch also closes sessions that finish creation after stop; creation and browser operations still need bounded deadlines. These are interface constraints independent of GPU hardware.

The SFT converter currently emits plain BrowserGym action text. Native harness inference uses structured tool calls. Choose and align the production action contract before using that SFT adapter for harness RL; the present smoke tests do not establish this policy-format alignment.

The intended concurrency controls are independent:

| Control | Baseline | Meaning |
|---|---:|---|
| `max_inflight_tasks` / `--inflight` | 8 | Live browser episodes |
| `num_generations` / `--group-size` | 4 | Episodes per prompt/reward group |
| microbatch | 1 | One reconciled sequence per trainer row |
| gradient accumulation / `--grad-accum` | 8 | Eight sequences per optimizer step on one GPU |
| `max_staleness` | 2 | Allowed lag in synchronized policy versions |
| `token_budget` | 0 | Disable dynamic multi-sample row packing |
| vLLM `--max-num-seqs` | 8 | Engine scheduling capacity |
| vLLM `--max-loras` | 4 | At least staleness + 2 registered versions |

The real multi-turn launcher is deliberately gated. The tiny **one-turn** mock validates trainer integration on supported attention hardware; it uses group-constant environment rewards and therefore does not demonstrate reward learning. It must not be described as a completed BrowserGym GRPO episode test.

```bash
# Hopper with the default backend, or SM120 after the optional FA2 build below.
# For SM120: export RL_ATTENTION=flash_attention_2
bash training/scripts/run_vllm_rl.sh --model Qwen/Qwen3-0.6B --context 1024 --eager
bash training/scripts/smoke_rl.sh --output outputs/rl-smoke-001
bash training/scripts/smoke_rl.sh --output outputs/rl-smoke-001 \
  --resume outputs/rl-smoke-001/checkpoint-3 --steps 5
```

`--sft-adapter PATH` initializes adapter weights before optimizer creation and first synchronization; rank/targets must match. It is distinct from `--resume`, which restores optimizer/RNG/rollout state. Async queues and browser sessions are not checkpointed. The trainer restarts from the first untrained prompt and discards buffered work; streaming datasets restart at their beginning. Do not combine initialization and resume.

## Remote preflight

The generic stages below preserve the earlier BF16/FA3 checks and are not the successful NF4/SDPA learning recipe. For the current qualified path, use the [SSH reproduction commands](../docs/agents/training-modal-preflight.md#ssh-deployment-handoff). `model` retaining an exit-2 gate is a limitation of that older script, not a claim that the later core RL learning test failed.

```bash
bash training/scripts/preflight.sh static  # safe locally
bash training/scripts/preflight.sh tiny    # Hopper/default FA3; cached 0.6B
# SM120 after bootstrap rl-sm120:
RL_ATTENTION=flash_attention_2 bash training/scripts/preflight.sh tiny
bash training/scripts/preflight.sh model   # Blackwell SFT + FP8 serving candidate
# After the packing build, test actual FP8-storage SFT:
SFT_CONFIG=configs/sft_qwen38_27b_fp8_lora.yml bash training/scripts/preflight.sh model
```

`all` runs tiny then real checks. Before loading any model, the tiny stage tests the selected attention backend against an FP32 reference, including backward and packed-sequence isolation. Blackwell requires the opt-in FA2 build and `RL_ATTENTION=flash_attention_2`; default FA3 still fails early. `model` continues with SFT/serving and exits 2 after successful checks to explicitly report that real RL remains blocked. Logs are in `reports/`; each invocation uses a new output suffix. The script starts/cleans up only its own server process group, and refuses to reuse a server already listening on port 8000. Cached-model loading and cold kernel JIT may exceed several minutes; the 15-minute serving timeout is an upper bound, not a promised startup time.

| Requested check | Implementation / current limitation |
|---|---|
| GPUs, capability, BF16, real FP8 GEMM | `verify_gpu.py` |
| PyTorch CUDA and NCCL between GPUs | CUDA backward + two-rank `torchrun` all-reduce |
| Model load, live BF16 LoRA, forward/backward | `sft_smoke_test.py`, through the actual Axolotl loader |
| Several Axolotl SFT steps | Tiny/model stage, 3 steps |
| FP8 model served | Model stage |
| Adapter load and version publication | `check_vllm.py`, two names, old version recheck |
| MTP | Optional `lora-mtp` + `benchmark_rollouts.py`; not qualified for RL |
| TRL native adapter synchronization | Tiny stage; SM120 requires optional FA2 patch/build and kernel test |
| Mock GRPO iteration | Tiny **one-turn** environment only; multi-turn blocked |
| Written checkpoints | Adapter headers and RL `rollout_state.json` assertions |
| Optimizer/RNG resume | SFT intermediate-checkpoint resume passed separately on L40S; actual AsyncGRPO resume remains untested |

## Benchmarks and records

```bash
bash training/scripts/benchmark_sft.sh --steps 20 \
  --sequence-len 2048 --grad-accum 8 --output outputs/sft-bench-001
bash training/scripts/benchmark_rl.sh --steps 20 \
  --config configs/rl_smoke.py --output outputs/rl-bench-001
cd training
.venv/bin/python scripts/benchmark_rollouts.py --concurrency 4 --requests 16 \
  --output reports/rollout-baseline.json
```

Repeat serving with concurrency 1, 2, 4, 8, 16 and each preset; cap context and use the same prompts/token budget. Select the adapter name using `--model` when benchmarking LoRA: merely starting an enabled server still sends base-policy requests if no adapter name is requested. Preserve server `/metrics` snapshots: MTP acceptance is accepted-draft tokens / proposed-draft tokens, distinct from tokens/sec. Warm up before comparing; the supplied serving benchmark excludes its warmup request from timing.

Benchmark outputs include raw framework metrics, mean steady-state metrics, peak allocated VRAM, supervised tokens/sec and seconds per million supervised tokens when reported. `*-telemetry/gpu.csv` records both GPU indices/utilization/memory/power each second. Epoch estimate = actual post-tokenization training tokens / measured corresponding token throughput; do not use characters or `sequence_len × examples` for unpacked data. Null metrics mean unavailable, not zero.

For RL use the native `rollout/generated_tok_s`, `tools/*_latency_s`, `rollout/duration_s`, `perf/fwd_bwd_s`, `perf/weight_sync_s`, `sample/staleness_*` and `sample/dropped_stale_total`. Browser episodes/sec requires counting completed environment episodes over wall time; no real-environment throughput has been measured. Generation and training overlap, so their fractions are not additive. The benchmark reports trainer wait/compute/sync fractions when available and retains the source metrics.

Every actual launch writes a config, git commit/dirty flag, source hashes, Python/package versions and model revision. Native checkpoint Trainer state plus `metrics.jsonl` preserve loss, reward and throughput. WandB is unnecessary; SFT can enable its normal `wandb_project` config, and RL can later set `report_to="wandb"` explicitly. The patched worker preserves group policy versions and writes episode/request/version lifecycle events to `policy-events.jsonl`. Registry reservations are runtime state: they are not restored from a checkpoint; resume starts a fresh worker and vLLM server.

W&B Academic is the selected human-facing dashboard. Its optional SDK connection
and synthetic metric accounting/readback have been verified. The
[metrics runbook](../docs/agents/training-metrics.md) covers the durable episode
ledger, local/W&B agent reader and saved-trainer-log import. Live producer wiring
is qualified for the bounded tests described above. The annotated dashboard is
now published; a joint visual walkthrough remains open.

`bash training/scripts/smoke_browser.sh --metrics` from the repository root checks
real local Chromium/OpenEnv outcomes, recorded group draws and retry-safe metric
accounting using scripted fixture actions. The optional uniform/adaptive family
sampler is CPU-tested; canonical-harness/TRL integration remains pending.

`training/.venv/bin/python training/scripts/validate_project_browser_metrics.py`
from the repository root checks the complete imported P07 shopping site with
fresh scripted clean/warranty episodes and the existing native verifier. It
freezes its source/site inputs and uses isolated sessions; `--online` also checks
W&B parity. The [runbook](../docs/agents/training-metrics.md#full-site-p07-accounting-probe)
explains required local assets and the distinction from model-driven learning.

Opt-in session sampling/metrics passed the installed TRL spawned browser worker;
trainer logging and checkpoint sidecars passed CPU callback/restore checks.
`run_async_grpo.py --monitoring-dir NEW_DIRECTORY` enables trainer-only monitoring
on its existing gated mock path. Real optimizer/resume qualification, canonical
browser adoption and remote-resource logging remain open. Opt-in row admission,
optimizer-use accounting and a conservative resume cursor passed native-code CPU
checks; see the [row-accounting runbook](../docs/agents/training-metrics.md#row-admission-optimizer-use-and-checkpoint-cursor).
Local CPU/PSS/device resource sidecars and a separate retrying W&B uploader now
pass fault tests and remote readback, including lost-acknowledgment recovery.
[Resource/upload commands and limits](../docs/agents/training-metrics.md#resource-sidecars-and-recoverable-wb-publication)
cover explicit device selection, missing readings, sampled history and restart.
No GPU compute or cloud rental was used for this check.
Checkpoint restores now publish to a linked W&B continuation, preserving the
original execution's later history. Uploader-only restarts retain their existing
run. [Continuation behavior](../docs/agents/training-metrics.md#checkpoint-continuation-history)
passed local, installed-callback and real W&B checks; model/optimizer restoration
still requires the real GRPO test.
See the
[logging setup](../docs/agents/training-modal-preflight.md#wb-dashboard-connection)
for credentials and the CPU-only test. Local evidence remains available without W&B.

Fixed-suite evaluation scheduling/comparisons and token-accounted SFT replay
preparation are now CPU-tested. The [data/evaluation guide](../docs/agents/training-data-and-evaluation.md)
includes commands, the evaluator worker contract and resource-file relay. The
real suites/corpora remain inputs from data curation; the mock workers are not
model-quality evidence. `scripts/preflight.sh static` runs the lightweight checks
in bounded parallel shards and preserves their reports.

## Short Modal hardware test

For a bounded one-L40S test of the actual 27B NF4 trainer, see the
[Modal preflight runbook](../docs/agents/training-modal-preflight.md). The launcher
builds the locked environment and prepares the model cache on CPU, then runs
GPU arithmetic checks and Axolotl SFT/checkpoint checks. A dry run is free of cloud
calls: `training/.venv/bin/python training/scripts/modal_training.py --dry-run`.
Each paid run needs a current allowance; the September 15 authorization was
20 minutes of L40S testing, not an ongoing training budget.

**Verified September 15:** the real 27B NF4 model passed rank-16 SFT and an actual
resumed adapter update on a single L40S, at 1,907 tokens per example. Logged
allocated memory peaked at 25.74 GiB; sampled total device use reached 27.39 GiB.
Both short tests together used about 5.3 GPU minutes, and no containers remain.
This qualifies the tested SFT configuration, not full RL or SM120.
[Results](research/modal-l40s-validation.json).

## How we plan to train our browser agent

Our goal is to teach an existing language model to complete browser tasks while
respecting what the user actually asked for. A successful shopping agent should
buy the requested item, stay within the budget, and handle extras according to
the user's instructions. Removing a warranty is correct when it is unwanted;
keeping it is correct when the user requested it.

The planned training process has two stages:

**Verified teacher demonstrations → supervised fine-tuning (SFT) → practice in
the browser with verifiable rewards (RLVR).**

The [training recipe](../docs/training-recipe.md) separates the data/equipment
checklist from the timeline, including teacher selection, replay and final testing.

### SFT: learn from examples of good browser behavior

**Supervised fine-tuning** trains the model to produce the demonstrated answer
given an input. In our case, an example contains the user's goal, the page
observation, the action history, and the next browser action. A stronger
*teacher model* will attempt tasks and produce **trajectories**: complete records
of what it saw, what it did, and what happened.

We will select a teacher by benchmarking a sweep of larger, frontier open models
on the tasks and data we intend to use, measuring both completion and adherence
to user constraints. If none outperforms our Qwen baseline by a meaningful margin,
we may skip SFT and proceed directly to RLVR from the existing Qwen model.

Offline SFT lets us reuse one expensive teacher dataset across student
experiments. RLVR then supplies practice on the student's own attempts.
On-policy distillation would need repeated teacher supervision as the student
changes, so it remains an optional later experiment. We will freeze the
canonical harness before teacher selection and keep selection tasks out of
training; the [experiment plan](../docs/training-plan.md) defines the splits.

For example, a future shopping demonstration might show the teacher noticing
that an optional warranty was selected, removing it because the user declined
extras, checking the revised total, and completing checkout. We intend to start
with trajectories that pass our outcome and constraint checks. A teacher saying
“success” is not enough to make its demonstration a good training example.

During SFT, the model learns to predict the teacher's action tokens. The user's
instruction and browser observations provide context; we do not train it to
generate the website's text. Our converter supports whole conversations or
individual state/action examples, with optional teacher-written explanations.
The action format must match what the browser harness can execute. We use
Axolotl for this stage. [Hugging Face's SFT introduction](https://huggingface.co/learn/llm-course/chapter11/3)
explains the underlying method and the role of example quality.

### RLVR: learn from the outcomes of its own attempts

**Reinforcement learning with verifiable rewards** lets the model attempt tasks
and learn from a score calculated by an independent checker. A browser attempt
can involve many observations and actions before its outcome is known.
[BrowserGym](https://github.com/ServiceNow/BrowserGym) provides browser interaction;
our harness coordinates the attempts and our task-specific verifiers determine
what actually happened.

For the shopping example, a simple reward could be 1 only when the correct item
was purchased within budget, no unwanted warranty or subscription was added,
and all other required constraints were met. Otherwise it would be 0. Some
requirements need the event history as well as the final page—for example,
whether an unauthorized purchase occurred and was later undone. An unchecked
requirement remains unverified.

Our chosen algorithm, **GRPO (Group Relative Policy Optimization)**, compares
the rewards of several attempts at the same task and uses their relative
performance to update the model. This can encourage successful approaches
beyond the exact demonstrations used for SFT. It needs informative tasks:
groups where every attempt gets the same reward provide no relative reward
signal. Our asynchronous setup overlaps new attempts with training updates,
while keeping each ongoing episode on one model version.
[TRL's GRPO guide](https://huggingface.co/docs/trl/main/en/grpo_trainer)
explains the algorithm and custom reward functions.

The quality of the checker matters as much as the score. If it only checks that
checkout completed, training could reward buying the right item with an
unwanted subscription. Writing reliable task objectives and verifiers is
therefore part of building the training data.

### What data we need

| Stage | What we need from our project |
| --- | --- |
| Teacher collection | Runnable tasks, realistic starting states, user constraints, and complete observation/action/result traces. |
| SFT | Reviewed, verified demonstrations converted into conversations with the intended actions as training targets. |
| RLVR | Resettable tasks and reliable outcome checkers. The current model generates fresh trajectories during training. |
| Evaluation | Held-out tasks and site variants, with independent completion and constraint checks. |

Our task definitions describe the goal and requirements; the environment must
also implement the starting state and checks. A collection of task prompts or
website source files is not yet a complete SFT dataset. The
[task-writing guide](../docs/task-definitions.md) and
[curation directory](../data/curation/) are the starting points for this work.

We should include both authorized and unauthorized versions of similar actions,
so the model learns to follow the user's intent—for example, whether to keep a
warranty. Evaluation should hold out complete tasks and entire sites/codebases,
with novel variants on known sites reported separately. Hidden answers
and verifier metadata must stay out of the model's observations.

### Keeping the training affordable—and interpreting our results

We update small **LoRA adapters**, keeping the pretrained base weights frozen.
The tested trainer stores much of the base in four-bit NF4 format, an approach
called **QLoRA**, with higher-precision adapters. SFT has run on one L40S GPU;
our RL test used a second GPU for FP8 vLLM inference while the first trained.
These choices reduce memory needs without changing the basic SFT/RLVR data flow.
We would prefer FP8 for both training and inference if its backward path is
qualified; the current native loader remains inference-only. Enough GPU memory
alone does not resolve that software limitation.

Both training paths have learned deliberately simple test tasks: SFT learned
to insert “apple” after each input word, and RL learned to favor a rewarded
answer. The browser integration has also passed scripted tests. **We have not
yet trained the model end to end on our browser tasks.** The next milestone is
to combine reliable tasks and verifiers with the validated training loop.

For further reading, start with [Hugging Face's introduction to RL for language
models](https://huggingface.co/learn/llm-course/chapter12/2). For the memory-saving
training method, see the original [QLoRA paper](https://arxiv.org/abs/2305.14314).
The tutorials explain the concepts; our pinned versions and tested limitations
are recorded in the [project findings](../docs/training-findings.md).
