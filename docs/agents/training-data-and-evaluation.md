# CPU preparation: fixed evaluation and SFT replay

Updated 19 September 2026. Owner: training. This prepares infrastructure; the
real held-out suites, teacher data, generic replay corpus and canonical harness
remain separately owned inputs. No model/cloud inference is performed by the
validation fixtures described here. No dashboard layout has been created.

## Fixed suites instead of mixed-checkpoint averages

`browser_training.evaluation` defines fixed `model_dev` and `generic_eval` suites.
Each case names task ID, family/template/instance, environment seed and exact
harness/verifier/environment/tokenizer revisions. Duplicate instances are
rejected. `final_test` and training splits are refused by this scheduler; sealed
final evaluation is a separately authorized workflow.

A request hashes the full suite and records one checkpoint identity, policy
version, publication run, completed-training-episode count and cadence boundary.
It is immutable. A changed task, seed or harness is a different suite; paired
checkpoint comparison rejects it. The suite must correspond to genuinely held-out
instances in the future data catalog: this validator cannot prove that an unseen
external training dataset does not contain those instances.

To opt into scheduling when constructing the existing local metrics service:

```python
monitor = RuntimeMetrics(
    new_monitoring_directory,
    run_id=logical_run_id, synthetic=False,
    tasks=reviewed_training_pool,
    expected_producers=["browser", "trainer", "rollout", "orchestrator", "evaluator"],
    evaluation_suites=[browser_dev_suite, generic_sanity_suite],
    evaluation_interval_episodes=1000,
)
```

The suite shape is `{"name": "browser-dev", "split": "model_dev", "cases": [...]}`.
Each case supplies `case_id`, `task_id`, `task_family`, `task_template`,
`task_instance`, integer `seed`, and the four `*_revision` fields listed above.
`validate_fixed_evaluation.py` contains a complete **synthetic** example.
No real task list is fabricated by the preparation scripts.

Requests are emitted **only beside a successfully saved checkpoint**, under
`checkpoint-N/monitoring/evaluation-requests/`. The cadence counts completed
logical RL training episode slots, excluding infrastructure failures/cancellations;
it does not count optimizer steps or require those episodes to have been trained
on. Multiple crossed intervals before a saved checkpoint coalesce to one request
per suite. Schedule state and suite revisions survive checkpoint restore, which
prevents an immediate duplicate request at the same boundary. Reconfiguring the
suite/cadence during resume is rejected.

Checkpoint creation does not execute evaluation, make model requests or rent
hardware. An independently launched evaluator consumes requests. Keep those
checkpoints on persistent storage. **Disable automatic checkpoint pruning** when
using this scheduler: `MonitoringCallback.on_train_begin` rejects a nonzero
`save_total_limit`. This prevents a pending evaluation's model/request from being
deleted. Automatic best-checkpoint selection and retention are not implemented;
review disk budgets and archive/delete checkpoints explicitly after evaluation.

## Worker contract and bounded execution

```bash
cd training
.venv/bin/python scripts/run_fixed_evaluation.py \
  --request /absolute/checkpoint-N/monitoring/evaluation-requests/REQUEST.json \
  --output outputs/evaluation-REQUEST \
  --monitoring-dir outputs/experiment/monitor \
  --concurrency 2 --timeout-s 120 \
  --worker /path/to/python /path/to/reviewed_evaluation_worker.py
```

The worker receives `--request FILE --case FILE --output FILE`. It writes:

```json
{
  "checkpoint_id": "the exact requested checkpoint identity",
  "policy_version": 3,
  "outcome": {
    "status": "completed",
    "goal_completed": true,
    "constraints_satisfied": true,
    "unauthorized_effect": false,
    "reward": 1
  },
  "trace_ref": "persistent reference to the raw trace and verifier evidence"
}
```

