# Browser-agent training recipe

Updated 17 September 2026. A practical checklist and order of work, distilled
from our training discussions. The [experiment plan](training-plan.md) retains
the detailed reasoning; [measured findings](training-findings.md) distinguish
actual tests from preparation. This recipe does not schedule paid work.

**The dish:** a browser policy that completes the user's task while respecting
their intent and constraints, including when the site encourages unwanted
choices. The primary route is **freeze harness → benchmark teachers → verified
demonstrations → SFT with a small replay experiment → RLVR → sealed evaluation**.
Skip SFT if the teacher comparison does not justify it.

**The equipment:** Qwen3.8-27B, NF4 frozen trainer base, BF16 LoRA, Axolotl for
SFT, TRL AsyncGRPO for RL and an FP8 vLLM rollout base. Retain the audited policy
session/adapter-lifetime fixes. Custom Megatron/FP8 integration is paused.
One W&B Academic dashboard is the human monitoring destination; durable results
and checkpoints also live outside W&B. Trace taxonomy/flagging has a separate
owner and feeds this workflow.

## Ingredients checklist

Checked items mean the specific stated capability exists, not that the complete
browser training system is ready.

### Equipment already tested

- [x] Real 27B NF4/BF16-LoRA SFT updates, saved-adapter learning and an
  intermediate-checkpoint SFT resume on short examples.
- [x] Real two-GPU AsyncGRPO learning and native adapter synchronization on a
  trivial choice task. This was not browser-agent learning.
- [x] Local BrowserGym/OpenEnv plumbing with scripted model replies; policy
  reservations and adapter lifecycle checks.
- [x] Basic trajectory-to-SFT converter: action-only or reasoning-plus-action,
  whole trajectory or individual state/action examples.
- [x] W&B Academic credentials and synthetic metric/table upload/readback.
- [ ] Unified launch path for the actual canonical browser harness and NF4 RL
  policy; model-driven multi-turn browser episodes, gradients and publication in
  one bounded acceptance test. The general browser launcher is still gated.
- [ ] Realistic-context memory/throughput checks, restart qualification and the
  production dashboard. Short toy learning tests do not establish these.

Additional CPU preparation now exists: fixed dev/generic evaluation scheduling
and checkpoint comparisons; exact-token SFT replay mixing with holdout/overflow
checks; resource collection/relay; and durable W&B upload/continuation history.
The [data/evaluation runbook](agents/training-data-and-evaluation.md) explains use
and limitations. These capabilities do not populate the actual data ingredients
below or replace the GPU model/optimizer acceptance test.

### Data ingredients

The SFT/replay corpora are conditional on choosing to run SFT. The generic sanity
suite and environment holdouts remain necessary if we go directly to RL.

| Ready? | Ingredient | What we need | Keep it separate from |
| --- | --- | --- | --- |
| ☐ | Source/task catalog | Stable site, template, condition, instance and seed IDs; source revisions, reuse terms, clean/injected pairs, difficulty dimensions and verifier coverage | A downloaded benchmark is not automatically approved training data |
| ☐ | Harness-dev | Small, diverse repeatable browser tasks, fresh-state snapshots and saved success/failure traces for parser, observation, action and recovery debugging | Generalization claims; repeatedly inspected tasks remain exposed |
| ☐ | Model-dev | Fixed held-out environment instances for teacher selection, SFT/RL checkpoint comparisons and limited hyperparameter selection | Weight training; teacher-selection traces stay in this split |
| ☐ | SFT training corpus | Independently verified successful teacher trajectories from training instances; all failed attempts retained separately | Teacher-selection/dev/test instances and suspected invalid successes |
| ☐ | SFT validation corpus | Held-out teacher trajectories for token-level validation loss | Training examples, duplicates and sibling chunks; this is not the browser dev suite |
| ☐ | Generic replay corpus | Reusable, high-quality instruction/reasoning/tool-use examples, normalized and deduplicated | Browser-held-out content and the generic evaluation suite |
| ☐ | RL training generator | Resettable procedural task instances, deterministic state/event verifiers, constraints and difficulty metadata | Final-test seeds, held-out sites and prohibited template overlap |
| ☐ | Generic sanity suite | Small fixed instruction/tool-use checks for severe forgetting after SFT/RL | Replay training examples |
| ☐ | Sealed final test | IID held-out instances, unseen templates/combinations, and a distinct cohort of entirely unseen sites/codebases | Harness tuning, teacher selection, curricula and checkpoint selection |

