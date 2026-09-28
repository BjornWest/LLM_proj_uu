# Episode accounting and metric validation

Updated 19 September 2026. Owner: training. This work does not change TRL's
rewards/loss, policy reservations or trace taxonomy. Human definitions are in
[the monitoring guide](../training-monitoring.md).

## Current scope

Implemented: immutable episode/admission/telemetry events; SQLite transaction,
deduplication and recovery; split/family/template reductions; atomic hashed JSON
snapshots; optional W&B publication/readback; local/API agent reader; explicit
normalization of saved AuditCallback SFT/RL logs.

Verified with synthetic fault/accounting cases, saved real SFT/RL logs, W&B
readback, and four real Chromium/BrowserGym/OpenEnv episodes on the existing
local plumbing fixture. Browser actions were scripted: three safe completions,
one unauthorized subscription, two isolated concurrent sessions. This is not
model/browser RL or an imported benchmark. No new GPU run/model download was
performed during those accounting tests. The annotated W&B dashboard was
subsequently published on 20 September; see the update below.

**Subsequent GPU qualification (19 September):** real NF4/BF16 GRPO accumulation,
checkpoint restore, policy publication and physical-GPU resource collection now
pass on a two-turn synthetic task. The [acceptance runbook](training-gpu-acceptance.md)
supersedes earlier GPU-pending statements for this narrow path. Canonical browser
integration, realistic contexts and the joint dashboard remain pending.

The full imported Tricky site also passed a P07 clean/warranty pair using the
existing historical harness profile and native verifier. Both purchased the
laptop; only the clean episode respected authorization. Completion was 2/2,
safe completion 1/2, and known unauthorized effects 1/2. All 124 emitted W&B
scalars, the family table and immutable snapshot matched local records. This
extends site/verifier accounting coverage, not canonical-harness or RL readiness.

The optional family sampler now has uniform/adaptive modes, committed draws,
probability/evidence logging and CPU-tested checkpoint resume. The browser
observer is exercised on actual fixture results and preserves missing verifier
fields. Opt-in sampled-session wrappers now execute inside the installed TRL
spawned harness worker; live trainer callbacks and checkpoint-sidecar restore
also pass CPU qualification. Still pending: canonical-harness adoption,
real GRPO optimizer/resume qualification (row accounting now passes the native
queue/collator and CPU-boundary checks described below);
cross-host producer transport; GPU-load qualification of resource readings; scheduled
dev/generic evaluation. Local Linux resource sidecars and a retrying W&B uploader
now pass the additional tests below. Earlier synthetic resource values qualified
transport only; the new probe measures actual CPU/PSS and read-only device counters.
Production metrics are not yet fully qualified.

## Files and commands

`training/browser_training/` contains `outcomes.py` (ledger/reducers/backup),
`metric_catalog.py` (meanings/units/bounds), `trainer_metrics.py` (explicit pinned
key mapping), and `monitoring_io.py` (optional W&B and structured agent reads).
No GPU-framework imports are required.

From `training/`, using the existing CPU environment:

```bash
.venv/bin/python -m pytest tests/test_outcome_metrics.py tests/test_monitoring_io.py tests/test_trainer_metrics.py tests/test_benchmark_reporting.py -q
.venv/bin/python -m pytest tests/test_curriculum.py tests/test_browser_metrics.py -q
.venv/bin/python scripts/validate_metrics.py
.venv/bin/python scripts/read_training_metrics.py --catalog
.venv/bin/python scripts/read_training_metrics.py --snapshot outputs/metrics-check/RUN_ID/snapshot.json --split rl_train --families
```

Real-browser fixture check, from the repository root:

```bash
bash training/scripts/smoke_browser.sh --metrics
```

Use the wrapper on this WSL workstation: it adds the already-cached private
`libasound.so.2` path. A direct initial invocation failed on that missing system
library; no installation/download was needed to fix it. The probe starts and
stops its own OpenEnv service on a free loopback port. It neither changes the
canonical harness nor uses a running imported-site deployment. Seven actual
browser actions are observed; model token counts stay null because no model or
tokenizer executes. All trainer admission decisions remain pending.

The validator prints the actual output path. `--full` returns the exact hashed
snapshot including templates. `--window all` selects cumulative outcomes instead
of the recent window. The default reader returns a smaller headline summary.

W&B commands use the existing optional `tracking` dependencies and ignored
project `.env`. They never print credentials. The validator creates a clearly
labeled synthetic run, excluded from model comparisons:

```bash
.venv/bin/python scripts/validate_metrics.py --online
.venv/bin/python scripts/read_training_metrics.py --wandb ENTITY/PROJECT/RUN_ID --split rl_train --history-key outcomes/rl_train/all/completion/value
```

The API reader retrieves the current immutable snapshot, validates its hash and
run/synthetic identity, then optionally scans one history key without sampling.
No SSH/GPU instance is needed. Missing/mismatched files fail explicitly instead
of returning older summary scalars. History bounds are W&B log steps, not
optimizer steps. Old finished-run data naturally reads as stale; freshness
describes age, not a diagnosis of a crashed process.

Import existing immutable trainer logs locally, without uploading them:

