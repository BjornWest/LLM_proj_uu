# Monitored GRPO checkpoint acceptance

This qualifies the monitoring attached to our existing NF4 trainer / FP8 rollout
path. It does not establish browser-agent learning, generalization, long-context
capacity, or bitwise reproducibility after an asynchronous restart.

## Acceptance criteria

1. Load the cached pinned 27B NF4 trainer with frozen base, BF16 rank-16 adapters,
   and FP32 Adam moments; use the existing audited TRL constructor and loss.
2. Sample real two-turn episodes through OpenEnv's native TRL worker and the
   persistent FP8 vLLM server. This synthetic environment rewards an exact final
   `B` response. Both turns are generated; there are no teacher-forced answers.
3. Perform three optimizer updates with four microbatches per update. Require
   four applied training rows per step and a changed adapter fingerprint.
4. Check that policy-event logs preserve each episode's adapter identity and
   never evict a policy with a reserved group. Require drained reservations on exit.
5. Save model adapter, optimizer, scheduler, RNG, native rollout cursor/version,
   and monitoring ledger/sampler state. Stop the trainer process.
6. Restore in a fresh trainer process against the same vLLM server. Check exact
   adapter tensor bytes, optimizer moments/counters, scheduler state and global
   step before further updates. Policy version numbers must continue increasing.
7. Run three further updates; verify twelve newly applied rows, twenty-four
   cumulative applied rows, and a separate monitoring publication linked to the
   source checkpoint. Verify the new checkpoint actually exists.
8. Fetch the small evidence files and publish the exact local snapshots to W&B;
   check snapshot and scalar readback. Keep W&B credentials off the GPU container.

The synthetic two-turn harness is deliberately simple. TRL still owns token
history, observation masking, logprobs, advantages and loss. The custom harness
only supplies conversation turns and the deterministic environment outcome.
The policy audit checks observed events; it does not prove every possible race.
The earlier reservation tests cover forced staleness/cancellation separately.

## Entry points

CPU-only worker validation (no weight download):

```bash
cd training
envs/rl/.venv/bin/python scripts/validate_acceptance_harness.py \
  --output outputs/acceptance-cpu-NEW
.venv/bin/python scripts/modal_acceptance.py --dry-run
```

Bounded Modal launcher, **requires current authorization for cloud execution**:

```bash
.venv/bin/python scripts/modal_acceptance.py --steps 3 --gpu-seconds 900
```

The allowance covers each of two L40S GPUs, including a 60-second startup
allowance. The function has at most 840 seconds; the internal execution deadline
leaves cleanup time. No automatic retries, one container, separate queue timeout.
CPU preparation checks source compatibility and cached snapshots before requesting
GPUs. It fails if weights are absent rather than downloading them on paid GPUs.
The launcher records the exact source closure, hashes and Git commit, including
uncommitted source bytes. Returned reports and persistent volume logs survive
ordinary failures; a hard kill may prevent the last volume commit.

The preparation image is reused from `modal_grpo.py`; the original toy-learning
launcher remains independent. No Modal API is required by
`grpo_acceptance_probe.py`. An SSH reproduction runs that ordinary CLI against
the private vLLM endpoint, once fresh and once with `--resume CHECKPOINT`.
The server must read the adapter directories and have no unrelated clients.
GPU IDs passed for resource sampling are physical `nvidia-smi` IDs, independently
of the trainer's `CUDA_VISIBLE_DEVICES` mapping.

Between stages the first process stops its worker, verifies drained reservations,
then unloads its remaining named adapters. The next process publishes new names
from the restored policy counter. This tests an orderly process restart, not
recovery while another trainer is still issuing requests or after an unclean
server crash. Production crash recovery still needs an ownership/cleanup contract.

## Validation record

CPU preparation: focused accounting tests and the actual spawned two-turn worker
passed locally on 2026-09-19. Inference was scripted for that CPU test.

**GPU acceptance passed on 19 September 2026.**
[Machine-readable evidence](../../training/research/modal-monitoring-resume-validation.json)
retains all three attempts, source-manifest hashes, individual checks and shutdown
evidence. Three updates produced checkpoint-3; a corrected fresh-process
continuation restored it and completed steps 4–6, writing checkpoint-6.

- Exact BF16 adapter tensors, FP32 optimizer moments/counters and scheduler state
  matched the saved checkpoint before updates resumed.
- Each update applied four rows: 12 before restart, 12 after, 24 cumulative.
  Seven unrestored queued rows were explicitly discarded and one admitted but
  unused row abandoned on restart; neither inflated applied counts.
