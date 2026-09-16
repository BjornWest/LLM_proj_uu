# Training validation and remote deployment handoff

**Latest status (2026-09-16): SFT and core RL learning passed; all test containers stopped.** Read the [consolidated findings](../training-findings.md) and [SSH handoff](#ssh-deployment-handoff) first. The entries below retain earlier tests and expired authorizations as history; they do not authorize another run.

## Initial Modal qualification (historical)

Owner: training. Scope: bounded invocations on one L40S running the existing 27B NF4 Axolotl SFT candidate.
User authorization on 2026-09-15: up to **20 minutes of L40S time** for testing.
This is a one-time allowance, not permission to repeat this command indefinitely.
No rollout server, final browser tasks, or sustained experiment is launched.

## Reproduce after authorization

```bash
uv sync --project training --locked --extra modal
training/.venv/bin/python training/scripts/modal_training.py --dry-run
# CPU image/cache preparation; no GPU allocation:
training/.venv/bin/python training/scripts/modal_training.py --prepare-only
# Includes CPU cache check, followed by ONE bounded GPU invocation:
training/.venv/bin/python training/scripts/modal_training.py --gpu-seconds 900 --sequence-len 2048
```

Use `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` in the repository-root `.env`.
The launcher reads only these two keys, client-side, without shell evaluation.
It does not upload `.env`, repository history, existing datasets, or local caches.
Do not copy credentials into an image environment or Modal training Secret.
SDK 1.5.1 and dotenv 1.2.2 are pinned in the root training lock; the cloud image
uses the existing SFT lock, uv 0.10.8, and Python 3.12.12. Model preparation and
GPU execution use the same locked interpreter. The image installs dependencies
on CPU before any GPU call. Pass `--default-index https://pypi.org/simple`
when syncing: the initial Modal build tried to re-resolve the lock under its
default index settings; the explicit index installs the unchanged lock. Base Debian/apt package updates are not fully pinned;
retain the Modal image ID and actual package versions for each result.

## Boundaries and artifacts

One `gpu="L40S"`, one container, no ordinary retries, 90-second startup timeout,
960-second invocation timeout. The caller passes a fixed absolute deadline 1080
seconds after submission (or a smaller `--gpu-seconds` allowance) and cancels with `terminate_containers=True` on exit.
Subprocesses have their own remaining-time limit and process-group termination.
There is a 120-second reserve before the user's 20-minute limit. Scheduling time
also consumes this conservative client window; the test may get less GPU time.
These are runtime safeguards, not a Modal billing-level spending cap.

Modal automatically replays preempted GPU functions independently of ordinary
retry settings. The deadline never resets, and a committed run marker refuses
replay of an already-started test. No automatic repair/relaunch is implemented.
Cancellation/termination evidence must be checked after an interrupted run.

The CPU function downloads the complete revision-pinned public NF4 snapshot,
checks total weight bytes, tests offline snapshot/tokenizer resolution, and
commits the cache. Using a complete snapshot avoids the missing-metadata failure
seen in the sibling inference project. `/model-cache` avoids a mount conflict
with pre-existing files under `/root/.cache/huggingface`.

Own Modal volumes:

- `browser-training-model-cache`, mounted at `/model-cache`: reusable weights.
- `browser-training-results`, mounted at `/results`: configs, logs, adapter and
  optimizer checkpoints, one-second GPU utilization/memory/power, report JSON.

Local `training/outputs/modal/<run-id>/` contains source hashes, model revision,
git commit, app/dashboard identity, cache result, and final report when available.
Cloud logs also appear in the caller's stdout. Current operator log is
`training/research/modal-launch.log`. A failure is a useful result; preserve its
traceback and checkpoint state before making a new authorized run.

## What this test qualifies

1. GPU identity, capability, PyTorch BF16 backward and actual FP8 GEMM.
2. Real prequantized 27B load through Axolotl, exact target modules and frozen vision.
3. Converted synthetic browser conversations, assistant-only loss, actual token lengths.
4. Two SFT steps with BF16 adapter parameters/gradients and FP32 Adam moments.
5. Checkpoint files and adapter tensor headers; resume intermediate checkpoint one
   within the original two-step schedule and verify a nonzero LoRA-B tensor change.
   Trainer/adapter/optimizer state is reloaded into the existing model.

The GPU probe uses SDPA for full attention and the installed hybrid-attention
implementation. It does not use the SM120-only FA2 wheel, CPU reference overrides,
or pretend that setting a 1024-token cap means examples contain 1024 tokens.
It records actual lengths. The 2048-cap follow-up contained 1907 tokens per example
(padded to 1920 by the training collator). This short run is a correctness/fit check, not a stable
throughput benchmark. It does not qualify L40S FlashAttention2 for AsyncGRPO,
Blackwell kernels, NF4/FP8 policy mismatch, vLLM adapter synchronization, or GRPO
rollouts. The isolated NF4 TRL constructor fix still requires production integration.

## Cost and deployment implications

As checked 2026-09-15, L40S is $0.000542/second: 20 GPU minutes cost $0.6504.
CPU ($0.0000131/physical-core-second), RAM ($0.00000222/GiB-second), image/download
work, and retained volumes are additional. Volume list price is $0.09/GiB/month;
remove this project's cached volumes when no longer needed, after preserving
results. Do not assume an account has unused credits. Modal is a convenient
short-test environment; sustained training pricing should be compared separately.

For future separate trainer/rollout containers, Modal Volume commits/reloads are
not automatically a strongly consistent shared POSIX filesystem. Do not assume
TRL's disk-based LoRA publications become visible in a sibling container without
checking those semantics. A single two-GPU container sharing a normal directory
is the simplest later end-to-end test, subject to separate authorization.

Sources: [GPU choices](https://modal.com/docs/guide/gpu),
[CUDA/driver environment](https://modal.com/docs/guide/cuda),
[pricing](https://modal.com/pricing), [timeouts](https://modal.com/docs/guide/timeouts),
[preemption](https://modal.com/docs/guide/preemption),
[volumes](https://modal.com/docs/guide/volumes),
[SDK App API](https://modal.com/docs/sdk/py/latest/App).

## Completed evidence

Both September 15 invocations passed. GPU telemetry spans total 317.719 seconds
(about 5.3 minutes); both apps have empty container lists after completion.
GPU-only list-price approximation is $0.172, excluding setup/cleanup outside
sampling and CPU/RAM/build/download/storage charges. No additional run is active.

| Actual tokens | Maximum logged allocated GiB | Maximum sampled device GiB | Resume |
|---|---:|---:|---|
| 395 | 20.73 | 27.34 | State/checkpoint reload passed; terminal schedule had zero LR |
| 1907 (padded 1920) | 25.74 | 27.39 | Intermediate checkpoint; LoRA-B change 0.0000500679 |

Both used rank 16, microbatch 1, gradient accumulation 1 and the same NF4 base.
Raw and consolidated evidence: `training/research/modal-l40s-validation.json`;
per-run logs/configs/checkpoints are described there. The second run's exact
sources and locks are archived under its local `sources/` directory. Checkpoints
remain on this project's results volume; model weights remain on its cache volume.

After these runs, reporting was corrected to preserve Axolotl's pre-reset memory
peak and suppress invalid rates across token-counter resets. The launcher now
streams subprocess logs immediately and archives source bytes as well as hashes.
These reporting/logging changes passed local regression tests (49 passed, two
optional-dependency skips); no further paid run was made for them.

## RTX PRO MIG attempt (subsequent authorization)

The user subsequently authorized starting RTX PRO with MIG and explicitly
required aborting if MIG was unavailable. `scripts/modal_mig_probe.py` implements
a read-only gate: one RTX PRO 6000, 45-second function timeout, 30-second startup
timeout, 90-second absolute caller window, no retries and forced container
cancellation on return. It does not load models or alter GPU configuration.

The actual Modal allocation exposed RTX PRO 6000 Blackwell Server Edition with
MIG **Disabled**, no MIG UUIDs, and no effective `CAP_SYS_ADMIN`. We aborted.
`training/outputs/modal/rtx-mig-20260915-222151/` contains the exact source, raw
NVIDIA outputs, result, app/call identifiers and an empty post-run container list.
The GPU commands took 0.214 seconds, excluding startup/teardown. App:
`ap-sjrpA9Q3LgjmnSEZsDYJA0`. No RL/inference model validation ran on this allocation.

A future provider needs to expose two MIG slices or support privileged host
configuration. The plan can then run independent tests followed by integration
within one allocation; keep the slices unchanged and restart only processes as
needed. Do not interpret this managed-container result as lack of hardware MIG
support. See the current NVIDIA sources linked in `training/NOTES.md`.

## Independent inference and GRPO probes after MIG abort

User subsequently requested separate L40S tests, with two L40S end-to-end as a
possible later step. `modal_inference.py` and `modal_grpo.py` each enforce a
360-second maximum absolute caller window, no automatic retries, and forced
container termination. CPU image/model preparation runs before that window.
They reuse the original locked RL environment and project-owned cache/results
volumes. Every invocation archives its exact sources and lock hashes locally.

```bash
training/.venv/bin/python training/scripts/modal_inference.py --dry-run
training/.venv/bin/python training/scripts/modal_grpo.py --dry-run
# CPU preparation only:
training/.venv/bin/python training/scripts/modal_inference.py --prepare-only
training/.venv/bin/python training/scripts/modal_grpo.py --prepare-only
# Paid tests, within the current explicit authorization only:
training/.venv/bin/python training/scripts/modal_inference.py --gpu-seconds 360
training/.venv/bin/python training/scripts/modal_grpo.py --gpu-seconds 360
```

The inference test uses the actual saved rank-16 SFT adapters. Rank 32 is a
zero-padded adapter with alpha/r held constant: only serving layout is qualified.
It uses native load/unload HTTP endpoints, the production session registry, and
a read-only worker extension through native collective RPC to verify cache IDs.
The vLLM 0.28 unload backport is required. The server exposes development routes
only on localhost. The test's own remote function always stops it on completion.

The native GRPO loss probe **passed** on one L40S:
`training/outputs/modal/l40s-grpo-20260915-224453-0600f35a/`.
Two optimizer steps used a 353-token single trajectory and 32 completion tokens;
800 BF16 adapter/gradient tensors and 1600 FP32 optimizer moments were checked.
Peak allocated VRAM was 25.788 GiB; peak reserved 29.566 GiB. Steps took 57.411
and 1.038 seconds, including first-use compilation in the first step. The changed
LoRA-B sample had maximum absolute update 0.00010014. A BF16 adapter checkpoint
and optimizer state were written; optimizer state reload passed. The probe checks
frozen parameter samples, not a full byte-for-byte copy of the 27B base.

Scope is actual AsyncGRPO constructor and `compute_loss`, synthetic behavior
logprobs/advantages, two updates, and serialization. It does **not** execute
`Trainer.train()`, rollout synchronization, group reward computation, a vLLM
request or full trainer checkpoint resume. The audited NF4 constructor candidate
runs in an isolated module; the installed package is not modified by that
candidate. Policy and attention-loader compatibility patches remain separate.
SDPA is valid here because each forward has exactly one trajectory; a runtime
hook rejects packed position IDs. Existing production config likewise requires
microbatch 1 and token_budget 0. Packing still needs boundary qualification.

The first inference attempt loaded the real FP8 base and rank-16/rank-32 adapters
but stopped at a repeated-request logprob assertion (maximum difference 0.144;
generated text matched). It did not reach the staleness/eviction stages. Preserve
this failure; do not attribute it to a policy switch without a repeat control.
Evidence: `training/outputs/modal/l40s-inference-20260915-224421-ffb64f54/`.
The follow-up adds a repeat before publication, disables prefix caching, uses
distinct checkpoint weights for versions 1 and 2, records full completion/logprob
responses, and completes eviction checks independently of the numerical diagnostic.
Both first-attempt apps have recorded empty post-run container lists.

Final status for this session:

- Native isolated GRPO loss/backward: **PASS**; full trainer/rollout integration not run.
- Real mixed-rank adapter lifecycle: **PASS**, ten versions, worker caches empty at shutdown.
- Repeated old-adapter logprobs: **REVIEW**, maximum 0.019604 difference after publication;
  pre-publication control exactly matched, generated text unchanged.
- Fixed-rank control: **startup timeout**, no comparison obtained. Four-minute
  allocation window was too short for provisioning + cold warmup + reserved test time.
- All four apps terminated; recorded GPU-function runtime 652.58 seconds plus
  earlier SFT telemetry 317.72 seconds. No new GPU run is active.

Consolidated results: `training/research/modal-rl-validation.json`.
The latest mixed-rank evidence is `l40s-inference-20260915-225017-1f8ab0e0`;
the startup timeout is `l40s-inference-20260915-225630-cf46ab66`.
The launcher now offers `--alternate-rank 16` for the outstanding control and
preserves Triton/vLLM compile caches on the model-cache volume. Those cache paths
were added after the runs, remain empty until a subsequent GPU invocation, and
have only local dry-run validation. Do not assume compilation is already cached.
A later two-GPU run should await the fixed-rank/integrity control and explicit
budget authorization. Do not repeatedly reuse this session's original allowance.

### Deterministic-kernel research follow-up

The pinned vLLM 0.28.0 GDN selector was called locally with
`VLLM_BATCH_INVARIANT=1`, CUDA devices hidden, no model loading. It raises
`VLLM batch_invariant mode is not supported for GDN_ATTN.` Do not spend a rental
attempt merely adding this flag to the current 27B command.

Upstream vLLM PR #49827 remains unmerged and its GDN support requires SM90+;
quantization is outside its validated scope. TorchTitan has a separate merged
Qwen3.5 parity integration, not a drop-in TRL change. Detailed sources, hardware
limits and proposed isolated validation stages are in the final section of
`training/NOTES.md`. The next current-stack GPU task remains adapter identity and
the same-rank control. No new cloud execution or kernel patch was made here.

### Same-rank identity test authorization and scope

The subsequent user instruction, “ok yeah lets do that,” authorizes the proposed
same-rank GPU identity test. Bound this invocation to **one L40S, 360 seconds from
submission, no automatic retries**; this is a new bounded test, not reuse of the
earlier 20-minute allowance. CPU preparation precedes allocation.

```bash
training/.venv/bin/python training/scripts/modal_inference.py \
  --identity --alternate-rank 16 --gpu-seconds 360
```

The diagnostic B adapter scales checkpoint-2's LoRA-B weights by 128; A retains
that checkpoint unchanged. These are identity fixtures, not training results.
The native worker extension compares all slot bytes with a CPU reconstruction
using vLLM's packing methods and checks actual shrink/expand weight-buffer pointers
and grouped token-slot metadata during selected requests. Instrumented and normal
requests are recorded separately. This inspects kernel inputs, not GPU instructions.
CPU negative controls reject corruption, wrong slots, duplicated token rows and
slot reassignment; omitted kernel coverage is reported. Local evidence:
`training/research/adapter-identity-local.json`.

The first submission `l40s-inference-20260915-234153-8339c0f3` remained PENDING
without a task ID. It was cancelled before assignment when too little of its
submission window remained; the app's container list was empty. This produced
no GPU identity result. The queued follow-up adds `--queue-seconds 600`:
300 seconds maximum function execution plus 60 seconds startup allowance, with
a 960-second outer deadline including waiting. The committed replay marker and
zero retries remain. This separates availability delays from the GPU test budget;
the initial plan was one executed GPU test. The first caller was stopped before
submitting the follow-up.

That GPU attempt stopped after 199.10 seconds on an overstrict diagnostic coverage
assertion: it required LoRA kernel calls for 48 frozen conv1d storage modules,
which are not adapter targets and are accessed directly by GDN. All 1,280 buffer
fingerprints matched and 7,296 observed kernel calls passed their metadata checks.
This is partial evidence, not a completed identity test. No publication/churn
comparison was reached. Logs and empty-container evidence are in
`l40s-inference-20260915-234744-2dd0b043`.

The coverage fix requires execution for actual adapter weights while continuing
to inspect all stored buffers and every observed kernel call. CPU tests cover
both missing targets and untargeted conv storage. One additional manual bounded
run is being made to complete the user-authorized identity test; the user was
told this adds an allocation. The six-minute bound remains per invocation, not
a claim that cumulative GPU use is still limited to six minutes. No automatic
retry or extended training is enabled.

Final follow-up: `l40s-inference-20260915-235431-53cc5a53` completed identity and
ten-version lifecycle checks. Recorded runtime 199.69 seconds (398.79 seconds
across the two executed attempts; not an invoice duration). Every app's final
container list is empty. Summary: `training/research/adapter-identity-validation.json`.

All 1,280 slot buffers matched native CPU packing, 36,480 kernel calls across
five instrumented requests had correct input pointers/slot metadata, and no
actual adapter target lacked execution. A/B had distinct text signatures. All
adapters were rank 16; stale retention and eventual removal passed, including
slot reuse. The report intentionally remains `LIFECYCLE_PASS_LOGPROBS_NEED_REVIEW`.
Normal A repeats initially matched; an instrumented A request changed logprobs
by up to 0.083283 **before B was loaded**. Its result exactly matched the later
normal A response after publication. Same rank does not eliminate the drift,
and this run does not isolate instrumentation, allocator history or reduction
order as the cause. Internal device pointer tables/instructions were not audited.

The next unresolved qualification is numerical execution and trainer/rollout
probability mismatch, followed by the previously planned two-GPU mock GRPO run.
Do not rerun the identity probe indefinitely or mark full RL qualified from it.

### 2026-09-16: user pauses numerical work; e2e learning probe prepared

The user wants literature-backed interpretation and a minimal real RL learning
experiment before pausing for the week. This supersedes the numerical-diagnostics
priority above. Do not spend more GPU time on logprob/identity investigations.

Prepared `training/scripts/modal_e2e.py` and `e2e_learning_probe.py`. Proposed
allocation is one host with two L40S, ten minutes each including startup allowance,
no retries. Existing snapshots only, native AsyncGRPO.train and LoRA sync, 16
updates of a response-dependent A/B reward. Full details/limitations and sources
are in the latest `training/NOTES.md` section. This is core RL e2e, not BrowserGym
model-driven e2e. The old constant-reward mock cannot demonstrate learning.

Local tests: 29 passed; native locked config/candidate imports pass on CPU;
Modal dry-run reports two GPUs, 540s function + 60s startup. No cloud preparation
or GPU launch yet. Asked user for this new allocation's authorization; pending.
Do not interpret earlier diagnostic budgets as permission to repeat this run.

Bjorn explicitly authorized this allocation: two L40S, at most ten minutes per
GPU / 20 GPU-minutes total, no automatic retries, cached weights, 16 updates and
before/after evaluation. Started `l40s-e2e-20260916-002725-92d7ebe9` under Modal app
`ap-kP4Cp8oX5Qfzpvbtoet4RO`. Outcome pending; preserve this run's archived sources
and do not launch a second allocation automatically on failure.

Outcome: the first app timed out in CPU preparation (160s subprocess), without
submitting any GPU call. Its final container list is empty. Offline preparation
with streamed stages succeeded in the follow-up app `ap-FBz0QZDhvr9gpFfqObA7FE`,
run `l40s-e2e-20260916-003126-4dfaa455`; this was the first GPU allocation under
the authorization, not a GPU retry.

That allocation ran 143.72 function seconds on each L40S and stopped before
calibration: our evaluation helper passed a Transformers `BatchEncoding` to
requests JSON. Both models loaded and the initial BF16 adapter loaded/unloaded;
no optimizer update or native scheduled sync was reached. Containers are now
empty. Evidence/logs archived locally; summary `training/research/modal-e2e-validation.json`.

Fixed with explicit `return_dict=False`, added CPU payload validation for both
cached tokenizers, and tested 32 requests against a local HTTP stub. 30 relevant
tests pass. Added `--gpu-seconds` to enforce a smaller per-GPU budget using Modal
function timeout plus the existing 60s startup allowance. A second GPU attempt
has NOT started. Asked user to approve a corrected eight-update test with
`--gpu-seconds 360 --steps 8`, within the remainder of the original budget.
Do not run the default fresh 600s allocation as a retry.

Bjorn explicitly approved the corrected shorter attempt: eight updates, six
minutes per GPU, no automatic retries, within the original combined budget.
Started `l40s-e2e-20260916-093959-9984fa35` in app `ap-agnPvQAHbnG89K8ufHIYiM`
using `--gpu-seconds 360 --steps 8`. Outcome pending. Function timeout is 300s,
startup timeout 60s, and the work deadline reserves 30s for cleanup.

Final outcome: remote CPU preparation PASSED, including both tokenizer HTTP
payloads and token-ID agreement. Modal never assigned a GPU container. At the
ten-minute queue cutoff, `get_call_graph()` still reported PENDING with empty
`task_id`; the call was explicitly cancelled. Saved `queue-cutoff.json`,
`report.json` and `containers-final.json` (empty) in this run's local directory.
The local waiting client was interrupted after confirmed remote cancellation.
No GPU-function time or RL result was added; no further retry was started.
Summary updated: `training/research/modal-e2e-validation.json`. This attempt's
blocker is GPU allocation availability, not a newly observed model/trainer error.

Bjorn subsequently authorized ten minutes per GPU for the corrected eight-update
test, acknowledging that six minutes was too tight. Started
`l40s-e2e-20260916-100055-1b0d7b07`, app `ap-GDPd05Wrb3xXjsVkJtXfFs`, with
`--gpu-seconds 600 --queue-seconds 1800 --steps 8`. Queue allowance is now a
separate CLI option; function timeout remains 540s plus 60s startup, retries zero.
This is a newly approved 20 GPU-minute execution allowance, not a claim that
the combined historical GPU use stays below the original 20-minute budget.
Outcome pending.

Final: `l40s-e2e-20260916-100055-1b0d7b07` completed calibration (A23/B9) and
independent baseline (A30/B34) after loading both models and the initial BF16
adapter. It then stopped before `trainer.train()` because `provenance.capture`
assumed `/opt/training/envs` exists; the image installs the environment at
`/opt/rl`. Function runtime 262.76s per GPU; final containers empty. No updates,
native scheduled sync, training checkpoint or post-training evaluation occurred.
No automatic GPU retry followed this failure.

Fixed provenance discovery for partial source mounts and separately installed
virtual environments. CPU preflight now executes actual capture and asserts
both `/opt/rl` lockfile hashes. Full local suite: 63 passed, 2 skipped. The real
Modal CPU-only preparation passed in app `ap-4vE7Ne5ghd1rr2GdfNISFt`; no GPU call
submitted and final containers empty. Logs, baseline/calibration responses and
source snapshots are local; `training/research/modal-e2e-validation.json` records
both failures and the intervening cancelled queue attempt. Further GPU execution
requires a new explicit authorization under the no-automatic-retry constraint.

Bjorn authorized another attempt after the provenance fix. Started
`l40s-e2e-20260916-120628-0cf5f142`, app `ap-cHCbJh36CUemOmQlgEnsSd`, with eight
updates, ten minutes per GPU, a separate 30-minute queue allowance, and no
automatic retries. Actual image provenance validation precedes GPU submission.
Outcome pending.


Final: **PASS** for the core learning smoke, not browser RL.
`l40s-e2e-20260916-120628-0cf5f142` completed eight native AsyncGRPO optimizer
steps. Independent rewarded-answer frequency improved from 34/64 (53.125%) to
64/64 (100%); final evaluation used native-published `trl-policy-v9`. NF4 frozen
base / BF16 adapters / FP32 optimizer moments were verified. `checkpoint-8`
contains adapter, optimizer, trainer and rollout state on the result volume;
actual resume remains untested. Diagnostic files only were fetched locally.

Native policy events show nine publications and six evictions (v1–v6), with no
active group/episode at eviction, matching request policy identities and all
57 groups / 228 episodes drained. Event replay evidence is
`training/outputs/modal/l40s-e2e-20260916-120628-0cf5f142/policy-event-audit.json`.
The trainer discarded 119 stale samples during this tiny task; the first
forward/backward took 121.44s, much longer than later 4.3–6.2s passes. Record this
for later tuning, not as an unresolved correctness failure or a throughput claim.

GPU function time was 392.91s per GPU (13.10 aggregate GPU-function minutes;
not invoice duration), within this attempt's approved cap. Final container list
is empty. `training/research/modal-e2e-validation.json` now records PASS and
preserves prior failures. No further run started. Model-driven multi-turn
BrowserGym, actual RL resume, sustained training, SM120 and numerical parity
remain unqualified. Respect the user's pause on numerical investigations and
limited credits; do not start further cloud work without authorization.


### Apple SFT learning probe (2026-09-16)

Bjorn approved proceeding with the proposed SFT behavior test. Started `l40s-sft-learning-20260916-123908-dbbb7ea3`, app `ap-uq5BepmM8yhoHkdGRkQuzS`, with one L40S, a ten-minute GPU allowance (540s function + 60s startup), 32 optimizer steps, and no automatic GPU retries. Uses existing cached NF4 weights and the pinned Axolotl image. CPU dataset preparation must pass in the actual image before GPU submission. Local validation: 65 passed, 2 skipped; actual Axolotl tokenization verifies all 64 assistant payloads/EOS and inference prefixes. Evaluates 16 unseen word combinations plus 8 training examples before updates and after erasing/reloading the saved adapter. Rule: append apple after each input word. Outcome pending.

An initial app initialization (`l40s-sft-learning-20260916-123836-e166c146`, `ap-hu4X6toVk4JRkgel4ZHqlX`) failed before any function submission because Modal disallows image.env after runtime file mounts. Offline environment flags now go to subprocess environments instead; no image rebuild or GPU retry was required.


Final apple SFT result: **PASS**. `l40s-sft-learning-20260916-123908-dbbb7ea3` completed 32 updates
on 64 examples with rank-16 BF16 adapters / NF4 frozen base. Held-out exact matches
improved 0/16 → 16/16; 8 training examples improved 0/8 → 8/8. Post-evaluation
zeroed then reloaded all adapter tensors from checkpoint-32 and checked 800 exact
BF16 tensor matches; 1,600 optimizer moment tensors are FP32. All final outputs
terminated with EOS. This is held-out combinations of familiar words only.

Function time 271.32s (4m31s) on one L40S, below the authorized cap. Final
containers empty; no additional GPU run started. Downloaded 27 small diagnostics,
not adapter/optimizer weights. Evidence: `training/research/modal-sft-learning-validation.json`.
Raw `word_preservation` means correct original words at alternating output
positions, so its zero baseline must not be described as losing all input words.
Training loss 6.05119 → 3.958e-6; no held-out loss was measured. Baseline generation
is inside the Trainer's 179.57s timer; pure training/checkpoint interval ~129s.
Peak sampled device memory 27,951 MiB; allocated tensor peak 19.63 GiB. No new
browser, FP8 serving, cold base reload or long-context qualification is implied.

## SSH deployment handoff

**Pause state, 2026-09-16:** the SFT apple and two-GPU RL choice probes both
passed. All their containers stopped. No further execution is authorized by
these example commands. The [consolidated findings](../training-findings.md)
separate measured results from remaining work. Earlier entries above are a
chronological record, including superseded blockers and expired run allowances.

### What is portable today

Use `training/scripts/sft_learning_probe.py` and
`training/scripts/e2e_learning_probe.py` directly. Neither requires the Modal
SDK at runtime; the latter imports a helper from `modal_grpo_probe.py`, which
also does not allocate cloud resources. Preserve the entire selected source
set, not only these two entry points.

The general `run_async_grpo.py` is still the earlier BF16/FA3, one-turn mock
launcher. Its interface has not absorbed the tested NF4/SDPA candidate.
`preflight.sh all` likewise does not reproduce the successful learning probes.
Do not treat their names as proof of parity. The commands below translate the
successful Modal subprocesses to a normal host; they have been syntax/source
checked but have **not** been executed on an SSH rental.

Before migration, ensure the training infrastructure commit is available on the
remote and clone that revision. It includes source, locks, tests, documentation
and reviewed JSON evidence, but not environments, weights, raw logs or generated
checkpoints; see the [artifact policy](../../training/research/README.md).
No standalone Docker image has been published or qualified. Prefer the three
separate uv locks for the first SSH reproduction; an image can package the same
locks later.

### Prepare before billable GPU time where possible

Use Linux x86-64 with git, Python/pip or an already provisioned uv 0.10.8,
`libgomp1`, a C/C++ build toolchain and sufficient CPU RAM/disk. The completed
Modal runs allocated 64 GiB host RAM for one-GPU SFT and 96 GiB for two-GPU RL;
these are provisioned amounts, not measured minimum requirements. Stage full
model snapshots and environments on a persistent disk or CPU image builder.

For the CUDA 13.0.3 stack, prefer Linux driver 580.126.20 or newer, matching the
[toolkit release recommendation](https://docs.nvidia.com/cuda/archive/13.0.3/cuda-toolkit-release-notes/index.html).
NVIDIA's broader CUDA 13 compatibility floor is driver family 580; driver/JIT
compatibility and actual kernels must still pass. Docker additionally requires
working host GPU access through NVIDIA Container Toolkit. Installing a Python
CUDA wheel does not install a host driver.

From the repository root, after dependency-download authorization:

```bash
uv python install 3.12.12
uv sync --project training --locked --default-index https://pypi.org/simple
uv sync --project training/envs/sft --locked --python 3.12.12 --default-index https://pypi.org/simple
uv sync --project training/envs/rl --locked --python 3.12.12 --default-index https://pypi.org/simple
bash training/scripts/preflight.sh static
cd training
```

The remaining blocks assume this `training/` working directory and writable
persistent mounts. Replace `/mnt/browser-training` with the provider's actual
persistent mount **before** running. Do not create data on an ephemeral root disk
by mistaking an absent mount for persistent storage.

```bash
export TRAINING_STORAGE=/mnt/browser-training
export HF_HOME="$TRAINING_STORAGE/model-cache"
export HF_HUB_CACHE="$HF_HOME/hub"
export TRAINING_RUN_ROOT="$TRAINING_STORAGE/runs"
export PYTHONPATH="$PWD:$PWD/scripts"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 USE_HUB_KERNELS=NO
export AXOLOTL_DO_NOT_TRACK=1 VLLM_NO_USAGE_STATS=1 WANDB_MODE=disabled
export TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
export TRAINING_SFT_PY="$PWD/envs/sft/.venv/bin/python"
export TRAINING_RL_PY="$PWD/envs/rl/.venv/bin/python"
mkdir -p "$TRAINING_RUN_ROOT"

uv pip check --python "$TRAINING_SFT_PY"
uv pip check --python "$TRAINING_RL_PY"
"$TRAINING_SFT_PY" scripts/verify_stack.py --role sft
"$TRAINING_RL_PY" scripts/verify_stack.py --role rl
"$TRAINING_RL_PY" scripts/patch_trl_policy.py --apply
"$TRAINING_RL_PY" scripts/patch_trl_attention.py --apply
"$TRAINING_RL_PY" scripts/patch_vllm_unload.py --apply
"$TRAINING_RL_PY" -c 'from browser_training.qlora_compat import candidate_module; candidate_module(); print("NF4 candidate import: PASS")'

export NF4_SNAPSHOT="$HF_HUB_CACHE/models--greghavens--Qwen3.8-27B-bnb-4bit/snapshots/26157380225e427827263c34df23018a1e28dff5"
export FP8_SNAPSHOT="$HF_HUB_CACHE/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"
test -s "$NF4_SNAPSHOT/model.safetensors.index.json"
test -s "$FP8_SNAPSHOT/model.safetensors.index.json"
"$TRAINING_SFT_PY" scripts/sft_learning_probe.py \
  --snapshot "$NF4_SNAPSHOT" --output "$TRAINING_RUN_ROOT/apple-cpu-preflight" --prepare-only
```

These paths assume preserved Hugging Face cache layout. When transferring,
retain snapshot symlink targets in `blobs/` or materialize the snapshot files;
copying just dangling snapshot links is insufficient. The metadata existence
checks above are not shard checksum verification. Preserve/check the pinned
snapshot manifests, including all tokenizer/config files. No weights are fetched
by these offline commands. Use `download_models.sh` before setting offline mode
only when downloads are intended and authorized; its defaults must be inspected
for the model selection needed. Reapply and verify audited patches after a uv
sync that restores package files; do not bypass a source-hash mismatch.

For a new hardware architecture, use a separate compiler-cache directory. Do
not reuse a directory labelled `sm89` as though it qualified SM120. The current
SM120-only FA2 wheel must not be installed as an L40S attention solution. The
successful L40S path uses SDPA and does not need that optional wheel.

### Bounded SFT reproduction on one L40S

After hardware allocation and authorization:

```bash
CUDA_VISIBLE_DEVICES=0 "$TRAINING_SFT_PY" scripts/verify_gpu.py --min-gpus 1
export SFT_PROBE_RUN="$TRAINING_RUN_ROOT/apple-$(date -u +%Y%m%dT%H%M%SZ)"
set -o pipefail
timeout --signal=TERM --kill-after=15s 540s env CUDA_VISIBLE_DEVICES=0 \
  "$TRAINING_SFT_PY" scripts/sft_learning_probe.py \
  --snapshot "$NF4_SNAPSHOT" --output "$SFT_PROBE_RUN" --steps 32 \
  2>&1 | tee "$SFT_PROBE_RUN.log"
```

Expect `learning-report.json`, separate before/after generation files and
`checkpoint-32`. The pass criterion is held-out exact-match rate >=75%, improving
by >=50 percentage points. The measured reference was 100% after versus 0%
before. NF4, BF16 adapter/gradient, FP32 moment, save/reload and frozen-vision
assertions execute inside the probe. This deadline bounds the process, not host
rental charges. SFT resume has a separate prior probe; this test reloads adapter
weights into the same base rather than resuming optimizer steps.

### Bounded RL reproduction on two L40S GPUs

First check actual device execution:

```bash
"$TRAINING_RL_PY" scripts/verify_gpu.py --min-gpus 2
# Optional topology diagnostic for future collective use; adapter-only sync
# itself does not use NCCL tensor transport.
envs/rl/.venv/bin/torchrun --standalone --nproc-per-node=2 scripts/verify_gpu.py --nccl
```

`verify_gpu.py` requires FP8 GEMM support on every visible device. A future
NF4-only trainer on an older GPU needs a role-specific preflight; rejection by
this two-FP8-GPU check is not itself proof that NF4 training is impossible there.

In terminal A, with the environment above, run the same conservative serving
flags as the successful test. Ensure port 8000 is free. The server is deliberately
private, with no MTP, FP8 KV option, prefix caching or multi-GPU parallelism:

```bash
export VLLM_SERVER_DEV_MODE=1 VLLM_ALLOW_RUNTIME_LORA_UPDATING=1
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export RL_PROBE_RUN="$TRAINING_RUN_ROOT/choice-$(date -u +%Y%m%dT%H%M%SZ)"
printf '%s\n' "$RL_PROBE_RUN"
set -o pipefail
timeout --signal=TERM --kill-after=15s 540s env CUDA_VISIBLE_DEVICES=0 \
  envs/rl/.venv/bin/vllm serve "$FP8_SNAPSHOT" \
  --served-model-name Qwen/Qwen3.8-27B-FP8 \
  --host 127.0.0.1 --port 8000 --dtype bfloat16 --language-model-only \
  --generation-config vllm --max-model-len 2048 --max-num-seqs 4 \
  --gpu-memory-utilization 0.85 --enable-lora --lora-dtype bfloat16 \
  --max-lora-rank 32 --max-loras 4 --max-cpu-loras 4 \
  --enforce-eager --no-enable-prefix-caching --logprobs-mode processed_logprobs \
  2>&1 | tee "$RL_PROBE_RUN-server.log"
```

In terminal B, restore the same working directory/environment and use the exact
`RL_PROBE_RUN` absolute path printed by terminal A. Wait for readiness without
consuming an unlimited rental window, then run:

```bash
curl --fail --max-time 5 http://127.0.0.1:8000/health
set -o pipefail
timeout --signal=TERM --kill-after=15s 420s env CUDA_VISIBLE_DEVICES=1 \
  "$TRAINING_RL_PY" scripts/e2e_learning_probe.py \
  --snapshot "$NF4_SNAPSHOT" --output "$RL_PROBE_RUN" \
  --server http://127.0.0.1:8000 --steps 8 \
  2>&1 | tee "$RL_PROBE_RUN-trainer.log"
```

Do not run the trainer if health fails. If server startup consumes too much of
its 540-second window, stop both and investigate before authorizing another run;
do not extend deadlines silently. On completion, stop the server immediately
rather than waiting for its timeout, verify no child workers remain, preserve
logs/checkpoints and terminate the rental if finished. For unattended operation,
replace the two terminals with an owner-scoped supervisor and process-group
cleanup; the Modal wrapper currently supplies that supervision.

Expect the report to show eight updates, native policies v1–v9, checkpoint-8,
and final evaluation using v9. The measured reference was 34/64 → 64/64 rewarded
answers. Require actual policy-event replay and initialized optimizer checks;
a process exit code alone is not evidence of correct synchronization. Real
AsyncGRPO resume, model-driven BrowserGym and longer contexts remain separate
next tests. These two toy probes do not need to be rerun until an environment,
hardware, model or integration change creates a reason.

### Storage, network and shutdown obligations outside Modal

Use the same absolute `output_dir` on trainer and server. With two machines,
verify shared-file publication, full file visibility before HTTP registration,
old-version retention, and deletion after leases drain. No custom network weight
transport was implemented. Benchmark actual private-link and filesystem latency
before choosing a cheaper remote trainer; 108,789,760 BF16 adapter elements are
217,579,520 payload bytes per rank-16 snapshot before metadata.

Keep `.vllm_lora` serving directories distinct from retained training checkpoints.
A copied adapter alone is not an optimizer-resume artifact. Back up completed
checkpoints and source/lock manifests before releasing ephemeral disks. Modal
result volumes contain the learned artifacts; local `outputs/modal` primarily
contains diagnostics, configs and source archives.

Capture host/GPU/driver identity, `nvidia-smi` telemetry, package and source hashes,
model revisions, resolved config, seeds, losses/rewards, policy events, stale
sample counts and synchronization timings. `tmux` preserves a terminal session,
not a spending cap or coordinated shutdown. Provider instance lifetime, persistent
storage charges, driver configuration and MIG administration become operator
responsibilities when leaving the SDK.