```bash
.venv/bin/python scripts/import_trainer_metrics.py --kind rl \
  --metrics-jsonl /path/to/immutable/metrics.jsonl --run-id archived-run-id \
  --output outputs/metrics-check/archived-run \
  --context 'Model/tokenizer revision and measurement scope from this run'
```

Use `--kind sft` for Axolotl and `--synthetic` for fixtures. Reimporting an
unchanged file is idempotent; this is not a growing-file tailer. Missing
policy/checkpoint identities remain null: trainer step is not policy version.
Unknown upstream keys remain in the original logs, not silently reinterpreted.

## Accounting contract

Events have `id`, `kind`, `occurred_at` (Unix seconds), `producer`, `payload`.
Creation fixes the ledger run ID, schema, synthetic flag and expected producers.
Duplicate delivery reuses the exact ID/body; changed content is rejected.
Related identity validation and insertion form one transaction. Episode outcome
and final admission are separate events, accepted in either arrival order;
unmatched admissions remain visible until joined.

Episode payloads require task family/template/instance, split, seed, group
ID/size/member, attempt number, generating policy version, harness/site/verifier/
tokenizer revisions, execution status and nullable deterministic outcomes/reward.
This module uploads no prompts, grader secrets or raw browser traces. Optional
local trace references are not yet exposed as episode drill-downs in W&B.

- Group members must share task, seed, policy and provenance. Do not invent IDs
  when wiring the worker to satisfy these checks.
- Retry only infrastructure failures/cancellations within a slot. Another trial
  after a completed policy sample requires a new group. Latest attempt number,
  not arrival order, determines the logical slot result.
- Rates use logical slots. Cost and infrastructure-failure counts retain all
  attempts. Missing measurements remain null with measured/missing counts.
  Tokenizer revisions cannot silently mix in one run's token sums.
- Infrastructure/cancellation records carry no verified outcome/reward. Unknown
  verification is distinct from policy failure. Safe completion is false when a
  failure/violation is known; otherwise sufficient evidence is required.
- Admission is final per attempt. Stale discards preserve observed success;
  admission is allowed only for verified RL-train trajectories. Admission does
  not prove an optimizer consumed the sample.
- Signal counts use complete verified GRPO groups. Nonconstant rewards count as
  mixed; all-success/all-failure labels apply only to binary 1/0 rewards.
- `all` and `recent` use episode event time; recent defaults to one hour. Groups
  spanning the window may be incomplete within it. Curriculum evidence additionally
  uses its configured recent-policy window and requires complete verified groups.
- Wilson intervals are descriptive episode-level intervals; related task/group
  rollouts are not independent benchmark trials.
- Telemetry retains its own step axis, policy/checkpoint when known, timestamp
  and measurement context. Snapshot values need not be contemporaneous.

## Storage and W&B behavior

SQLite WAL is for one orchestrator host's local filesystem, **not a shared NFS
DB or direct multi-machine writes**. Indexed identity checks avoid a history
scan per append. Snapshot generation currently reads history, so publish
periodically rather than per token. `Ledger.backup()` makes a consistent copy;
copying only a live main DB file may omit WAL data. Backups/snapshots must survive
ephemeral instance deletion.

Snapshot writes use a same-directory temporary file, fsync and atomic replace.
Persistence precedes upload. The optional uploader below retries independently
of training. Repeated publication can add a W&B history row:
deduplicate by snapshot ID/watermark; never sum cumulative snapshot counters.

Aggregate split/window metrics are scalars; family detail is a table and template
detail remains in the snapshot. The snapshot is authoritative for nulls: summary
scalars may retain old values when a newer snapshot has no valid denominator.
Read availability and freshness alongside the values.

W&B 0.30.0 converted a long summary list of metric names into a `large-array`
placeholder during the first test. Replaced that list with count + SHA256; the
full keys remain derivable from the snapshot/catalog. Readback verifies every
scalar, the snapshot file, exact history and family table. Failed validation
runs remain labeled synthetic; no model result was affected.

## Optional curriculum: implemented CPU boundary

`FamilySampler` chooses a family, then a template uniformly within that family;
the draw supplies a procedural seed and instance ID shared by every member of
the group. **Uniform means uniform families**, not necessarily uniform templates
if families have different sizes. The default is uniform; adaptive mode is
opt-in. No sampler is installed into TRL by importing the module.

Adaptive mode uses verified safe completion from complete RL-train groups with
matching pool provenance. Dev/test, infrastructure failures, unknown verification,
incomplete groups, expired observations and policies outside the allowed age
range are excluded. Their reason counts remain visible. Valid environment
outcomes can contribute even if training discarded them, subject to these age
and coverage rules; this does not admit stale trajectories to GRPO.

Initial heuristic: Beta(1,1)-smoothed pass rate `p=(successes+1)/(episodes+2)`;
priority `4*p*(1-p)` after at least eight eligible groups. Sparse families retain
priority 1. Mix normalized priorities with a 20% uniform component. These are
untuned starting values, not research claims or a qualified learning improvement.
The default evidence window is one hour and maximum policy age is two versions;
configure them deliberately alongside the runtime staleness limit.

Call `refresh(ledger, policy_version=..., now=...)` periodically, then `draw(...)`
once per GRPO group. Reserve the actual generating policy before making that
draw. The draw persists before return; replaying its group ID returns the same
task/seed/probabilities. A different policy or pool/config for that ID is rejected.
Browser terminal events must agree with the committed draw identity.

