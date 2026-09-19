# WebArena task expansion

**Final review snapshot:** 103 accepted original tasks / 30 upstream templates on
shopping and forum sites. See [review guide](../dataset-expansion-review.md) for
current scope and limitations; counts below are historical batch records. Further
adaptation and Maps/Wikipedia provisioning are paused at user request.

Owner: curation WebArena worker. No shared harness, site source, production catalog,
or existing database is modified. This is original-task development and scripted
verification, not model evaluation or training certification.

## Inventory and first batch

Pinned source: `ServiceNow/webarena-verified@6473f72db5dcefc97b5725b59e734504edc28a21`.
Cached dataset SHA256:
`d65275660814663375028e9017e1f929e3c38321041b125795e2713b52243d30`.
The installed native evaluator is `webarena-verified==1.2.3`; its bundled code
license is Apache-2.0. This does not establish licensing for every original site's
images/content; retain separate upstream site notices.

The cache contains **812 task IDs / 190 templates**. The two existing full sites
(shopping and forum) support the dependencies of **298 IDs / 70 templates**;
**137** of those are retrieval/navigation candidates. These are inventory counts,
not validated-task counts. Five of the 298 require both sites.

First batch: ten IDs from ten templates:

| ID | Site | Original task/capability |
|---|---|---|
| 21 | shopping | Read reviews, identify reviewers describing small ear cups, paginate |
| 27 | forum | Find newest personal-finance post, author and qualifying-comment count |
| 66 | forum | Inspect the ten hottest books posts and identify single-book recommendations |
| 96 | shopping | Retrieve latest order status and delivery-date availability |
| 117 | shopping | Find first purchase date through account/order history |
| 158 | shopping | Navigate to Nintendo game-card storage fitting eleven cards |
| 163 | shopping | Read and filter product review titles by rating |
| 188 | shopping | Retrieve the latest cancelled order's total |
| 260 | shopping | Navigate to the Video Games category |
| 324 | shopping | Search chairs and sort by ascending price |

The generated inventory keeps exact goals in `policy_input` and upstream
expectations in separate `grader_input`. Its readiness fields are unknown until
there is evidence; source availability is never a browser pass.

## Reproduction

From the project root (each output path must be new):

```bash
python3 data/curation/expansion/webarena/inventory.py --output .local/expansion-webarena/inventory-new
PYTHONPATH=. python3 data/curation/expansion/webarena/propose_candidates.py --output .local/expansion-webarena/candidates-new
.venv/bin/python data/curation/expansion/webarena/browser_batch.py --output .local/expansion-webarena/browser-new
.local/webarena-verified/venv/bin/python data/curation/expansion/webarena/grade_saved.py --browser-report .local/expansion-webarena/browser-new/report.json --output .local/expansion-webarena/native-new
python3 -m unittest data.curation.expansion.webarena.test_inventory -v
```

Browser runs require coordinating use of the shared local sites, currently
`http://localhost:7770` and `http://localhost:9999`. No model, search, or cloud calls
occur. Each task gets a fresh BrowserGym context; HTTP methods other than GET/HEAD
and off-origin requests are blocked. Trusted upstream synthetic auto-login headers
are supplied during setup. This is **not** a full database reset, nor a general
proof that all GET endpoints are side-effect free. The selected scripted paths
are read-only and never activate subscribe/vote/cart/save controls.

The unchanged runner and ordinary parsed BrowserGym actions create exact saved
observations, screenshots, action/error history and a full HAR. The driver is
explicitly privileged DOM-assisted scripted code; it checks selected BIDs against
delivered AX, but answer extraction and semantic selections are test assistance,
not evidence a model can solve the tasks. Task158's narrowed brand search is a
hand-selected reachability test, not an autonomous product-comparison solution.
Task66's recommendation candidates are hand-selected and their posts opened.

The driver uses the legacy action protocol, a 120,000-**character** AX ceiling,
50-step limit, 100ms slow motion and one-second pre-observation delay. This
establishes browser/site feasibility with wide observations, **not** compatibility
of every task with the latest native-tool/context profile or its token budget.
That separate adoption/profile gate is required before teacher comparisons.

Native evaluation is offline after the browser closes and flushes its HAR. The
runner's original unknown evaluation is never rewritten. Retrieval responses are
derived from retained page data. Wrong-answer negative fixtures contain an empty
answer array; navigation negatives remove required-path requests from otherwise
valid HARs. They are **derivative verifier controls, not negative browser runs**.
Broader authorization and safe success remain unknown.

## Coverage expansion and isolation

`propose_candidates.py` produces a provisional 100-ID queue across shopping (40),
forum (30), and map (30), representing **90 distinct source templates**. It favors
new templates before another instantiation. This is a planning queue, not an
accepted dataset; map provisioning, task semantics, and reset gates still apply.

