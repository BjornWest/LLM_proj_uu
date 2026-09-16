# Validation evidence kept in Git

This directory keeps small, reviewed JSON records of source audits, CPU checks
and bounded GPU experiments. They are evidence snapshots, not test fixtures or
claims that every configuration is ready for production. Read `scope`, `status`
and `limitations` before interpreting a result. Historical failures are retained
when they explain a fix or a boundary of the tested setup.

Start with these records:

| Record | What it establishes |
| --- | --- |
| [SFT execution/resume](modal-l40s-validation.json) | Actual NF4/BF16-LoRA updates and intermediate-checkpoint resume on L40S. |
| [SFT learning](modal-sft-learning-validation.json) | Apple-format behavior before training and after saved-adapter reload. |
| [RL learning](modal-e2e-validation.json) | Native asynchronous updates, FP8 rollout synchronization, choice-task improvement and earlier failed attempts. |
| [Adapter identity](adapter-identity-validation.json) | Same-rank adapter identity/lifecycle checks and unresolved numerical variation. |
| [Browser integration](browser-validation.json), [spawned harness](spawned-harness-validation.json), [policy sessions](policy-session-validation.json) | Real local browser plumbing with scripted model replies, token/reward handling and session retention. |
| [Hybrid packing](hybrid-packing-validation.json), [SM120](sm120-validation.json) | Reproduced limitations and the distinction between CPU preparation and GPU qualification. |
| [Checkpoint audit](nf4-checkpoint-validation.json), [attention build](flash-attn-build.json) | Pinned weight checksums and compiler/artifact provenance; the binaries themselves are not in Git. |

Other JSON files preserve related configuration snapshots, package versions,
source hashes and focused compatibility checks. Machine-specific paths, Modal
app/run IDs and references to raw artifacts are provenance; those paths will not
necessarily exist on a new checkout. Source/model revisions and artifact hashes
are the portable identifiers.

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
