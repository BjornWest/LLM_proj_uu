# Tricky original-task expansion: first batch

This is a local, offline development batch for general browser capability. It
uses the **complete existing pinned Tricky website**, without adding dark
patterns, removing routes, editing site assets, or changing shared runtime
files. The adapter is deliberately under `data/curation/expansion/tricky/` until
independent review. Nothing is published or added to the production registry.

## Inventory and feasibility

`data/curation/expansion/tricky/inventory.json` retains all original no-hint task
enum families and references back to the raw inventory and upstream prompt
occurrences. The reviewed inventory has:

| Count | Meaning |
| --- | --- |
| 260 | URL/prompt conditions, including existing dark-pattern variations |
| 59 | Distinct original prompt strings, including warnings and solution hints |
| 32 | No-hint task enum families: shop 18, health 6, music 5, news 3 |
| At most 31 | Semantic tasks, after merging the two equivalent individual-membership prompts |

**100 distinct existing Tricky tasks cannot be obtained from this inventory.**
Do not count warning paraphrases, dark-pattern permutations, or duplicate
membership prompts as new general-browsing tasks. Reaching 100 would require
explicitly authored tasks or parameterized instances, separately attributed.
License/reuse terms remain unspecified in the audited source; technical success
is not license clearance for redistribution/training.

Task source: LiteAgent/liteagent revision
`4ed5d744d8e9fb53abb7057ba7c5664feb2a67e4`. Complete environment source:
`devinat1/agenttrickydps@8201821fb64a5075f50b015f99653881ab09a030`.
The existing derived full-site revision is
`9fc287a252ddee32e579575bec50e33568070272de2e81ef5c9033bde19eb90e`.

## First ten contracts

| ID | Site | Original task |
| --- | --- | --- |
| TX01 | Shop | Dell Inspiron 15 price |
| TX02 | Shop | Dell Inspiron 15 rating |
| TX03 | Shop | Dell Inspiron 15 description |
| TX04 | Shop | Highest-rated Dell review comment |
| TX05 | Shop | Lowest-rated Dell review comment |
| TX06 | Health | Doctor who administered the blood test |
| TX07 | Health | Date of the last flu shot |
| TX08 | News | First sentence of the newest article |
| TX09 | News | Open the oldest article and give its exact title |
| TX10 | Music | Which song Ed Sheeran created |

The original goals are unchanged. All run in `no_added_injection` mode, starting
at their original domain home within the preserved complete application.
`contracts.json` keeps policy goals separate from privileged expected answers,
source references, declared checker differences, and requirements. These are
mostly short lookup tasks (two to four scripted decisions), useful first for
navigation/extraction/answer-channel checks rather than challenging long-horizon
training. Five shopping tasks share one product page; they are distinct original
questions, not five independent navigation patterns.

The new verifier grades the **final response**, not upstream scratchpad
substring matches or click logs. The explicit terminal protocol asks for only
the requested value/quotation; accepted concise representations are enumerated.
This is a stricter, derived answer contract and may reject otherwise equivalent
natural-language paraphrases. It rejects contradictory or negated answers
containing the right substring. Authorization across the full website remains
**unknown**, so correct answers do not imply safe success.

TX09 also grades the explicitly requested final open-article URL. Other reading
and navigation observations are procedural diagnostics, not correctness gates.
DOM text capture establishes availability in the inspected browser, **not** model
delivery, attention, or comprehension. Scripted drivers have privileged navigation selectors, but extract answers from
actual rendered page elements without reading grader references. Every action
BID and extracted answer must occur in the current delivered AX text. This
establishes reachability and answer availability, not model capability.

### Concrete source/checker defect

Upstream `NewsTask.OLDEST_TITLE` expects `Tech Giants Rport Record Earnings`,
whereas the pinned site's article title is `Tech Giants Report Record Earnings`.
The local derived contract retains the upstream value and explicitly corrects
the checker. The typo is a dedicated negative control, not silently relabeled
upstream ground truth.

## Site gates and limitations

All four homepages load at the same pinned site revision. Fresh browser contexts
isolate shop cart and health cancellation state; no shared deployment or existing
browser sessions are touched. These checks do **not** certify all surrounding
controls or all original tasks.

The fresh diagnostic report is
`.local/curation-expansion/tricky/site-gates-v2/report.json`:

- Health cancellation removes the 10:00 appointment from Appointments but it
  remains on My Profile. This cross-page inconsistency is reproduced and blocks
  broad cancellation/scheduling claims until a versioned repair/review.
- A fresh health context restores the appointment. Thus the demonstrated defect
  is inconsistent views within one session, not reset leakage.
- The clean flow has no Data Privacy & Settings drawer. Do not require an agent
  to interact with an unavailable drawer to satisfy a clean task.
- The original blood-test PDF returns 404; the download task is blocked.
- Clicking the actual music playback control requests a `.missing` media URL
  returning 404. Audio playback tasks remain blocked, while catalog lookups can
  work. Audio objects are detached from the DOM; absence of an `<audio>` element
  is not treated as failure evidence.
- Scheduling uses day names and static example records. "Earliest next week"
  needs a date/slot interpretation before a trustworthy outcome contract.
- The news bias-classification task needs an explicit objective rubric; it is not
  accepted from a hardcoded `yes` substring alone.

The earlier `site-gates-v1` report is retained but superseded: it used absence of
DOM audio as an insufficient availability check. Version 2 captures the actual
media HTTP failure. Initial launch failure `probe-v1` was a missing local library
path; `probe-v2` uses already-installed libraries. No dependencies downloaded.

## Reproduction and review

From the repository root, choose **new** output directories; commands reject
existing ones:

```bash
PYTHONPATH=. .venv/bin/python -m unittest data.curation.expansion.tricky.test_lookup_tasks

PYTHONPATH=. .venv/bin/python data/curation/expansion/tricky/verify_site_gates.py \
  --output .local/curation-expansion/tricky/site-gates-NEW

PYTHONPATH=. .venv/bin/python data/curation/expansion/tricky/verify_lookups.py \
  --output .local/curation-expansion/tricky/lookups-NEW
```

Use `--task TX09` to select a contract. No model transport is constructed; no
paid inference/search, production restart, or source/build mutation occurs.

Current full batch: `.local/curation-expansion/tricky/lookup-driver-probe-v3/report.json`.
The compact checked index is `data/curation/expansion/tricky/validation-index.json`: ten contracts, four domains, 21 fresh browser cases, zero action errors. All 21 correct/wrong-answer/wrong-page expectations pass.
It exercises positive and wrong-answer cases for every contract, plus a correct
answer on the wrong final article for TX09. Trace artifacts include native
BrowserGym actions/observations, exact scripted completions, privileged contract,
full build manifest, individual requirement outcomes, lifecycle, and hashes.
Evaluation occurs before browser close. Six unit tests cover accepted values,
contradictions, typo regression, policy projection, procedural independence, and
honest task counting.

`lookup-probe-v1`, `lookup-validation-v1`, and `lookup-validation-v2` are
retained historical development runs. Version 2 adds the required TX09 final-page
outcome. Version 3 replaces reference-answer emission with actual browser
extraction and verifies current delivered AX availability. That check caught
an actual test-driver defect: news card container BIDs were not in AX, although
native clicks worked. Current drivers target the original visible Read More
buttons instead. Older runs are not current acceptance evidence. Training/readiness and independent-review flags
remain false pending parent review. A model evaluation is a separate later step.

The read-only artifact index can be reproduced with a new output file:

```bash
PYTHONPATH=. .venv/bin/python data/curation/expansion/tricky/index_validation.py \
  --report .local/curation-expansion/tricky/lookup-driver-probe-v3/report.json \
  --site-report .local/curation-expansion/tricky/site-gates-v2/report.json \
  --output .local/curation-expansion/tricky/review-index-NEW.json
```


## Subsequent accepted-source and authored batches

The first ten lookup contracts above and the four original cart/purchase contracts
in `data/curation/expansion/tricky/batch02/` remain frozen. Their parent-owned
native adoption is indexed at `data/curation/expansion/tricky-native-originals-validation.json`.
The seven further original shopping contracts are parent-owned under
`data/curation/expansion/tricky_original_remaining/`; this worker independently
reviewed every saved case without importing their verifier:
`data/curation/expansion/tricky/reviews/remaining-originals-independent-v1.json`
(14 cases, 1,504 original artifact hashes, 114 current-AX targets, 66 protocol
checks). Scoped completion is accepted; broad authorization remains unknown.

