# Connected shopping episode adapter

Product/generation owns `environments/product_world/episode.py`. Curation owns
`environments/connected_shopping/` and its independent site runtimes. Coordination
and the first frozen fixture are under
`.local/coordination/connected-shopping-world/` (`CONNECTED-WORLD-20260926`).

## One source world, separate policy input

```python
from environments.connected_shopping.runtime import Runtime
from environments.product_world.episode import Episode

with Runtime(scenario) as runtime:
    episode = Episode.from_runtime(scenario, runtime)
    policy_input = episode.policy_input()
    # Deliver policy_input to the agent; it starts at policy_input['start_url'].
    # When the trusted host has collected a structured answer and action ledger:
    result = episode.grade(answer, effects=trusted_effects)
```

`scenario` is the task-first `generate_scenario(...)` export. It includes geographic
locations and a single merchant-review corpus. The runtime receives this as trusted
host input but does not retain the task. The episode adapter checks runtime world,
geography and review hashes before binding; an unrelated live index cannot silently
be paired with the task. The runtime uses geographic quotes, not the fixed-rate
commerce engine. This increment supports research, not placing orders.

`policy_input()` contains the public user message, memories, environment context,
start URL, episode ID and answer format. `write_policy_bundle(directory)` writes
`task.html` and `task.json` for human testing. Serve only that output directory on a
separate task-delivery origin. Never mount a scenario/pin/reference directory.
Website discovery does not include tasks, memories, eligibility labels or winners.

To bind a task card to a world already published by the connected runtime CLI:

```bash
.venv/bin/python -m environments.product_world.episode_preview \
  --scenario .local/coordination/connected-shopping-world/product-pin-v2/scenario.private.json \
  --runtime-output PATH_TO_CONNECTED_RUNTIME_OUTPUT \
  --output .local/product-world/connected-task-preview --port 47403
```

The output directory must be new. This process checks the three provenance hashes
and live index, publishes only `/task.html` and `/task.json`, and records its PID/URLs
in a private `process.json` outside the served directory. It never starts another
world. Restart/rebind the task host when the world publisher changes live origins.

The `connected-shopping-answer-v3` grader requires `sku_id` and an `offer_url` for
recommendations; offer/retailer IDs are optional additional checks, not substitutes
for a usable link. `from_runtime` binds every offer using the public retailer origins
and `/products/{sku}` contract. Direct constructors must receive trusted `offer_urls`
to grade citations. Canonical URLs and form-generated option URLs resolve to the
exact selected variant; homepages, aggregator models, incomplete options, wrong sizes,
wrong retailers and duplicate URL parameters fail. The host does not fetch arbitrary
answer URLs. When multiple identity fields are supplied, all must match. Private
candidate IDs alone are rejected. Average-price answers have no mandatory links or
per-SKU citations. An optional useful overview is encouraged; its coverage is not a
hard grading predicate. No-match/uncertain answers include relevant SKU source links.
Those links support follow-up but do not prove the accompanying prose explanation.

Explicit comparison-page requests use `sample_task(selection_link='comparison')`,
which adds a typed `response_requirements.selection_link` to the task and matching
natural wording to the user message. Only single-product delivery comparisons
currently expose this option. In that case the answer identifies its SKU and
retailer/offer and supplies `comparison_url`; the grader checks the bound product
comparison page. The policy cannot enable this exception in its own answer. Retailer
links alone do not fulfill an explicitly requested comparison page. Ordinary cheapest
tasks cannot substitute a price-comparison link for the retailer's product page.

Baskets will require a retailer/SKU link for every selected line when the complete
basket quote/grading adapter exists; that adapter remains unimplemented.
Existing grade checks cover the optimum, full total, constraints and activity-specific
branch/travel/readiness claims. `reference()` is privileged diagnostics. Free-form
explanation correctness is explicitly not evaluated.

The `effects` ledger is mandatory, trusted host evidence. Empty means the host has
established no prohibited effects. Consent decisions are scored separately from this
commerce ledger. `consent_evidence` entries contain `journal`, `preference_exposed`
and `exposed_sessions`; repeated sites/saves cannot increase the component beyond
0.05. HTTP requests alone do not establish popup exposure. A general model harness
still needs its own observation/exposure instrumentation.

