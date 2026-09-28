# Validation evidence kept in Git

This directory keeps small, reviewed JSON records of source audits, CPU checks
and bounded GPU experiments. They are evidence snapshots, not test fixtures or
claims that every configuration is ready for production. Read `scope`, `status`
and `limitations` before interpreting a result. Historical failures are retained
when they explain a fix or a boundary of the tested setup.

Start with these records:

| Record | What it establishes |
| --- | --- |
| [W&B overview revision](wandb-dashboard-overview-validation.json) | Six operational signals together, two fixed-dev charts below, and linked behavior/GRPO/throughput diagnostics preserving all 56 original detailed panels. Four report readbacks and HTTP routes checked; revised visual acceptance remains open. |
| [W&B dashboard](wandb-dashboard-validation.json) | Original annotated report, saved layout/filter/axis readback and metric-source coverage. P11 is explicitly an infrastructure example; fixed-dev/SFT exclude synthetic runs. |
| [W&B connection](wandb-connection-validation.json) | Hosted SDK authentication, synthetic metrics and exact outcome-table readback. No real training, Trainer callback or browser-dashboard integration in this historical check. |
| [Metric accounting and readback](metrics-validation.json) | CPU outcome/deduplication/crash-recovery tests, saved SFT/RL log mapping, synthetic W&B scalar/history/table parity and local/API agent reads. Live producer wiring, curriculum and dashboard layout remain pending. |
| [Curriculum and browser metrics](curriculum-browser-metrics-validation.json) | Optional sampler filtering/draw/resume tests and four actual Chromium/OpenEnv fixture episodes with scripted actions; snapshot/curriculum-table W&B parity. No canonical-harness or model-driven training qualification. |
| [SFT execution/resume](modal-l40s-validation.json) | Actual NF4/BF16-LoRA updates and intermediate-checkpoint resume on L40S. |
| [SFT learning](modal-sft-learning-validation.json) | Apple-format behavior before training and after saved-adapter reload. |
| [RL learning](modal-e2e-validation.json) | Native asynchronous updates, FP8 rollout synchronization, choice-task improvement and earlier failed attempts. |
| [Monitored GRPO resume](modal-monitoring-resume-validation.json) | Real accumulation, exact adapter/optimizer/scheduler restore, policy-version retention, GPU telemetry and local/W&B parity. Records the nested-fingerprint test fix and actual BF16-resume regression. Synthetic two-turn task, not browser learning. |
| [NeMo FP8 Hopper probe](nemo-fp8-modal-validation.json) | Small native FP8-base/BF16-LoRA backward checks, hybrid checkpointing, duplicate FP8 weight storage and the hybrid supervisor timeout; no 27B NeMo GRPO claim. |
| [NeMo nonzero-adapter export](nemo-fp8-export-validation.json) | Ordinary BF16 export preserved updates; explicit physical-FP8 tasks failed. Includes native quantization CPU checks, scope limits, timing and cleanup evidence; no live inference refit claim. |
| [Hybrid loss boundary](hybrid-loss-boundary-validation.json) | Unchanged pinned TRL loss with a synthetic CPU BF16 model/adapter: masks, clipping, accumulation and gradients. No Megatron/FP8/export execution; see the [hybrid comparison](../../docs/agents/training-fp8-hybrid-feasibility.md). |
| [Adapter identity](adapter-identity-validation.json) | Same-rank adapter identity/lifecycle checks and unresolved numerical variation. |
| [Browser integration](browser-validation.json), [spawned harness](spawned-harness-validation.json), [policy sessions](policy-session-validation.json) | Real local browser plumbing with scripted model replies, token/reward handling and session retention. |
| [Full-site browser metrics](project-browser-metrics-validation.json) | P07 clean/warranty episodes on the complete imported site; native verifier mapping, backup replay and W&B snapshot/scalar/table parity. Scripted actions, no model learning or upstream checker certification. |
| [Runtime metrics integration](runtime-metrics-validation.json) | Installed TRL spawned-worker sampling/metrics, real browser reward/token/version agreement, and installed Transformers callback dispatch with checkpoint-sidecar restore. No model or optimizer run; native checkpoint metadata in the callback probe is a fixture. |
| [Row admission accounting](row-accounting-validation.json) | Native queue/collator and Accelerate checks; mixed row admission, skipped optimizer steps, unused prefetch, conservative native checkpoint cursor and W&B parity. Scalar CPU backward/SGD only; no GRPO model/optimizer run. |
| [CPU data/evaluation readiness](cpu-readiness-validation.json) | Fixed-suite schedule/worker/accounting/W&B, actual cached-tokenizer Axolotl replay counts, overflow rejection, local rsync and current CPU/browser regression checks. No model or GPU training. |
| [Checkpoint publication continuation](publication-resume-validation.json) | Local lineage/restore isolation, installed callback dispatch and real W&B parent/child history preservation. Metadata fixture only; no model/optimizer checkpoint restoration. |
| [Resource collection and upload recovery](resource-upload-validation.json) | Actual local CPU/PSS and read-only device samples; transport faults, uploader restart, exact W&B readback and lost-acknowledgment deduplication. No GPU compute, training or cross-node transport. |
| [Hybrid packing](hybrid-packing-validation.json), [SM120](sm120-validation.json) | Reproduced limitations and the distinction between CPU preparation and GPU qualification. |
| [Checkpoint audit](nf4-checkpoint-validation.json), [attention build](flash-attn-build.json) | Pinned weight checksums and compiler/artifact provenance; the binaries themselves are not in Git. |

Other JSON files preserve related configuration snapshots, package versions,
source hashes and focused compatibility checks. Machine-specific paths, Modal
app/run IDs and references to raw artifacts are provenance; those paths will not
necessarily exist on a new checkout. Source/model revisions and artifact hashes
are the portable identifiers.

The isolated FP8/NeMo scripts are retained as research reproductions, not current
training entry points: `modal_nemo_fp8.py`, `nemo_fp8_probe.py`,
`nemo_fp8_export_cpu.py`, `validate_fp8_training_cpu.py`,
`probe_grpo_loss_boundary.py` and `probe_megatron_grpo_adapter.py` under
`training/scripts/`. Custom FP8 trainer work is paused. In particular, the prepared
Megatron/GRPO adapter probe has not been GPU-qualified. Keep these sources beside
their evidence so the negative findings remain reproducible; old cloud-test
allowances do not authorize running them again.

Raw `*.log` files and generated `*-help.txt` output are ignored. Virtual
environments, downloaded weights, compiler caches, generated datasets, full run
directories and rendered report pages are also ignored elsewhere in `training/`.
Do not force-add them to reproduce an experiment. Back up needed checkpoints and
raw evidence in persistent artifact storage, then record their identifiers here.

The learned GPU checkpoints remain in the Modal result volume; local
`outputs/modal/` primarily contains diagnostics and source archives. Neither is
automatically included in a clone. No local artifacts were deleted when the
training source was prepared for its first commit.

For interpretation and future work, see the [consolidated findings](../../docs/training-findings.md)
and [research notebook](../NOTES.md). Updates to these evidence records should
describe an actual new validation run, not merely a change to a configuration.

Latest browser qualification: [P11 real-model GRPO](modal-project-browser-grpo-validation.json)
records successful optimizer/checkpoint/publication work followed by a shutdown
safety failure. The subsequent bounded shutdown fix is CPU-tested, not GPU-qualified.
[Frozen harness acceptance](browser-harness-snapshot-validation.json) is the separate
scripted site/profile prerequisite. Neither result establishes browser learning.