These are task/environment splits, not just random JSONL splits. A new seed on a
familiar site is not an unseen-site test. Keep clean/injected variants and near
duplicates together when constructing the relevant holdouts; split trajectories
before creating chunks. Model-dev can share the training task distribution, but
its instances stay excluded from weight training. Repeated model-dev use makes
it selection data, not the final unbiased result.

### Preparation and quality controls

- [ ] An exposure ledger links every task and trace to its split and records
  harness inspection, teacher selection, SFT eligibility and RL use. Harness-dev
  may move into training after freeze, but cannot become held-out evidence.
- [ ] Versioned, complete websites with reliable reset and reproducible initial
  state. Preserve normal navigation and distractions; do not simplify a site to
  make our agent or verifier succeed.
- [ ] Explicit authorization contracts and verifier tests covering final state
  **and relevant event history**. Pair “decline insurance” with “buy insurance”
  when requested; abandonment must not pass as safe completion.
- [ ] A strict boundary between policy inputs and privileged task/grader data.
  Expected answers, hidden state and verifier notes must not enter observations
  or SFT context. Audit suspicious passes as well as failures.
- [ ] Raw immutable traces, versioned derived examples, dataset hashes and
  provenance for model/tokenizer, sampling, harness, site and verifier revisions.
  Keep original outcomes separate from later annotations or revised grading.
- [ ] Canonical rendering and loss masks verified with the actual Qwen tokenizer:
  user/site/tool observations supply context; selected assistant outputs carry
  loss. Validate tool-call syntax and reasoning fields against deployment.
- [ ] Token-length distributions, overflow policy and reviewed chunking. Measure
  complete rendered requests and loss-bearing tokens separately. State/action
  examples must retain any history needed to determine the authorized action.
- [ ] Replay mixture accounting by **loss-bearing tokens**, with processed-token
  shares also reported; known sampling seed and a browser-only baseline.
- [ ] A versioned episode outcome ledger consumed by both dashboard summaries
  and the curriculum. Infrastructure errors, unknown verification, valid failures
  and training discards are distinct states; retry events do not double-count.
  The ledger/reducer and local/W&B reads passed CPU and synthetic online checks
  on 19 September. The sampler/resume tests and four scripted real-browser fixture
  episodes also passed. The full-site P07 clean/warranty pair subsequently passed
  native-verifier mapping and local/backup/W&B parity with scripted actions and
  the historical harness profile. Sampled sessions subsequently passed the installed
  TRL spawned worker, and trainer callbacks/checkpoint sidecars passed CPU checks.
  Row/episode admission and optimizer-use accounting also pass native-code CPU
  checks and W&B parity, including partial admission and unused prefetch.
  Actual monitored GRPO accumulation and checkpoint restoration subsequently
  passed on a two-turn synthetic task: six updates and 24 applied rows, with
  exact adapter/optimizer/scheduler restore and local/W&B parity. See the
  [GPU acceptance record](agents/training-gpu-acceptance.md). Canonical-harness
  adoption and real-data evaluation remain pending.

### Training controls

- [ ] Teacher sweep manifest: common task instances, harness/tool capabilities,
  attempt budgets, model/provider revisions, sampling/reasoning settings and
  selection criteria defined before looking at scores.
- [ ] Matching SFT→RL LoRA rank, scaling and targets. Start with the tested rank
  16 path for minimal risk; rank 32 throughout is an option after qualification.
  Rank-32 SFT cannot simply become rank-16 RL with our current loader.
- [ ] BF16 adapter/gradient assertions, suitable higher-precision optimizer
  state, frozen-base checks, saved-adapter reload and first-rollout handoff test.
- [ ] Context/batch/accumulation benchmark and estimate of throughput, peak VRAM,
  tokens per update and time per million tokens before a sustained rental.
- [ ] Fixed evaluation cadence, meaningful intermediate checkpoints, resume
  test and stop criteria for invalid rewards, broken resets or stalled dev gains.
- [ ] Uniform task sampling first; adaptive sampling only after pass-rate
  accounting, exploration floors, policy-age handling and sampler resume work.
- [ ] One W&B dashboard combining task performance, dev/generic results,
  curriculum weights, training diagnostics, stale/discarded work and resource
  usage on both GPU hosts. Episode rows link to the existing trace viewer.
  Include a reproducible layout, plain-language metric explanations and agent
  read access as specified in the [monitoring guide](training-monitoring.md).

## Cooking order and timeline

This is a dependency timeline, not a promise of calendar duration. Teacher
collection and RL duration depend on observed success rates, trajectory lengths
and hardware throughput. We set those budgets after pilot measurements.

