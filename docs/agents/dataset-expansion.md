# General-browsing dataset expansion

Owner: curation. Started 2026-09-19. Active goal: work toward 100 accepted
general-browsing tasks each from WebArena-Verified and TrickyArena. First
checkpoint: 10 accepted tasks per dataset, spanning available sites. This is
integration and scripted validation, not an authorized paid model cohort.

## Ownership and ordering

| Worker | Owned additions | Responsibility |
|---|---|---|
| WebArena subagent | `data/curation/expansion/webarena/`, `webarena-expansion.md` | Original task inventory, contracts, isolated browser checks and native graders |
| Tricky subagent | `data/curation/expansion/tricky/`, `tricky-expansion.md` | Four-domain source audit, original contracts and independent outcome checks |
| Curation parent | Other files under `data/curation/expansion/`, this document | Acceptance review, coverage aggregation, isolated infrastructure and coordination |
| Backend agent | Existing shared harness/runtime | Context, tools and runtime changes; no ownership transfer in this increment |

Keep complete upstream sites and their navigation. Verify the site, then its
existing tasks, before considering new tasks or permutations. New dark patterns
are deferred. Existing source patterns are identified explicitly rather than
counted as independent general-browsing tasks. Do not modify historical catalogs,
certificates, runs or source freezes. No automatic deployed registry promotion.

Shared shopping/forum ports 7770/9999 must not be reset or mutated. Bounded
read-only browser checks use fresh contexts and request interception. Stateful
checks require separately named containers with independent writable layers or
volumes. Parent coordination: `.local/coordination/dataset-expansion.md`.
Active core changes are fingerprinted per execution, not assigned old certificates.

## Acceptance and counting

Track upstream task IDs, semantic template IDs, site dependencies, source
conditions and generated instances separately. Report both task and template
counts. Rewording an instruction or switching a pattern does not create a new
independent task template. Count a cross-site task once, with both dependencies.

A task may be inventoried, blocked, specified, scripted-validated, or
independently-accepted. Acceptance requires all of:

1. Source identity/revision and retained original objective; any clarification
   or grader correction is a named adaptation.
2. Complete-site setup and reachable original task information/controls.
3. A successful native browser execution with retained evidence, not merely a
   source-derived expected answer or direct application API call.
4. Plausible incorrect outcomes rejected by the grader. Separate real browser
   negative paths, altered answers, and synthetic HAR omissions in reporting.
5. Reset/session isolation evidence appropriate to the task. Browser contexts
   alone do not reset server-side account or application state.
6. Reviewed outcome coverage and a separate independent review. Procedure
   observations do not become outcome requirements. Unknown authorization or
   unobserved side effects are not safe-success passes.

Contracts follow the separation in [task definitions](../task-definitions.md):
policy-visible instruction, private source/requirements, implementation binding,
and per-requirement results. Retrieval responses must come from recorded browser
evidence; reference answers remain evaluator-side. Native evaluator acceptance
alone does not establish that a source task is achievable or that its answer is
correct on our fixture.

Scripted acceptance and model evaluation are distinct. The former can make a task
eligible for a future evaluation profile; it does not establish teacher quality,
training eligibility, deployment readiness, or the absence of all environment
defects. Preserve raw failures and use new evidence paths for reruns.

## Baseline and feasibility

- WebArena pinned dataset: 812 IDs. 298 depend only on installed shopping/forum;
  295 are beyond the previously exercised IDs 118, 399 and 528. These 298 span
  70 upstream intent-template IDs. Candidate count is not validated count.
- Tricky static inventory: 260 URL/prompt conditions and 59 normalized prompt
  texts. First worker audit identifies 32 original no-hint enum families across
  shop/health/music/news, with some semantic overlap. The 100-distinct-task target
  cannot be met solely by relabeling those conditions. Review the worker inventory
  before deciding on explicitly new tasks or another dataset.
- Known health cross-page state inconsistency and missing music assets require
  task-specific handling; a successful older episode is not a blanket site gate.