Map has 109 single-site IDs / 29 templates, including place lookup, coordinates,
contact information, nearest facilities, route planning and time/distance
comparison. Ten first-map candidates are 70,248,253,369,377,16,36,52,98,363. Map
plus Wikipedia has additional dependencies; do not count them as single-site-ready.

ShoppingAdmin has 182 single-site IDs / 41 templates. It broadens widgets and
reporting, but its customer-record/inventory workflows are retailer work, not
consumer assistance. Candidate diagnostic IDs are included separately, requiring
an explicit relevance decision before they enter the primary consumer dataset.
Parent owns provisioning; this worker downloads no site assets.

Mutation tasks on the shared applications remain blocked. Container restart or
`env-ctrl init` does not reset the database. Use isolated copied/pinned containers
with independent volumes and an evidenced seeded restore/reset; authentication
contexts alone are insufficient. Parent is preparing that infrastructure. Do not
reset the backend agent's active sites or reuse historical certificates for a new
source/runtime.

## Findings and evidence discipline

Development attempts remain in `.local/expansion-webarena/browser-batch-01*` and
matching native directories. Locator mistakes (accessible names with icon
prefixes, forum names formatted `name — name`, duplicate hidden pagers) are driver
bugs, not model failures. Review content may contain duplicate imported reviews
and doubled author names; retain raw evidence before explicit answer deduplication.
The initial review heuristic falsely matched small instruction typography, which
is preserved in the failed answer/native grading.

Task324 initially stopped after choosing the Price field while the live control
still offered **Set Ascending Direction**. Its native failure was correct. An
early coordination hypothesis that default ascending was rejected was withdrawn
after checking exact AX; do not cite that hypothesis as a grader defect.

BrowserGym's historical 500ms press/click timeout can report an action error even
when navigation completed. Such attempts retain their native outcome separately
and do not pass the zero-action-error browser gate. Original error traces and
failed development negative-HAR controls are retained. No automatic retries or
silent scoring repairs occur.

Final per-task evidence and independent acceptance decisions belong in the
parent's acceptance report. These scripts alone never set `training_ready=true`.

## First-batch result — 2026-09-19

Review index: `.local/expansion-webarena/first-batch-review-v1/report.json`.
All ten selected tasks have a zero-action-error scripted positive and native
positive/negative-fixture pair (10 pass, 10 intended fail). That is ten source IDs,
ten templates, and two site contexts. Independent acceptance, negative browser
paths, current native-profile adoption, database-reset coverage, authorization,
and model performance are **not** established by this result.

The first eight completed cases are indexed from original per-case reports in
`.local/expansion-webarena/browser-batch-02-recovery/report.json`; the corresponding
native grades are in `native-02-recovery/report.json`. That index was reconstructed
because the ninth case (260) hung inside the ordinary click for over three minutes.
One SIGINT did not return. The own process subtree was subsequently terminated,
with incidents retained under `browser-batch-02/hung-task260-*.json`. The partial
original episode stays incomplete and was never relabeled a success; stack
attachment was unavailable. Root cause remains unknown.

A new bounded per-case process run completed260 and324 without action errors:
`browser-bounded-03/report.json` and `native-bounded-03/report.json`. Task324 passes
after actually activating its Ascending Direction control. Eight cases predate the
wrapper's diagnostic signal handler and two follow it; original per-case source
hashes remain distinct. No claim of a single frozen whole-batch runtime is made.
Use the bounded wrapper for future scripted batches:

```bash
PYTHONPATH=. .venv/bin/python data/curation/expansion/webarena/run_bounded.py --output .local/expansion-webarena/bounded-new --case-timeout 120
```

The wrapper confines timeout termination to its own process group and retains
partial evidence. Its latest SIGUSR1 diagnostic targets only its Python child;
SIGTERM/SIGKILL target the owned group. Seven offline tests now pass, including completion, preservation of an existing
log before dispatch, invalid timeout rejection, and actual termination of an owned
descendant which ignores SIGTERM after its leader exits. This validates the process
boundary; it does not explain the underlying browser hang.

## New native-profile follow-up (separate evidence)

`native_case.py` and `run_native_bounded.py` reuse the actual `core-tools-v3`
profile (native calls, compact feedback, reasoning replay preserved, fresh
observation hook), with offline `httpx.MockTransport` responses and zero network
model calls. The observation ceiling is 48,000 characters. This is a new profile,
not a relabeling of the legacy first batch. A still newer v4/v5 harness increment
may exist concurrently; these records explicitly identify v3.

