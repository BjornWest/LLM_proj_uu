# Isolated opt-in fact recording implementation

7 October 2026. Owner Inspect; Website owns any live renderer adoption; Harness owns
live AX output and acknowledged-delivery recording. Bjorn authorized implementation
and testing with Website files unchanged unless Website participates.

**The copied recorder and paired provider pass 32 focused tests and 14 browser
state comparisons on two modern pages, including quote/service/address changes.
HTML, AX field values and stored state are identical on/off. All 14 exports also
pass real Harness formatting and scripted retained-delivery extraction. Live
Website adoption and actual model delivery remain unverified.**

## What exists

| Module | Responsibility |
| --- | --- |
| `training/browser_training/assets/fact_render_recorder.js` | Annotated fragments with UTF-16 parts; opaque temporary existing-element anchors; actual text-node/control paths; effective-state snapshots; current connected-node registry and stale-content invalidation. Removes opaque attributes at the synchronous commit before normal agent observation. |
| `training/browser_training/fact_render_overlay.py` | Default-off, byte-identical asset copying; exact-count 16-seam instrumented copy of shared shop renderer; receipts pin original/transformed/helper bytes. No shared Website file writes. |
| `training/browser_training/fact_render_capture.py` | Settled scripted DOM/AX capture, actual backend-node binding and per-part spans; direct AX projection plus explicit unknown diagnostics; pure `ax-fact-sources-v1` handoff to Harness. |
| `scripts/check_fact_render_recording.py` | Accepted finite two-worker saved91 product check: separate runtime/browser/output per case, original/off versus copied/on, default/variant/disclosure states, HTML/AX-field/storage parity. Six captures retained. |
| `tests/test_fact_render_overlay.py` | 16 source/DOM contract tests, including mixed facts in a single text run, stale/conflicting bindings, verified control values and nonmutating Harness packet export. |
| `training/browser_training/fact_source_provider.py` | Default-off provider. `observe(operation)` brackets exactly one existing raw AX capture; checks render/URL/draft before and after; pairs by observation object identity and AX digest. The Harness callback consumes the frozen pair with no additional AX capture. Eight focused controls. |
| `training/browser_training/fact_delivery_features.py` | Offline per-recipient/per-prefix native-part coverage. Revalidates retained requests and exact source/output spans, unions repeats and equivalent state-bound realizations, keeps unsupported/absent delivery unknown. Eight focused controls. |
| `scripts/check_fact_delivery_pipeline.py` | Two-worker saved paired exports → actual AXContext/FactRecorder/PolicyDelivery → native-part features. Scripted acknowledgment and different-recipient controls; no model calls. |
| `scripts/extract_fact_delivery_features.py` | Small saved-trace prefix extraction CLI; JSON retains granular binding, effective state, individual parts and counts for later requirement joins/predictor work. |

Registrations currently cover structured definition/table facts and highlights,
listing price, selected configuration, recipient subfields, quote subtotal/discount/
shipping/total, individual shipment charges, selected service and selected location.
Lists, units and qualifiers retain
separate parts; no per-product selectors or English-label matching determines
identity. Quote occurrences retain the actual projected result and selected service,
not quote ID alone. Captured draft state is not proof that a result belongs to the
newest asynchronous request. The saved browser checks verify the native settled
renderer result/revision and disappearance on invalidation; arbitrary producer or
out-of-order-response behavior still needs its own qualification. Recipient spans
describe recorded address input, while selected-location spans describe the actual
renderer-selected shipment destination; neither is inferred from the other.

A native field or renderer scalar is qualified as such; it is **not** promoted to
an approved assertion ID. Selected-content slots retain their supplied assertions,
but compound assertion-specific prose remains unresolved. Coverage inventories and
model exposure remain unknown until accepted producer/harness joins exist.

## Isolation and source drift

Use an asset-copy overlay rather than a clean HEAD worktree for this phase. Current
project work includes uncommitted dependencies absent from HEAD; copying the pinned
served bytes includes those without committing or modifying another owner's work.
The API returns new byte mappings/source strings and never writes its input. The
browser check intercepts the copied asset only in its own browser context.

Website reviewed core seams in
`.local/coordination/fact-recording-implementation-20261007/Website-seams-v1.md` and
pinned current sources in `Website-seam-pins-v1.json`. No active redesign conflicts
with the copied overlay. A pure frozen-source probe also applies the saved basket,
local-branch and review transformations before the recorder; all 15 seams match and
Node syntax validation passes. This is source evidence, not actual served-browser
acceptance. Receipt: `.local/fact-recording-implementation-20261007/served-source-probe.json`.