New-site resource assessment is in
`data/curation/expansion/site_resources.json`. The user approved 200 GB total
downloads. HEAD metadata exposed a documentation underestimate: Maps' three
archives total 187,334,164,480 bytes, including a 124.8 GB geocoding archive.
The pinned Maps and Shopping Admin images plus these archives and a 1 GB
metadata/retry allowance reserve 190,767,029,439 bytes. Wikipedia's original
endpoint was unavailable; no alternate snapshot was substituted. Maps data
download is ongoing; an available image does not mean the site is runnable.
Shopping Admin remains secondary harness diversity: most of its tasks are
retailer back-office work outside the earlier consumer-assistant preference.

## First checkpoint evidence

- Tricky first ten: independently accepted for scoped general-browsing
  development. `data/curation/expansion/tricky-batch01-independent-review.json`
  rechecks 547 exact artifact hashes, 21 verdicts, 37 current-AX action targets,
  and 21 browser-derived answer extractions. Four site contexts, no model calls.
  This is saved-evidence/source review, not an independent fresh browser replay.
- Tricky second batch: four original cart/comparison/purchase tasks independently
  accepted on the same site. Parent reconstruction checks 19 verdicts, 701 hashes,
  85 current-AX targets and catalog rankings. See
  `data/curation/expansion/tricky-batch02-independent-review.json`. Original total:
  14 accepted development contracts, not 14 navigation templates or sites.
- The user explicitly authorized new general-browsing objectives on verified
  Tricky pages after original-task validation. These are separately attributed
  project-authored tasks with template/instance counts, not retroactively
  attributed upstream tasks. Broken review/playlist/audio/PDF workflows remain
  excluded pending repair and revalidation. New dark patterns remain deferred.
- WebArena first ten: parent replay confirms 10 native positives, 246 artifact
  hashes and 32 current-AX targets. Full acceptance remains pending real negative
  browser paths, native profile adoption and task-specific data/reset closure:
  `data/curation/expansion/webarena-batch01-independent-review.json`.
- Isolated forum reset: `.local/curation-expansion/infrastructure/reddit-reset-v2/report.json`
  proves a real browser biography edit is removed by recreating only the
  dedicated container. This does not certify all state. A 500 ms profile-link
  timeout occurred despite navigation taking effect; the reset passes while
  the separate browser smoke fails. Failed v1 attempt remains retained.
- Existing shared services are unchanged. Independent Reddit ports18999/18998
  use `data/curation/expansion/compose.isolated.yaml`; their mutable database is
  in a disposable container layer, with no host/shared mounts.
- Backend DATA-EXP-02 confirms no rehearsal hold: new navigation is opt-in and
  does not repair timeouts/hangs. Keep per-process fingerprints and separate
  protocol cohorts. WebArena worker is adding bounded subprocesses after a hang.
- DATA-EXP-03 granted a stable core window through14:31UTC after a per-episode
  guard detected active edits during a native task96 rehearsal. The earlier
  evidence remains unclosed. Dependent browser runs finished and curation released
  the hold early; future runs retain per-process guards.
- Shopping Admin is independently hosted at port17780 (control17781), with a
  positive original task157 scripted navigation and native evaluation retained
  under `.local/curation-expansion/infrastructure/admin-site-gate-v2/`. Native
  config must map `__SHOPPING_ADMIN__` to `http://localhost:17780/admin`, not just
  the origin; the earlier configuration failure is retained. This is a secondary
  back-office site diagnostic, excluded from the primary consumer task count.

## Milestones

1. Inventories, site gates and blockers; concrete feasibility of target counts.
2. Ten accepted tasks each, varied capability coverage and site diversity.
3. Expand breadth: all four Tricky domains and at least four WebArena contexts
   where source suitability and resource approval permit. Supporting pages only
   count as task coverage when exercised by accepted tasks.
4. Batches of 10–20 toward the targets, reporting shortages without padding.
5. Freeze reusable sweep inputs for authorized model evaluation, then use trace
   triage to distinguish environment/tool failures from teacher limitations.

## Authored tasks and stricter grader review