Actual wrong-answer browser episodes and correct-destination-then-home episodes
are under `native-browser-negatives-v1` and `native-browser-navigation-v1`; native
grades are in their separate `*-grade-v1` directories. All ten intended negative
outcomes are rejected by native grading. In particular260/324 do **not** reproduce
an ever-visited loophole: both correct-then-home traces fail. Upstream
`network_event_evaluator.py` explicitly uses the last navigation event for navigate
tasks. This does not establish that every mutation/checker has final-state coverage.

Some runs retain500ms navigation/action warnings. The task96 negative's conservative
all-module guard saw changes in `harness.py` and `feedback_presentation.py`; its
observed native failure is preserved, but it cannot close frozen-source acceptance.
Subsequent task298 pairs saw `cli.py` changes. Source diffs do not automatically
prove that runtime behavior changed: this is a conservative closure rejection.
Final certification awaits the coordinated stable-core window or snapshot.

`extra_driver.py` and `native_case_next.py` add ten more original templates:
231(cancelled-order number),298(completed-order details),358(shipping method),
274(search results),386(product rating),399(biography),404(upvote newest post),
595(forum subscription),640(create notice),731(edit own post). The first five use
read-only shared shopping. The last five can write only the isolated forum at
`http://localhost:18999`, with explicit wrapper authorization. Both successful and
wrong-value paths are real browser actions. They deliberately leave changed
isolated data; reset coordination is required before a new seeded cohort.

These scripted response envelopes are not proof of a teacher-ready final-answer
protocol: the future model-facing adapter must declare the native structured
response schema without leaking expected answers. The original task goal remains
unchanged and retained separately. Native HAR passes alone never establish absence
of other side effects.


## Twenty-task native closure and exclusions — 2026-09-19

Final independent-review input: `.local/expansion-webarena/review-20-v1/report.json`.
It binds 2,518 artifact hashes covering **20 original task IDs / 20 templates /
two full site contexts**, 40 real positive/negative browser cases and one
additional adversarial history case. There were zero model-network calls.
All 40 paired cases used `core-tools-v3` with identical core module hashes,
per-process before/after guards, fresh observations, and declared structured
terminal response fields. The newer `native_case_next.py` protocol fixes the
previous scripted envelope's schema declaration prospectively; old evidence is
unchanged. The coordinated core hold was released after browser execution.

The review index deliberately distinguishes:

| Status | Tasks | Meaning |
| --- | ---: | --- |
| Scripted pair validated, independent review pending | 14 | Both native outcomes match and no action warnings |
| Scripted pair with action warnings | 4 | Correct native outcomes, but 500ms action/navigation warnings retained |
| Wide-observation-only | 1 | Task595 requires a separately labeled observation setting |
| Blocked native final-state false positive | 1 | Task399 excluded from accepted counts |

No task is promoted to training-ready or authorization-safe by this index.
Positive scripted reachability is not a model capability result. Task158's
"best" wording remains underspecified and its driver uses a hand-picked candidate;
task386's native answer expects the displayed percentage (65), not the equivalent
3.25/5 rating. Those are explicit review flags.

The cohorts are `native-closure-first10-v2`, `native-closure-extra9-v2` and
`native-closure-595-wide-v2`; separate native grades have corresponding
`*-grade-v2` directories. Warnings occur in 27-positive, 66-positive, 96-negative
and 358-positive. The held run does not make these zero-error cases.

**Task399 must remain excluded.** The adversarial episode first saves the correct
biography, then saves a wrong biography and reloads the profile. The wrong final
value persists and the intended value is absent, yet native grading returns 1.
The case has zero action errors. Evidence is under
`biography-history-negative-v1/case/report.json` and
`biography-history-native-grade-v1/report.json`. The upstream check accepts an
earlier matching event (`last_event_only: false`); this is a final-state coverage
hole, not evidence of successful current biography. Preserve its raw score. The
parent owns a separate scoped outcome check; this expansion does not patch or
relabel upstream grading.

**Task595 needs observation review.** At the standard 48,000-character prefix,
the visible Subscribe button is missing from delivered AX. The saved full AX is
79,587 characters and the control begins at character offset 78,778; its recorded
visibility is 1.0 and its bounding box is on-screen. A separately labeled
120,000-character run completes both positive and negative cases without action
errors. These are character counts, not token measurements. See
`task595-observation-gap-v1.json`; increasing a limit is not claimed as a general
solution for context delivery.

The forum database was reset by the parent before the final retrieval/mutation
cohort: `.local/curation-expansion/infrastructure/reddit-reset-for-batch2.json`.
Each case has a fresh browser context, but the database is shared sequentially
within the cohort, not reset for every case. Mutation negatives deliberately
change state; the isolated forum18999 is now mutated and quiescent. A new seeded
cohort needs coordinated reset. The shopping paths remain read-only rehearsals
against7770; no broader authorization coverage is inferred from those routes.

