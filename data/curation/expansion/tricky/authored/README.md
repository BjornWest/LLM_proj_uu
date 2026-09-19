# Twenty authored general-browsing instances

These tasks are **project-authored**, using existing verified pages of the
complete pinned Tricky site. They do not increase original benchmark coverage.
There are **20 instances / 16 templates**, across shop (8), health (4), news (4),
and music (4). Original batches 01 and 02 remain unchanged.

The goals cover two-product price/review comparisons, constrained catalog
selection, composite carts, cross-page dates, record aggregation, persistent
news bookmarks, multiple article quotations, chronological filtering,
artist/catalog joins and plan-price arithmetic. No dark patterns, source-site
changes or reduced fixtures were introduced. Broken review/playlist persistence,
audio playback, appointment mutation and PDF downloads are excluded.

`contracts.json` separates the public goal and task parameters from expected
outcomes. `template_id` and `instance_id` are explicit. For example, three
composite-cart instances share one template; two filtered catalog questions
share another. We do not call these five independent task mechanisms.
`source-facts.json` is private reference data extracted from the pinned source,
never a policy asset. Its presence does not change what the website serves.

Answer tasks use a declared structured response convention: JSON with the keys
named in the goal; money is a two-decimal string. Each expected field is graded
separately. Cart/bookmark tasks grade stored state; news bookmarks also require
the explicitly requested final page. Completion remains separate from observed
unauthorized purchases/subscriptions/extras. Broader authorization is unknown,
not automatically true. Procedure evidence does not impose a preferred path.

## Site gates and rehearsals

`solver.py` reads actual rendered pages and emits ordinary click/fill/press
instructions. It never reads `grader_input` or `source-facts.json`. Negative
answer cases change an extracted answer; negative cart/bookmark cases perform
an actual extra browser action. News bookmarking is an existing site feature;
its state and cart state are additionally checked after full reload.

The Playwright reachability reports are explicitly separate from native harness
acceptance. `.local/curation-expansion/tricky/authored-reachability-v3/report.json`
retains 38 passing cases and two failures caused by a mistaken authored product
name. The goal was corrected to the actual `Brita Premium Filtering Water
Bottle`; those two cases pass in `authored-reachability-v4/report.json`.
Earlier v1/v2 attempts are retained diagnostics: CSP disallowed the string
wait predicate; then the driver expected an aria attribute dropped by the
upstream link wrapper. No site behavior was changed to make these checks pass.
The stalled v2 diagnostic was stopped after a graceful interrupt did not finish.

## Native BrowserGym validation

`native.py` is an additive EpisodeTask adapter under curation, with final
independent evaluation before browser close. `verify_native.py` uses the real
**core-tools-v3** request/parser/action path with `httpx.MockTransport`; it makes
zero provider calls. Each case runs in a bounded child process and records
source hashes before/after; the coordinator rejects source drift or expiry of
its declared run window. Native actions must target BIDs in current delivered AX.
Do not infer model ability from privileged scripted navigation plans.

The current full cohort is
`.local/curation-expansion/tricky/authored-native-v2/report.json`.
The earlier native-v1 report is a two-case AU01 probe. Evidence has its original
source closure even if backend development subsequently changes the checkout.
Seven unit tests cover origin/counting, strict answer types, unwanted effects,
cart quantities, bookmark final page, reference arithmetic and excluded features.

Commands from the repository root (always choose new outputs):

```bash
PYTHONPATH=. .venv/bin/python -m unittest data.curation.expansion.tricky.authored.test_authored
PYTHONPATH=. .venv/bin/python data/curation/expansion/tricky/authored/verify_reachability.py \
  --output .local/curation-expansion/tricky/authored-sites-NEW
PYTHONPATH=. .venv/bin/python data/curation/expansion/tricky/authored/verify_native.py \
  --output .local/curation-expansion/tricky/authored-native-NEW \
  --not-after REVIEWED-ISO8601-UTC-DEADLINE
```

The native command deliberately defaults to the original coordinated deadline;
future runs require an explicitly reviewed closure/window, not a silent reuse of
that readiness. `--task AU13` selects one task. No paid model is instantiated.
Independent review and training/readiness flags remain false until acceptance.
No production registry, deployment, shared runtime or historical task was edited.

### Response-format delivery boundary

The accepted cohort runner explicitly supplies
`terminal_response_instruction=task.data['policy_response_protocol']`.
`response-protocol-evidence.json` checks that the exact convention, including
JSON objects and two-decimal monetary strings, appears in the saved **system
message of all 175 requests**. It was not hidden in grader metadata.

A caller constructing `AuthoredTask` directly must also bind that convention;
`policy_goal` alone contains the human goal, and the adapter does not currently
enforce the caller's terminal instruction. Do not register it in a new generic
caller without preserving this binding or introducing a separately versioned
public-goal convention. This is a future integration boundary, not a claim that
the existing cohort omitted its answer protocol.

Current checked index: `validation-index.json` records 20 authored instances,
16 templates, 40 passing native browser cases, 2,390 artifact hashes, 135 current
AX action-target checks and 175 mocked native requests. All source closures
matched the cohort and each process before/after. No teacher/model API calls.