The real worker must use the specified saved policy and pin it for every
inference call. It should be a client of a persistent serving instance; the
per-case process should **not reload 27B weights**. A metadata echo does not prove
that the right adapter was loaded. Existing policy reservation/adapter checks
must be used and qualified with the real browser/trainer setup. Native project
evaluations can be mapped with `native_metrics.native_outcome`, while retaining
the original evidence. The mock worker is a plumbing fixture, never a task grader.

Independent cases run in bounded parallel processes with separate output paths.
A timeout kills that worker's process group. Process failure, malformed output or
wrong checkpoint metadata produces an infrastructure-error case with unknown
reward, not a failed policy sample. The runner retains each case before producing
a complete delivery. Restarting reuses saved cases and requires the same command,
request and limits. An interrupted *unsaved* case may execute again; this is not
an exactly-once model-call billing guarantee.

One planned attempt per case is used. Infrastructure errors do not trigger silent
retries until success. A deliberately repeated whole evaluation can use a new
explicit `repetition` number in `evaluation.request()`; it retains the same suite
revision and a distinct evaluation ID. Preserve the failed report and declare the
comparison procedure rather than cherry-picking repetitions.

The runner atomically places completed delivery JSON in `MONITOR/evaluation-inbox`.
The local service imports at most four deliveries per snapshot emission and
archives import status. It validates case identities, requested policy, configured
suite, execution identity and timestamps. Duplicate delivery is idempotent.
Late reports from a parent execution cannot leak into a resumed child's history.
No remote ledger writes, distributed database, or new RL loss is involved.

## Metrics and checkpoint comparisons

The snapshot's `evaluations` list retains each complete suite/checkpoint report,
including case outcomes and trace references. Dashboard scalars use
`evaluation/SUITE_NAME/...`, selecting that suite's latest report. Use these for
checkpoint scores. Existing `outcomes/model_dev/all/...` pools recorded history
and must not be interpreted as one checkpoint's score.

Key fields are safe completion, completion, unauthorized effects, infrastructure
errors, unknown verification, policy version, timestamp, inherited status and
`valid_for_comparison`. Definitions are available in `read_training_metrics.py
--catalog`. An ancestor report is explicitly marked inherited after resume.
A complete report with any infrastructure error or undecidable safe outcome is
ineligible for safe-completion checkpoint ranking; diagnostic rates/coverage are
still visible. A smaller valid denominator must not make it appear better.

```bash
.venv/bin/python scripts/read_training_metrics.py \
  --snapshot outputs/experiment/monitor/snapshot.json \
  --compare-evaluations LEFT_EVALUATION_ID RIGHT_EVALUATION_ID
```

This checks identical suite revisions and reports paired improvements, regressions
and unchanged cases. It is descriptive, without a statistical-significance or
“best checkpoint” claim. The same comparison is available with `--wandb`.

CPU acceptance uses two fixed suites and four scripted worker cases, scheduling,
restart, inbox import, native snapshot metrics and W&B readback of all **458
scalars**. Unit fault tests also cover incomplete reports, unknown verification,
wrong policy/execution, timeout, duplicate delivery, explicit repetitions and
checkpoint-pruning protection. These are mock responses, not a browser benchmark.
The independent installed TRL spawned-worker probe still passes against actual
Chromium/OpenEnv with scripted responses and real tokenizer/parser processing.

## Token-accounted SFT replay

`prepare_sft_mixture.py` accepts normalized `messages` JSONL from the converter
and an independently reviewed generic replay corpus. Run it with the existing
SFT environment, **offline**:

```bash
cd training
envs/sft/.venv/bin/python scripts/prepare_sft_mixture.py \
  --browser data/browser-train.jsonl --replay data/generic-replay.jsonl \
  --protected data/sft-validation.jsonl --protected data/generic-evaluation.jsonl \
  --replay-fraction 0.05 --sequence-len 16384 \
  --output data/mix-browser-replay-05
```