Grader-only changes do not enter the recorder. Renderer/payload changes can require
an overlay refresh; seam changes raise explicit errors. Exact seams alone do not
prove compatible meaning or behavior, so eventual live adoption requires Website
review plus actual served-source/state and parity checks. Unsupported mutations
invalidate their bindings; they are not repaired by guessed text matching.

## Validation and next boundary

Small source tests completed: 16 passed. The accepted bounded browser job completed
in 7.024s with two independent workers, four fresh browser contexts (on/off for
each product) and six recording captures. No worlds, models or grades were run.
The browser check imports frozen producer/runtime modules from a separate source
copy and verifies original pins; new Inspection modules come from the live tree.
It uses the native Runtime's physical preview transport, not a model episode or a
logical-origin Harness acceptance.

Initial startup checks exposed missing transitive policy data. The accepted copy
retains all 764 frozen source files and adds 132 exact policy files whose hashes
are already in the frozen catalogue manifest. Original packets/archives remain
untouched; no semantic repair or source-hash bypass occurs. The checker constructs
native BranchRuntime directly, avoiding an unnecessary model-tokenizer profile.
It uses the existing local browser libraries, with no downloads.

| Case | States | DOM runs per capture | Direct AX mappings before opening / after opening | On/off parity |
| --- | --- | ---: | --- | --- |
| Saved91 alternate product | Default, variant, disclosures | 36 | 36 / 36 | HTML, AX field values and stored state all match |
| Saved91 second product (artifact label `winner`) | Default, variant, disclosures | 38 | 5 / 38 | HTML, AX field values and stored state all match |

Closed-disclosure text has real DOM bindings but remains unmapped in raw AX until
opened. Unsupported mappings remain unknown; AX mapping still does not prove
model delivery. Each capture records authoritative actual node paths, independently
checked DOMSnapshot text, URL/state attestation and current revision.

Evidence: `.local/fact-recording-implementation-20261007/browser-v4/`.
Immutable release: `.local/coordination/fact-recording-implementation-20261007/browser-terminal-v1.json`.

Evaluation returned the reserved slot; the saved-only product batch is now
terminal. Inspect explicitly returned slot two to Product's requested <=75s
startup-only recovery window and retains no heavy reservation. Future browser
checks require another coordinated slot. Example fresh output/receipt paths:

```sh
python3 scripts/run_bounded_job.py --memory-mib 4096 --receipt .local/fact-recording-implementation-20261007/NEW-bounded -- .venv/bin/python scripts/check_fact_render_recording.py --packet .local/coordination/task-support-expansion-20261007/branch-stock-inspection-packet-v1/packet.json --output .local/fact-recording-implementation-20261007/NEW
```

The accepted first browser batch validates products/defaults/variants/disclosures.
Its immutable receipts remain unchanged. The continuation in `browser-v7` now
validates three product states and four quote states per page: default quote,
different selected service, edited/unvalidated address and revalidated recipient.
Each ready quote has eight registered occurrences and 15 conjunctive parts;
the invalidated quote has zero occurrences. Native quote IDs can recur after
revalidation, so effective draft/result revision and selected state remain part
of the identity. No credit transfers merely because quote IDs match.

The paired provider uses the existing AX result rather than taking a second AX
tree. It binds DOM/CDP metadata to that exact observation and rejects races,
deep-copied/unwrapped observations and mutated trees. Recording failures return
the ordinary observation unchanged. The opt-in integration caller still must
wrap its actual capture boundary with `provider.observe(operation)`; universal
runner/pipeline installation is not claimed. BrowserGym DOM marking or deferred/
cross-frame capture needs an explicit compatible boundary, otherwise unknown.

`delivery-v1` consumes all 14 saved paired exports through the real Harness
formatter and delivery recorder. Scripted retained acknowledgments earn coverage;
unacknowledged or other-recipient outputs earn none. The two closed-disclosure
product captures retain 33 unknown parts each; opening the disclosure produces
38 complete parts. This measures text transport, not model attention, memory or
semantic task sufficiency. Empty invalidated-quote inventories do not mean that
all task evidence is absent or that there are no task obligations.

Source/export closure: `.local/coordination/fact-recording-implementation-20261007/continuation-terminal-v1.json`.
Both bounded jobs exited zero; slot two was explicitly returned to Product/Website.
Failed driver batches v5/v6 are retained and excluded from acceptance. Current
consumer module pins are in `delivery-v1/result.json`; the older Harness acceptance
receipt remains historical and its former runner/capture hashes are not rewritten.
No runner was invoked. Any future ungraded runner diagnostic must explicitly use
`allow_ungraded` plus a recorded reason under the current Harness contract.

Typical compact private commit sizes measured here are 56,494–62,502 bytes on the
product states and 337,102–495,313 bytes on ready quote states. These include HTML
and duplicated full quote/state snapshots, not just spans. They are byte measures,
not tokens or latency measurements. On-mode deduplication and performance testing
remain useful follow-ups; off mode installs no provider hooks or copied asset.