Current owned scripts are also preserved in
`.local/expansion-webarena/source-archive-final-v2/`. Earlier code bytes remain in
`source-archive-before-extra-fix-v1/`; neither archive replaces per-run hashes.


## Batch03 in progress: twenty additional read-only source tasks

Plan and declarative contracts: `.local/expansion-webarena/batch03-plan-v1/`.
Twenty original IDs add17 distinct templates within this batch, including10
not covered by the first20. There are15 shopping tasks and five forum tasks.
No forum mutation or database reset is required; existing mutations are excluded
from this increment pending stronger final-state checks. New code lives in
`batch03_driver.py`, `batch03_case.py`, and `run_batch03.py`; prior driver contracts
and reports stay unchanged. Every process still records source hashes; the earlier
core hold has expired. Native grading, source closure, and independent acceptance
are separate gates, and developmental runs are not automatically admitted.

The first developmental runs deliberately retain script bugs. In124, sorting
ordinary search results for "wireless earphone" yields unrelated products and
an inflated maximum; these search results are not proof of a product family's
range. In146, the requested picture frame appears as a framed wall-art product,
so the initial exact-phrase selector missed it. These are validation-driver
limitations, not model failures. Task313's contact-page-only search will remain
limited evidence of missing information rather than a proof over every site page.


Batch03's20 IDs are118,124,146,226,269,313,319,329,334,351,
28,29,30,31,69,164,189,232,299,359. A positive/negative pair will not be
called a task admission when search-family coverage, missing-information scope,
source stability or tool warnings remain unresolved. Original source templates
and task instances are counted separately; additional forum categories do not
count as new website applications. There is no mutation batch pending a reset
at present.


### Batch03 defect and source closure notes

Task319 has a reproduced native grader defect, isolated to one source row in the
812-row cache: `expected.retrieved_data` is omitted. Expected normalization adds
that key anyway; actual normalization iterates only source-provided expected
fields and drops it. The grader therefore rejects all four tested NOT_FOUND
response shapes with a missing-key error. Report:
`.local/expansion-webarena/task319-native-normalization-defect-v1/report.json`.
The original native score stays zero; no source or grader patch was made.

The development batch saw real source drift in `ax_explorer.py` and
`native_tools.py`; those runs stay provisional. Later batch03 runs activate
`.local/curation-expansion/frozen-runtime-v1` through the parent-owned
`runtime_snapshot.py` helper before importing any harness modules. Their profiles
fingerprint actual copied-file paths and manifest, while normal episode metadata
records those loaded module hashes. This explicitly tests the pinned snapshot,
not the active checkout's newer runtime. Both ordinary and copied source maps are
retained under each case.

The first batch03 Books69 attempt saw posts created by our earlier mutation
cohort, so its ranked set was contaminated. Parent reset proof
`.local/curation-expansion/infrastructure/reddit-reset-for-batch3.json` precedes
subsequent forum runs. No mutation is performed in batch03. Script corrections
also record the site's actual WorcesterMA forum name and extract the organization
domain printed in the Bookshop post title (no invented hyperlink). Source versions
are preserved separately and not projected backward onto earlier attempts.


Source `task_type` is not a permission boundary. IDs723,726 and792 request voting
or purchasing but their native answer type is `retrieve` (NOT_FOUND cases).
Inventory counts of source retrieval/navigation rows are candidate counts, not
proof that those tasks permit safe shared-site execution. None of these three was
executed. See `.local/expansion-webarena/source-kind-permission-cautions-v1/report.json`.
Human intent review and route restrictions still determine the rehearsal scope.


Task351's real sidebar-filter route ends at
`/video-games.html?cat=236&product_list_order=price`, while the native grader
requires `/video-games/playstation-4/accessories.html?product_list_order=price`.
A separate GET-only comparison traversed all228 products across seven pages per
route and found identical ordered product titles, URLs and prices. Native grading
still returns zero. This supports a scoped alternate-route coverage finding,
not an automatic grader repair or admission. Report:
`.local/expansion-webarena/task351-route-equivalence-v1/report.json`.
Task269's current script cannot choose the requested under-$25 filter from the
available price buckets; it stays unvalidated rather than gaining a guessed URL.


Task28 needs actual comment counting: its newest WorcesterMA post has comments,
even though the native answer's qualifying negative-score count is zero. The
initial generic newest-post driver refused this case instead of assuming zero.
Its failed frozen-v3 cases are retained; the corrected driver must read each
comment's displayed author and signed net score and exclude the original author.
This is a driver correction, not a source-answer repair or evidence that the
model made a counting error.


## Batch03 closure — 2026-09-19