Save `state_dict()` beside the checkpoint and the durable ledger. It includes
pool/config identity, the last refreshed distribution/evidence and a checksum.
Randomness is keyed by algorithm version, run ID, sampler seed, pool revision
and group ID; it does not depend on a process-global RNG cursor. Restore using
`load_state_dict()`. Draws already present in the ledger remain authoritative,
including in-flight groups not represented in an older checkpoint. A sampler
state ahead of the restored ledger fails rather than silently losing evidence.
This CPU boundary is tested; coordinating it with actual AsyncGRPO checkpoint
and task-ID lifecycle is still an acceptance gate.

Snapshot `curriculum` data and the W&B curriculum table separate requested
probabilities at the latest draw from realized counts/fractions over the named
window. Drawn groups are not necessarily started/completed groups. An API reader
can access the same allocation/evidence metadata without the dashboard.

## Next gates before the joint dashboard session

1. Qualify the new worker sampling and checkpoint sidecars with a real optimizer
   and resume. CPU/native-worker evidence is below; keep reward/advantage
   implementation unchanged.
2. Wire metric normalization into the producer/launch path; collect remote GPU
   and browser resources explicitly. Do not conflate allocator and device memory.
3. Connect canonical browser outcomes and real admission/discard events using
   agreed group IDs. Coordinate when changing harness-owned interfaces; consume
   existing taxonomy annotations rather than duplicating classifiers.
4. Adopt the canonical harness once its task/verifier contract is qualified,
   then qualify model-driven browser learning. The reviewed imported-site
   P07 verifier already passed with the historical profile below. Missing
   fields must not be invented to pass validation.
5. Review completeness and interpretation with the user, then build the dashboard
   together and check every required applicable metric has a panel.

Replay preparation, split/provenance safeguards and evaluation/teacher manifests
follow in the agreed order. Final browser formatting and model comparisons still
depend on the canonical harness and tasks.

## Full-site P07 accounting probe

From the repository root, with the existing complete build and browser runtime:

```bash
training/.venv/bin/python training/scripts/validate_project_browser_metrics.py
# Optional aggregate-only W&B publication and API readback:
training/.venv/bin/python training/scripts/validate_project_browser_metrics.py --online
```

The parent uses the small training environment; browser execution uses root
`.venv/bin/python` (override `--browser-python`). No packages or browsers are
downloaded. The script copies the local Python closure, pilot manifest, build
manifest/catalog and **every built asset** into its own ignored output directory.
It checks hashes across the copy, starts an isolated Python process, verifies
project imports came from the copy, and checks frozen hashes after execution.
Concurrent AX edits cannot change the running copy. This is a captured working
tree, including uncommitted changes, not a claim that HEAD alone reproduces it.

Each episode owns a fresh task, browser context and ephemeral loopback server.
No shared WebArena service is used or reset. Existing `FixtureDriver` resolves
fresh selectors/BIDs for clean and unsafe warranty plans; no model is called.
Outputs include original traces/evaluations, their hashes, normalized events,
SQLite ledger/backup, snapshot, source/import manifests and readback results.
The logged step count includes the terminal `send_msg_to_user` dispatch: five
runner browser-step calls per episode, four of them UI interactions.

`native_metrics.native_outcome()` consumes native Evaluation schema v1. **The
raw BrowserGym reward is zero in both cases**; the normalized binary reward is
derived from verified safe completion (1 clean, 0 unauthorized warranty). It
does not modify the harness reward or install a reward callback into TRL.
Native evaluation, injection nulls, evidence and limitations remain unchanged.
An empty effect list with unknown authorization remains unknown, rather than
asserting no unauthorized effects. Technical errors do not become learning
failures. Missing effect coverage can make the mapped outcome more conservative
than native `safe_success` alone.

The pair is recorded as **synthetic/scripted, harness_dev, training_eligible=false**.
It must not enter adaptive RL evidence or model performance comparisons. Policy
version 0 is a scripted placeholder; generated tokens and interventions are
unknown/not applicable, not invented measurements. Retain the native verifier's
derived client-origin journal limitations: no upstream LiteAgent certification,
no resistance to arbitrary JavaScript forgery, and exposure is an acknowledged
policy input rather than proof of model/API inference.

Readback reopens the SQLite backup, remaps saved native evaluations and redelivers
identical events, then compares the whole snapshot at the original timestamp.
This is **metrics replay**, not offline regrading or replaying old browser actions.
Future receipt regrading must retain/recheck full-site extra effects and unknown
route coverage; calling the base `verify_p07` alone is insufficient.

Evidence: [project-browser metrics validation](../../training/research/project-browser-metrics-validation.json).

## Live worker and trainer boundary

`RuntimeMetrics` is an opt-in local multiprocessing-manager service. It alone
owns the sampler and ledger; worker session threads and trainer callbacks use
its picklable proxy. This uses standard local process IPC, not a cross-machine
database/service. The rollout vLLM host remains separate and is not required to
access the ledger. The service serializes draws, writes and checkpoint backup.
W&B is not on this path; snapshots can be published independently.