Twenty project-authored Tricky instances (16 templates, all four domains) now
have independent native-profile acceptance: `tricky-authored20-independent-review.json`
under the expansion directory. Parent recomputation checks reference arithmetic,
40 outcomes,2390artifact hashes and135current-observation targets. The JSON/money
response convention is present in the actual system requests via the runner
terminal-response instruction; a future adapter caller must retain that binding.
Total accepted Tricky development coverage is34instances:14original plus20authored.
No model success rates or training-readiness claims follow from scripted cases.

WebArena task399 has a confirmed native-grader loophole: a correct biography
followed by an incorrect persisted overwrite still scores1. Independent review
`biography-history-review.json` verifies the two captured writes and the final
rendered profile. A standalone final-read diagnostic rejects the overwrite and
passes the correct saved case; it is not installed into the adapter or historical
evaluations. Other mutation templates require final-state review before promotion.
Unqualified “best” in158 and ambiguous rating units in386 also need explicit
contract decisions. These are dataset/grader issues, not model failures.

## Stable runtime for concurrent dataset work

The DATA-EXP-03 hold ended. Subsequent live-checkout rehearsals correctly rejected
source drift in `ax_explorer.py` / `native_tools.py`. These remain diagnostics.
New offline cohorts can explicitly set `CURATION_FROZEN_RUNTIME` to
`.local/curation-expansion/frozen-runtime-v1`. Its manifest binds36 copied core
files to the earlier navigation-v1 snapshot. `runtime_snapshot.py` checks exact
file membership and hashes before import and refuses an already loaded different
package. Four offline tests cover import selection, changed files, extra modules,
and preloaded-package conflicts. Child processes inherit the choice.

Each adopting wrapper must call activation before core imports, fingerprint the
actual copied source paths (not relabel them as the current checkout), and still
hash its task drivers, contracts, helper scripts and builds. This is the recorded
core-tools-v3 baseline, not validation of newly developed harness behavior. It
requires no further shared edit hold and authorizes no model calls.

Maps has109 single-site source tasks spanning29templates; representative
source contracts are inventoried in `map-template-inventory-v1.json` only.
`map-setup-plan-v1.json` records isolated future volume paths and required gates.
The actual image is cached, but data download and full site validation remain
pending. Do not count Maps tasks from this inventory as accepted.

The remaining seven original shopping tasks TO15–TO21 pass14native cases on
the copied runtime and independent second-agent review:
`data/curation/expansion/tricky/reviews/remaining-originals-independent-v1.json`.
This adds1504artifact checks and114current-AXtargets. Original Tricky accepted
coverage is now21tasks, plus20authored instances =41development tasks. The sort
combobox click was obstructed by its label; ordinary keyboard navigation works.
Failed click/AX-target attempts and live-checkout source drift remain preserved.

Authored batch02 AU21–AU40 adds20accepted instances (20 declared template IDs)
after independent arithmetic/source/seed-state and40outcome replays. Review:
`tricky-authored40-independent-review.json` (2360artifact hashes,132current-AX
targets). Total61Tricky tasks:21original +40authored. Template IDs are reported
separately; distinct IDs do not imply independent skills or new site features.

Targeted AX-STRESS-01 review independently accepts WebArena146/334 positive and
wrong-answer pairs, with current-target checks and native replay. Together with
nine clean read-only tasks in `webarena-native20-independent-review.json`, strict
WebArena development acceptance reaches11tasks. First10-per-dataset checkpoint
is fulfilled. The20-task worker expansion and wider/failure cases remain separate.

### Independent review checkpoint: 79 Tricky / 20 WebArena

`tricky-authored60-independent-review-v1.json` checks 40 saved AU41–AU60 cases,
2,250 artifact hashes, 161 mocked native requests and 121 current-AX action targets.
18 tasks are accepted. AU46/AU47 remain held: their goals require exact draft text,
but the original comparator normalizes case/whitespace/final punctuation. Correct
saved examples do not establish rejection of these near-miss drafts; a versioned
repair is pending. News alert tasks certify only displayed drafts, not saving or
subscription persistence; authorization remains unknown where coverage is missing.