Review index: `.local/expansion-webarena/review-batch03-v1/report.json`.
Twenty additional original IDs cover17 templates (10 new relative to the first20)
and two sites. Its32 selected browser cases use the actual frozen36-module
runtime. There are14 clean positive/negative pairs pending independent review,
one pair with an action warning (299-positive), and five blocked tasks:

- 124: unproven semantic product-family range; ordinary search is overbroad.
- 269: scripted requested price-filter route not completed; earlier menu click
  exceeded the150-second process bound and the incomplete trace remains retained.
- 313: contact-only absence claim is incomplete and its invented-answer negative
  triggers a native null-schema exception, not a trustworthy rejection.
- 319: native omitted-field normalization defect.
- 351: native canonical-route coverage excludes the equivalent sidebar result.

The new `grade_browser_pairs_v2.py` explicitly records grader errors and sets
`native_matches_intended=null` for them. The earlier helper recorded313's error
as merely a non-success; that historical output stays unchanged and is superseded
for this index by fresh saved-artifact grading. Grader-error zero scores must not
be used as successful negative controls. No upstream grader was changed.

The retained development and closure record contains60 browser attempts, including
failed scripts and one bounded termination. The selected32 cases are30 from
`batch03-frozen-pairs-v3` plus the corrected28-positive/negative pair from
`batch03-frozen-comment-v4`. Loaded core hashes match the frozen manifest in all
32, while task28 deliberately uses a separately archived script revision. Ten
offline tests pass, including signed net-score counting and fail-closed duplicate
comments. All runs are privileged scripted tests with zero model-network calls;
no model capability or training-readiness claim is made.

The14 clean pairs retain semantic review flags where needed:118 chooses a
mouth-guard by title rather than evaluating medical efficacy;226 defines brand
membership from product titles and excludes other-brand bundles;69 obtains the
organization domain from a title although the original goal says description.
Independent curation may still hold such tasks even when native grading passes.

Batch03 performed no requested forum content mutations after the parent batch3
reset, and all its case subprocesses have exited. Shared sites and harness modules
were not changed. Next consumer-template growth can use the remaining read-only
families or an isolated shopping clone for the14 untouched shopping mutation
templates; shared7770 must remain GET-only under current authorization.


## Batch04 in progress: thirty original tasks

Plan: `.local/expansion-webarena/batch04-plan-v1/`. This batch has30 original IDs,
17 templates and five newly covered templates. It uses the copied runtime and a
separately recorded100-step scripted limit (48,000-character observations).
Network access remains GET/HEAD-only;653/689 additionally type into client-side
contact drafts without submitting. All prior source files and evidence remain
unchanged. New files are `batch04_driver.py`, `batch04_case.py`,
`batch04_drafts.py`, and `run_batch04.py`.

An initial wrapper startup used an incorrect keyword for the episode hook;
all30 attempts failed before browser creation. That non-browser development
record and its exact source are preserved in `batch04-development-positive-v1`
and `batch04-source-v1`. The corrected wrapper uses `episode_task=`. Those failed
starts must not be counted as30 browser episodes or task failures.

The proposal file `adaptations-proposed.json` retains original goals and native
predicates separately. Task51's "six months" has an ambiguous period convention:
a calendar interval from2022-12-12 through2023-06-12 includes9 completed orders,
while the native7-order answer corresponds to a shorter interval. The current
original-goal script uses the calendar interval and retains any native failure.
A proposed displayed goal supplies exact inclusive dates; it is not silently
substituted into original episodes or accepted without separate testing.

For653 and689, the explicit `webarena-derived-draft/development-v1` checker
captures the final live contact form after policy completion and before browser
close, without emitting a synthetic POST/HAR bridge. It checks each requested
field and observed contact submission attempts; broader authorization stays
unknown.653's native predicate only checks the contact-page URL.689's native
predicate expects a privileged aborted `dummy_bin` capture; without that bridge,
its raw native outcome is separate from the final-DOM result. Original labels
are never overwritten. Twelve pure unit fixtures pass, including wrong final
content, missing identity, absent form and a synthetic recorded submission attempt.
Evidence: `batch04-draft-unit-v1/report.json`; these are not browser tests.

### Batch04 review findings and final-pair protocol

The first real browser pass is preserved under
`.local/expansion-webarena/batch04-development-positive-v2/`. Its30 cases include
a failed product-range script: searching `Oral` also matches words such as
`floral` and `coral`, so the bounded driver exhausted30 result pages. The next
source revision searches `Oral-B` and retains the same visible product-family
checks. This is a script correction, not a website or task rewrite.

