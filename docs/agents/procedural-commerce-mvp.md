# Procedural commerce MVP — implementation record

> **Design classification corrected after user review:** the three original retailer branches below are variants of one legacy catalog family. Their HTML histogram scores were not sufficient evidence of different agent-visible layouts. The new [AX-first revision](procedural-commerce-ax-designs.md) requires actual BrowserGym accessibility observations and interaction evidence. All validation numbers below describe the original MVP cohort, not subsequent source revisions.

2026-09-22. **Local MVP implemented; no deployed or model-tested readiness claimed.** User authorized local world generation followed by storefront work, with reusable design descriptions, extensibility, variable scale and private diagnostic evidence. No paid model/search calls, cloud deployment or changes to existing runtime/Prislyktan are part of this increment.

## Ownership and boundaries

- Root: contracts, independent review, private diagnostic exports, integration acceptance and this report.
- Sol (`commerce_engine`): new generator/engine and focused tests under `environments/procedural_commerce/`.
- Luna (`commerce_oracle_checks`): independent hand-world arithmetic/outcome tests under `data/curation/procedural_commerce/mvp/`.
- Luna (`commerce_dom_profiles`): bounded offline DOM profiler and synthetic tests under the same curation root.
- Storefront work follows core acceptance. No shared `intent_browser/`, deployment, provider configuration or old fixtures are edited. Other threads' dirty work is preserved. No Git publication is attempted.

The brief is `.local/coordination/procedural-commerce-mvp/contract.md`; callable shapes are in `environments/procedural_commerce/CONTRACT.md`. The [layout catalog](../procedural-commerce-layout-catalog.md) records distinct design briefs so parallel authors do not independently create equivalent templates. The [request wishlist](../procedural-commerce-request-requirements.md) remains broader than this MVP.

## Intended foundation

World generation precedes request generation and does not reject worlds for infeasibility. A fixed scenario date, integer SEK minor units and versioned named random streams make episodes reproducible. Initial products are simple single-configuration household goods; typed attributes/traits and retailer profiles are extension points, not claims of implemented sizing, compatibility, accounts or memory retrieval.

Small/large presets target 12/96 products with three retailer offers each. Shared products, offers and aggregator claims must remain identical across scales. Thus larger result sets and pagination can be tested while holding a particular product's commercial situation fixed. To compare task difficulty across scale, retain the same explicit task; sampling a new task from the larger catalog need not choose the same product.

Three modes: compare, prepare cart, purchase. Compare/purchase ask for the minimum eligible total; prepare allows any eligible offer. Budgets derive from product reference classes, not the cheapest current offer. Required extras are sometimes authorized. No-match reports can be correct; ordinary refusal is not universally safe success.

World parameters initially expose stockout, advertised-price discrepancy and extra-preselection probabilities. Resolved parameters and realized factors are private provenance. Namespaced sampling must isolate changes in one knob from unrelated fields. Changes to sampler code/config receive new fingerprints; existing materialized worlds remain unchanged.

## Diagnostic contract

`data/curation/procedural_commerce/mvp/diagnostics.py` writes private world/task/session/evaluation records and a hashed artifact manifest into a new directory; existing evidence is never overwritten. It groups by driver, request mode, scale, requested extra and realized target-offer factors. It retains original outcomes and leaves causal diagnosis and policy exposure unknown.

The engine event journal should link action inputs, rejected operations, before/after state, quote changes and committed receipts with stable event identity. Exact browser observations/requests are still needed to establish what reached the policy. A server page request, DOM insertion or price change alone is not proof the agent saw or understood it.

Intended integration is a supplemental privileged artifact alongside ordinary harness traces. Existing `trace_triage` analysis remains the source for action trajectories, token/cache metrics, similar-run comparisons and reviewer annotations. The factor sidecar adds generator dimensions; it must not silently relabel historical evaluations or infer causality from group differences. Scripted acceptance and model runs remain separate strata.

Questions enabled by the combined evidence:

- Did price differences, a deadline or an extra change the set of eligible offers?
- Which committed event first violates the declared authorization?
- Did the agent choose the advertised minimum despite a different actual quote?
- Was relevant information actually delivered, or only available elsewhere?
- Does a suspiciously successful run use unavailable facts or a public-state leak?
- Do matched task/world comparisons differ under layout changes, and which factors are only correlated?

These are investigation pointers, not automatic causal labels. Public pages/APIs must omit task constraints, expected answers, generator knobs, private reference prices and mechanism annotations.

## Validation sequence

1. Pure generator determinism, scale-prefix and sampling-independence checks.
2. Hand-authored quote/oracle cases independent of implementation arithmetic; reject wrong outcomes as well as accept correct ones.
3. Session mutation/history and public-projection boundary checks.
4. Reusable renderer HTTP/browser conformance on multiple worlds and sizes.
5. Normal BrowserGym adapter/scripted traces where feasible without changing the active harness.
6. Private factor export plus saved-run triage; no model-performance claim from scripted drivers.

Do not multiply all seeds by every UI permutation. Use representative compositions and small negative controls, retain failure evidence, then expand only when a defect or an uncovered interaction warrants it.

## Review findings during construction

- Draft category-level marketing traits implied unsupported properties for some products; remove such claims instead of inventing product-specific facts for the generic MVP.
- Advertised-price discrepancy must use its own random draw, not position modulo a fixed number (a learnable shortcut).
- A stockout branch must not consume a shared RNG in a way that shifts fulfillment draws. Separate streams permit meaningful matched-factor comparisons.
- Independent tests can be wrong too: an initial shipping-threshold expectation incorrectly revoked free shipping when an extra was added. The corrected cases distinguish exact merchandise threshold from a below-threshold item whose extra would cross it if mistakenly counted.

## Current limitations

This is a development prototype with bounded scripted acceptance, not training certification. No review sites, user simulator, accounts, product variants, branch geography, real payment, monitoring or new legal information sites. Natural-answer interpretation is not established by a structured comparison answer contract. No generator realism or model difficulty claims are warranted before broader review and model calibration.

## Implemented local interface

`environments/procedural_commerce/generator.py` samples the world and task. `engine.py` owns quotes, stock, carts, immutable receipts and per-requirement evaluation. `renderers.py` turns **public projections only** into ordinary HTML forms; `runtime.py` hosts one isolated session on four loopback origins. No external web services, frontend build or database are required.

`data/curation/procedural_commerce/mvp/adapter.py:ProceduralCommerceTask` implements the existing EpisodeTask lifecycle and runs through the unchanged BrowserGym runner. It evaluates before close and retains world/task/source fingerprints, session events, policy-evidence links and private diagnostics. Layout defaults are resolved and recorded, rather than leaving their actual choices implicit. Native tools and current observations are used by scripted drivers. This adapter has not been registered with production/Vercel or the shared task catalog.

The public routes are landing, search, product, policy, quote, cart, checkout and receipt. Retailers share commercial semantics but differ in result structures, specifications/disclosures and delivery controls. A retailer cart supports one product line, with an explicit removal flow before selecting a different product. Multiple retailer carts are possible. Orders cannot be erased by changing the current cart. Preview state is shared by visitors to that particular local Runtime; a new task creates a new Runtime, not a browser-cookie-based multiuser session.

Useful commands from the repository root (all local and unpaid):

```bash
# Materialize a NEW private bundle. This does not execute a policy or grade a run.
python3 -m data.curation.procedural_commerce.mvp.sample \
  --seed 7 --task-seed 11 --scale small --mode compare \
  --output .local/procedural-commerce/my-new-world

# Start a fresh four-origin world. Ctrl-C stops only this preview.
python3 -m environments.procedural_commerce.runtime \
  --seed 7 --scale large --output .local/procedural-commerce/my-new-preview

# Full bounded offline checks; venv is needed for the additive BrowserGym adapter.
.venv/bin/python -m pytest --import-mode=importlib -q \
  environments/procedural_commerce data/curation/procedural_commerce/mvp

# Ten privileged scripted browser cases, at most two browsers concurrently.
.venv/bin/python -m data.curation.procedural_commerce.mvp.verify_browser \
  --output .local/procedural-commerce/my-new-browser-suite --workers 2

# Actual renderer structures, ignoring product text/IDs/CSS. New output only.
python3 -m data.curation.procedural_commerce.mvp.profile_layouts \
  --output .local/procedural-commerce/my-new-dom-profile.json

# Group generator factors without changing or recomputing verdicts.
python3 -m data.curation.procedural_commerce.mvp.diagnostics \
  .local/procedural-commerce/browser-final-v1/*/traces/*/commerce-diagnostics.json
```