| Phase | Main work | Ready to move on when |
| --- | --- | --- |
| 0. Organize | Inventory data, assign splits, define verifiers and provenance | Reusable task catalog and protected holdouts exist |
| 1. Stabilize | Run base Qwen on harness-dev; repair harness and reset issues | Canonical harness and grading contract are frozen |
| 2. Select teacher | Compare larger open models with Qwen on model-dev | Teacher advantage justifies collection, or SFT is skipped |
| 3. Prepare datasets | Collect/verify demonstrations; normalize, mask, tokenize; prepare replay | Reviewed SFT train/validation and replay manifests are reproducible |
| 4. Run SFT | Qualify context, run browser-only baseline, test small replay mixture | Reloaded adapter improves browser dev without severe generic regression |
| 5. Qualify RL | Hand off adapter; measure task difficulty; test real browser GRPO and restart | End-to-end browser learning plumbing and verifiers are trustworthy |
| 6. Run RLVR | Uniform baseline, then optional curriculum; monitor fixed dev suite | A checkpoint is selected using development evidence and budget limits |
| 7. Serve and evaluate | Freeze policy/runtime; evaluate sealed IID/OOD/site cohorts | Final results, artifacts and limitations are reproducible |

### 0 — Sort the ingredients before making traces

Start with the existing [curation inventory](../data/curation/README.md), not a
fresh indiscriminate trajectory download. It already reviews SusBench and
TrickyArena/LiteAgent task material and records source/verifier defects. Existing
WebArena integrations and small browser fixtures can contribute candidates, but
their local versions, task coverage and grading need review. Published source
inspection and saved development sweeps are not training-readiness approval.

For each candidate: check reuse terms, pin the source, identify the actual site
and workflow, inspect the requested goal, remove exact duplicates while keeping
meaningful paired conditions, and determine which constraints the verifier can
really observe. Build fresh-state fixtures and test the grader with scripted
successes, failures, unauthorized intermediate effects and premature stopping.
Unknown coverage stays unknown. Check that the grader never relies solely on
the model's declaration of success.

Assign splits and seal final cohorts now. Build toward roughly five substantial
training/development sites and 50–100 meaningful templates if feasible, with
procedural variation and separately reserved evaluation sites. That is a planning
envelope, not a minimum required to start the pilot or a completed inventory.

**Output:** task/coverage manifest, split ledger, verifier fixtures and source
provenance. Source review, splits and scripted tests can largely happen locally.

### 1 — Stabilize the harness with base Qwen

Use harness-dev for observation formatting, action grammar/parser, tool results,
navigation, reset, step limits and error handling. Save exact model inputs and
responses, browser actions and independent outcome evidence. Use the other
agent's flags/taxonomy to find recurring problems, while distinguishing harness
defects from policy mistakes. Review a sample of apparently successful traces
for leakage, shortcuts that violate explicit rules and verifier blind spots.

Once reliable, freeze the canonical harness, prompts, observation construction,
action schema, environment versions and verifier. Record base-Qwen performance
under that version. Subsequent necessary fixes get a new version and comparable
baseline checks; changing the harness and weights together confounds attribution.

**Output:** frozen harness and baseline. This needs browser resources and bounded
model inference, but not training GPUs. Taxonomy work continues independently.

### 2 — Taste-test the teachers

Choose a small sweep of larger open models that can actually use our action
interface and fit a practical inference budget. Confirm model/data reuse terms
and accessible reasoning outputs before deciding to imitate them. Run the same
model-dev tasks and fresh-state seeds as base Qwen, with comparable tool access
and step/token budgets. Preserve model-specific chat formatting and document
reasoning-mode differences instead of pretending all providers expose identical
controls.

Compare verified completion, intent-preserving completion, unauthorized effects,
interventions, steps, tokens, cost and per-family results. Record every attempt,
including environment/provider errors, and repeat enough cases to assess whether
an apparent margin is credible. Set what counts as a worthwhile margin before
choosing the winner; no universal percentage has been agreed.

**Gate:** if no candidate clearly exceeds Qwen at acceptable collection cost,
skip/reconsider SFT and proceed from the base policy to RL qualification. A
teacher need not dominate every family; per-family evidence can guide collection.
The teacher-selection traces remain model-dev, not free training examples.

### 3 — Collect and prepare SFT plus replay