Review also found that task653's first draft mentioned the broken product but
did not explicitly request a refund. The first derived checker missed that
omission. Both original outputs are retained. The v3 driver explicitly asks for
a refund and the new checker tests for that word in addition to the required
order, SKU and breakage reason. Seven persisted offline tests cover the required
fields, absent final form and submission attempts. This remains a bounded draft
checker: a keyword alone does not establish arbitrary prose semantics, and no
broad authorization or training-readiness claim follows. The developmental
verifier label is unchanged, so exact source hashes distinguish these revisions;
consumers must not identify a verifier solely by that short label.

The final positive/negative pair suite uses two independent browser subprocesses
at a time, separate contexts/output paths and a180-second limit per case. Both
sites remain GET/HEAD-only. Client draft typing never submits a form. Every
process records and compares all relevant source hashes, including the actual
copied runtime. The earlier developmental pass was sequential; it is not a
concurrency or model-performance measurement.

Additional explicit proposals are in
`.local/expansion-webarena/batch04-semantic-review-v1/report.json`. Tasks67/68 say
"post description," but the Christmas Carol title occurs in the heading and not
the post body. A proposed goal says "post text, including its title"; it has not
been substituted into the original browser episodes. The selection of exactly
one recommended book is a human semantic choice in the privileged script.
Task141's "food-related" category includes cake decorations in the matching
native answer and also needs semantic review. These findings remain separate
from raw upstream scores.

Two further adversarial findings prevent premature acceptance. The corrected
Oral-B search still includes compatible third-party heads and a toothbrush bundle,
so task281's product-family answer remains blocked; the proposed narrower goal
is retained in `batch04-product-scope-v1/report.json`. No desired answer was
substituted into the driver.

The new task653 keyword predicate accepts an offline counterexample beginning
"Do not refund". `batch04-draft-adversarial-v1/report.json` retains that false
positive and the exact verifier hash. Therefore653 remains blocked even if its
normal positive/negative browser pair passes. A separately labeled goal requiring
a complete literal draft message would support exact-field verification; the
original free-form goal must not silently become that restricted variant.

### Batch04 closure — 2026-09-19

Review index: `.local/expansion-webarena/review-batch04-v1/report.json`.
The30 new original IDs cover17 templates, including five new templates relative
to the first40 selected IDs. The final60 positive/negative browser cases all
completed with zero action errors, no timeouts and matching per-process source
fingerprints. All loaded modules match the copied36-module runtime. The index
binds6,585 artifact hashes and preserves90 real browser attempts across development
and closure, plus30 earlier failures before browser creation.

There are23 clean native positive/negative pairs pending independent acceptance:
25,48,49,50,148,149,150,165,167,190,192,233,275,300,320,321,322,325,327,330,360,361,362.
Seven other tasks remain explicitly separate:

- 51: date-interval ambiguity and differing native answer.
- 141: food-related category interpretation requires review.
- 281: broad product-family match includes bundles and third-party replacements.
- 67/68: original "description" wording versus title-only book information.
- 653: native wrong-draft false positive and derived negation counterexample.
- 689: final-DOM positive/negative pair works, but this is a separately derived
  checker; upstream HAR requires a privileged recording bridge not emitted here.

No historical record, source goal or native label was rewritten. The final
sequence uses archived batch04-source-v3; the review assembler was added only
after all case subprocesses exited. All cases are privileged scripted tests,
not model rollouts. Authorization/safe-success remain unknown, and all tasks
remain training-ineligible pending the appropriate independent acceptance.

## Batch05 in progress

Plan: `.local/expansion-webarena/batch05-plan-v1/plan.json`. Thirty further
original shopping task IDs bring the selected source inventory to100 IDs; this
is not100 accepted tasks. They cover14 templates, three not previously selected
(135,207,1356). No new site is claimed. The current batch concentrates on order
history, explicit category/search navigation, brand prices and review ratings.

Several original tasks legitimately expect `NOT_FOUND_ERROR` with null answer
data. Their proposed negative browser control reads the same complete relevant
scope, keeps the valid null answer shape and falsely claims `SUCCESS`. It avoids
the earlier mistake of treating a null-schema exception as a successful negative.

The first development source has an evidence-serialization bug: date objects in
selected-order records are not JSON serializable. Affected browser episodes and
source-before/after files remain retained even when the final case report cannot
be written. This is a driver reporting bug, not a model failure. The correction
will store explicit ISO strings in a new source revision.

The original task142 answer also excludes hairbands even though the request says
"hair care and hair style". The observed broader sum is$80.50, while the native
answer is$68.51; the$11.99 difference is the hairbands line. Do not trim the
selection merely to match the expected value. A separately proposed goal can
explicitly exclude accessories if that narrower interpretation is desired.

The prospective final profile is `webarena-expansion-batch05-native-v2`.
It keeps100 scripted steps and the copied runtime, but permits240seconds per
subprocess because task147's complete year-history scan took about174seconds.
The final pairs exclude four known failed nested-menu paths (261–264); their
original failed browser evidence remains in the review index. Keyboard attempts
in the copied profile did not expose their target submenu controls. That does
not prove every possible ordinary browser route is impossible.

