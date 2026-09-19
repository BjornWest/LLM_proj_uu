# Authored Tricky batch 03: AU41–AU60

Twenty project-authored instances, **five per domain**, using 16 template IDs.
Quantity-edit, message-draft and alert-draft parameter variations share template
IDs. Several templates also reuse earlier batch IDs; the contract file records
which IDs are new. These counts describe task instances, not original upstream
benchmark tasks or independent website features.

The source-preserving feature gate exercises quantity input plus reload, health
message drafts, News Alerts email/frequency controls, and playlist inventory.
No website assets were modified. `authored03-site-gates-v2/report.json` records
all four passing. The earlier v1 gate is retained: its shopping driver attempted
to add Bluff before searching, so the product control was not present. Adding
the ordinary search action fixed the driver, without changing the site.

Tasks cover cart quantity edits and budget-aware additions/replacements;
medical-record-to-draft copying and appointment/message joins; news form drafts,
article search and seeded saved-news histories; podcast filtering/comparison,
playlist inventory and artist-catalog comparisons.

## Deliberate limits

- News Alerts' original Save action only displays a success toast. It does **not**
  persist an alert subscription. AU51/AU52 request an open draft form only;
  they do not claim that saving alerts works. Fields/final page are graded,
  submission/backend persistence remains explicitly unchecked with authorization
  unknown. Message drafts likewise are final in-page state, not durable drafts.
- Health message sends are observed by the unchanged source instrumentation;
  a sent-message journal event is an unauthorized effect for these tasks. The
  draft may still meet its field outcome, so completion and authorization remain
  distinct.
- Playlist **inventory reading** is exercised. Playlist addition persistence,
  playback, unavailable PDFs, calendar scheduling, and the stale profile
  appointment preview remain excluded. No known broken flow is silently repaired
  by shrinking the website.
- Cart and news initial states are explicitly project-authored setup, applied
  once per fresh session. Reload does not reseed. Existing bookmarked articles
  must survive tasks that request adding another.
- Every public goal includes the response convention. Expected values, seeded
  setup and verifier state are not policy fields. Broad authorization remains
  null unless a scoped violation is observed.

## Offline reproduction

Choose new output paths; no provider transport or paid calls are used.
The accepted batch has two versioned closures: 16 non-draft instances use v1;
AU46/AU47/AU51/AU52 use strict-draft v2. Do not run the unfiltered v1 wrapper
as current acceptance for the draft tasks.

```bash
.venv/bin/python -m unittest data.curation.expansion.tricky.authored03.test_authored03_v2
# Sixteen accepted non-draft instances retain the original adapter.
CURATION_FROZEN_RUNTIME="$PWD/.local/curation-expansion/frozen-runtime-v1" \
.venv/bin/python data/curation/expansion/tricky/authored03/verify_native.py \
  --output .local/curation-expansion/tricky/authored03-nondrafts-NEW \
  --task AU41 --task AU42 --task AU43 --task AU44 --task AU45 \
  --task AU48 --task AU49 --task AU50 --task AU53 --task AU54 \
  --task AU55 --task AU56 --task AU57 --task AU58 --task AU59 --task AU60
# Four draft instances require the independently accepted strict comparator.
CURATION_FROZEN_RUNTIME="$PWD/.local/curation-expansion/frozen-runtime-v1" \
.venv/bin/python data/curation/expansion/tricky/authored03/verify_native_v2.py \
  --output .local/curation-expansion/tricky/authored03-drafts-v2-NEW \
  --task AU46 --task AU47 --task AU51 --task AU52
```

Native settings: `core-tools-v3`, 28 decisions, fresh observations, 48,000
**characters** maximum observation text, fresh sessions, MockTransport, bounded
90-second child processes. Copied runtime, task/helper sources and all served
assets are fingerprinted per process and checked against the cohort. Drift or
failure stops the run. There are no silent retries.

Plain site rehearsal is recorded in
`.local/curation-expansion/tricky/authored03-reachability-v1/report.json`:
40 positive/negative cases pass, including persisted cart/bookmark states after
reload. That plain site-rehearsal script retains its historical v1 grader and is not
a current strict-draft acceptance command. Native evidence and independent review
are separate. Contracts remain
training-ineligible and do not establish any teacher-model pass rate.


The historical full native cohort is
`.local/curation-expansion/tricky/authored03-native-v1/report.json`; the compact
`validation-index.json` rechecks 40 outcomes, 2,250 original artifact hashes,
121 actual current-AX targets and 161 mocked native requests. All cases have
zero action errors and evaluation before browser close. Twelve offline tests
pass. The index also verifies answer literals and prepared draft fields in
retained policy-delivered observations; derived arithmetic is checked separately.
Its 16 non-draft instances retain independent acceptance; the four draft instances
are superseded by the separately accepted v2 evidence below. This quantity-input validation applies to
the preserved full-site path and this profile, not every historical fixture.


## Strict draft correction (v2)

Independent review found that the original general answer comparator also
normalized draft case, spaces and punctuation. `grader_v2.py` now compares
all draft fields strictly, including message punctuation and email spelling.
`native_v2.py` / `verify_native_v2.py` preserve the original files. Fourteen
offline tests include missing-period, case, extra-space and email regressions.
Eight fresh cases cover AU46/AU47/AU51/AU52 at
`.local/curation-expansion/tricky/authored03-drafts-native-v2/report.json`;
`draft-v2-validation-corrected.json` is the current compact proof. The previous 40-case cohort
and index remain unchanged. For draft tasks use v2; the other 16 instances retain
their original independently reviewable source closure.

The corrected compact index is `draft-v2-validation-corrected.json`. The first
draft-only index inherited a hardcoded four-site summary; the actual four draft
instances span two sites (health/news). Recomputed indexing corrects that count
without changing browser evidence, outcomes, or the earlier index bytes.