`webarena-batch03-independent-review.json` checks 4,276 hashes, 32 native replays,
190 mocked requests and 158 current-AX targets. Eleven tasks pass conservative
review (two were already accepted by the AX-stress review); the distinct accepted
WebArena total is20. Task118's broad clinical-benefit wording/URL matcher, task226's
brand-range inference, task69's title/description mismatch and the already flagged
blocked/action-warning tasks are not promoted. Native exceptions do not count as
negative-test success. No new browser runs or model calls were needed for these
independent reviews.

Counts remain development-only:79 Tricky =21 original +58 authored instances;
48 distinct authored template IDs across accepted instances (deduplicated across
batches). Static progress board regenerated from `progress.json`. Existing full
sites, original prompts, historical cohorts and raw native grades remain unchanged.

### Strict-draft closure and discovery index

`tricky-authored-drafts-v2-independent-review.json` independently replays8 new
AU46/AU47/AU51/AU52 cases and538 artifact hashes. Exact form fields and final page
agree; explicit case/space/punctuation/type adversaries fail the new comparator.
Old grader acceptance of near-misses is preserved in the review. All60 authored
instances are now accepted (81 Tricky total); the original v1 draft cohort remains
historical and does not acquire the new comparator retroactively. News alert
submission/persistence remains outside coverage, with authorization unknown.

`accepted_index.py` offers read-only dataset/site/origin/kind/task filtering and
exclusive JSON export. It joins accepted task IDs with their original contract
and independent review hashes, retaining nulls and source attribution. The first
snapshot `.local/curation-expansion/accepted-discovery-v1.json` holds101 tasks across
six dataset/site contexts. It does not register production tasks or launch models.

### Tricky 100-task target reached

