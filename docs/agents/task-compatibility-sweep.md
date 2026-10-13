# Task compatibility and schema sweep

Use one fixed source release and its immutable asset closure. This tool measures
applicable configuration interactions from a finite, explicitly declared pool.
It does not prove that every advertised combination is implemented or feasible.
Keep native inspection, ordinary preparation, scripted lifecycle and real-model
performance as separate stages.

## APIs

`task_compatibility_sweep.select_cases(candidates, limit=200, seed=0, triples=())`
accepts rows containing an opaque ID, named JSON-valued factors and a task
instance. It covers applicable factor pairs and selected triples, then fills the
remaining budget with seeded diversity. Prose-only duplicates do not count as
new native configurations. The pool is the coverage denominator; unsupported
combinations must remain visible in execution results.

`run_native(selection, fresh_output, workers=2, prepare=True, share_assets=True)`
uses actual `task_instances.inspect`, `task_instances.prepare` and the ordinary
source freezer. It does not mock references, source collection or world reads.
Every case has a separate directory and retained stage result. Preflight holds and compaction have separate stages, preserving successful preparation receipts. An exception
means triage, not necessarily a model failure or an unsupported task family.
The returned report distinguishes design coverage from passed stage coverage. A pair with one passing case is not universally accepted: mixed/failing pairs are explicit, and attempted preparation pairs count invoked freezes only. Factor labels remain caller supplied, not authenticated against native parameters.
Use the repository bounded launcher for these batches.

The 1 GiB free-space preflight records a structured `held` result before freeze. It does not
reserve disk atomically across workers. Budget the simultaneous temporary
copies as well as completed recipes, and do not erase failed outputs.

`compact_prepared(completed_preparation, separate_store)` shares exact bytes
and file modes through a SHA256-addressed hardlink store after real preparation.
It rejects unfinished preparations and symbolic links. Supply only new owned
outputs: this API does not establish file ownership. Keep these files immutable;
hardlinks do not enforce immutability, and manifest/hash validation remains
mandatory before reuse. Neither historical evidence nor running recipes should
be written through shared links. Corrupt existing entries fail closed.

`task_schema_audit.audit_schema(schema, expectations=...)` validates JSON Schema
and reports wire types, enums, required fields, closed objects, and nullable
value/evidence pairs. Expectations use exact schema pointers. Use `nullable` and `unmatched_option` flags to audit reserved choices; ordinary `choices` excludes both. Missing special-choice flags leave that policy unaudited. A categorical
expectation requires the complete public declaration domain, never private
winners or the sampled merchant menu. A missing wire restriction can still be
enforced by a post-extraction mechanical validator; report that distinction.

`audit_grader(grader, observations=..., expectations=...)` binds the actual grader
class, code hash, response contract and extraction-instruction digest. The file hash covers the defining class module, not all delegated dependencies; the enclosing release must bind those. Expected verdict mismatches are audit findings. It exposes
native checks emitted by correct/wrong/missing/malformed controls. Reference to
grade roundtrips do not independently prove population scope or oracle validity.

`task_compatibility_controls.controls(...)` constructs supplied structured answer
fixtures for feature offers, priorities, shortlists, basic offers, statistics and
product reviews. It intentionally uses private references. Use an offline
JSON-copy formatter to test lifecycle wiring; do not claim extractor prose
accuracy or public solvability from these fixtures. Money fixtures preserve
integer minor units through Decimal arithmetic.

## Initial retained experiment

Evidence is under `.local/coordination/task-compatibility-sweep-20261013/`.
The source base is `821682b1f8ced6b76afc0850ed26c7073f7a3eb8` with its exact
R20 asset closure. `selection-v2.json` retains 200 selections from 2,007 finite
configurations, spanning ten instance adapters, five concepts and saved worlds.
Its human request edits preserve native parameters. Full declared-pool pair
coverage is not full runtime acceptance.

The initial native sweep passed 193 configurations and rejected seven tablet
reference-mass priority cases because the declaration does not supply the
measurement-basis metadata required by that ranking constructor. Keep these
failures; do not substitute the footwear basis. The pool heavily exercises
interval boundaries/no-match cases. Four additional public interior-size cases
exercise successful feature/priority recommendations without editing worlds.

The initial audit ran 356 supplied controls on 178 configurations; 106 offer-family negative fixtures were empty selections in no-match worlds. That is retained historical wiring evidence, not broad discrimination coverage. The corrected audit uses concrete real offers for no-match counterexamples, and adds wrong SKU, currency, real nonwinner, aggregate, mean, direction and citation mutations where applicable. Two interior supplements are positive priority selections and two are feature selections. The corrected offer audit has priority24no-match/2match, shortlist57no-match/13match, feature25no-match/6match configurations. Five basic-offer configurations have an additional actual native audit. Capture-dependent families remain separate. No-match negatives may fail on expected status even with concrete rows; do not infer independent eligibility/ranking coverage from that branch. Count fields and many categorical variant choices already have
wire types/enums. Some numeric variant values and decimal aggregates remain
strings; decimal validators and literal evidence checks are separate from wire
types. Nullable pairing findings indicate a validator dependency, not absent
validation. Topic-only contracts need not grade unused rating-mean fields.

All 30 scripted browser controls pass, spanning ten configurations across five answer families,
with correct/wrong/missing controls, actual BrowserGym, automatic native grading,
canonical artifacts and live local HTTP projection. The original disk preflight holds are retained; only unstarted cases continued after duplicate-file compaction. Completed episodes were reused without rerun. Consult final receipts for exact stage/source bindings. The current experiment
contains no real model calls and no newly sampled worlds. Fresh-world diversity,
all capture-dependent families, delivery/hidden/memory combinations and real
extractor interpretation require additional coverage; they are not implied by
a successful saved-world preparation or supplied-answer control.
