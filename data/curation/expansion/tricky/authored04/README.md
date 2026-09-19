# Authored Tricky batch 04: AU61–AU79

Nineteen further project-authored instances: five shopping, five health, five
news and four music tasks. Nineteen template IDs occur in this batch, but only
**eleven IDs are new** across authored batches. Cart composition/quantity changes,
message drafts, chronological article lists, bookmarks, album joins, plan-price
comparisons and podcast filters retain their existing template IDs.

This reaches 79 authored instances if all four batches are independently
accepted. Combined with 21 separately validated original tasks, that meets the
100-task target; it does not mean 100 original upstream prompts or websites.

The additional operations include comparing product descriptions and review
ratings, reducing quantity under a basket budget, removing the largest line
subtotal, joining record/lab dates, copying the latest record into a draft,
joining appointment and record doctors, extracting numeric article facts,
comparing article content, choosing a plan by displayed account capacity, and
intersecting podcast categories. These use previously gated pages/controls;
no site, shared adapter or build was modified.

## Scope and grading

`contracts.json` separates public goals, setup, template/instance identity and
private expected values. All goals carry the response protocol. Integer counts
and money strings are type checked; draft fields use the **strict** comparator
introduced after independent review of authored03. Case, whitespace and missing
punctuation cannot satisfy the exact copied draft.

Cart/bookmark setup is explicitly synthetic, using full original product records
or existing news IDs. It runs once in each fresh session; reloads preserve actual
changes. Cart repair failures distinguish an unchanged initial excess from a new
unauthorized addition. Observed checkout, membership activation or message-send
history remains separate from completion.

Full authorization is still unknown where coverage is missing. No playback,
follow-state, unavailable download, persistent playlist-edit, working news-alert
subscription or calendar-scheduling claim is made. Health/news text is the site's
fictional/static content, not independently verified real-world advice. Source
license/reuse clearance remains unresolved. Tasks and evidence are
training-ineligible pending independent review and later model validation.

## Reproduce without inference

Use fresh output directories. The copied runtime must remain immutable.

```bash
.venv/bin/python -m unittest data.curation.expansion.tricky.authored04.test_authored04
CURATION_FROZEN_RUNTIME="$PWD/.local/curation-expansion/frozen-runtime-v1" \
.venv/bin/python data/curation/expansion/tricky/authored04/verify_reachability.py \
  --output .local/curation-expansion/tricky/authored04-reachability-NEW
CURATION_FROZEN_RUNTIME="$PWD/.local/curation-expansion/frozen-runtime-v1" \
.venv/bin/python data/curation/expansion/tricky/authored04/verify_native.py \
  --output .local/curation-expansion/tricky/authored04-native-NEW
```

The native runner uses `core-tools-v3`, MockTransport, fresh observations and
sessions, a 28-decision cap and a 48,000-**character** observation-text limit.
Every child has a 90-second bound. Copied core, task/helper sources and all served
assets are pinned before imports and guarded throughout each case/cohort.
Failures stop the cohort; there are no automatic retries or paid calls.

The plain site rehearsal at
`.local/curation-expansion/tricky/authored04-reachability-v1/report.json` contains
38 passing positive/negative cases. Native acceptance is separately indexed in
`validation-index.json` when complete; independent review remains a further gate.


Current native evidence is
`.local/curation-expansion/tricky/authored04-native-v1/report.json`: all 38
positive/negative cases pass, with zero action errors. `validation-index.json`
rechecks 2,158 original artifact hashes, 117 current-AX targets, 155 mocked native
requests and all 38 saved outcomes. Ten offline tests pass. Exact draft state,
answer literals, response protocol and grade-before-close evidence are retained.
Independent acceptance is pending; model calls remain zero.