This creates `mixed.jsonl` and a provenance/count manifest. Point the existing
Axolotl dataset path to the resulting JSONL. Match the manifest's tokenizer,
chat-template settings, sequence limit, assistant-only roles and turn-EOS masks
in the training config. `--reasoning` enables the reasoning-plus-action rendering.
For a browser-only baseline, omit replay and use `--replay-fraction 0`.

Measurements use the cached, hash-verified official Qwen3.8 tokenizer and actual
installed Axolotl 0.19.0 labeling classes. The script explicitly requests a token
list because the installed Transformers API otherwise returns a dictionary.
It verifies rendered IDs equal Axolotl IDs and rejects overflow **before output**;
there is no silent truncation or invented chunking. Loss-bearing tokens count
non-masked labels after the causal shift. Processed tokens count the full rendered
conversation. No model weights or network download are involved.

Selection retains every unique browser example once, chooses whole replay
examples without replacement using a recorded seed, and reports the achieved
loss-token ratio and processed-token ratio separately. The initial supported
range is 0–10%; default tolerance is 0.5 percentage points. Whole examples may not
achieve the target exactly. An unattainable ratio is an error: add suitable
examples or explicitly review the tolerance, rather than silently over-repeating
replay. The simple greedy selection is not an optimal subset solver.

Exact duplicates within a source are removed and counted. Exact browser/replay
or supplied holdout overlaps are rejected. These checks do **not** establish
semantic deduplication, task-instance separation, licensing, successful teacher
verification or protection against exposure through sibling traces/chunks. Those
remain data-catalog/curation work. No attention packing is added; hybrid packing
still needs its existing separate qualification.

The cached-tokenizer test used 200 synthetic browser examples and 60 available
replay examples. Selecting 24 yielded **5.077% loss-token replay**, **4.779%
processed-token replay**, 13,936 processed tokens and 1,359 loss-bearing tokens.
The browser-only baseline had 13,270 / 1,290 tokens respectively. A one-token
sequence limit was rejected before creating output. These numbers qualify
measurement/selection plumbing; they are not a recommendation for real data size.

## Resource samples across SSH-accessible nodes

The optional `relay_resource_sample.py` uses existing rsync/SSH, not a new service.
On the source node, copy the receiving execution's snapshot once to establish its
identity, run the resource sampler against that local copy, and relay its selected
role mailbox. On the receiver, create its `MONITOR/resources` directory first.

```bash
.venv/bin/python scripts/relay_resource_sample.py \
  --sample /source/monitor/resources/rollout.json \
  --identity-snapshot /source/monitor/snapshot.json \
  --ssh-host trainer-host --target /receiver/monitor/resources
```

It makes an immutable temporary copy, then rsyncs with delayed atomic replacement,
SSH batch mode, existing host-key verification, connection/I/O/outer timeouts and
owner-only file permissions. Credentials are not embedded. Use your process
supervisor/timer for periodic delivery; no automatic remote allocation or SSH
configuration occurs. Failed transfer leaves the previous destination sample to
age. The receiving service still checks run/publication identity; a changed
execution requires a new identity snapshot and sampler process. Use one source
per role, not competing writers or an inferred aggregate across rollout GPUs.

Actual local rsync delivery and duplicate import passed; SSH command construction
was tested. **Real SSH connectivity, permissions, throughput and latency remain
unqualified until two reachable instances exist.** This utility transports tiny
metrics files, not model/adapter checkpoints or NCCL traffic.

## Remaining acceptance boundary

The prepared CPU pieces do not establish a production browser training launch.
The subsequent [bounded GPU acceptance](training-gpu-acceptance.md) now passes
NF4/BF16 accumulation, runtime publication, checkpoint save and exact
optimizer/model resume with these monitoring hooks on a synthetic two-turn task.
Realistic context/throughput measurements remain necessary before sustained training.
Canonical-harness stabilization, actual held-out suites and verified teacher/
replay data remain inputs from the ongoing harness/data work. Dashboard layout
is intentionally reserved for the joint session with Bjorn. No paid job was
started by this CPU preparation.