`MonitoredSessionFactory` consumes the existing reservation context **after the
group has acquired its policy**. It draws one reviewed task and procedural seed,
shared by all members, then delegates session creation to OpenEnv. A matching
`MonitoredHarnessAdapter` counts actual completion token IDs returned by TRL's
model callback. Native verifier results, generation, GRPO scoring and advantages
are unchanged. An explicitly supplied extractor defines which verifier fields
are known; the current runnable fixture extractor is *only* for the pinned
OpenEnv local plumbing task. It is not a P07/canonical-harness bridge.

A stop-triggered session close cannot record a finished episode while inference
is still draining. The native final close records it once. Local persistence
errors trip the existing policy safety guard, because native OpenEnv otherwise
logs and swallows close exceptions. W&B unavailability has no such effect.
Infrastructure errors and interrupted sessions retain null verification/reward.

The installed `HarnessRolloutWorker` test uses real spawn, actual BrowserGym and
Chromium, the cached Qwen tokenizer and native TRL parsing/scoring. Scripted
HTTP responses produce a success and unauthorized-subscription failure; ledger
rewards, reserved versions and generated-token counts must match returned native
samples. Additional groups may start before shutdown; the report distinguishes
the inspected first group from all recorded episodes, including cancellation.
No model, optimizer, vLLM kernel or learning behavior is tested here.

```bash
# Repository root; fresh output name on every execution:
bash training/scripts/smoke_browser.sh --spawned \
  --metrics-output outputs/runtime-metrics/my-worker-check
# Installed callback dispatch; native rollout_state.json is a labeled fixture:
cd training
envs/rl/.venv/bin/python scripts/validate_monitoring_callback.py \
  --output outputs/runtime-metrics/my-callback-check
```

`MonitoringCallback` logs native trainer metrics with actual `model_version`,
not `global_step` guessed as a policy ID. This is the published version at callback
time; an aggregated loss may cover earlier versions and must not be interpreted
as a per-policy evaluation. `on_save` writes a `monitoring/` sidecar
after native `rollout_state.json` exists. It contains a consistent SQLite backup,
immutable metric snapshot, checksummed sampler/config/pool state and in-flight
episode identities. The directory becomes visible by atomic rename. An altered
ledger, changed pool/config, or mismatched native rollout state rejects resume.

Resume into a **fresh monitoring directory**, preserving the run ID from the
sidecar. Pending sessions in the saved state become cancelled with unknown
outcomes. A new worker-generation namespace prevents restarted native integer
group IDs from colliding with older records. New groups refresh sampling from
the restored evidence; this is fresh episode generation, not exact replay of
interrupted browser trajectories. Restart vLLM and reservations as required by
the existing policy-resume contract. Do not restore beyond-checkpoint live
metrics from the abandoned execution as if their optimizer updates were saved.

The existing gated `run_async_grpo.py` launcher accepts `--monitoring-dir` for
**trainer-only** logging/sidecars on its one-turn mock path. It is optional and
does not activate browser sampling. It rejects missing resume sidecars or an
existing metrics directory before loading a model. A browser launcher should
inject the monitored session factory/adapter and callback using the same service,
once the canonical task contract is ready. Single trainer-process topology only
for now. There is no new trainer subclass or upstream source patch.

Two important boundaries:

- A native episode can fork into multiple training rows. The opt-in row hooks
  below distinguish queue decisions from backward/optimizer use. Plain session
  wrappers alone still leave admission pending; queue inspection by a test is
  not an optimizer update.
- The current sampler refresh scans completed ledger evidence for each new
  group, and callback logging creates snapshots synchronously. This is suitable
  for qualification; measure overhead before a long run and bound refresh/upload
  frequency. W&B publication remains separate. Local resource collection and
  upload recovery now pass the tests below; separate-node transport is pending.

Evidence: [runtime metrics integration](../../training/research/runtime-metrics-validation.json).

## Row admission, optimizer use and checkpoint cursor

`row_accounting.py` adds immutable row manifests, admission decisions and use
events to the same ledger. A manifest maps native `TrainingSequence.rollout_id`
to episode/index row IDs and hashes the IDs, masks and behavior logprobs. Raw
token histories are not uploaded in metrics. Manifests require persisted terminal
episode evidence; admitting unknown/unverified outcomes fails validation.

`MonitoredHarnessWorker` delegates scoring/advantages to the pinned native
implementation and checks row cardinality/content before attaching identity.
The attachment is an attribute on the scalar-metrics dictionary, not a fake
numeric metric. It survives pickle and native queue/collator handling. Cancelled
groups with no emitted rows are recorded as no-row episodes when an episode
actually started; unstarted members are not invented as failures.

`MonitoredAsyncGRPOTrainer` uses `RowTrainingMixin` to wrap the existing queue
and collator. The queue observer records the **same version read and staleness
threshold** used by the hash-checked native branch. The collator preserves native
tensors and adds one numeric batch identity for Accelerate; `training_step`
removes it before calling the native trainer. Only a successful return records
backward completion. `MonitoringCallback.on_step_end` records applied or skipped
according to `accelerator.optimizer_step_was_skipped`. Applied means participation
in a completed optimizer operation, not proof of a nonzero gradient/weight change.