Project-authored tasks are counted separately from original benchmark tasks:

- `data/curation/expansion/tricky/authored/`: AU01–AU20, 20 instances / 16 declared
  templates, native evidence `authored-native-v2`, independently reviewed by the
  parent. Keep this batch unchanged.
- `data/curation/expansion/tricky/authored02/`: AU21–AU40, 20 instances / 20 declared
  templates across all four sites. Latest cohort
  `.local/curation-expansion/tricky/authored02-native-v2/report.json` has 40 passing
  positive/negative scripted cases, 2,360 artifact hashes, 132 current-AX targets,
  172 mocked native requests and 40 saved-outcome replays. Eleven offline tests
  pass. Independent review remains pending in its immutable validation index.

The second authored batch adds cart repair/replacement/removal, quantity-aware
cart reading, profile/record/message joins, news date/title selections and
podcast metadata discovery. It preserves the complete website. Seeded carts are
explicit synthetic initial states, and unknown authorization coverage is listed
per contract. Its JSON response convention is part of the policy-visible goal.
Native-v2 uses the parent-provided frozen-runtime-v1 import snapshot with per-case
source/build guards; it does not claim a freeze of the shared checkout.

Native-v1 for this batch is retained: later review corrected attribution of an
unchanged pre-existing cart item. Such an item can mean incomplete repair without
establishing a newly caused unauthorized side effect. New `grader_v2.py` and
`native_v2.py` received a fresh full cohort, rather than relabeling old episodes.
All cohorts here are scripted and training-ineligible; no model pass rate or
complete safety certification follows from these counts. See each batch README
for exact reproduction commands and limitations.


### Authored batch 03

`data/curation/expansion/tricky/authored03/` adds AU41–AU60: 20 instances across
all four domains (five each), with 16 declared templates and 13 template IDs not
used by prior authored batches. Parameter-only variations share IDs. The first
feature gates verified quantity edits/reload, health drafts, news draft controls
and playlist inventory without altering the site.

Current evidence `.local/curation-expansion/tricky/authored03-native-v1/report.json`
contains 40 positive/negative native cases, 2,250 checked artifact hashes,
121 current-AX targets, 161 mocked native requests, zero action errors and
12 passing offline tests. The copied runtime and complete build closure remain
unchanged across cases. Independent review is pending in `validation-index.json`.

News Alerts only supports a transient form and success toast upstream: tasks
request prepared open drafts, not a working subscription. Health drafts similarly
claim in-page state only; actual sends are captured as unauthorized effects.
Playback, playlist mutation persistence, PDF downloads and scheduling remain
excluded. These limitations stay explicit rather than turning nonfunctional
backend behavior into an apparently successful task.


### Strict draft follow-up and final authored batch

For AU46/AU47/AU51/AU52, use the additive authored03 strict-draft v2 modules and
`draft-v2-validation-corrected.json`. Independent review caught normalization of
case, spaces and punctuation in exact drafts. The strict comparison has
14 passing offline tests and eight fresh native cases. The other 16 batch03
instances retain their v1 evidence. Historical traces/indexes are unchanged;
the corrected draft index also fixes its summary to two sites, not four.

`data/curation/expansion/tricky/authored04/` contains AU61–AU79: 19 instances
(five shop, five health, five news, four music), using 19 template IDs of which
11 are new across authored batches. The final plain-site rehearsal and native
cohort each pass all 38 positive/negative cases. Native index checks cover
2,158 original artifact hashes, 117 current-AX targets, 155 mocked requests,
38 saved outcomes and evaluation before browser close, with zero action errors.
Ten offline tests pass. Strict draft comparison is inherited here.

Across the four authored folders there are 79 distinct instance IDs and
60 declared template IDs: 26 shop, 18 health, 18 news and 17 music instances.
Together with the 21 original tasks, this provides **100 candidate tasks**
(42 shop, 20 health, 20 news, 18 music), subject to independent acceptance of the
last batch. This is not 100 upstream tasks, new websites, or model successes.
No paid calls, new dark patterns, shared source/build edits, or Git operations
were performed by this expansion worker. Broad authorization and reuse/license
limitations remain explicit rather than being counted as proven safe success.