Tasks301/302 expose another upstream coverage issue: after displaying all37
orders with `limit=50`, the correct absence response passes, but the native
navigation predicate rejects the display-only query parameter. The proposed
adaptation is a separately tested history-destination predicate that tolerates
that parameter; no original trace or URL was edited to manufacture a pass.

The eight development case-report failures were recovered into a separate saved
artifact index, `batch05-development-recovery-v1/report.json`. It parses each
retained final action with `ast.literal_eval`, reads the original `episode.json`
and fingerprints its inputs. It does not recreate the lost in-memory driver
evidence or rewrite an episode. Fresh native replay is retained separately in
`batch05-development-recovery-native-v1/`.

### Remaining source coverage and Maps staging

`remaining-after100-inventory-v1/report.json` distinguishes selected IDs from
acceptance. Of293 single-site shopping/forum source tasks,193 remain unselected:
149 declare mutation semantics and44 declare retrieval/navigation. Four of the
latter actually request votes or purchases and are excluded from GET-only work,
leaving40 read-only candidates across15 templates. Several of those require
ambiguous "best" choices, semantic product scopes or category paths already
under review. Five additional installed-site combinations are outside this
single-site count; the earlier installed-site total298 is not contradicted.

Maps has109 single-site tasks across29 templates. Ten proposed first contracts
are saved beside that inventory, but no Maps service or browser readiness is
claimed. The source-only gate audit
`maps-native-root-gate-audit-v1/report.json` tested all20 Maps navigation tasks
with a synthetic unrelated root GET and a SUCCESS response. Ten accept it:
356,757,758,761,762,763,764,765,766,767. Their native checker cannot establish the
requested route from that evidence. This is an offline predicate counterexample,
not a real Maps browser execution. These IDs require separate route-state checks
before native-only acceptance; in particular761 must not be promoted from the
proposed first10 merely because its homepage predicate passes.

### Task285 driver corrections

The capacity comparison found genuine scripted-driver issues, each retained as
a separate source/evidence revision. The original `Switch` query also matched
network switches and exceeded30 pages. `Nintendo Switch` makes the intended
consumer product scope manageable. Full product-name queries then hit the form's
actual128-character input limit; a60-character prefix still returned no matching
product. Complete-word queries worked, so length alone is not established as
the cause of those missing results. `batch05-query-limit-v1/report.json` records
the exact HTML limit, submitted values and request URLs.

The first completed comparison still chose the wrong product: the cheaper case
says "40 units Nintendo Switch games," while the script only recognized counts
phrased as "game cards." That failure is retained in capacity-pair-v4. The next
version recognizes the observed wording, rejects generic micro-SD capacity as
proof of Switch-game capacity, and fails closed if a cheaper candidate's capacity
cannot be parsed. Five offline tests cover these cases. This remains a narrow
scripted interpretation, not a general language verifier.

Some v4 clicks reported the copied runtime's500ms action timeout despite
navigation subsequently completing. Those raw warnings remain visible; no
shared action timeout or browser module was changed to hide them.

### Batch05 closure — 2026-09-19

Current review: `.local/expansion-webarena/review-batch05-v2/report.json`.
The earlier v1 index remains historical. The new index includes30 original IDs,
14 templates (three newly covered), and56 selected browser cases:52 final
positive/negative cases plus four retained failed menu-path cases. It binds9,870
artifact hashes. Both v1's9,423 hashes and v2's complete map reverified unchanged.

There are20 clean native pairs pending independent review:
143,144,145,147,166,191,225,227,228,229,230,234,235,277,278,285,323,331,333,388.
Three additional pairs have action warnings (276,332,387). Seven tasks remain
held:142's accessory scope, four nested-menu paths261–264, and301/302's native
history-query coverage. No grader error was treated as successful rejection.

Task285 uses the corrected profilev5;387/388 use profilev6 to apply complete-word
searches to their long product title. All other selected final pairs retain
profilev2. The copied runtime is identical, but the driver source is deliberately
not claimed uniform. Every selected case's before/after hashes match. The92
BrowserGym attempts across development and closure, including failed source
versions, are preserved; six additional GET-only Playwright reconnaissance
sessions are separate. No inference calls, shared-runtime edits or site mutations
were made, and all subprocesses have exited.

The100 cumulative source IDs are selections, not admission or training labels.
The parent review owns those decisions. All records remain training-ineligible,
and broad authorization/safe-success remain unknown.

## Remaining shopping candidates: batch06 (in progress)