To adopt in a reviewed browser launcher, use `MonitoredHarnessWorker` with the
monitored factory/adapter, instantiate `MonitoredAsyncGRPOTrainer` with that worker,
call `trainer.enable_row_monitoring(monitor)`, and attach `MonitoringCallback`
with `callback.trainer = trainer`. All share one local service. Do not enable
the trainer hooks with a worker that does not attach row identities. The existing
gated one-turn mock launcher remains trainer-telemetry-only. The subclasses
reject unknown TRL sources; no installed upstream files are edited by this feature.

For the project's **NF4 trainer**, retain the already-audited constructor from
`qlora_compat.candidate_module()` and compose `RowTrainingMixin` with that returned
`AsyncGRPOTrainer` class. Do not accidentally substitute the plain HF constructor
and lose its k-bit preparation fixes. The row hooks sit outside initialization;
the next GPU qualification must exercise this exact NF4 composition. The plain
`MonitoredAsyncGRPOTrainer` is for the unmodified native constructor path.

Episode admission is derived only after all emitted row decisions are known:

| State | Meaning |
| --- | --- |
| Admitted | Every emitted row passed the queue gate; optimizer use is separate. |
| Discarded | Every emitted row was discarded. |
| Mixed / partially admitted | Some rows passed, others were discarded. |
| Pending | At least one emitted row has no recorded decision. |
| No rows | Scoring emitted no trainable rows; counted as discarded with that reason. |

The new `mixed_admission` outcome metric prevents a partial episode being counted
as a complete admission/discard. For a multi-row episode, `policy_age` uses the
maximum policy version among its final row decisions, not an average row age.
Snapshot `training_rows` contains cumulative totals and per-episode detail. W&B
receives `training_rows/totals/*` and `training_rows/episode_states/*`; the agent
reader exposes the same totals. `--catalog` includes their definitions. These
cumulative stage counts overlap: never stack admitted + backward + applied as
disjoint work. Absent row accounting is unavailable, not evidence of zero work.

Checkpoint discovery: pinned TRL's `DataCollatorForRollout.torch_call` updates
`_trained_groups` during packing, and `_save_checkpoint` uses it for the resume
cursor. CPU execution confirmed that unused prefetch already enters that set.
The monitored mixin substitutes **fully applied groups** only while native
checkpoint saving computes its first-untrained cursor, then restores the original
set. All expected group members must have nonempty manifests and every row must
have an applied event. The normal collator/stop loop is unchanged. This cursor is
conservative: partial/discarded groups can be regenerated after resume; it does
not preserve the old browser sessions, token rows or their queue order.

On restore, applied events in the checkpoint backup remain applied. Pending
queue rows are discarded with an explicit resume reason. Admitted rows without
an applied/skipped event become abandoned; accumulated gradients and lookahead
are not restored. Post-checkpoint updates in an abandoned execution are not
silently merged into the restored history. Duplicate events are idempotent;
contradictory decisions/stages fail. Old snapshot files remain readable; earlier
experimental sidecars whose regenerated snapshot no longer matches this reducer
fail checksum validation and need explicit migration rather than silent reuse.

```bash
cd training
envs/rl/.venv/bin/python scripts/validate_row_accounting.py \
  --output outputs/row-accounting/my-native-check
```

Qualification: native queue staleness and collator, actual Accelerate dispatch,
installed callback dispatch, pickle identity, and a scalar CPU backward/SGD
boundary. The audited native checkpoint-cursor method executes with only its
superclass model saver stubbed. This is **not** a real GRPO optimizer/model
checkpoint run. The independent spawned browser-worker probe also passes with
row identities. W&B returned the identical snapshot and all 145 emitted scalars.
Source/evidence: [row accounting validation](../../training/research/row-accounting-validation.json).

Current limits: one trainer process, no replay of the same row across several
updates, no GPU qualification yet. The numeric batch marker adds a small device
synchronization when read on GPU; measure instrumentation overhead in the next
bounded rental. Model-loss mathematics and native advantage computation are
unchanged. The next GPU test must include actual gradient accumulation,
checkpoint saving and resume with these opt-in hooks enabled.

## Resource sidecars and recoverable W&B publication

Implemented and locally qualified on 19 September 2026. These are optional
separate processes; no W&B API call enters a trainer callback. No additional
Python dependency is required for resource collection. Uploads use the existing
pinned `tracking` extra (W&B 0.30.0).

### Resource measurements

`monitor_resources.py` samples a **selected root PID and observed descendants**,
and/or one explicitly selected **physical NVIDIA device**. CPU usage is the
CPU-time delta for surviving process identities divided by elapsed monotonic
time; 1 means one fully occupied core. PID start times prevent reuse from
creating enormous false CPU deltas. Very short-lived/departed processes can be
missed; this is sampled observability, not exact process billing.

Memory is summed proportional set size (PSS) from Linux `smaps_rollup`, which
apportions shared pages instead of counting their entire RSS for each browser
process. Permission failures or disappearing selected processes make PSS
unavailable for that sample. `/proc` must be visible in the sampler's PID
namespace. The selected root must remain alive; an exited/reused root is reported
unavailable until the collector is restarted with the new workload PID.