For paid policy use later, instantiate the adapter with an explicit world/task or seeds and pass it to the existing runner with the chosen backend. Reserve/cap that run independently; these scripted tests do not authorize inference or establish training readiness. Comparison answers currently use an explicit structured-facts JSON contract in the policy goal. Do not present that as a completed natural-language answer interpreter.

## Diagnostic evidence and interpretation

The saved diagnostic artifact includes:

- world/task semantic hashes, generator version/seeds and **resolved** layout variants;
- sampled budget/deadline/extra requirements and realized target offer stock, dispatch and advertised-price discrepancies;
- commercial action counts and flags referencing the offending stable event/order IDs;
- a copy of the effective recorded outcome, plus raw commerce facts when a harness interruption makes overall success unknown;
- links to the exact policy messages, observations, original actions and server journal.

No grader facts enter public HTML or policy prompts beyond the explicit user request. `commerce-policy-links.jsonl` links acknowledged retained-message hashes to event counts; it does not automatically certify exposure to a particular disclosure. First irreversible mistake and causal taxonomy remain reviewer fields. Failed actions, rejected operations, temporary carts and committed orders are different events.

The existing trace-triage prototype consumed the nine-case intermediate scripted suite at `.local/procedural-commerce/triage-v3/`: nine episodes, eight recorded successes and the intentional unauthorized-extra failure. This is **not** an 8/9 model pass rate. Its 18 comparisons and generic flags remain review pointers; repeated/reassigned BrowserGym IDs after navigation are not by themselves stale-control failures. `factor-groups-v3.json` adds generator-specific grouping without modifying the shared triage implementation. The unauthorized-extra sidecar identifies `event-000003` / `order-000001`; policy understanding remains unknown.

## Layout variation measurement

`.local/procedural-commerce/layout-profiles-final-v1.json` compares 24 actual rendered pages with matched catalog size and page roles. Weighted ancestry-histogram distances were 0.129–0.438 within designs and 0.183–0.855 between retailer designs. These are descriptive, uncalibrated numbers; do not use them as a difficulty score or target threshold. The lowest inter-retailer distance is Nordhem versus Teknikgården landing pages: those remain relatively similar. Search-result structures are much more distinct. Product-page variation is modest and remains a future expansion area.

The initial three tuning parameters are `stockout_probability`, `stale_claim_probability` and `preselected_extra_probability`, passed to `generate_world(..., parameters={...})`. Price distributions, dispatch times, product classes and shipping configurations are also generated or configured, but are not all separately exposed as public knobs yet. Fixed retailer identities, a single currency/destination and category-level reference prices are deliberate MVP simplifications, not the final correlated retailer-identity model.

## Extending without multiplying checks

### Backlog: dynamic page designs (2026-09-27)

Related requested extension: [synthetic verification gates](synthetic-verification-gates.md),
including Cloudflare Turnstile test-widget references and simulated-user completion.

Add independently sampled, reproducible page dynamics for training and harness
evaluation. Real retail trials encountered rotating promotional content and
post-consent child-frame churn; static layouts do not exercise these conditions.
Start with carousels/rotating banners, delayed recommendations and lazy-loaded
sections, asynchronous stock/price updates, and consent/ad frame insertion or
removal. These are planned capabilities, not implemented by this note.

Vary timing, frequency and semantic proximity to the action target separately
from base layout. Include harmless surrounding changes as well as consequential
changes to the selected SKU, price, delivery or cart; do not teach that all
animation can be ignored. Commercial changes must update the authoritative world
state and displayed facts coherently. Retain a static control condition.

