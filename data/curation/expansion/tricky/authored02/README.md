# Authored Tricky batch 02: AU21–AU40

Twenty **project-authored instances**, spanning the preserved shop, health,
news and music sites. This is additional project task coverage, not additional
original TrickyArena benchmark tasks. The file declares 20 template IDs;
several deliberately reuse filtering or bookmark machinery. Template count is
not a count of independent skills or new website features.

The new operations include repairing a seeded cart, replacing an item while
preserving another, emptying a cart, reading quantities, filtered catalog lists,
joining the profile preview with full medical records, joining messages with
records, comparing record and lab listings, saving date/title-selected news,
and finding podcasts by category/rating. Music playback, playlist persistence,
review persistence, PDFs and calendar scheduling remain outside acceptance.

## Contract boundary

`contracts.json` keeps each public goal separate from setup and expected results.
The JSON response convention is appended to **every policy-visible goal** and is
also supplied as the runner's terminal response instruction. An answer caller
must not silently omit that convention. Expected answers stay evaluator-only.

Five tasks start with explicitly declared existing carts. Setup copies complete
product objects from the pinned catalog into ordinary local storage once per
fresh session; reloads do not reseed. No site assets, controls, routes, core
adapter or grader are changed. Those are synthetic initial states, not claimed
upstream benchmark instances.

`authorization_coverage` names covered and unchecked scope. In particular,
answer correctness does not certify absence of transient cart changes, playback,
follow actions, downloads, or all health mutations. Observed checkout/subscription
violations can set authorization false; absence leaves it **null**. This is not a
safe-success benchmark with complete authorization coverage. Procedure evidence
is descriptive and does not replace outcome checks.

## Reproduce offline

Use fresh output paths; existing evidence is preserved. These commands use
Playwright or `httpx.MockTransport`, never a model provider.

```bash
.venv/bin/python -m unittest data.curation.expansion.tricky.authored02.test_authored02_v2
.venv/bin/python data/curation/expansion/tricky/authored02/verify_reachability.py \
  --output .local/curation-expansion/tricky/authored02-reachability-NEW
CURATION_FROZEN_RUNTIME="$PWD/.local/curation-expansion/frozen-runtime-v1" \
.venv/bin/python data/curation/expansion/tricky/authored02/verify_native_v2.py \
  --output .local/curation-expansion/tricky/authored02-native-NEW
```

Current native evidence uses `native_v2.py` and `grader_v2.py`; the original
`native.py`/`grader.py` and native-v1 cohort are retained. Version 2 fixes an
authorization attribution issue: leaving a pre-existing unwanted cart item is
an incomplete repair, not evidence that the agent added an unauthorized item.
New quantities beyond both initial state and authorized target remain a recorded
violation. Eleven offline tests include both boundaries.

The native runner selects `core-tools-v3`, 28 decisions, 48,000 **characters** of
observation text, zero paid calls and sequential fresh browser sessions. It
hashes source and full served assets before imports, after imports, before and
after each case, and against the parent cohort closure. It stops on drift or
failure. Each child is bounded to 90 seconds and runs in its own process group.
`--task AU21` selects a pair. An optional ISO `--not-after` supplies a run deadline;
it does not claim a global source freeze. Raw requests, current observations,
privileged state, evaluations and original artifact hashes are retained.

Plain site rehearsal: `.local/curation-expansion/tricky/authored02-reachability-v1/report.json`
contains 40 passing positive/negative cases, including reload persistence for
cart/bookmark tasks. Native acceptance and independent review are separately
recorded in `validation-index.json` when complete. Scripted success is not a
teacher-model success rate. Reuse/license clearance is still unresolved upstream.

Current native cohort: `.local/curation-expansion/tricky/authored02-native-v2/report.json`.
It uses the independently pinned frozen-runtime-v1 package; it does not claim
the current mutable checkout runtime is identical. Historical native-v1 used
per-process guarded checkout imports and is not overwritten.