GPU readings use a bounded, read-only `nvidia-smi` query. The recorded UUID/host
and scope accompany each sample. `--gpu` uses **physical nvidia-smi identifiers**,
not ordinals remapped by `CUDA_VISIBLE_DEVICES`. GPU utilization and memory are
whole-device measurements, including any other process on that GPU. They are
not per-process use, model allocation, peaks, or separate MIG-instance metrics.
Explicit MIG UUIDs are rejected; MIG qualification remains pending. No selected
GPU means GPU metrics remain missing, not implicitly GPU 0. Device-query failures
and `[N/A]` produce explicit unavailable reasons, never invented zeros.

Resource events can mark a previously available measurement unavailable. The
snapshot then clears its old value and retains the reason/time/scope under
`telemetry_unavailable`. All telemetry has W&B `telemetry_available/{key}` flags;
mask charts with that flag and their measurement timestamp. W&B may retain an
old scalar in its summary even after its availability flag becomes zero. The
snapshot/API reader is authoritative about this distinction.

One atomic mailbox per role lives under `MONITOR/resources/`. `RuntimeMetrics`
imports the latest samples when emitting a snapshot, validates run/classification,
and deduplicates event IDs. A rejected mailbox gets a local `*-import-status.json`;
it does not stop training or become a zero reading. Collector locks prevent two
local samplers from owning the same role. **One scope per role/run** is supported;
multiple rollout devices/nodes need a reviewed aggregation scheme before adoption.

This intentionally bounds collector storage: samples between snapshot emissions
**coalesce**, so it is not a utilization trace or a peak profiler. There can be
long gaps during a long training step. The historical ledger stores imported
samples, not every collector poll. Use a profiler for high-frequency analysis.
The same mailbox envelope can later be copied atomically from another node;
there is no SSH/network transport or remote SQLite writer implemented here.

Example after the trainer has created its monitoring snapshot, from `training/`:

```bash
# In separate terminals/process supervisor jobs. Replace paths/PIDs/UUIDs.
.venv/bin/python scripts/monitor_resources.py \
  --monitoring-dir outputs/experiment/monitor --role browser --pid BROWSER_ROOT_PID
.venv/bin/python scripts/monitor_resources.py \
  --monitoring-dir outputs/experiment/monitor --role trainer \
  --pid TRAINER_PID --gpu GPU-TRAINER-UUID
.venv/bin/python scripts/monitor_resources.py \
  --monitoring-dir outputs/experiment/monitor --role rollout \
  --pid VLLM_PID --gpu GPU-ROLLOUT-UUID
```

`resource_monitor.ingest_sample()` is the validated ledger boundary exercised
by the mailbox importer and CPU tests. Do not share the ledger over NFS or let a second process bypass its checkpoint
coordination. The current CLI mailbox integration is the supported local path.

### Upload delivery and recovery

```bash
.venv/bin/python scripts/upload_training_metrics.py \
  --snapshot outputs/experiment/monitor/snapshot.json \
  --state-dir outputs/experiment/uploader
```

Credentials come from environment or ignored project `.env`. Entity defaults to
`WANDB_ENTITY`, project to `browser-training`; the W&B run ID is selected from the snapshot's publication identity (the logical run ID
for original runs; a linked continuation ID after checkpoint restore). **This process must be the sole W&B writer for that run**:
disable the trainer's native `report_to="wandb"` for it. The existing native-log
normalization supplies trainer diagnostics to the same snapshot. Local locks do
not arbitrate two different hosts writing to the same W&B run; assign one owner.

Delivery guarantees and limits:

- The pending immutable snapshot is fsynced before network work. One pending
  snapshot is retained across restarts, while newer source snapshots coalesce.
  Raw events and trainer logs remain the complete local history. W&B history is
  sampled snapshots, not a promise to upload every optimizer log row.
- Each attempt runs in its own process group, with a 120-second external timeout
  covering SDK initialization, upload, finish and readback. Failures back off
  from 5 seconds to at most 300 seconds, subject to the polling interval (60
  seconds by default). Pending data remains on disk; training does not wait.
- Confirmation requires the exact hashed remote file and every expected scalar
  to match. A lost local acknowledgment is recovered by reading the already
  published snapshot; the real W&B test confirmed no extra history row in this
  case. An interrupted **partial** upload may still need repair and can duplicate
  a history row. Delivery is at least once; deduplicate by snapshot ID.
- A process crash releases the writer lock automatically. Restart with the same
  arguments/state directory. `status.json` reports pending/confirmed identities,
  failures, timestamps and the next attempt. Exception messages and credentials
  are deliberately excluded. `--max-attempts N` bounds attempts and exits nonzero
  with pending data on failure. SIGTERM finishes the current bounded attempt.
- Confirmed staging files are removed. The pending snapshot/status are bounded;
  W&B SDK logs/cache and the authoritative ledger still grow and belong on the
  persistent run volume with a storage budget. Do not delete the SDK directory
  during an active attempt. Archive it after stopping the uploader if needed.
- Each bounded SDK attempt finishes and later resumes the same W&B run. Its
  UI state can therefore say **Finished while training continues**. Use snapshot
  and producer freshness, not W&B run state, as the workload health signal.
- Publication is monotonic within one execution history. A source or remote
  watermark rollback is rejected; restoring an **older model checkpoint** is
  not an uploader restart. The continuation mechanism below handles publication into a new linked run;
  real model/optimizer restoration still needs the GPU acceptance test. Do not
  repoint an old uploader queue at a new execution or clear its state to conceal
  rollback.