Run the selected teacher on **training** instances. Collect a small reviewed
pilot across the chosen families before scaling. Retain all attempts and their
costs; select primarily independently verified successful trajectories for SFT.
Low-success families need additional attempts, corrected demonstrations or
recovery examples with reverified continuations. Do not fill a quota by imitating
failed actions. A successful final outcome alone does not make every step a good
demonstration: review malformed actions, excessive loops, leaks and suspicious
passes. Quarantine uncertain examples rather than silently relabeling them.

Convert eligible traces to a stable conversation representation using the frozen
harness semantics. The [existing converter](../training/scripts/prepare_sft_dataset.py)
is only a starting point: it consumes normalized task/step JSON and trusts
`success: true`. It neither verifies that success nor reconstructs every native
browser/tool message from raw logs. An eligibility manifest and canonical trace
adapter are still required.

Choose action-only or available, reviewed reasoning-plus-action targets. Prefer
complete multi-turn history when it fits; use state/action examples or windows
only where necessary context survives. Never put privileged verifier evidence
in the prompt. Tokenize with the pinned Qwen tokenizer/chat template, inspect
representative rendered examples and masks, and report length quantiles and
discard/truncation counts. Chunks inherit the parent split. Mask repeated context
from loss and avoid counting a target twice; accumulation cannot carry hidden
state across chunks or reuse stale activations after an update.

In parallel, find broad, high-quality instruction/reasoning/tool-use replay from
sources with suitable reuse terms. Normalize to compatible messages, remove
duplicates/leaks and malformed or unsuitable answers, and keep the generic test
suite separate. This approximates general capability data; it is not Qwen's
unknown pretraining mixture. Freeze source revisions and sampling manifests.

**Output:** browser SFT train/validation, replay corpus, token/mask audit and a
manifest describing the exact mixture. Compare **0% replay** with one small
candidate, e.g. **5%**, before considering 1%/10% or a broader sweep. Ratios are
fractions of loss-bearing training tokens; also report processed tokens and
browser exposure. State whether replay adds tokens or replaces browser tokens
so improvements are not confused with a larger compute/data budget.

### 4 — Run a small SFT batch before the full recipe

Start on one training GPU with NF4 base weights and explicitly BF16 adapters.
Use the architecture-checked attention/MLP/selected Gated DeltaNet targets,
freeze vision and retain the simple same-rank path into RL. Rank 16/alpha 32 is
the tested adapter configuration; the earlier r32-SFT/r16-RL idea is not a direct
handoff. A candidate SFT learning rate is about `1e-4`, not a tuned recommendation.

Validate a short forward/backward, masks, dtype assertions and checkpoint reload.
Then benchmark useful contexts, starting short and exploring 8k/16k/32k only as
memory allows. Microbatch 1 and non-reentrant gradient checkpointing are the
starting point; use accumulation for effective batch size. A rough initial
100k–200k **processed** tokens/update is only a benchmark candidate; actual
assistant loss tokens can be much fewer. Independent-example packing stays off
until both attention and recurrent-state isolation are proven.

Run the browser-only pilot, evaluate its reloaded adapter on fixed browser
model-dev and generic checks, and compare a small replay mixture. Watch validation
loss, browser behavior and forgetting; low SFT loss alone is insufficient.
Scale collection/training only after the pipeline and data quality look useful.
Keep intermediate checkpoints and tested resume metadata.

**Output:** selected SFT adapter, exact dataset/config manifests, dev/generic
results and measured throughput/VRAM. Teacher inference is no longer needed for
each student experiment: this is the reason for offline SFT distillation.

### 5 — Prepare the RL kitchen

Load the selected adapter into the NF4 trainer and as a native BF16 adapter on
the persistent FP8 vLLM base. If SFT was skipped, start from the base policy with
the configured adapter. Check rank/targets/scaling, saved weights and selected
rollout adapter identity. NF4/FP8 numerical mismatch remains a documented
limitation; do not claim parity merely because synchronization succeeds.

Run a bounded, model-driven multi-turn BrowserGym/OpenEnv task through the
canonical harness, deterministic reward, AsyncGRPO update, version publication
and saved checkpoint. Interrupt/resume deliberately, including the handling of
in-flight work. Policy reservations are runtime state; restart with a fresh
worker/server unless persistent recovery has been explicitly implemented and
qualified. The existing choice-task RL test does not replace this browser test.

The two-turn synthetic checkpoint test now closes the basic accumulation/restore
gate. Its BF16 resume guard is part of the audited NF4 constructor; keep using
that constructor when connecting the canonical browser harness. The successful
continuation started a fresh vLLM server, so it does not qualify crash recovery
against a surviving server with unknown outstanding reservations.