- Published policies were v1–v4 and v5–v8. All observed requests retained episode
  identity, retired versions were evicted without reserved groups, and sessions
  drained before cleanup. These short episodes do not exhaust possible races.
- Local/W&B snapshots matched exactly, with 237 initial and 238 continuation
  scalar values. [Initial run](https://wandb.ai/bjorn-westerlund-3326-uppsala-universitet/browser-training/runs/l40s-acceptance-20260919-194945-6f356272),
  [continuation](https://wandb.ai/bjorn-westerlund-3326-uppsala-universitet/browser-training/runs/resume-ad676e27f9ea4f368a85e2c697931be2).
- Physical memory peaks were approximately 29.63 GiB on the trainer and 37.88 GiB
  on the rollout GPU (including reserved memory); trainer PyTorch peak allocation
  was 25.28 GiB. These were very short native rows, typically **61 Qwen-tokenizer
  tokens**, not a 2k/16k/32k context-fit benchmark. The 2,048-token server setting
  was only a cap.
- All attempts totalled 21.22 GPU-minutes of function execution. Adding all three
  60-second startup allowances gives 27.22 GPU-minutes, below the announced 30.
  This is execution accounting, not a final Modal invoice. All three apps were
  queried and had zero running containers afterward.

The successful continuation used a **fresh vLLM server** after the earlier failed
attempts. The launcher supports retaining the server across its two stages, but
that exact successful restore topology was not established by this run. No
model-driven browser, long-context, multi-node or unclean-crash result is implied.
The learning test from 16 September remains the evidence of learning; this test
checks infrastructure and does not estimate a new learning effect.

### Resume dtype regression found

The first attempt completed three updates and checkpointing, then the test's
optimizer fingerprint failed on nested tensors. The recursive checker now covers
the bitsandbytes nested state, with a local serialization regression test.

The second attempt passed optimizer restoration but caught a real storage-policy
regression: the pinned Transformers checkpoint loader calls PEFT `load_adapter`
without `autocast_adapter_dtype=False`. PEFT therefore promotes saved BF16 LoRA
parameters to FP32 again. Setting the flag only during initial `get_peft_model`
construction is insufficient. Sources: [Transformers 5.16.1 loader](https://github.com/huggingface/transformers/blob/v5.16.1/src/transformers/trainer.py),
[PEFT 0.20.0 loader](https://github.com/huggingface/peft/blob/v0.20.0/src/peft/peft_model.py).

`BF16AdapterResumeMixin` delegates the full native checkpoint load, then explicitly
restores trainable LoRA storage to BF16 before optimizer restore, vLLM publication
or forward/backward. It leaves frozen base weights alone. The audited NF4
constructor incorporates this mixin and records its source hash. A tiny local
Qwen model using the actual HF/PEFT loader reproduces the promotion and verifies
the fix, exact adapter bytes and preserved optimizer parameter references.
This qualifies the single-process RL path; it is not a change to sharded loading
or Axolotl's separate resume path.

The corrected GPU continuation reuses the first run's real checkpoint. The failed
verification attempts are retained as evidence, not discarded or called passes.

### Next browser integration: isolated P11 snapshot

Backend recommended P11 clean on the complete restored music site with
`core-tools-v3`: `native_tools_profile(parallel_tool_calls=None,
compact_feedback=True, reasoning_replay='preserve')`. Newer v7/v8 profiles are
not adopted by this task adapter. Backend development needs no hold.

Run `training/.venv/bin/python training/scripts/freeze_browser_harness.py` to
copy the current source/site closure into a new ignored output directory and
run positive/negative scripted checks in two independent browser subprocesses.
Copies contain actual file bytes, include uncommitted changes, check hashes
before/after copying and execution, and reject project imports outside the copy.
Python environment versions and the configured Chromium executable hash are
recorded; installed dependencies/browser binaries are reused, not frozen into an
image. No credentials or shared sessions are copied.

The 19 September snapshot passed: requested Individual purchase completed safely;
Duo purchase failed completion/authorization. Both took two scripted actions,
with no action errors; exposure/avoidance remain unknown. See
[reviewed evidence](../../training/research/browser-harness-snapshot-validation.json).
These privileged scripted checks are infrastructure evidence, not training data
or model results. BrowserGym's raw step reward remained zero: the future reward
bridge must consume the final native `evaluation.json`, preserving unknowns and
technical errors, rather than treating that raw reward as task success.

At the snapshot stage, the remaining gate was to connect
`backend.configure_tools` / `backend.complete(messages)`
to TRL's native white-box sampling callback, preserving the actual sampled token
IDs, logprobs and generated-token masks. Parsed API tool JSON is not the raw model
token stream. Keep the existing single-tool parser, evaluate before cleanup,
and never train on browser/tool-result tokens. Only then run the bounded real
model → browser → reward → GRPO test; this snapshot does not establish that path.

### P11 white-box connection (19 September, follow-up)

`browser_training/project_harness.py` now connects native TRL sampling to an
isolated `scripts/project_browser_worker.py` subprocess per episode. The child
imports only the qualified frozen harness/site, uses its normal tool parser,
and persists final native evaluation before cleanup. The parent receives exact
messages/tool definitions and sends back parsed sampled output plus original
prompt/completion IDs and logprobs. TRL still constructs sequences, masks,
advantages and the loss. Unknown/technical-error grades remain unscorable;
they are not silently converted into successful or failed task rewards.

The CPU qualification `scripts/validate_project_grpo.py` uses actual browsers,
the spawned native TRL worker, and scripted token responses from an HTTP test
server. It checks positive/negative rewards, policy reservations, exact generated
spans/logprobs and exclusion of context from the loss. Local run
`training/outputs/project-grpo-cpu-08` passed with four two-turn rows, each 56
generated tokens, and full requests of 2,288–3,288 **Qwen3.8 tokenizer tokens**.
These are scripted plumbing results, not model performance.

Issues caught before GPU allocation:

- OpenEnv's normalized `LLMResponse` omits reasoning. Parse original IDs with
  Transformers' response parser instead, retaining reasoning in harness history.
- TRL's Qwen XML response template eagerly JSON-parses parameter values before
  schema-aware casting. Numeric browser ID `107` became an integer despite the
  tool requiring a string. The adapter copies the upstream response template,
  removes that eager value parser, and passes actual `tools=` definitions to
  Transformers' supported schema-aware parser. No generated tokens are changed;
  no invalid/batched action is repaired or partially executed. Regression tests
  cover string IDs, reasoning, truncation and multiple calls.
- XML has no generated tool-call IDs. Assign distinct per-turn transport IDs;
  repeating OpenEnv's default `call_0` violates the harness history contract.
- Browser-sized rows can fill multiprocessing pipes during native worker stop.
  An opt-in `enable_shutdown_drain()` runs native shutdown while consuming its
  remaining IPC queues, explicitly marking unconsumed rows discarded and keeping
  final native metrics. Without draining, the native 15-second join terminated
  the worker; the small synthetic rows had not exposed this. No training
  admission or optimizer logic is replaced.

`scripts/modal_browser_grpo.py` repeats the CPU test in a locked separate browser
environment before allocating 2 × L40S. The bounded GPU test uses two optimizer
steps, group/in-flight limits of four, rank-16 BF16 adapters, the existing NF4
trainer and FP8 rollout, an 8,192-token server cap, 512 output tokens per call and
four browser decisions per episode. Maximum allowance is ten minutes per GPU,
including startup; no automatic retries. Uniform-reward groups are allowed to
have zero gradient and are not reported as evidence of learning. This test does
not adopt newer harness profiles or promote P11 into generalization data.

### Real P11 GPU outcome: partial qualification, shutdown failure

Run `l40s-browser-20260919-231004-f1053f6d` completed **two optimizer steps**,
applied eight native training rows, wrote checkpoint-2 (adapter, optimizer,
scheduler, RNG, rollout cursor and monitoring state), and published LoRA versions
1–3 to the persistent FP8 vLLM server. The saved adapter header confirms all
800 tensors are BF16. Twenty fully graded browser episodes included 18 safe
successes and two verified failures. This is a repeatedly used development task,
not a held-out pass-rate result. Both optimizer steps consumed all-success
reward groups: loss and gradient norm were zero. **This run establishes no
learning effect**; the earlier synthetic experiment remains that evidence.

The final safety check **failed**. Native TRL's stop waits only 15 seconds before
terminating its child. Two real inference requests were still draining under
policy v2; the guard marked the worker unsafe. There were no observed request
version mismatches or evictions of reserved adapters, but outstanding reservations
mean the complete retention/shutdown audit cannot pass. The entire vLLM/trainer
container was stopped, and Modal subsequently reported zero running containers.
Restart vLLM before any continuation; do not reuse a server from this failed stop.

Post-run fix: the opt-in shutdown path now signals stop, drains IPC and waits for
the configured request timeout plus 15 seconds (bounded grace), then delegates
to native stop, retaining its forced-termination/unsafe fallback. A native spawned
TRL/browser CPU test with a deliberately delayed **22-second** HTTP response
exited cleanly in **24.19 seconds**, with a healthy registry and no reservations
left. Intentional-close interruptions now receive `cancelled`, rather than an
infrastructure-error outcome; unknown rewards stay null. Fifteen focused tests
passed. **These fixes have not been requalified on GPUs.** The next launch's CPU
gate includes the slow-shutdown regression. No second GPU attempt was made.

Useful measurements from this small run:

- Peak physical VRAM: trainer **42.05 GiB**, rollout **38.37 GiB**. Logged rows
  reached 6,212 Qwen3.8-tokenizer tokens; an 8k server cap is not an 8k training
  memory qualification, and this says nothing about 16k/32k fit.
- Forward/backward time: 85.06 s then 60.93 s per four-microbatch update. Second
  step wall time was 64.26 s; native adapter synchronization took 1.32/1.77 s.
- Native history processing reported some first-step prompt realignment
  (maximum drift 29 tokens), none in step two. Preserve these diagnostics; this
  is not a claim of exact trainer/rollout numerical parity or universally exact
  prompt-prefix replay. Original generated IDs/logprobs remain in browser traces.
- GPU function elapsed 457.33 s: **15.24 GPU-minutes total**, or **17.24** including
  both full startup allowances, within the 20 GPU-minute cap. CPU preparation
  and image-build usage are separate; this is execution accounting, not an invoice.
- Post-stop ledger: eight applied rows, six queued rows explicitly discarded,
  one extra admitted row not applied. Two interrupted episodes were classified
  as infrastructure errors by the version run on GPUs; do not rewrite historical
  evidence using the newer cancellation classification.

[Machine-readable evidence](../../training/research/modal-project-browser-grpo-validation.json)
retains checkpoint sizes/dtype verification, policy audit limits, per-step logs,
source identity, shutdown confirmation and the subsequent CPU regression.
Raw diagnostics are under `training/outputs/modal/<run-id>/`; large adapter and
optimizer checkpoints remain on the Modal results volume. Source copies in that
run identify the executed version, which predates the final shutdown fix.

### Next larger browser test: retained acceptance checklist (20 September)

Do not rent another instance solely to demonstrate nonzero gradients. The earlier
synthetic RL test established learning; P11 established the browser connection.
Combine the remaining checks in a future explicitly budgeted run. Do not fabricate
failures for successful episodes to manufacture a learning signal.

Before allocating GPUs:

- [ ] Freeze the selected harness/site/task closure again and run the CPU gate,
  including the delayed-response shutdown regression. Validate scripted positive,
  negative and interrupted episodes with authoritative outcome grading; unknown
  outcomes must remain null rather than becoming task failures.
- [ ] Select a short, reliably graded task with evidence of mixed model success
  from existing evaluations where available. If no suitable evidence exists,
  budget a small baseline evaluation within the GPU run. Keep a fixed held-out
  comparison set separate from task selection and training.
- [ ] Confirm that the run records group reward variance/zero-variance fraction,
  applied rows, gradient norms, adapter changes, policy versions/staleness,
  discarded rows, cancellations, prompt realignment and resource measurements.
  Check local ledger/W&B agreement; dashboard layout is a separate human task.

During the same GPU allocation:

- [ ] Exercise the new shutdown grace with real in-flight requests. Require clean
  worker exit, drained reservations and safe adapter cleanup; a forced termination
  must retain the unsafe/restart-required classification.
- [ ] On genuinely mixed-reward groups, verify finite nonzero gradients and actual
  adapter changes. Compare a saved/reloaded checkpoint on the fixed evaluation
  set; a short noisy comparison is not sufficient to claim robust browser learning.
- [ ] Observe enough policy updates and overlapping episodes to exercise retention,
  stale complete-episode rejection and eventual eviction. Check that browser
  processes and host/GPU memory do not grow continuously as episodes finish.
- [ ] Inspect multi-turn token masks, truncation and native prompt realignment on
  representative traces, preserving original sampled token IDs/logprobs. This is
  not a request to reopen expensive numerical-parity experiments.
- [ ] Measure realistic context lengths, throughput and peak memory before scaling
  concurrency. P11 already reached 42.05 GiB on the trainer at logged row lengths
  up to 6,212 Qwen3.8-tokenizer tokens; 16k/32k fit remains unqualified.
- [ ] Reload a browser-run checkpoint and validate restored optimizer/monitoring
  state with a fresh vLLM server. Synthetic resume already passed; do not treat
  this as qualification of unclean-crash recovery or live-server failover.

SSH provisioning, cross-node adapter transfer and network performance remain
deployment-specific gates for the later bare-instance rehearsal. They need not
block the next bounded Modal test. FP8 trainer research remains paused.