Validation command (CPU workload under a second; no model/GPU compute/cloud):

```bash
.venv/bin/python scripts/validate_resource_upload.py
# Optional read-only device query and small authorized W&B publication:
.venv/bin/python scripts/validate_resource_upload.py --gpu 0 --online
```

The online probe measured approximately one CPU core and nonzero PSS from a
separate process, imported actual local device query responses, injected a
transport failure, restarted the uploader, and verified **all 46 scalars** and
the immutable snapshot. It then simulated a lost acknowledgment and verified
that a real resumed W&B attempt did not duplicate history. WSL's idle GTX 1070
returned zero device utilization/used memory; these readings are not a validation
of device-counter accuracy under a rented training workload. CPU fault tests
cover unsupported/missing devices, partial PSS, PID reuse, unavailable readings,
delayed/duplicate delivery, lock ownership, timeout cleanup and snapshot rollback.

Evidence: [resource/upload validation](../../training/research/resource-upload-validation.json).
No dashboard layout, GPU learning, canonical-harness adoption, or cross-node
collector transport is claimed by this test.

## Checkpoint continuation history

Restoring a checkpoint and restarting the uploader are different operations:

| Operation | Publication behavior |
| --- | --- |
| Restart uploader for the same execution | Same W&B run, same pending/confirmed state and deduplication identity. |
| Restore a model checkpoint through `RuntimeMetrics(..., resume=...)` | New W&B continuation ID, linked to the checkpoint's publication run. |
| Restore the same checkpoint twice | Two distinct continuation IDs; neither overwrites the other. |
| Restore a checkpoint from a continuation | Link to that immediate parent, keeping the original logical experiment ID. |

`publication.py` separates the stable logical `run_id` used by ledger/sampler
provenance from the publication ID selected for W&B. Original snapshots without
lineage retain their old behavior. On restore, the service verifies the existing
checkpoint checksum/native rollout metadata and copies the checkpoint ledger.
Only the **new copy's metadata** receives the continuation identity. Neither the
parent live ledger nor its checkpoint is rewritten to disguise newer results.

The snapshot and subsequent checkpoint state carry `publication` with:

- a new publication ID and immediate parent publication ID;
- checkpoint name, saved snapshot hash and monitoring-state hash;
- inherited event watermark and saved policy version;
- restore timestamp.

These identify the monitoring checkpoint. They do **not** hash model weights or
establish optimizer/weight restoration correctness. The upcoming real GRPO test
must still verify that boundary.

The uploader automatically selects this identity from the source snapshot, and
sets W&B `group` to the logical experiment ID. Its config includes
`logical_run_id`, `publication_run_id` and `publication_lineage`. A resumed
execution needs a **fresh uploader state directory**, just as it already needs
a fresh monitoring directory. Restarting that uploader later reuses its state
directory. No manual W&B fork command or history rewriting is involved.

Example after launching the reviewed trainer with its existing `--resume` and a
fresh monitoring directory:

```bash
cd training
.venv/bin/python scripts/upload_training_metrics.py \
  --snapshot outputs/experiment-resumed/monitor/snapshot.json \
  --state-dir outputs/experiment-resumed/uploader
```

Do not reuse the original execution's resource collector. Start it against the
resumed monitoring directory/new workload PIDs. Resource envelopes now carry the
publication identity; a producer from the old execution is rejected even when
its logical experiment ID matches. Legacy resource envelopes remain valid only
for original runs. An uploader with old pending data similarly rejects a source
from a different continuation **before** sending its pending queue.

The continuation preserves events up to the checkpoint, including curriculum
history and prior applied-row counts. Outcomes/cumulative counters therefore
include that inherited prefix. **Do not sum parent and child cumulative totals**
in an experiment dashboard: the prefix would be counted twice. Select a branch
for its policy trajectory; audit unique events across branches separately when
accounting total experimental cost. A group is an experiment lineage, not a set
of independent replicas.

Inherited trainer/resource diagnostics remain in the exact snapshot with
`inherited: true` for audit, but are excluded from live telemetry scalars and get
`telemetry_available/{key}=0`. Producer freshness ignores inherited events.
A new callback/resource sample replaces that diagnostic and makes it available.
Outcome history is retained deliberately; the health of the new process is not
inferred from the old process's logs.

Qualification:

```bash
cd training
.venv/bin/python scripts/validate_publication_resume.py
# Optional small W&B test, no models or rented hardware:
.venv/bin/python scripts/validate_publication_resume.py --online
# Installed callback path, still no model/trainer execution:
envs/rl/.venv/bin/python scripts/validate_monitoring_callback.py \
  --output outputs/publication-resume/new-callback-check
```

The real W&B test uploaded a parent snapshot beyond the checkpoint, then an
inherited-only child snapshot, then a child update. Readback verified lineage,
the shared experiment group, all 34/37 child scalars, two child history entries,
and unchanged parent history. A separate check confirmed the updated uploader
can resume a pre-lineage synthetic W&B run. CPU tests cover siblings, a second
restore, old-producer rejection, pending-queue isolation and corrupt lineage.
Installed Transformers callback dispatch also confirmed inherited health remains
masked until new logs arrive. The native `rollout_state.json` in these probes is
a fixture: **no real GRPO optimizer/model checkpoint was restored**.

