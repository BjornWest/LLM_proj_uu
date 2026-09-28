# Browser-agent training decisions and experiment plan

For the human checklist and separate step-by-step timeline, start with the
[training recipe](training-recipe.md). This document retains the decision details.

User decisions recorded 16 September 2026. This is the intended experiment plan,
not a claim that every option is implemented or GPU-qualified. See
[measured infrastructure findings](training-findings.md) for what has passed and
[the FP8 trainer investigation](../training/NOTES.md#fp8-trainer-recheck--16-september-2026)
for the main precision blocker. Existing successful NF4 smoke configurations
remain reproducible; proposed ranks, contexts and learning rates below do not
silently replace them.

## Order of work and teacher use

The primary pipeline is **verified teacher trajectories → offline SFT
distillation → RLVR**. First tune the browser harness using base Qwen, freeze
the canonical harness, then select the teacher and begin serious post-training.
Teacher selection uses larger open models on model-dev tasks, measuring both
completion and adherence to user intent. Retain the earlier gate: if no teacher
clearly exceeds Qwen, reconsider/skip SFT rather than assuming demonstrations
will help.

Offline demonstrations amortize expensive teacher inference across many student
experiments. On-policy distillation needs supervision on states visited by the
current student; collecting it in rounds still entails repeated teacher use.
It can be more student-data-efficient without being cheaper overall. RLVR
provides the planned on-policy learning phase using deterministic environment
rewards, although that reward signal is different from teacher supervision.
Iterative/on-policy distillation is a stretch experiment only if teacher compute
later proves cheap. It is not part of the implementation plan now.

SFT primarily imitates **independently verified successful teacher traces**.
Failed trajectories remain useful for finding difficult task families,
regenerating/correcting demonstrations and mining recovery states; future
preference/contrastive training is another possible use. Do not directly imitate
known failed behaviour just to fill the dataset. For low-pass-rate families,
consider more teacher attempts to obtain enough positive examples and record
that collection cost. Preserve all attempts separately from the SFT selection.

## Data splits and harness exposure

Assign stable site, template, instance/seed and trajectory IDs before generating
data. Keep an exposure ledger for harness development, teacher selection and
training. Deduplicate across splits, including chunks from the same trajectory.

| Split | Purpose and allowed exposure |
| --- | --- |
| Harness-dev | Repeated harness debugging/tuning. Can become training data after harness freeze, never later evidence of generalization. |
| Model-dev | Fixed held-out environment tasks for teacher selection, rank/hyperparameter comparisons and shared SFT/RL evaluation. Teacher-selection traces stay here. |
| SFT train | Verified successful teacher trajectories from training instances. |
| SFT validation | Separate teacher trajectories for token loss and SFT overfitting checks; not a substitute for environment evaluation. |
| RL train | Fresh procedural episodes from training sites/templates/seeds. |
| Final test | Sealed until final evaluation; both IID held-out instances and OOD tasks, templates and dark-pattern combinations. |

Preserve the stronger existing [generalization requirement](agents/generalization-requirements.md):
reserve **entire sites/codebases** from training and repeated development tuning.
New products or seeds on an exposed site do not establish unseen-site transfer.
Keep that cohort distinct from novel-template/combination tests. Model-dev is
held out from weight training, but repeated selection makes it development data,
not an unbiased final test.

Version the frozen harness, action grammar, observation construction, parser,
environment assets and reward code in every run. Explore harness changes
separately. Necessary bug fixes need a new version and comparable baseline
evaluations; do not attribute their gains to model weights.

## Environment scale and reward design

Planning envelope: **4–8 substantial sites/workflows with roughly 10–25 templates
each** (40–200 templates). A practical initial target is about **five sites and
50–100 templates**, plus separately reserved evaluation sites. This is a scope
target, not an inventory of completed environments. Procedural variation should
cover products/content, prices, constraints, synthetic users, layouts, deceptive
patterns and difficulty. Prefer depth and meaningful variation over shallow
site count. Selecting tasks does not authorize reducing the imported website;
preserve complete navigation, distractions and surrounding workflows.

Pair tasks to prevent blanket conservative policies from winning: include both
“decline insurance” and “buy insurance” when the user requests it. Authorization
depends on user intent and site state. Early termination that avoids side effects
without completing the goal must not receive the successful-completion reward.
Verify relevant event history as well as final state; unverified side-effect
coverage must remain explicit.

## Sequence length, memory and batches

A trajectory can be one sequence when it fits, or become windowed/state-action
examples with enough preceding context. If the second half of a 100k-token trace
needs all of the first half, a 50k-token window cannot contain both: use a larger
context or an explicitly evaluated truncation/summary strategy. Reprocessing an
overlapping prefix costs compute. Mask repeated prefix tokens from the loss
when they only supply context, and avoid double-counting target tokens.

Gradient accumulation means multiple forward/backward microbatches under the
same weights, followed by one optimizer step. It does not provide stateful
continuation between chunks or reusable cross-update KV/activation caches.
Variable lengths are primarily an efficiency concern, but truncation and the
choice of token/example loss weighting also affect learning.

LoRA saves base gradients/optimizer state, not the need to propagate gradients
through base layers. Activations remain a substantial variable memory cost.
Without checkpointing, a rough activation term scales with microbatch × sequence
length × layers × hidden dimension when attention avoids materializing a
quadratic matrix. This is not a VRAM calculator for Qwen's hybrid attention;
Gated DeltaNet state, workspaces, the vocabulary head and implementation choices
also matter. “27B FP8 ≈ 27 GB” describes an ideal weight payload only; exceptions,
scales, vision weights and runtime allocations add memory. Our measured trainer
base is NF4; custom FP8 trainer integration is now paused.

Proposed production benchmark: **microbatch 1, around 16k context, non-reentrant
gradient checkpointing enabled**, then compare 8k/16k/32k and checkpointing on/off
where memory permits. Start qualification at a short context first. No 16k/32k
fit is promised. Checkpointing trades recomputation for memory; disable it only
when measurements show a worthwhile throughput gain within headroom.

Treat **100k–200k processed non-padding tokens per optimizer update** as an
initial scale to investigate, not a fixed requirement. Eight full 16k microbatches
contain about 128k input-plus-output tokens; they need not contain 128k assistant
loss tokens. Log processed tokens, loss-bearing tokens, episodes, accumulation
and actual optimizer updates separately. For GRPO also log groups/generations
and reward variation: SFT token budgets do not directly determine an RL batch.
Make loss normalization explicit so changing lengths/accumulation does not
silently change the weighting of examples.

Packing is secondary until benchmarking shows it matters on the intended single
trainer GPU. The validated hybrid baseline stays unpacked. Any later packing
must isolate both full-attention and recurrent/DeltaNet state at boundaries;
an attention mask alone is insufficient. Do not use spare sequence capacity
until that path is qualified.

## Small replay and general-capability checks

Test broad, high-quality instruction/reasoning/tool-use replay at **0% baseline,
1%, 5%, possibly 10% of loss-bearing training tokens** during SFT. Also report its
share of all processed tokens, since observation-heavy browser samples and short
generic answers can have different loss densities. These are token mixtures,
not example-count mixtures, and not a reconstruction of Qwen's unavailable
pretraining data. Replay beside short examples is an optional packing use only
after isolation is proven.

[Replaying pre-training data improves fine-tuning](https://arxiv.org/abs/2603.04964)
provides motivation, including target-domain data-efficiency gains in controlled
150M-parameter experiments; it does not establish an optimal ratio or benefit for
our 27B browser policy. Evaluate domain performance and a small fixed generic/
tool-use sanity suite after SFT and selected RL checkpoints. Mixing an auxiliary
SFT/replay objective into GRPO would be a separate experiment; arbitrary generic
texts do not automatically provide verifiable RL rewards.

## Curriculum and RL evaluation

Before RL, estimate the SFT model's pass rates over the training task pool.
Difficulty dimensions include browser steps, constraint count, deceptive-pattern
type/count, hidden-information depth, distractors, navigation and eventually
memory requirements. Memory is a future dimension, not permission to build a
memory-training subsystem now.

Plan a simple sampler that uses observed success rates as well as authored
difficulty. Downweight near-certain successes, prioritize intermediate success,
and occasionally retry near-zero-success families. Retain rehearsal/exploration
probability for every eligible family. Smooth estimates and log sample counts
and sampler versions so a few lucky trials cannot dominate the curriculum.
Use training-pool estimates, not final-test feedback, for adaptation. A uniform
sampling versus adaptive-curriculum ablation is a useful small comparison.
With a binary reward, all-success/all-failure GRPO groups provide no group-relative
reward advantage; other regularization terms, if enabled, are a separate signal.

Do not fix a validation-to-training rollout ratio. A tentative schedule is
**100–200 fixed model-dev episodes every 1,000–2,000 training episodes**; count and
report completed, admitted and discarded episodes separately. Optionally add
fresh instances from a reserved dev generator. Use roughly **300–500+ episodes**
for serious checkpoint comparisons, with paired tasks/seeds and uncertainty
estimates. These counts are starting budgets, not statistical guarantees.
Final-test access remains sealed until the model/selection procedure is frozen.

Watch train/dev divergence, gains confined to exposed templates, declining
entropy/formulaic behaviour, drift from the SFT policy, and reward gains without
corresponding behaviour gains. Policy drift is a diagnostic, not necessarily a
failure; the current AsyncGRPO stack does not automatically supply an SFT-reference
KL penalty. Additional SFT-reference scoring has its own compute cost.

Keep intermediate checkpoints and their evaluation records: reward can peak and
regress. Select by model-dev results rather than latest training reward. Preserve
adapter, optimizer, scheduler/RNG/trainer state and provenance where supported;
actual asynchronous restart still needs qualification. The existing smoke-test
checkpoint-retention setting is not a production retention policy.

## Failures and metrics

Log structured failure categories alongside deterministic reward: misunderstood
constraint, missed hidden information, wrong UI action, hallucinated state,
navigation failure, memory/preference violation, step-budget exhaustion,
unauthorized side effect and unnecessary user intervention. Allow multiple labels
and unknown/unclassified cases; separate model failures from environment/tool
interruptions. LLM-assisted trace classification can support analysis, with
manual spot-checks and classifier/version records. It must not silently replace
deterministic reward verification or reveal sealed-test traces during selection.

Report completion, intent-preserving/safe completion, unauthorized effects per
episode, interventions/clarifications, steps/tokens/cost, and breakdowns by task,
site, deceptive pattern and failure category. Keep verification coverage visible.
Include generic/tool-use regression checks and throughput/staleness diagnostics.

## Adapter and learning-rate experiments

| Setting | SFT candidate | RL candidate |
| --- | --- | --- |
| LoRA rank | 16–32, preference to investigate 32 | 8–16, preference 16 |
| Learning rate | 5e-5 / 1e-4 / 2e-4; start candidate 1e-4 | 2e-6 / 5e-6 / 1e-5; start candidate 5e-6 |
| Adapter storage | BF16, asserted explicitly | BF16, asserted explicitly |

Use a small 8/16/32 rank sweep on model-dev only if budget permits. Keep the
architecture-verified text attention, MLP and selected Gated DeltaNet projections
from the existing setup; do not reduce this to generic q/v targeting or expand
to vision/head/MTP without justification. Standard alpha=2×rank is the existing
baseline. rsLoRA is optional and changes scaling from alpha/r to alpha/sqrt(r);
revisit alpha/LR and export compatibility rather than toggling it invisibly.

**SFT-to-RL handoff must preserve the learned policy.** Our current adapter loader
requires matching rank/targets; r32 SFT cannot simply load into r16 RL. The
lowest-complexity first experiment continues the same rank/scaling/targets through
both stages (r16 is GPU-tested; r32 throughout needs qualification). Keeping a
frozen SFT adapter plus a new RL adapter, compressing an adapter, or merging and
requantizing a new base adds compatibility/numerical work and is not implemented.
Defer the final rank pairing until this choice is explicit. Spend more tuning
effort on tasks, curriculum and rewards than on rank.

## Precision and rollout policy

**Operational decision (2026-09-16):** retain the tested NF4 QLoRA trainer + BF16
LoRA adapters, with an FP8 vLLM rollout base. NF4 is the selected working path,
not merely a temporary fallback while we build a custom FP8 trainer. Pause the
Megatron/TE hybrid integration: its implementation and maintenance burden is not
justified within the project timeline, and matching dtype names would not
guarantee matching kernels/scales/logprobs. Preserve the research and prepared
probes; reconsider only if a sufficiently supported upstream path becomes
available. No new FP8 experiments are scheduled.

The current [source/CPU audit](../training/NOTES.md#fp8-trainer-recheck--16-september-2026)
finds no clean direct official-FP8 AsyncGRPO training path. Keep the proven NF4
dependencies pinned. The [hybrid feasibility review](agents/training-fp8-hybrid-feasibility.md)
is historical investigation, not authorization to proceed with its proposed next
GPU probe. Retain FP8 rollouts: the earlier NVFP4 comparison
found only about 10% improvement at high concurrency on the tested setup, and
does not justify extra infrastructure now.

Browser rollout concurrency, vLLM concurrent sequences, GRPO group size and
optimizer batch are distinct settings. Increase concurrency until useful
throughput approaches saturation, while measuring CPU/RAM/browser limits and
stale/discarded work. Every episode retains its starting policy version; publish
new versions for new work and release old adapters only after active use drains.

## Execution priorities

1. Establish split/exposure tracking, task coverage, paired authorization cases,
   deterministic verifiers and failure logging; freeze the canonical harness.
2. Select teachers on model-dev and collect a reusable verified SFT corpus.
3. Retain the selected NF4/FP8 stack, qualify same-policy adapter handoff and realistic contexts,
   then run bounded SFT and evaluate both browser and generic capabilities.
4. Establish task-pool pass rates and a uniform RL baseline; validate checkpoint
   resume before sustained training, then compare a simple curriculum if feasible.
5. Choose checkpoints with model-dev; perform the sealed final evaluation once
   the comparison procedure is frozen.

Budget and RL duration remain uncertain. On-policy distillation and
[browser-specific DFlash2 adaptation](training-findings.md#optional-after-training-adapt-a-browser-specific-dflash2-drafter)
remain optional additions after the core work. This plan schedules no paid runs.

### Next training-infrastructure candidate: task outcomes and curriculum

Prepare observability before enabling adaptive sampling. TRL remains responsible
for GRPO rewards/advantages/loss and updates; the proposed project layer records
outcomes and selects future training tasks. The outcome ledger, metric reducer,
local/W&B reader, saved-trainer-log normalizer and optional family sampler are
implemented and CPU-tested. The observer also passed four actual local-browser
fixture episodes with scripted actions, followed by the full imported P07
clean/warranty pair using its native verifier and historical harness profile.
P07 local/backup/W&B snapshots matched; no model was involved. Sampled-session
wrappers also pass the installed TRL spawned worker, and live trainer callbacks
plus checkpoint-sidecar restore pass CPU checks. Canonical-harness adoption,
actual GRPO optimizer/resume qualification remain pending. Row/episode admission
and optimizer-use accounting now pass native queue/collator, Accelerate and CPU
boundary checks, including partial admission and unused prefetch.
See the [implementation runbook](agents/training-metrics.md). Trace
flagging/taxonomy is owned separately. The dashboard will be built together with
the user after metric-source qualification.

1. Record episode/group IDs, task family/template/instance and split, verifier
   and harness versions, generation-policy version, deterministic outcome,
   completion/error status, tokens/steps/duration and training admission/discard
   status. Deduplicate events and separate infrastructure errors or missing
   verification from verified task failures. Preserve genuinely observed
   outcomes even when the resulting trajectory is discarded from training.
2. Produce recent pass rates with counts/uncertainty by family/template, safe
   completion and unauthorized-effect metrics where verified, and all-success,
   all-failure and mixed-reward group counts. **Human-facing training metrics and
   outcomes must appear in one dashboard**, including dev evaluations, curriculum
   weights, policy staleness/discards and trainer/rollout/browser resource metrics.
   Use drill-down tables or trace links for episode detail rather than a second
   metrics dashboard. Retain JSON/CSV as durable machine-readable data and for
   recovery, not as separate required human monitoring surfaces. The dashboard
   backend is W&B Academic: account access and a synthetic SDK logging round-trip
   were verified on 2026-09-17; production metric wiring is still pending. Separate-node resource
   metrics require explicit collection; the trainer logger alone cannot observe
   the remote rollout GPU. Production hosted logging remains optional and is not
   enabled by the connection check. Curriculum consumes the outcome records
   directly, not dashboard APIs.
3. Establish a uniform baseline and fixed model-dev evaluation schedule. Changes
   in the adaptive training mixture make aggregate training reward unsuitable as
   the sole measure of progress. Keep final test sealed; adaptation uses training
   outcomes only.
4. Add an optional smoothed sampler prioritizing intermediate difficulty, with
   minimum evidence, recent-policy windows and a uniform exploration/rehearsal
   floor. Sample one task instance per GRPO group, preserving its environment
   seed across group members; sample model responses independently. Change task
   sampling frequency, not reward values or gradient weights.
5. Persist sampler state, RNG, task-pool revision and draw history alongside
   checkpoints. TRL's ordinary prompt-position resume is not automatically a
   correct adaptive-sampler resume. Verify process boundaries, stale results and
   retry deduplication with synthetic episodes before browser/GPU integration.

The outcome reducer, reports, sampler and replay tests can be developed on CPU
without finalized tasks, model weights or taxonomy labels. Live integration with
the pinned asynchronous worker is a distinct acceptance gate.

Dashboard delivery includes the layout and explanations, not only logging keys:
the user should not have to discover metrics and add panels manually. Follow the
[monitoring guide and acceptance criteria](training-monitoring.md). Routine
agent monitoring uses the W&B Public API; exact audits, offline recovery and
curriculum use durable records/snapshots from the same aggregation implementation.
Include snapshot identity and freshness so both paths can be compared without
requiring SSH access to a running GPU instance.


### Monitoring increment: resource sampling and W&B recovery (19 September)

Local Linux collectors and an independent uploader now pass CPU fault tests and
real W&B readback. A single CPU workload produced the expected roughly-one-core
reading; missing/partial measurements remain unavailable. The uploader retains
pending evidence across faults and recognizes an already-published snapshot
after losing its local acknowledgment. This is preparation, not deployment or
GPU training qualification. See the [runbook](agents/training-metrics.md#resource-sidecars-and-recoverable-wb-publication).

Still open: actual NF4 GRPO accumulation/checkpoint/resume with monitoring;
canonical-harness adoption; separate-node resource transport; scheduled fixed-dev
and generic evaluation; real model/optimizer restore qualification; and the joint
dashboard layout/interpretation session. No dashboard was created by this increment.


### Checkpoint publication continuation (19 September)

Monitoring now separates uploader recovery from model-checkpoint restore. A
restore creates a new publication ID linked to the checkpoint's parent run, under
the same W&B experiment group; original post-checkpoint results are preserved.
Inherited resource/trainer diagnostics are not advertised as live. Local tests,
installed callback dispatch and real W&B parent/child history readback passed.
This closes the monitoring-history design gap, not the real NF4 optimizer/model
resume gate. Details and evidence are in the
[continuation runbook](agents/training-metrics.md#checkpoint-continuation-history).


### CPU acceptance completed for the current infrastructure increment (19 September)

- Fixed `model_dev`/`generic_eval` suite identities, checkpoint cadence, resumable
  bounded worker execution, per-checkpoint reports and paired comparisons are
  implemented. Final-test scheduling is excluded; partial/unknown suites cannot
  be ranked. Automatic checkpoint pruning is guarded when requests are enabled.
- Offline SFT replay preparation now uses the actual cached Qwen tokenizer and
  installed Axolotl masks, records both token shares and checks exact holdout
  overlap/overflow. The 5% synthetic target measured 5.077% loss-token replay.
- Resource mailboxes have a small rsync/SSH relay; actual local rsync passes,
  while real remote permissions/latency need reachable instances.
- Static tests (177) plus five optional-framework CPU tests pass. The installed
  Chromium/OpenEnv/TRL worker still passes; fixed-suite W&B readback matches all
  458 scalars. No weights were loaded or GPU time allocated.

[Runbook](agents/training-data-and-evaluation.md) and
[evidence](../training/research/cpu-readiness-validation.json) specify boundaries.
The next model-training correctness acceptance needs suitable GPU hardware:
actual NF4 accumulation, LoRA publication, saved optimizer/model restore and
realistic-context measurements. The canonical harness, held-out suite population,
verified teacher/replay data and joint dashboard remain separate inputs/tasks;
this preparation does not claim those are complete.

### GPU monitoring and checkpoint acceptance (19 September)

The narrow NF4 GRPO accumulation/resume gate above is now closed for the synthetic
two-turn harness: three updates, exact adapter/optimizer/scheduler restoration,
and three further updates on two L40S GPUs. Applied rows are 12 + 12 = 24;
policy versions continue through v8 with no premature eviction or leaked
reservations. Trainer/rollout resource samples and local/W&B snapshot readback
passed. The test found and fixed PEFT promoting BF16 adapters to FP32 on resume.
See the [acceptance record](agents/training-gpu-acceptance.md).

The successful continuation used a fresh vLLM server and completed checkpoint;
it is not an unclean-crash or live-server failover qualification. Canonical-browser
integration, realistic-context/throughput measurements, SSH deployment, actual
held-out datasets and the joint dashboard remain open. FP8 trainer research stays
paused; the tested baseline remains NF4 training + BF16 adapters + FP8 rollouts.

### First model-driven browser integration (19 September)

The frozen full-site P11/core-tools-v3 path now runs real model actions through
native TRL, with two completed optimizer steps, eight applied rows, checkpoint-2
and adapter publications v1–v3. Both applied steps had zero reward variance and
zero gradient, so this is plumbing evidence, not learning. The final safety check
failed because native shutdown killed the worker after 15 seconds while requests
were still draining. A bounded-grace fix passed a 22-second delayed-response CPU
test; a short GPU requalification remains open. All rented containers stopped.
See [evidence](../training/research/modal-project-browser-grpo-validation.json)
and [details](agents/training-gpu-acceptance.md). No extra GPU attempt was made.
