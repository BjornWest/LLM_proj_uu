# Dataset expansion

This directory contains new task integration work for general browsing. It does
not replace historical curated catalogs or certify all upstream benchmark tasks.

See the [work plan and acceptance rules](../../../docs/agents/dataset-expansion.md).

- `webarena/`: original WebArena-Verified tasks and validation tooling.
- `tricky/`: original Tricky tasks, site audit and validation tooling.
- Parent review records and coverage summaries will distinguish source candidates,
  runnable tasks, scripted validation, independently accepted tasks and model runs.

Generated screenshots, HTML, HAR, traces and bulk source copies belong under
`.local/curation-expansion/` (ignored), not in this tracked directory. Retain
small contracts, code, reports with artifact hashes, and explicit unknowns here.

## Find an accepted development task

This command reads local contracts and independent reviews; it launches no browser
or model. It excludes held tasks and keeps original and authored instances distinct.

```bash
python3 -m data.curation.expansion.accepted_index --summary
python3 -m data.curation.expansion.accepted_index --dataset webarena-verified --site shopping
python3 -m data.curation.expansion.accepted_index --dataset trickyarena --kind draft
python3 -m data.curation.expansion.accepted_index --origin original
python3 -m data.curation.expansion.accepted_index --task tricky:AU47 --json
python3 -m data.curation.expansion.accepted_index --output .local/curation-expansion/my-task-selection.json
```

The JSON index includes contract/review paths and hashes, task IDs, site, goal,
source type, and coverage limitations. Expected answers stay in the private source
contracts, not the index. This is **discovery metadata**, not a replacement for the
hosted registry, a runnable model sweep, or authorization to spend inference funds.
Use the referenced adapter and its response-format instruction together; freeze a
new execution profile and preflight the actual runtime/site before model use.
Source graders and historical task contracts remain unchanged by index generation.

The first saved selection is `.local/curation-expansion/accepted-discovery-v1.json`.
It records81 Tricky tasks (21 original,60 authored) and20 original WebArena tasks.
Later selections need a new output path. The mutable progress board is available at
<http://localhost:8876/dataset-expansion/>.

The second snapshot, `.local/curation-expansion/accepted-discovery-v2.json`, records
the completed Tricky milestone:100 instances (21 original +79 authored,60 authored
template IDs), plus20 WebArena originals. Previous snapshots are historical.

Snapshot v6 records100Tricky +49WebArena tasks. The WebArena set includes six
original tasks with **derived verifiers** (biography399 and coupon drafts689–693),
separately marked in discovery metadata. Native-only acceptance is not implied.
For precise current counts, use the CLI summary and `progress.json`.

## Export implementation bindings for a later sweep

```bash
python3 -m data.curation.expansion.sweep_inputs \
  --task tricky:AU47 --task webarena:334 --task webarena:689 \
  --output .local/curation-expansion/NEW-sweep-inputs.json
python3 -m unittest data.curation.expansion.test_sweep_inputs
```

Omit `--task` to export all currently accepted rows. This reads code/contracts and
creates an exclusive new JSON file; it launches nothing. Each row binds an exact
policy goal and response instruction to existing adapter symbols, reviewed source
files, setup/isolation rules, and grading timing. Only `policy_input` belongs in
the agent prompt. Seven state-only Tricky tasks intentionally retain a null
terminal override, matching their saved runs; do not replace it with an invented
answer convention.

Native WebArena HAR grading runs after context close, unlike the derived Tricky,
biography and coupon runtime checks. The exporter keeps those phases distinct.
It does not turn saved acceptance into current-source certification or spend
permission. Freeze the full transitive runtime/site closure, resolve the actual
service/account and select an explicit step cap before a new model cohort.
`new_execution_ready`, model-tested and training flags remain false. The first
whole export has169 rows at
`.local/curation-expansion/sweep-inputs-169-v1.json`.

Use schema-v2 snapshot `.local/curation-expansion/sweep-inputs-169-v2.json` for the
current binding example. The earlier v1 export is superseded: v2 keeps the optional
copied runtime for **new** adoption separate from actual historical execution
identity, and resolves WebArena step caps from each reviewed case profile (50 or
100), rather than leaving them unspecified. Seven export/projection checks pass.
Neither snapshot has triggered an inference run.

Schema-v3 snapshot `.local/curation-expansion/sweep-inputs-170-v3.json` supersedes
v2: the seven derived WebArena bindings explicitly require frozen-runtime
activation before imports; AU01–AU20 retain their actually tested24-step cap.
Task407 adds a final-vote binding with full isolated reset and chronology checks.
Historical adapter/module source and original output files are preserved; the
export still does not execute a sweep or establish current readiness.


Current reviewed discovery:100Tricky/82WebArena instances,81/25 templates.
Snapshot: `.local/curation-expansion/accepted-discovery-v12.json`;
bindings: `.local/curation-expansion/sweep-inputs-182-v3-normalized.json`.
Task/template IDs are normalized strings in discovery; `raw_template_id` retains
the contract serialization. Original contracts and older exports are unchanged.
Biography400–403 use their own19089 factory and the mandatory copied baseline;
scripted warming is documented, not a fix for cold-route navigation warnings.


Latest:100Tricky/97WebArena instances,81/28 templates. Discovery v13 and
`sweep-inputs-197-v3.json` supersede the82-task exports above. Forum posts add15
originals with independent final-state review; retained cases use several pinned
driver versions. Current bindings name v7/v3 explicitly and require new preflight.
No model capability or general reset readiness follows from scripted acceptance.