Evidence: [publication continuation validation](../../training/research/publication-resume-validation.json).


## Fixed evaluation, replay and remaining CPU acceptance

The [data/evaluation runbook](training-data-and-evaluation.md) now documents fixed
model-dev/generic suites, checkpoint-triggered requests, bounded independent
workers, exact-suite checkpoint comparisons, loss-token replay preparation and
an SSH/rsync resource-mailbox relay. CPU acceptance includes real cached Qwen
and installed Axolotl token masks, real local rsync, installed callback dispatch,
and the real Chromium/OpenEnv spawned-worker fixture. No model was loaded.

The static preflight now runs independent unit-suite shards in parallel and
preserves JUnit/log reports. Latest evidence: 177 lightweight tests passed; the
three optional-dependency skips were separately covered by five CPU tests in the
existing RL environment. Fixed-suite W&B readback matched all 458 emitted scalars.
See [CPU readiness evidence](../../training/research/cpu-readiness-validation.json).

Cross-node transport now has a prepared rsync/SSH path with actual local-copy
qualification; live SSH/latency still needs reachable instances. Physical GPU
measurements now pass in the [bounded GPU acceptance](training-gpu-acceptance.md).
Scheduled evaluation now creates reviewed worker requests, but no model-serving
worker is automatically started. Synthetic two-turn policy pinning and real
model/optimizer restore passed; canonical-harness adoption, checkpoint-specific
model evaluation and realistic-context qualification remain acceptance gates.

## Published dashboard (20 September)

The [annotated W&B report](https://wandb.ai/bjorn-westerlund-3326-uppsala-universitet/browser-training/reports/Browser-training-%E2%80%94-progress-and-health--VmlldzoxNzk2ODA0Ng==)
now opens with six operational graphs on one grid, each with a diagnostic link,
and two fixed-dev graphs immediately below (21 September layout revision).
The original 56 detailed panels are preserved across three linked reports:
behavior, GRPO and throughput. Each links back to the same overview URL.
Operational overview charts share W&B publication time; detailed charts retain
their producer step/event axes. This supports joint inspection without treating
publication time as measurement simultaneity or causation.
Its current focus is the real-model P11 infrastructure run, explicitly marked
synthetic/excluded from model-quality comparisons. Quality and SFT run sets require
`synthetic=False` and exclude `exclude-from-model-results` tags; missing flags
do not admit an unclassified run. They currently have no eligible experiments.
Focus selection uses stable run IDs, never display names. Report publication
does not alter project visibility or enable a public share link.

Source: `training/browser_training/dashboard.py`. Optional presentation SDK
`wandb-workspaces==0.4.11` is pinned in the lightweight environment only. GPU
locks/images are unchanged. Report identity, focus IDs and suite names live in
`training/configs/wandb_dashboard.json`; there are no credentials in that file.
The user's API key remains in the ignored project `.env`.

From the repository root:

```bash
uv sync --project training --extra dashboard --extra modal
training/.venv/bin/python -m pytest training/tests/test_dashboard.py -q
# Read-only preparation and current snapshot/scalar comparison:
training/.venv/bin/python training/scripts/build_wandb_dashboard.py
# Regenerate the SAME managed report for the next selected run:
training/.venv/bin/python training/scripts/build_wandb_dashboard.py \
  --run-id NEXT_WANDB_RUN_ID --publish
```

`--run-id` is repeatable, but unrelated runs and checkpoint continuations must
not be summed or interpreted as independent comparable cohorts. `--browser-suite`
and `--generic-suite` select scalar namespaces for fixed suites. The publisher
replaces the overview and three diagnostic reports' managed blocks, including manual edits to those blocks;
edit the source definition for persistent layout changes. It leaves other
reports/workspaces and run data alone. After saving, it persists the URL before
readback so a verification failure can be investigated without creating a duplicate.

Four focused tests cover emitted metric keys/axes, unknowns, cohort filters and
no smoothing/aggregation. W&B readback compares semantic filters, panel types,
keys, axes, units, ranges, layouts and text. Metrics are compared to the exact
hashed snapshot, allowing only floating-point JSON roundoff in scalar copies.
Existing fixed-evaluation and newly refreshed synthetic accounting fixtures test
otherwise unpopulated metric paths without adding them to quality comparisons.
Evidence: [original metric-source validation](../../training/research/wandb-dashboard-validation.json)
and [overview revision](../../training/research/wandb-dashboard-overview-validation.json).
Definitions/readback and detailed coverage are in ignored `training/outputs/dashboard/`.

Limits: this is API/data qualification, not a signed-in visual acceptance. W&B's
Reports API is public preview, so layout/runtime rendering should be reviewed
with the user. Historical P11 publication contains sparse snapshots; no artificial
per-step/resource history was added. Availability prose is as of report publication;
charts query W&B history. Availability 1 is not freshness, and historical summary
values can outlive a measurement. Use the local/API reader for current age, exact
missing reasons, template details and discard reasons. Failure taxonomy panels,
episode drill-downs and direct adapter-reservation/checkpoint-weight audit panels
are not implemented by this report. They remain explicitly listed limitations.

Official presentation API reference:
[W&B Reports](https://docs.wandb.ai/models/ref/wandb_workspaces/reports).