Example extraction from these scripted saved receipts:

```sh
.venv/bin/python scripts/extract_fact_delivery_features.py --trace .local/fact-recording-implementation-20261007/delivery-v1/alternate/quote_default --step 0 --output /tmp/native-fact-prefix.json
```

Cross-snapshot union requires identical native binding, effective state, part set
and fully mapped realized part text. Unknown mappings stay separate; repeated
reads union intervals rather than multiplying counts. The baseline emits native
rows/counts only. Approved semantic requirement joins, automatic live installation
and evaluation on real policy prefixes remain separate adoption steps.
Broader compound prose/cards/reviews/server-rendered families remain later scopes.

No Website edits or publication are implied by this implementation. Live helper
adoption remains a separate Website-owned step; default deployment stays off.
The earlier one-to-two-week estimate is withdrawn; the target is a small working
slice appropriate to Bjorn's remaining assessment schedule.

## Prospective Git release boundary

Future accepted recording fixes/features must be delivered as owned exact-base
commits with declared changed paths, recorder assets, focused tests and dependency
closure. Main HEAD/index and other owners' dirty files remain untouched. Evaluation
is the sole release publisher; no commit or handoff automatically updates an active
suite or enables instrumentation. The existing acceptance remains evidence for
its original source pins, not a claim that the first frozen address release already
contains all recording/Harness APIs. Current packaging preparation is recorded in
`.local/coordination/fact-recording-implementation-20261007/release-package-handoff-v1.md`;
its patch commit awaits Evaluation's exact first base and isolated commit workflow.


## Prospective native BrowserGym compatibility

A separate Inspect dev revision adds `meta.render_state` to copied-render commits.
Its shared JS attestation compares node types/names, child order, text, ordinary
attributes and live value/checked/selected/indeterminate properties. Only the
pinned BrowserGym `bid`, visibility-ratio and set-of-marks attributes are omitted;
value/checked markup mirrors are normalized against separately recorded live
properties. The installed post-extraction cleanup must restore temporary ARIA
prefixes. Unknown schema versions and shadow roots fail closed. Older exports
retain the strict HTML check. Disabled instrumentation still performs no recording.
This qualifies current control state, not default/reset semantics.

`check_fact_render_recording.py --capture-mode browsergym` prepares validation
using the installed native marking/DOM/merged-AX/cleanup functions. It brackets
one extraction and adds no second AX tree inside the provider. Use
`--browser-workers 1` under the observed256-PID startup dependency; the two saved
cases remain isolated and run sequentially. This diagnostic does not invoke the
runner, task grading or models. Full runner integration still needs the separately
owned Harness provenance Git closure and its own acceptance. Source preparation
and a Git candidate do not claim native browser acceptance, producer assertion
qualification, live Website adoption, general task exposure or policy attention.


The first native diagnostic candidate22367312 completed source checks but failed
both saved journeys at quote invalidation; ten earlier mapped captures are retained,
with no complete parity/native adoption claim. An additive source fix binds the
live read to the export available after pending private callbacks are dispatched.
It uses the same page read and rejects changed scope/version or a later mismatching
snapshot. Six source regression cases cover callback delivery and unsafe races.
This is consistent with the observed failure, whose actual mismatching live state
was not retained; a corrected browser diagnostic has not been run. Preserve the
original candidate/captures/terminal and do not automatically retry it.

## Per-prefix retailer/review development extension

The copied native-rich review classes are constructed with
`fact_review_overlay.copied_review_classes` from two explicitly hash-pinned
renderer source strings. The shared modules/classes/files are never replaced.
Install the returned classes only in the separately copied Runtime. Three native
layouts retain the original complete HTML after opaque private anchors are removed.
The private collector annotates model fact label/value nodes, separate counts
sharing a paragraph, histogram cells and canonical opinion text. Model aggregates
remain over all options/silent ratings even when comments are filtered or paged.
Legacy inline comments, review card summaries and star aria-label bindings remain
unmapped. The root selector/state kind are explicit (`#main`, static review);
retailer recording retains `#app` and actual stored state. Disclosure toggles and
form changes refresh private render attestation. No screenshots or model attention
are inferred. Source/fragment tests are not native browser acceptance.

`extract_fact_delivery_features.py --all-prefixes --trace TRACE --output NEW.json`
replays each retained policy receipt separately. An append-order `model_started`
boundary plus the matching retained `model_completed` request freezes the eligible
capture inventory, rather than trusting `capture.step <= request.step`. Missing or
ambiguous lifecycle joins yield unknown inventory. Later receipts at the same step
remain excluded by receipt ordinal. Worker lifecycle boundaries remain unsupported;
they never borrow the main-agent boundary. `--step` retains the older explicitly
labelled step-grouped diagnostic, not an exact request inventory.