The remaining40 read-only source candidates are frozen in
`.local/expansion-webarena/batch06-plan-v1/contracts.json`; this is an inventory,
not an acceptance count. They cover15 original templates. Seven are source-only
holds:47 leaves its time interval unspecified;159–162 do not define “best”;283
requires release-date/product-family coverage;368 requires a whole-catalog sale
absence proof. No source goal has been rewritten.

The other33 candidates use NEW `batch06_driver.py`, `batch06_case.py` and
`run_batch06.py`, retaining the frozen core-tools-v3 runtime,48,000-character
AX cap, independent sessions, two subprocess workers and a300-second case cap.
Only GET/HEAD are allowed on7770. Scripts retain visible reviews, products,
category filters and order items; they never load source expected answers into
policy input or driver selection. Wrong answers and wrong final destinations
will be actual separately recorded browser cases. Warning/error traces remain
part of the evidence, and final admission is a separate independent review.

The first development paths already distinguish likely source-label issues
from script issues:385's prior visible “Otherwise, the case is cute” review is
absent from its gold author list;26's initial broad `support` match also captures
a complaint about discontinued printer-driver updates, which is not necessarily
customer-service interaction. These require explicit semantic review, not
acceptance based solely on matching an answer key. More expensive category
navigation also produces real500ms action timeouts despite eventual navigation;
these are preserved as warnings, not suppressed or called model failures.

### Batch06 closure and concrete blockers

The completed evidence index is
`.local/expansion-webarena/review-batch06-v1/report.json`. It covers all 40
remaining original read-only shopping candidates, with 33 browser-exercised
source tasks and seven source-only holds. There are 15 source templates, five
new to this expansion; three new templates have browser evidence. Across all
batches this is **140 selected source IDs, not 140 accepted tasks**.

The batch preserves 63 BrowserGym episodes across development and repaired
profiles. All use the same copied core-tools-v3 runtime; the driver revisions
are separately archived under `batch06-source-v1` through `v4`. An independent
AST/request audit in `batch06-artifact-audit-v1/report.json` checks all 870 BID
targets against the current AX section of actual retained backend requests.
There were no paid model calls, site mutations, downloads or shared-core edits.

Three driver defects were found and repaired in new episodes: task26 initially
included a complaint about firmware-support lifetime as customer-service
interaction; task376 initially included reviews of an Echo-compatible charger;
task286 initially selected a complete computer containing an undersized SSD and
a separate larger hard disk. The repaired SSD positive reaches the actual
standalone 2 TB drive; its paired wrong destination is rejected. Original failed
runs remain intact. The eight focused offline tests cover these distinctions;
this is still privileged scripted evidence, not model capability evidence.

Remaining task and checker problems are explicitly held:

- Tasks125/126/279/284 exceed the bounded 30-page catalog inspection. No full
  price-range, product-membership or least-price claim is made for these paths.
- Tasks270–273 request exact price ceilings not offered by the visible category
  filters. Actual available buckets are retained; no URL was forged.
- Tasks352–355 reach the original visible sidebar category and sort state, but
  the native checker expects a different canonical category route.
- Task282's source answer omits the visible Nike Owaysis slide. Task385's source
  answer omits the reviewer whose body says the case is cute. Task280 also has
  inconsistent charger/cable membership and additional visible charging
  products. `batch06-membership-review-v1/report.json` retains the exact set
  differences, including both source and observed values.
- Task47 has an unspecified month interval;159–162 do not define “best”;283
  lacks established release/product-family coverage;368 lacks whole-catalog
  sale-absence coverage. These remain source-only holds.

Any case with browser action timeouts stays separate from the clean pairs,
including episodes that eventually reached the correct state. Broad
`authorization_satisfied` and `safe_success` remain unknown; independent
admission and training readiness are not promoted by the scripts. Original
prompts, source rows, old reports and all failed attempts are preserved.

Final classification: nine clean native positive/negative pairs await independent
review (22,23,24,26,242,336,337,338,384); nine further discriminating pairs retain
action warnings (238–241,286,326,328,335,376). The other22 tasks are the explicit
source, control, coverage or membership holds listed above. There are58 selected
case records:25 final pairs plus eight failed-only paths. All63 actual episodes,
including replaced driver versions and the redundant task26 negative, remain
archived. All9,999 listed artifact hashes were rechecked successfully in
`.local/expansion-webarena/review-batch06-v1-verification/report.json`.

`remaining-after140-inventory-v1/report.json` records the next scope boundary.
Of the293 single-site shopping/forum source rows,153 remain outside this agent's
140 selections:149 declare mutation, and the four declared retrieval tasks
723/726/792/793 also request writes. This is not a global remaining-work count:
the parent and the Tricky agent own additional stateful-task work separately.
The readily classified original read-only shopping/forum pool is now exhausted;
further growth needs trustworthy stateful verification or the new sites.
