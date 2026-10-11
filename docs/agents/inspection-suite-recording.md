# Optional suite recording

The inspection package supplies provider-independent private DOM recording and
recipe-bound task compilation. This is an opt-in development feature. Keep the
suite's native task/world/recipe/root, grader, original environment factory and
policy profile. Do not update running suites or rewrite historical traces.

## Runner connection

Pin `scripts/load_suite_inspection.py` before importing it, and provide an
immutable Git package root plus the complete package-relative SHA256 map for
`training/browser_training/*.py` and `assets/*.js`. The loader checks bytes
before executing modules, loads source rather than bytecode, and uses a fresh
private package name. It does not replace native `training`, `environments`,
`intent_browser` or `scripts` modules. Released-package functions must not be
retained for later calls: reload a checked private package for subsequent offline
compilation or projection.

```python
from scripts.load_suite_inspection import load_recording  # independently pinned loader
module, sources = load_recording(inspection_package, approved_relative_sources)
run = module.recording_runner(
    native_run_episode,
    enabled=True,
    expected_sources=sources,
    report=case_output / 'inspection-status.json',
)
try:
    return run(original_factory, backend, metadata, **native_options)
finally:
    module.release_package()  # after all uses of this private case package
```

Install this wrapper where Evaluation already passes `episode_task.make_env` and
attached `AutomaticGrading` to the native runner. Create one wrapper per episode.
No pre-construction renderer installation is required. Disabled recording returns
the original callable. A failed optional setup calls the original runner once;
a failure after policy startup never causes a second episode. Unsupported profiles,
checkpoint/delegation/handover modes and explicit progressive pipelines fall back
without changing native options. A non-class task entrypoint leaves the original
environment usable and disables recording without closing or recreating it. Inspect the
wrapper's `recording_status` as well as its optional exclusive-create report;
report-write errors cannot replace a native task/transport outcome.

The enabled path installs the provider before native task setup, uses the
released original-capture callback and sets `observation_pipeline=None` for the
qualified native full-capture boundary. Progressive/deferred observation caches
are outside this acceptance. Native grading and policy limits stay attached.
The native pipeline is unchanged, although its runtime-selection diagnostic is
recorded as explicit `None` rather than the caller's `native` selector.
`metadata.inspection.source_sha256` records the separately checked inspection
closure; it does not replace the native grader's existing source union.

## Asset and capture boundary

The private evaluated probe uses cached public retailer modules, existing DOM
nodes, current configuration and original local state. It records exact UTF-16
parts and selected variant/quote state. It does not replace served assets, insert
fact text or context, edit websites, trigger producer refresh or edit storage.
This preserves atomic tasks' served-asset checks. Successful cached quotes are
queried with cloned state; producer fetch/ensure/refresh methods are not called.
Evaluated probe/recorder bytes are hashed before use; the attestation function is
extracted eagerly from those same pinned recorder bytes. No renderer callback
binding or page global is installed. Release each case package after use to avoid
accumulating private import finders/modules in a suite process.

`native_fact_recorder.js` is a private copy of the existing recorder with the
`adopt(..., options)` control-value fix. The historical recorder remains unchanged.
The old overlay installation is a separate capability; its tests and model traces
do not establish parity for this new probe. Registrations remain producer-qualified
bindings, not new Product assertion identities.

Supported direct probe fields include product name/listed price, currently
rendered exact native fact rows, selected-option labels/values, address controls,
existing successful quote scalars/services/locations/cart lines, and native review
comments/ratings and rating-count summaries. Ambiguous or missing matches remain
unresolved with explicit reasons. Review summaries remain model-wide even on
SKU-filtered pages. Directory/research/empty documents have a qualified body root
and may legitimately emit zero registrations. Screenshots, full comparison
population, review histograms, carrier pages, source menus, arbitrary prose,
private outcome proofs and exhaustive unvisited-page mappings are not established
by this probe. Absence of a registration cannot establish a negative predicate.

## Compilation and offline prefixes

`compile_suite_task` delegates established schemas to the existing RL inspection
compiler and adds exact native inputs for atomic/link tasks and the two cart
instances. Factories must come from the case's checked frozen native root. Link
acceptance must be validated by its original native capability validator.

New-additions cart instances reserve existing units and rank only added item
subtotal. Existing-cart checkout instances do not introduce product search or
new-unit coverage. Their actual target carts, unchanged quantities, public memories
and delivery-selection scope remain distinct. Native truth and a compiled obligation
are neither public disclosure nor policy delivery. Field/quote declaration hashes
resolve under the exact imported native producer root independently of the
separate inspection package location.

`build_inventory` accepts pinned original-task and compiled-program documents,
plus recorded captures. It retains every required information-need template,
records exact source witnesses and scoped configuration/quote joins, and gives
unmapped templates explicit reasons. An unresolved task role, declaration or
subject cannot be satisfied by an arbitrary occurrence of the same field. Such
templates remain unknown until a scoped semantic adapter resolves them. Exact-ID
matching and producer display hints alone are supported by this minimal inventory.
Malformed occurrence/state contracts are rejected with an explicit validation
error instead of guessed coverage. Its inventory feeds the existing
`replay_model`/`scripts/replay_task_model_prefixes.py` reader. It is partial to the
captured public scopes: compilation of all suite tasks does not imply complete
field coverage. Use `unknown` for unresolved mapping/delivery; `not_observed` is
valid only once a target source is resolved and receipt evidence excludes delivery.
Do not infer attention, reasoning correctness, action completion or reward from
capturing a source. Native state/terminal outcomes use their existing separate
adapters and grader proofs. The successful-full-extraction visibility assumption
remains an explicitly labeled alternative to strict receipt evidence.

## Acceptance

Evidence for the Luna34/Qwen-ready preparation lives under
`.local/coordination/inspect-luna34-wiring-20261011/`. Scripted zero-provider checks
validate native startup/capture independently of model results; an original
atomic native-runner check includes actual PolicyDelivery, native automatic grade
and canonical reader projection. A scripted task failure can still establish
recording/transport integration when it completes technically and grades correctly.
The existing Luna launch predates this hook. Do not inject it into that in-flight
release or claim retroactive fact delivery. Evaluation owns future adoption and
provider/host acceptance, including the complete frozen viewer dependencies.