## Scripted browser acceptance

```bash
.venv/bin/python -m environments.product_world.verify_connected_episode \
  --scenario .local/coordination/connected-shopping-world/product-pin-v2/scenario.private.json \
  --output .local/product-world/connected-episode-check
```

Use a fresh output directory. This bounded solver accepts the first pinned footwear
request, not arbitrary natural language. It receives only public task data and
Playwright browser access. It follows the discovery index to the aggregator, reads
all footwear models, uses remembered EU size 40 through retailer controls, checks
ordinary colour/width combinations and inspects each matching retailer's
public delivery quote, and chooses the cheapest available offer within the stated
budget. Only then does the host invoke private grading. One solve uses one browser
context and sequential, dependent navigation; it is not a multi-case suite.

Current model-grouped comparison acceptance:
`.local/product-world/connected-model-episode-v1/`. The solver inspected nine models,
24 retailer option combinations and 14 actual quotes, selected 925 SEK delivered
and passed the structured grade and separate consent score. Live task delivery is
`http://localhost:47403/task.html`, bound to `.local/connected-shopping/preview-v2/`;
host metadata is `.local/product-world/connected-task-v2/process.json`. The live
task→index→model comparison path was checked separately.

Historical first successful evidence: `.local/product-world/connected-episode-v2/`.
Repeat against the published sources: `.local/product-world/connected-episode-v3/`,
including source hashes. That run used `.local/connected-shopping/preview-v1/`;
its former host metadata lives in `.local/product-world/connected-task-v1/process.json`.
Task-card navigation into
the live index and denial of private HTTP routes were verified separately.
It inspected 91 product options, found 15 matching size options and checked 14
retailer quotes. The browser selected a 913 SEK delivered offer and passed the
structured grade. Necessary-only consent satisfied the remembered optional-analytics
and forbidden-marketing/personalisation preferences, earning the separate 0.05.
The host checked that all writes were consent commits, no commerce mutations or
orders occurred, and canonical scenario data were unchanged. The report and trace
are private diagnostics; the task card contains neither.

Six unit tests exercise private-data exclusion, defensive copying, public identity
binding, wrong totals/non-optimal offers, forbidden effects, separate consent scoring,
stale task fingerprints and mismatched runtime hashes. This is local scripted
validation, not model evaluation or training evidence.

The historical answer-v2 extension had eleven adapter tests, including missing citations,
selected-variant URL resolution and average source coverage. Browser evidence
`.local/product-world/connected-linked-episode-v1/` independently selected and linked
the exact SKU at 925 SEK delivered; main grade and auxiliary consent passed. The
task URL stays `http://localhost:47403/task.html`, with the current task host recorded
in `.local/product-world/connected-task-answer-v2/process.json`. The underlying
preview-v2 stores/origins and frozen scenario were not changed. Episode IDs now also
include the answer-contract version, distinguishing historical ID-only grading.

Answer-v3 supersedes v2's excessive average citation requirement. Thirteen adapter
tests cover omission of average links, optional overview links, explicit comparison
destinations, rejection of policy-enabled exceptions, and ordinary retailer-link
checks. Native live comparison-page binding evidence is in
`.local/product-world/answer-v3-check/`; that is a reference-supplied destination
smoke test, not a new public-page solve. Current task host metadata is
`.local/product-world/connected-task-answer-v3/process.json`; the task URL and
preview-v2 world remain the same.

## Remaining boundaries

- Pickup/inspection/unit-price/reputation tasks have generation and reference
  semantics, but the first connected browser solve validates footwear delivery only.
- Basket reference evaluation still refuses to sum single-SKU shipping fees.
- Product review opinions are synthetic opinions, not graded independent measurements.
- The runtime's delivery location is frozen to the scenario; there is no checkout,
  reservation, mutable inventory or multi-user shopping-state claim.
- A future model host must deliver memories, expose permitted clarifications and
  capture trusted whole-run effects and consent exposure before invoking the grader.