`tricky-authored79-independent-review.json` independently recomputes all19 new
AU61–AU79 expected outcomes and replays38 saved native cases,2,158 artifact hashes,
155 mocked requests and117 current-AX targets. Artist-page joins follow artist IDs
(the upstream display name `Tekashi 6ix9ine` differs from the song's `6IX9INE`),
not an assumed text-equality join. All38 selected cases have zero action errors.

Accepted total:100 Tricky instances =21 original +79 authored, across42 shopping,
20 health,20 news and18 music tasks. Authored instances use60 distinct declared
template IDs after cross-batch deduplication; this does not claim60 independent
skills or benchmark originals. Model evaluations remain0, and training eligibility
remains false. Newly added dark patterns were not used. Broken upstream features
remain excluded and documented, without removing their surrounding site pages.

The second discovery snapshot `.local/curation-expansion/accepted-discovery-v2.json`
contains100 Tricky plus20 WebArena accepted tasks. The previous81+20 snapshot and
all previous reviews remain unchanged. The overall goal is still active because
WebArena has not reached100 and Maps infrastructure is still downloading.

Download continuation tooling: `download_ranges_v2.py` adds fail-closed completed
chunk/archive SHA256 checks and fixed-boundary validation on resume. Six offline
tamper/type/path tests pass. It has not replaced the active v1 background process;
readiness is recorded in `.local/curation-expansion/infrastructure/download-resume-v2-readiness.json`.
Use it only on a necessary continuation with the same approved manifest/ledger;
no download allowance reset. Maps remains unvalidated until complete data, service
checks and browser task validation are available.

Index usability audit found an ambiguous revision field on TO15–TO21: their raw
contract pins the environment repository, while other originals pin the task
repository. Discovery schema v2 adds `qualified_provenance.task_source` and
`environment_source`, grounded in exact inventory record IDs. It preserves the
old raw field and labels its scope; no historical contract or episode is changed.
Snapshot `.local/curation-expansion/accepted-discovery-v3.json` records this
metadata correction with unchanged100/20 counts. Consumers should use qualified
references, not assume every legacy `source_revision` names the same repository.

### WebArena 43-task checkpoint

`webarena-batch04-independent-review.json` replays60 selected cases and checks
6,585 artifact hashes,330 mocked native requests and270 current-AX targets. All
selected cases have zero action errors.23 additional original tasks pass review,
bringing accepted WebArena tasks to43 (39 shopping,4 forum).

Held separately: task51 calendar-six-month/native-answer disagreement; task141
food-related category ambiguity; task281 product-family/native disagreement;
Books67/68 title-versus-description wording; task653 native and keyword-grader
false positives; task689 separate final-DOM grading needing its own acceptance.
Held cases are diagnostic evidence, not model failures. Original grades and
proposed goal clarifications are preserved; no silent source corrections.

Discovery snapshot4 (`.local/curation-expansion/accepted-discovery-v4.json`)
contains143 accepted development tasks:100 Tricky and43 WebArena. Qualification
of task/environment revisions is retained. No model calls or new browser runs
were used for the parent review.

### Maps/Wikipedia download plan v2

Complete remote TAR-header traversal (7,224 entries) proves that the Nominatim
archive contains the full37,329,782,784-byte PostgreSQL prefix followed only by
two flatnode directories and an87,445,115,784-byte update cache. Independent
cached-image inspection confirms Nominatim4.2.4 query code uses PostgreSQL; its
own static-data command removes flatnode. We will NOT run that command because
it also drops database tables. All original database tables and all page content
remain included; replication/import updates are outside the static benchmark scope.

`download-plan-v2.json` explicitly supersedes the unstarted full Nominatim asset
with its exact source prefix. It adds the original May2022 full-image Wikipedia
ZIM from a working Internet Archive mirror, with a published SHA256 and archived
SHA1 to verify on completion. No claim of complete-file identity precedes that
check. Total planned data, image and metadata/retry reservations are198,568,153,001
bytes, within the user's200GB cap. Metadata and failed header probes remain
covered by the original1GB allowance. No new allowance was requested or inferred.

The old downloader was stopped and confirmed terminal before migration.
`migrate_download_plan.py` verified and reused26,340,229,120 existing body bytes
under an exclusive source lock; original ledger/parts are preserved. New ledger:
`.local/curation-expansion/downloads-static-v2/ranges-ledger.json`; active downloader
`download_ranges_v3.py` validates original Content-Range totals for prefix requests
and requires the Wikipedia whole-file SHA256 before completion. Nine offline
range/resume checks pass. `map-setup-plan-v2.json` records the derived packaging
layout and required search/reverse/routing/tile/browser gates. No Map/Wikipedia
site or task is accepted yet.

### 44-task WebArena checkpoint and Maps grader gate

The accepted discovery v5 snapshot adds original task399 using the separately
reviewed final-server-profile verifier. It retains upstream native scores,
including the correct-then-overwritten false positive, and keeps authorization
unknown. Its accepted profile uses slow_mo=0; unrestricted model runs require a
complete independently owned service reset. See
`data/curation/expansion/webarena-biography-independent-review.json`.

Map task selection now excludes native-only acceptance for
356/757/758/761/762/763/764/765/766/767: an offline synthetic-HAR diagnostic accepts
an unrelated root GET plus declared SUCCESS. This is a checker weakness, not a
browser execution result. Evidence:
`.local/expansion-webarena/maps-native-root-gate-audit-v1/report.json`.
Actual route-state evidence and adversarial negative cases are required before
these tasks can count. Downloads and site readiness remain separate gates.

### 49-task checkpoint

Original coupon-draft IDs689–693 now add five instances/one template with a derived
final-DOM verifier. Independent review checked16 selected browser cases,769 hashes
and37 current-AX action targets. Required name/email fields, no-submit intent and
missing-capture unknowns are explicit. Historical weak v1 and two v2 timeout cases
remain separate. Current accepted snapshot:
`.local/curation-expansion/accepted-discovery-v6.json` (100Tricky +49WebArena).
See `data/curation/expansion/webarena_coupon/README.md`.

Map extraction uses the new `prepare_map_volumes_v2.py`; do not execute the earlier
v1 helper. Its three safety gaps are resolved in independent mocked tests, with a
separate provenance addendum recording exact captured ledger bytes and helper
hashes. Data extraction/site launch have not yet occurred. `plan_map_launch.py`
constructs an isolated no-pull command from successful extraction evidence; it
never launches a service itself. Downloads remain on the unchanged v3 process.

### 69-task WebArena checkpoint

Batch05 v2 adds20 clean original task pairs after parent replay of9,870 artifact
hashes,52 native grades and450 current-AX action targets. Earlier v1 review and
all incomplete/warning cases remain preserved. Category totals and brand ranges
have an additional saved semantic/arithmetic review; a UGREEN bundle omitted by
the driver's prefix filter was independently included and does not change the
range endpoints. This is scoped seeded-catalog evidence, not a general brand
classifier. Current snapshot v8 has100Tricky/69WebArena instances, with81/23
respective declared templates (Tricky's81 =21original +60authored templates).

The accepted site spread is still four Tricky sites and shopping/forum for
WebArena. Maps/Wikipedia are preparation only. Forum “newest” voting tasks are
held where displayed publication timestamps contradict source UI-New order;
strict final-vote grading alone cannot resolve an ambiguous objective.

### 70-task checkpoint and reusable bindings

Original forum task407 now passes independent final-vote review:1,140 hashes,95
mocked requests and82 current-AX targets across13 selected diagnostics. Only407
counts;404/405/406/408 remain held for conflicting publication dates. Five407
controls include wrong vote, undo, neutral and unavailable evidence; broader
authorization remains unknown. Snapshot v9 records100Tricky/70WebArena.

New sweep-inputs schema v3 records required pre-import copied-runtime activation
for the derived WebArena adapters and corrects AU01–AU20 to their recorded24-step
cap. Earlier169-row v1/v2 exports remain historical; current170-row export is
`.local/curation-expansion/sweep-inputs-170-v3.json`. No model runs were started.

Maps image inspection found no openstreetmap website database before startup; its
entrypoint creates/migrates an empty schema and the description controller looks
up local object records. Actual description-page validation is still required;
this is a likely setup gap, not a browser-reproduced404. An offline native-grader
probe confirms404/500 are rejected (implicitHTTP200 criterion), while matching
URL withHTTP200 but no object content passes. See
`data/curation/expansion/maps-description-preflight-review.json`. No site content
has been removed or replaced. Tiles finished transferring and assembling; the
Nominatim database prefix is downloading next, followed by routing and Wikipedia.

The follow-up isolated Rails application probe now confirms the Maps description
gap: homepage200, all five description targets404, zero node/way/relation rows
after original entrypoint migrations. This uses ActionDispatch integration
requests, not BrowserGym; geocoder/tiles/routing were deliberately not mounted.
Evidence: `data/curation/expansion/maps-description-app-review.json`. Original
image/site code is unchanged. The first network-none probe failed because the
container hostname did not resolve; the second adds only a localhost hostname
mapping. Tasks369–373 remain held until complete object data is available.

The download stopped with a DNS-resolution error after completing and hashing
the41.28GB tile archive and1.476GB of Nominatim ranges. PID47354 and tool3972 were
confirmed terminal before resuming the unchanged downloader/plan on the same
ledger. DNS resolution had recovered; saved partial ranges and completed files
remain intact. Resume evidence and separate logs are under
`.local/curation-expansion/infrastructure/download-static-v3-resume1.json`.

### 78-task checkpoint

Batch06 adds eight original clean pairs after parent verification of9,999 hashes,
50 native grade replays and784 current-AX action targets in selected evidence.
All40 candidates and63 attempted episodes remain recorded. The ninth clean native
pair,384, is separately held after semantic review: the broad quality-complaint
goal does not clearly justify excluding cosmetic/material complaints while its
source answer includes only durability complaints. Historical native agreement
is preserved; the original goal is not rewritten.

Current snapshot v10 records100Tricky/78WebArena with81/25 declared templates.
The current178-row sweep binding export is
`.local/curation-expansion/sweep-inputs-178-v3.json`; no new execution readiness or
inference claim follows from the export. Four further original biography tasks
are being verified in a separate19089 service, with their initial Save timeout
preserved. Forum-post work independently uses19099; shared services remain intact.


### 82-task checkpoint and stable template identities

Four original biography instances400–403 passed independent review of ten fresh
warmed scripted cases. The cold Save-navigation warning stays excluded and
retained. Their derived final-profile checks reject wrong/overwritten biographies
and preserve null when the final read is absent; account authorization remains
unknown. These four share template6 with399 and add no new site or template.

Current discovery snapshot is `.local/curation-expansion/accepted-discovery-v12.json`
and bindings are `.local/curation-expansion/sweep-inputs-182-v3-normalized.json`.
Counts are100Tricky/82WebArena, with81/25 declared templates. Snapshot v11 exposed
an integer/string template-ID collision; it remains historical. Current discovery
normalizes template identity to strings while preserving `raw_template_id` and
original contract bytes. Twelve binding tests pass, including task identity,
mandatory copied-runtime activation and the template-ID regression.

New Maps source inspection confirms search uses legitimate read-only POST
requests and cannot reuse the shopping GET/HEAD-only route unchanged. Search
result links can also enter the confirmed absent-object-description pages.
See `data/curation/expansion/webarena_maps/source-findings.json`; these are source
requirements, not browser acceptance. No shared services or core harness files
were changed in this checkpoint.


Forum-post independent review is staged in `review_webarena_posts.py`. The saved
647 positive and freshly versioned630 duplicate cases independently reproduce
server-row/HTML outcomes and exact delivered-AX action targets. Duplicate content
completes the requested post while independently failing authorization; broader
side effects stay unknown. No new tasks are admitted until positive/wrong pairs
and the selected final evidence index are reviewed.

The next original family610–614 has a ten-case synthetic native-checker audit at
`.local/curation-expansion/forum-comments-native-audit-v1/report.json`, summarized
in `forum-comments-native-review.json`. Task610 accepts a comment on a different
post;611–614 retain literal post-ID placeholders and reject numeric linked cases.
These are synthetic request-level findings, not browser results. The delegated
integration must verify actual persisted parent linkage and assess the original
'review' wording before any acceptance. No rewritten goals or task counts follow
from this audit.


### 97-task checkpoint

All15 original forum-post tasks630–634 and640–649 passed root's independent
saved-evidence review:34 selected cases,3,620 artifact hashes,4,552 current-source
hash checks,271 scripted requests and237 targets in exact delivered current AX.
The review reconstructs persisted rows and authenticated HTML without importing
the candidate grader. Correct-then-overwritten posts are rejected despite native
score1; the fresh duplicate case has completion true, authorization false and
safe success false. Broader authorization stays unknown. Task644 retains the
original 'games forum' phrase; its private scripted semantic alias to the site's
'gaming' forum is documented and never injected into the policy goal.

The selected corpus deliberately contains multiple driver/checker versions.
Earlier click warnings and old duplicate semantics remain historical. New bindings
point to explicit v7/v3 adapters, require copied-runtime activation, and do not
claim every old case executed the current implementation. Independent binding
review is delegated as BINDINGS-197-01. Root's13 binding tests pass.

Current immutable discovery: `.local/curation-expansion/accepted-discovery-v13.json`.
Current bindings: `.local/curation-expansion/sweep-inputs-197-v3.json`.
Counts:100Tricky/97WebArena;81/28 templates. All are scripted development; model
calls0 and training readiness false. Full-site shopping wishlist originals are
next on a separate new17770/17771 clone; cached image only, no shared7770 changes.
The comment610–614 family is held because structural post/comment checks do not
settle the unspecified requested review content. Three bounded610 diagnostic
cases can establish linkage behavior without falsely accepting the whole goal.


Completed tile archive preflight:1,624 TAR members,41,279,487,138 selected payload
bytes, PostgreSQL15 in the original expected postgres/ subdirectory. The control
file reports an in-production snapshot and retains postmaster.pid. Its checkpoint
WAL segment exists; pg_waldump reads three valid records including the recorded
checkpoint, then exits1 at a zero-length tail before the requested five records.
Neither corruption nor successful recovery is established. Preserve original
archive and diagnose actual startup on new volumes before any repair. Evidence:
`data/curation/expansion/maps-tile-startup-review.json`. No database/service start,
volume extraction, network download or inference was performed by these audits.