Measure the starting policy's training-pool pass rates by family/difficulty.
Bootstrap the outcome ledger and dashboard, including uncertainty and counts.
Use separate rollout and trainer GPUs initially; two L40S GPUs validated the
short learning probe, not long-context fit. Separate machines are an option
after testing adapter-file visibility/transfer, bandwidth, latency and recovery.
Modal is for bounded diagnostics; longer runs can use reproducible SSH/container
launches on cheaper suitable hardware. Do not depend on MIG availability.

**Output:** browser end-to-end acceptance evidence, resumed-run evidence,
initial difficulty estimates, resource benchmark and a bounded RL run budget.

### 6 — Practice with RLVR and adjust the menu

Generate fresh procedural training episodes with deterministic rewards derived
from task completion, user constraints and unauthorized effects. LLM taxonomy
annotations support diagnosis; they do not silently replace or modify the reward.
Record verifier coverage and inspect suspicious reward improvements.

Start with uniform task sampling. For each GRPO group, draw one task instance
and initial-state seed, then sample multiple model trajectories under the same
reserved policy. TRL performs reward grouping, advantages and updates. Preserve
policy versions throughout each multi-turn episode; new versions apply to new
work, and adapters are evicted only when reservations/requests drain or safe
cancellation finishes. Tune browser concurrency separately from optimizer batch
size, watching throughput, browser CPU/RAM and discarded stale work.

After enough valid recent outcomes, optionally prioritize intermediate-success
families. Smooth sparse estimates, retain a uniform exploration/rehearsal floor,
and do not count infrastructure failures as evidence a task is hard. Observe the
actual fraction of mixed-reward groups: all-equal binary rewards provide no
group-relative policy-gradient advantage. Save sampler state/RNG/draw history
with checkpoints; incomplete or stale results must not corrupt accounting.
Compare adaptive sampling against the uniform baseline if budget allows.

The RL learning-rate candidate is around `5e-6`, with only a small dev-guided
sweep if needed. Generic SFT replay is **not automatically an RL replay buffer**;
mixing an auxiliary supervised loss into GRPO is deferred. Likewise, the current
trainer's behavior-policy KL diagnostic is not an SFT-reference KL penalty.

Periodically evaluate a fixed model-dev suite; an initial planning budget is
100–200 dev episodes per 1,000–2,000 training episodes, adjusted after timing.
Track training attempts, completed/admitted/discarded episodes and optimizer
updates separately. A changing curriculum changes the aggregate training score;
fixed dev results establish progress. Retain intermediate checkpoints, monitor
generic regressions and stop/repair if rewards become unreliable or gains fail
to transfer. Larger 300–500+ dev comparisons may help select finalists; they are
budget candidates, not guarantees of statistical precision.

### 7 — Plate, evaluate and archive

Choose the final checkpoint using **model-dev**, freeze it together with harness,
decoding settings, tokenizer, verifier and environment versions, and then unlock
the sealed final suite. Compare base Qwen, the selected SFT policy when present,
and the selected RL policy on paired instances/seeds with equal budgets. Report
IID, novel-template/combination and unseen-site results separately, with counts
and uncertainty, completion/safe completion, unauthorized effects, interventions,
steps/tokens/cost and relevant task/dark-pattern breakdowns. Include the generic
sanity suite and distinguish unknown/infrastructure outcomes from verified failures.

Do not tune on the final results. If they reveal a defect requiring changes,
document that exposure and arrange a fresh untouched final evaluation rather
than treating repeated tests as sealed. Archive adapter/checkpoint identifiers,
source/data/config hashes, evaluation traces, split/exposure ledger and W&B
exports. Keep large checkpoints and raw artifacts in durable storage independent
of the dashboard/account.

**Optional dessert, only after the core result:** on-policy distillation if
teacher compute becomes cheap, or adapting a DFlash2 drafter to the finished
browser policy. Neither is on the critical path. NVFP4, custom FP8 trainer
integration, memory training and a learned preference-reward system remain out
of scope.

## What can happen in parallel now

The data/harness owners can refine task coverage, verifiers and the canonical
harness; the taxonomy owner can continue trace review. Training infrastructure
can implement the outcome ledger, W&B panels, token/mask audits, replay mixture
accounting and CPU sampler/resume tests. Replay-source review and evaluation
manifest design can also proceed before teacher selection. These activities
need shared IDs/contracts, not premature model training.

Large teacher collection waits for the harness and teacher gate. Sustained SFT
waits for approved data and a context benchmark. Sustained RL waits for the real
browser end-to-end and restart gates. No remaining training duration is known
well enough to assign reliable calendar dates yet.
