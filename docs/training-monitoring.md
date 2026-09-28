# Understanding training progress

The [W&B training dashboard](https://wandb.ai/bjorn-westerlund-3326-uppsala-universitet/browser-training/reports/Browser-training-%E2%80%94-progress-and-health--VmlldzoxNzk2ODA0Ng==)
was reorganized on 21 September around a compact overview. The charts are already
configured, and the explanations sit beside them. It currently focuses on the
finished P11 infrastructure test. Its 18/20 verified safe completions are **not a
held-out benchmark**, and its two optimizer steps had zero gradients. The report
explicitly records that learning was not demonstrated and shutdown failed.

The top view shows six signals together: **recent safe completion, gradient norm,
rollout tokens/s, mixed-reward groups, browser episodes/min and trainer waiting**.
Each graph has an explanation and an **Investigate this signal** link. The three
linked views cover behavior, GRPO updates and throughput; each links back to the
overview. All 56 earlier diagnostic panels remain available there.

Read across the overview to connect agent scores, update health and rollout speed.
Its six operational charts share publication time. Measurements may differ in age,
so coincident changes suggest what to investigate rather than establishing cause.
The fixed browser-dev and generic/tool-use scores are directly below: these are
the checks for actual improvement and forgetting. Nonzero gradients alone are
not evidence that the policy improved.

If the training score changes, follow its link to denominators, unknown outcomes,
unauthorized effects and task-family allocation. If gradients vanish, inspect
reward variation and applied rows. Generated mixed groups may never have reached
the optimizer, explaining why they can coexist with zero-gradient training steps.
If throughput falls, inspect browser/GPU resources, timings and data freshness.

Fixed-dev and SFT panels exclude all synthetic/infrastructure
runs; they are currently empty because no eligible experiments are uploaded.
Unavailable resource/throughput measurements are listed explicitly. A single dot
is a published snapshot, not a learning curve. Historical uploads cannot recover
intermediate measurements that were never uploaded.

The same report URL can follow the next run without rebuilding charts by hand.
Charts query W&B history; the focus description and availability list describe
the time the report was published. The agent reader remains the way to obtain
fresh ages and exact missing-data reasons. API readback verified the chart
definitions and source data. The user reviewed the original layout; the revised
overview still needs signed-in visual review.
[Reproduction and update command](agents/training-metrics.md#published-dashboard-20-september).

## Earlier validation and metric meanings

Updated 19 September 2026. The episode ledger, metric calculations, local/API
agent reader and synthetic W&B scalar/history/table readback are implemented
and tested. Saved real SFT/RL logs also pass the explicit metric mapping. Live
browser observer accounting also passed four scripted Chromium/OpenEnv fixture
episodes, with matching W&B readback. A full-site P07 clean/warranty pair also
passed: both bought the laptop, but only one avoided an unauthorized warranty.
The dashboard data correctly distinguishes 100% completion from 50% safe
completion; these are scripted checks, not model scores. Uniform/adaptive curriculum accounting and
sampler resume are CPU-tested. Sampled sessions now also pass through the installed
TRL worker, with matching rewards, policy versions and token counts. Live trainer
callback and checkpoint-sidecar checks also pass on real NF4 GRPO: three updates,
exact checkpoint restore, three more updates, and 24 applied rows. Separate
trainer/rollout GPU measurements are recorded. The test caught and fixed BF16
adapter promotion to FP32 on resume; see the [GPU acceptance record](agents/training-gpu-acceptance.md).
The later P11 integration is partially qualified; shutdown GPU revalidation and
remote SSH deployment remain open. See the
[implementation runbook](agents/training-metrics.md).

The original accounting tests preceded dashboard creation. The published report
above now supplies the layout for our joint walkthrough.

Admission accounting now also distinguishes **partially admitted episodes**:
one long episode can produce several training rows, and some may become stale
before use. The local native-code test confirmed that queued or prefetched work
does not count as an optimizer update. These fields passed W&B readback.

Read the training-row counters as stages, not separate piles: a row can be
accepted, complete backward, and participate in an optimizer step. “Applied”
means the step completed; it does not prove weights changed or a checkpoint was
saved. Skipped optimizer steps and work abandoned on restart have separate counts.

Resource collection and upload recovery now also pass local checks. CPU is shown
in **cores used** (1 means one busy core); process memory uses PSS, which shares
the cost of shared pages between processes. GPU readings name the actual device
and cover the whole device. Missing readings clear the old value and carry a
reason; we will show their availability and age alongside the chart.

W&B uploads run separately from training. A network failure leaves a local pending
snapshot for retry, and an upload is only confirmed after its data can be read
back. We tested losing that acknowledgment too: restarting recognized the saved
snapshot without duplicating its history. Restoring a checkpoint now starts a linked continuation in W&B and preserves
the original run's later results. Actual model/optimizer restoration still needs
the GPU acceptance test. Uploads are sampled,
so detailed audit history stays in the local ledger and trainer logs.

Checkpoint continuations share one experiment group but keep separate histories.
For example, if training reaches step 120 and we restart from step 80, the original
results through 120 remain available while the continuation starts from 80. Its
cumulative counts include the shared prefix, so we must not add the two runs'
totals together. Old resource/loss readings remain available for audit but are
marked inherited until the resumed process produces new measurements.

Fixed evaluation now has its own checkpoint-specific results. A scheduled suite
uses the same task instances, seeds and harness/verifier revisions each time.
The comparison reports which cases improved or regressed and refuses to rank a
suite with infrastructure errors or unknown safe outcomes. This avoids confusing
an average over several checkpoints with the score of the current model.

The evaluator records requests beside saved checkpoints and runs independently
of training. Automatic checkpoint deletion is blocked while this scheduling is
enabled, so it cannot remove a policy before its queued evaluation. Actual browser
and generic holdout lists still need to come from the data work.

## One dashboard, with the explanations included

The training setup must create or update the standard W&B dashboard/report.
Logging a metric alone does not satisfy this requirement. You should receive one
link with the useful charts already present, arranged around these questions:

1. Is the policy getting better at the user's task?
2. Is it respecting the user's constraints?
3. Is the training process healthy and producing useful updates?
4. Where are time and compute going?

Each panel needs a plain-language title, definition, unit, denominator or sample
count, time window and a short interpretation. Distinguish cumulative results,
recent training results and fixed development evaluations. Show uncertainty for
pass rates and explicitly label unavailable measurements; missing is not zero.
Synthetic connection tests must be excluded from experiment comparisons.

### What the main panels mean

| Panel | Meaning | How to use it |
| --- | --- | --- |
| Fixed-dev completion | Verified task successes divided by evaluable episodes in the fixed development suite, with counts and uncertainty | Main evidence of progress on a consistent task distribution; rising training reward alone is insufficient |
| Fixed-dev safe completion | Episodes with both verified completion and verified adherence to the authorization contract, divided by episodes with sufficient evidence to decide that combined outcome | The principal project outcome; report verifier coverage and unknown outcomes beside it |
| Unauthorized effects | Episodes with at least one verified unauthorized effect divided by episodes with sufficient effect coverage; also report event counts | Should decrease; avoiding every action is not success, so read beside safe completion |
| Recent training pass rates | Verified completion rates by task family/template over a named recent window, with counts | Reveals difficult families and supplies curriculum evidence; a changing task mixture can change this rate without changing model quality |
| Errors and unknown outcomes | Counts and rates of infrastructure failures and insufficient verification, separate from verified policy failures | A spike can invalidate apparent progress; do not silently turn these into difficult tasks or successful episodes |
| Useful GRPO groups | Fraction of complete, valid groups with nonconstant rewards, plus all-success/all-failure counts for binary rewards | Equal rewards give no group-relative reward advantage; mixed groups are an opportunity to learn, not proof of improvement |
| Policy age and discarded work | Difference between the trainer's recorded policy version at admission and the episode's generating version; counts of discards by reason | Shows whether concurrency is creating stale work; version distance is distinct from elapsed seconds |
| Curriculum allocation | Requested sampling probabilities and realized group counts by task family | Explains what the model is practicing and whether exploration/rehearsal floors are respected |
| SFT train/validation loss | Prediction loss on the selected assistant target tokens, labeled by dataset and masking configuration | Useful for fitting/overfitting diagnosis; lower loss does not establish better browser behavior |
| RL loss, entropy and policy diagnostics | The pinned trainer's actual optimization diagnostics, with their source definition | Diagnose updates; do not expect RL loss to monotonically decrease. The current behavior-policy KL diagnostic is not an SFT-reference KL penalty |
| Generic evaluation | Results on the fixed generic/tool-use checks, separate from replay examples | Flags severe forgetting; it is a sanity check, not a comprehensive capability claim |
| Throughput and time | Generated tokens/s, completed episodes/min, optimizer-update and adapter-publication durations | Identify bottlenecks. Name the tokenizer/model and counting boundary; overlapping async stages must not be summed into a misleading 100% pie chart |
| Resources on both hosts | GPU utilization and VRAM separately for trainer and rollout, plus browser CPU/RAM | Distinguishes an idle trainer waiting for episodes from an overloaded browser or rollout server; one host's logger cannot observe the other automatically |
| Data freshness | Timestamp and event watermark of the latest snapshot, plus publication status | Distinguishes a stalled run from delayed telemetry; a previously good value may now be stale |

Metric definitions must also state how retries, cancellations, policy discards
and unknown verification affect their denominators. Preserve valid environment
outcomes even if the associated trajectory is rejected for training; filter
curriculum evidence by its declared freshness/eligibility rules. Do not overwrite
historical outcomes when annotations or verifier versions change.

## How an agent should read the same information

For routine questions such as “is this run improving?” or “which family is
failing?”, use the **W&B Public API**. An agent can retrieve run configuration,
summary values and logged history without browsing charts or accessing the GPU
host. W&B documents reads from active and finished runs. A panel's visibility
does not determine whether a logged metric is queryable.
[W&B export/API guide](https://docs.wandb.ai/models/track/public-api-guide).

For exact history, use `scan_history()`: `history()` is sampled by default.
Request metrics separately when they are logged at different times, because
`scan_history(keys=[...])` returns rows containing all specified keys. Summaries
are useful snapshots, not episode ledgers or a guarantee that every value came
from the same step. Refresh cached API reads and always report data freshness.
[W&B Run reference](https://docs.wandb.ai/models/ref/python/public-api/run).

For detailed audits, offline recovery and curriculum decisions, use the
**durable episode records and metric snapshots** produced by our orchestrator.
They must survive termination of the rented instance. A mounted persistent volume
or periodic copy to durable storage is sufficient initially; no second metrics
service is required. SSH access is a diagnostic fallback, not a prerequisite for
routine monitoring. An artifact reference can connect W&B to the exact snapshot.

The intended data flow is:

```text
Trainer, rollout and browser events
                 ↓
Durable records → one versioned aggregation implementation
                         ├── W&B: dashboard + agent API reads
                         └── JSON snapshots: audit/offline agent reads

Curriculum reads validated training outcomes locally; it does not wait for W&B.
```

Both outputs must carry the same run ID, metric-schema version, snapshot ID,
event watermark, split, policy/checkpoint identity and time window. This lets an
agent explain a temporary upload delay without mistaking it for contradictory
results. Persist records before publishing telemetry, and keep training usable
when W&B is unavailable. There are two delivery paths, but one set of metric
definitions and calculations.

The implemented agent reader returns structured JSON: freshness,
headline metrics with counts, dev-versus-train distinction, family breakdowns,
errors/discards, and the W&B run link when read remotely. Exact history and
per-template snapshots can be requested separately. Episode drill-down integration
is still pending. Use read operations only; the Public
API also exposes mutations, so its name does not imply read-only credentials.
No new agent protocol/server is needed for the initial Python CLI.

## Acceptance criteria before calling monitoring ready

- [x] Version a metric catalog containing keys, meanings, units, aggregation and
  denominators; snapshots distinguish recent and cumulative windows.
- [ ] Finish source/applicability qualification and agree dashboard placement.
- [x] Provision a standard dashboard/report from code with explanatory text;
  no manual metric discovery or chart construction required from the user.
- [ ] Test that every required applicable metric has a panel and is emitted by
  the synthetic fixture; unavailable or not-applicable metrics are explicitly
  identified rather than silently omitted or filled with zero.
- [x] Verify synthetic events produce identical local snapshot and W&B readback
  values at the same watermark, including retries, unknowns and stale discards.
- [x] Use CPU fault tests to verify missing uploads/producers, abrupt process
  exit and resumed writes do not return old snapshots as current or double-count
  episodes. Live multi-node recovery still needs qualification.
- [x] Demonstrate an agent reading the summary and a selected history through
  the API, then reading the matching snapshot without GPU-node access.
- [ ] Walk through the finished dashboard with the user using a labeled synthetic
  example, explaining what deserves action and what is merely diagnostic.

W&B provides a Reports and Workspaces API for programmatic layout and report
creation; it is currently documented as public preview. Pin and test that
optional presentation dependency independently of the GPU training environments.
[Reports and Workspaces API](https://docs.wandb.ai/models/ref/wandb_workspaces).