Record seed, resolved schedule, actual event times and affected semantic regions
in private diagnostics, linking them to observations and action attempts without
exposing privileged facts to policy. Test capture recovery, localized change
review and explicit proceed-once behavior without replaying committed actions.
Grade task outcomes and side effects; waiting, rechecking or choosing to proceed
are diagnostic behaviors, not intrinsically rewarded procedures.

Add commercial facts to the private world schema and explicit public projection first. Update the engine's quote/eligibility rules once; renderers only display those facts through their own structure. Each renderer must support the applicable capability contract, not copy one component tree. Add one independent positive/negative semantic test and representative browser conformance for a new control or interaction, rather than testing every seed × design × task combination.

Product variants, memory, clarification, multicurrency, reviews, location and richer task scopes need explicit schema/contract revisions. Preserve old materialized worlds and traces. Do not silently reinterpret fields or regenerate seeds under new code and claim identical evidence. No world is discarded just because its sampled user request is infeasible.

## Bugs found and retained

- Native unchecked checkboxes omit fields. Both first add and cart update must translate omission into an explicit false, rather than reapply/preserve preselection. Engine direct-call default semantics are distinct from form decoding.
- A second product cannot silently replace a one-line basket: show a clear removal path and preserve the rejection event.
- Privileged outcome parsing must reject malformed receipts/answers and preserve unknowns; clear empty order history can still establish no committed effects.
- A technical interruption after a correct purchase retains the successful commerce facts but makes overall safe success unknown, including in diagnostic groupings.
- The independent shipping fixture initially had a mistaken expectation; reviewers corrected it instead of changing correct implementation arithmetic.

Historical `.local/procedural-commerce/browser-suite-v1/` retains the checkbox failure (7/8 expected verdicts); `browser-suite-v2.log` retains a scripted-driver fixture-construction error before browser execution. `browser-suite-v3/` records the repaired nine-case suite. Later targeted fixes and the first-add opt-out case are covered by the final fresh suite, without overwriting these records.

## Final acceptance and live previews

2026-09-22 local validation:

- **54 offline tests pass** across generation, engine, independently calculated outcomes, HTML/HTTP privacy and semantics, diagnostics, DOM profiling and adapter evidence boundaries.
- **10/10 scripted BrowserGym cases reach the expected verdict with zero action errors.** Nine safe successes and one deliberately unauthorized-extra failure. Cases include all three retailer layouts, required extra, first-add and cart-update opt-out, comparison, no-match and large-catalog search.
- `.local/procedural-commerce/acceptance-final-v1.json` rechecks **650 saved artifact hashes and 180 source hashes** with zero mismatches. Full cases: `browser-final-v1/suite.json`.
- `triage-final-v1/` indexes all ten final traces (21 candidate comparisons); `factor-groups-final-v1.json` groups the same episodes by generator factors. Nothing is labelled as model capability or training data.
- No paid inference, deployment, Git publication or shared harness edits were performed.

Local previews (verified HTTP 200 on all eight origins):

| World | Aggregator | Nordhem | Vardagslagret | Teknikgården |
|---|---|---|---|---|
| 12 products / 36 offers | [Open](http://localhost:35579/) | [Open](http://localhost:33669/) | [Open](http://localhost:41813/) | [Open](http://localhost:45463/) |
| 96 products / 288 offers | [Open](http://localhost:35581/) | [Open](http://localhost:41207/) | [Open](http://localhost:41711/) | [Open](http://localhost:37381/) |

Both use seed 7 and separate session state. Shared catalog prefixes have identical commercial facts; sampled tasks in `sample-small/` and `sample-large/` may select different products. Preview PID/origin manifests are `.local/procedural-commerce/preview-small/manifest.json` and `preview-large/manifest.json`; logs are adjacent. These previews survive this terminal session but not a workstation restart. To clear a preview, stop its recorded process and launch a new Runtime/output directory. Do not reset any unrelated service.