Optional `--task FORMAL_TASK.json` adds the bounded comparison/review projection
from the approved `website-catalog-compare-review-task-v1` obligations. Direct
retailer model fields require exact subject/field/unit scope; compound selected
slots require complete transport of the whole slot and an explicit scoped scalar
record. Partial compound reads cannot identify which constituent fact was read.
All five labelled histogram counts from the same model/corpus state support the
exact rounded mean dependency; partial or conflicting states do not. Topic
classification dependencies, unbound measurement bases, unknown/NA declarations
and unsupported meanings stay unknown. This is dev semantic-role preparation;
complete trusted task/world/source bindings and actual public/runtime acceptance
must precede its use on a policy episode.

Harness dependency release is separate: reviewed compatible commits `4ade66e` then
`2372f922` rooted at `cdb28444`. The copied observer uses native capture only
(`observation_pipeline=None`) and preserves original observation identity. The
previous failed candidate `22367312` and native diagnostic are immutable evidence;
new callback-ordering and navigation/root fixes have only source tests until a new
explicit bounded integration window is accepted. The one authorized Sol episode
has not launched and has no automatic retry or redraw.

The formal CLI binding requires `--task TASK --requirements required-obligations.private.json`
together. Validate byte-file hashes and the exact native role list before
projection; never rewrite obligations from the user prose. A staged integration
amendment preserves the actual `site_id` (friendly names are not identities) and
adds a private copy of `surrounding.mount` so renderer classes are selected before
hosts bind `view.page`. Merely replacing `runtime.surrounding_views` afterward
would leave the original bound HTTP handler active. Install that private module
only in the copied Runtime's namespace before construction as
`copied_Runtime_namespace['mount_surrounding'] = private_mount.mount`.
The inherited Runtime imports that callable directly; its `surrounding`
constructor parameter is the sidecar, not a module installation point. This amendment is
packaged as f31a9501 with60 frozen owned-source controls. Candidate47e9868f
remains immutable; integration must use the reviewed amendment and its separately
released Harness/Website dependencies.

The staged amendment also distinguishes a retailer's `page_id` from its
`canonicalProductId`. Native task/product joins use the latter; selected SKU and
page identity remain separate state fields. The older source-only candidate used
page aliases as product IDs and is not eligible for native composite adoption.
The corresponding Node source regression uses different page/model IDs and
checks their preservation. No actual episode was recorded with the incorrect
join. Public semantic readiness still requires an actual auditor/receipt; the
Website readiness envelope alone does not establish that required facts occur
in accessible public pages with their units/qualifiers.


## Public capture audit and review script transport

`fact_public_readiness.audit_captures` consumes saved normalized DOM/AX captures
and the exact native task/reference, with the actual Runtime publication digest.
It validates hashes, document/frame identities, complete UTF-16 part mappings,
rendered values, explicit typed scalar/whole-slot assertions, printed count labels
and same-corpus all-rating histogram dependencies. Evidence points to immutable
public capture files and occurrence locators. A missing public value cannot be
satisfied by the oracle. Unknown/NA declarations, topic classification and
unbound qualifiers remain unresolved. This is a bounded producer-contract audit;
authored JSON controls alone cannot authenticate an actual public runtime. The
caller must supply a separately pinned, real browser capture closure. Audit
captures establish source availability and never become policy delivery receipts.

Native review hosts permit same-origin scripts while refusing inline execution.
The copied review class therefore serves one private JavaScript asset at
`/__fact-recorder-private.js` and embeds only inert JSON plus an external script
reference. The disabled class retains its original routes. No shared Host CSP,
Website source file or global module is changed. Native browser qualification
remains pending; source syntax/HTML preservation controls are preparation only.


The frozen source check scope also includes the retained
`tests/test_fact_render_attestation.py`: legacy versus structural validation,
exact selector/key/static callback configuration, schema-first rejection and
content/control mutation checks. Lifecycle/recipient-delivery tests additionally
require the separately released Harness bundle and must run against the integrated
candidate before any native/Sol acceptance. Earlier narrower test counts remain
immutable historical receipts.


Direct scalar auditing follows the exact retailer display contract: native
booleans become `Yes`/`No`; numbers use JavaScript `String(Number)` formatting
after JSON transport. A cached local Node conversion handles integral floats,
small/exponent values, negative zero and shortest decimal output rather than
guessing JavaScript output with Python `str`. This work is offline/audit-only and
adds no browser Harness bookkeeping. Native arbitrary-precision integers beyond
JavaScript's exact integer range remain unresolved. Numeric JSON representation
may change between int/float; booleans and strings never coerce into numbers.
