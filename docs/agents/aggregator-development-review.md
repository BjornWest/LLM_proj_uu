# Aggregator development and usage review

| Work | Model | Uncached input | Cached input | Output | Standard API equivalent |
|---|---|---|---|---|---|
| Primary / review | gpt-6-astra | 181,527 | 8,661,248 | 26,021 | $11.78 |
| Shared implementation | gpt-5.6-sol | 199,750 | 11,332,096 | 74,356 | $6.82 |
| Two UI workers | gpt-5.6-luna | 171,836 | 4,214,272 | 49,995 | $0.18 |
| Backend thread | gpt-6-astra | 396,635 | 15,766,784 | 68,557 | $23.16 |

## Scope

Frozen usage window: 2026-09-20 21:11:58.084 Z to 22:12:31.273 Z, about 61 minutes (23:11 on 20 September to 00:12 on 21 September in Stockholm). This covers initial construction, the product-page/server follow-up, deployment discussion, and the search-first homepage increment. Earlier planning and this retrospective are excluded. Backend is compared over the identical window, not its lifetime. Only coding-agent usage is counted, not application model calls or external tool charges.

## Division of work

Luna implemented the Hemteknik and Signalboden retailer UI triples and later the promotional homepage. Sol implemented the server/state engine, catalog, aggregator/reference retailer, task adapter, graders, scripted drivers, browser validation, dedicated product pages, and search-first integration. Astra handled initial specification, coordination, semantic review, visual review, and the detached-server/fixed-port repair. The UI cost includes the small usage-accounting helper; workstream totals do not precisely separate coding from repair.

## How independently did Luna work?

Luna produced distinct, usable-looking layouts from the written API/design contract without a wholesale rewrite. Its later homepage change integrated and passed shared browser tests. It was less reliable at establishing correctness: Signalboden removed status DOM nodes then referenced them; Hemteknik CSS exposed hidden overlays; its free-shipping banner contradicted server prices. Luna fixed the Signalboden DOM issue after diagnosis, but did not successfully run the requested browser smoke itself. The browser-environment failure recurred even when given the repository interpreter instructions; Sol subsequently ran the checks. This is a small task-specific sample, not a general capability benchmark.

## Other sources of rework

Sol also needed corrections: the public offer initially omitted product_id, scripted selectors were ambiguous, and initial grading conflated missing requested actions with unauthorized effects. Root caught an unstated cheapest-price requirement, unnecessary compare-only cart restrictions, and non-atomic rejected warranty updates. The original demo process disappearing was a launch/lifecycle problem handled by root; there was no recorded exception proving an application crash. These defects should not all be attributed to Luna. AG 04 and AG 06 still have previously documented unresolved acceptance defects; the website is not a fully certified six-task environment.

## Comparison

Curation total:24,760,729 input tokens (24,207,616 cached;553,113 uncached),150,372 output,270 responses. Backend:16,163,419 input (15,766,784 cached;396,635 uncached),68,557 output,106 responses. Curation used 2.19 times as many output tokens and 2.55 times as many responses, but its standard API equivalent was$18.78 versus$23.16—about 19% lower. These were different jobs, so this is a cost/accounting comparison, not evidence that one team is 19% more productive. Five backend descendants were discovered, but none had usage in this window.

## What drove the estimate?

Root accounts for about 63% of our estimated cost, Sol 36%, and both Luna workers together about 1%. Luna produced roughlyone-third of the output tokens. Repeated input matters:97.8% of our input was cached, yet cached input still accounts for most of the estimated spend. Repricing our identical recorded requests entirely at Astra rates would be$37.26; this is a pricing counterfactual only, not a claim that an all-Astra implementation would follow the same steps.

## Pricing assumptions

Published Standard rates per 1 M tokens (uncached input / cached input / output): Astra$10/$1/$50; Sol$4/$0.40/$20; Luna$0.20/$0.02/$1.20. Estimate=(uncached×input rate+cached×cached rate+output×output rate)/1,000,000. Reasoning tokens are already inside output and are not charged twice. All 376 records explicitly report zero cache-write tokens; no request exceeded 272 k input. Service tier is absent from these logs. Fast-mode API equivalents would be twice the displayed estimates. These are not invoices, Codex allowance measurements, or a claim about the internal cost of the subscription. Rates checked 21 September 2026.

## Next trial

Keep Luna for bounded UI/catalog work with a fixed API contract. Supply one working browser-check command and require a landing screenshot plus a native cart/checkout smoke before handoff. Have Sol own everyday coordination/integration and reserve Astra for an initial contract review and one final semantic audit. Use fresh short-context workers for new bounded increments; avoid repeatedly reading the long parent conversation. Consolidate test results rather than duplicating checks. The remaining expensive skill here was integration and verification, not generating more HTML.

## Evidence and reproducibility

Metadata-only audit script and frozen JSON: .local/coordination/aggregator-trial/cost-comparison-v 1/audit_usage.py, usage-comparison.json and price-comparison.json. Records use exact thread IDs, first session metadata, explicit ancestry and globally deduplicated response IDs. No cumulative token_count events are summed. Model identities resolve from per-record/turn metadata. No unknown models, duplicate IDs, malformed lines or missing response IDs were found; thread/model/phase aggregates agree. Original defect ledger: .local/coordination/aggregator-trial/engine-report.md; latest browser evidence: .local/aggregator-trial/search-first-v 1/validation.json. Earlier 112 k-output initial checkpoint is a subset, not a competing estimate.

Pricing source: [OpenAI API pricing](https://developers.openai.com/api/docs/pricing).