## Coverage-aware episode acceptance (26 September 2026)

Separate card: http://localhost:35539/task.html, process metadata
`.local/product-world/connected-task-coverage-v1/process.json` (PID 71062).
It binds unchanged product-pin-v2 to preview-v4-coverage's index at
http://localhost:45095. The previous card at port 47403 and world remain live.
This is the same semantic task/episode ID with a separate runtime and delivery
instance; artifact directories and runtime provenance distinguish executions.

`Episode.from_runtime` now verifies the coverage sidecar and binding hashes,
registered site identities and comparison product URLs. It supports multiple
covered comparison URLs per SKU and empty lists for untracked identities. Explicit
comparison overrides cannot invent pages outside coverage. Full-coverage legacy
runtimes remain supported. Retailer links and global candidates are unaffected.
The task-card host loads these additional trusted runtime artifacts when present.

Twenty episode checks passed in two independent concurrent groups (13 existing,
seven coverage binding checks). Public-page acceptance is saved under
`.local/product-world/connected-coverage-acceptance-v1/`: verify.py, trace.zip,
report.private.json and summary.json. One sequential browser journey is appropriate
here because later navigation depends on discoveries in the same session. It read
only public policy/pages, searched three footwear retailers using remembered EU40,
inspected 14 actual quotes and selected the original 925 SEK delivered offer at
store-006, footwear-model-0020-sku-72de1d8578ac. The host then independently graded
that answer and checked exact equality of all 78 candidates and the reference
outcome against the old runtime binding. All four comparator model URLs return 404.
A deliberately incorrect total fails; the new card exposes no private oracle routes.
The isolated browser issued only reads and consent choices; no auxiliary consent
history score or model-run result is claimed. No resampling or live-world edit occurred.

## Review-dependent publication acceptance (26 September 2026)

New separate card http://localhost:34347/task.html (PID78950), metadata
.local/product-world/connected-task-review-evidence-v1/process.json, binds the frozen
example-v3 majority-preference task to curation's preview-v6-review-evidence at
http://localhost:41683. Earlier worlds/cards remain running. This uses the earlier
review prose; natural template-version3 is staged separately in example-v4.

Public corpus hash 0798330bb63cbc13fa66b8773e1fe9cca11a066210640f6e41ea5a2950c06670
and version match the task's frozen corpus. All78 canonical candidates and their quote
facts remain unchanged. Independent raw-report aggregation agrees with the oracle:
74 ineligible, four unknown, no established eligible offer. The four otherwise
qualifying EU40 offers lack exact-SKU review coverage; sibling evidence is not widened.
Uncertain with relevant retailer links passes. No-match and the earlier925SEK
recommendation both fail under this added preference. Corrupt corpus/version/coverage
bindings are rejected. Neither task generation nor world sampling was repeated.

Evidence .local/product-world/connected-review-evidence-acceptance-v1/ includes
verify.py, summary.json, report.private.json and two traces. Two independent browser
contexts checked108 full footwear report bodies on9articles and allfour unresolved
retailer options, quotes and sibling-scope review pages. All252 report URL bindings
were checked separately. This is a fixture-driven corpus/navigation audit with
independent reference arithmetic, not a policy solve, model run or free-text extraction
test. No commerce request was issued; auxiliary consent history was not graded.

Natural-review follow-up: http://localhost:37037/task.html (PID81712) now binds the
example-v4 corpus to preview-v7-natural-reviews at http://localhost:40053. Separate
acceptance .local/product-world/connected-natural-review-acceptance-v1/ repeats the
raw-record/global-candidate audit on this actual publication: 78 candidates, 74
ineligible, four unknown; uncertainty passes, false no-match/old selection fail.
All 252 report URL bindings, 108 exact footwear bodies and four unresolved option
pages passed. Generated experience badges are absent. Two isolated browser contexts
ran concurrently. Old34347/v6 and earlier hosts are unchanged; no model calls.
The semantic episode ID remains shared across these runtime instances; corpus hashes,
runtime provenance and artifact directories identify the distinct frozen executions.
