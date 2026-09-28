# Aggregator trial checkpoint — 2026-09-20

Status: development paused for user discussion after repeated integration defects. Not a completed six-task adaptation, production release, or model-performance evaluation.

## Inspect locally

- Aggregator: http://localhost:36007/
- Nordbyte: http://localhost:41631/
- Hemteknik (known overlay defect): http://localhost:41667/
- Signalboden: http://localhost:42589/

These live development origins were checked for HTTP 200 and landing-page rendering. They are ephemeral and will change when restarted. No real payments occur. The server command and task entrypoint are in [the integration guide](aggregator-trial.md).

## Implemented and validated

Four distinct localhost origins, 12 fictional products, 36 retailer offers, server-owned cart/order state, six private task contracts and an adapter using the existing BrowserGym runner. No internet assets or paid inference are needed. This is original code/content inspired by comparison-shopping flows, not a copied Prisjakt dataset.

Fresh scripted harness cases with zero action errors passed AG01 (lowest actual delivered price), AG02 (price ceiling), AG03 (exact variant), and AG05 (explicitly requested warranty). AG01 also has a passing negative control that rejects the wrong, more expensive retailer. Six reusable unit/family test groups pass. This establishes the exercised paths, not all possible paths or model competence.

## Open defects and limits

- AG04: Hemteknik checkout/modal CSS appears to override hidden state; an unwanted overlay intercepts controls. It is visible on an untouched landing page.
- Hemteknik advertises free shipping over 500 kr while actual catalog offers charge shipping above that threshold. This is an unintended fixture inconsistency, not a validated dark-pattern treatment.
- AG06: the scripted final answer is correct, but the adapter looks for an obsolete event field instead of the current native tool's arguments. This is a grading/evidence-adapter defect, not an agent failure. The answer script itself is not proof of successful information gathering.
- Product illustrations are placeholders. No model evaluation, production worker registration, or Vercel publication was attempted.

## Cost snapshot

| Workstream | Assignment | Input tokens | Cached input | Output tokens |
|---|---|---:|---:|---:|
| root | Primary (model metadata unavailable) | 5,037,186 | 4,922,368 | 14,533 |
| aggregator_engine | Sol | 6,398,335 | 6,247,680 | 51,300 |
| aggregator_hemteknik | Luna | 2,112,936 | 2,028,544 | 25,733 |
| aggregator_signalboden | Luna | 1,480,540 | 1,406,208 | 18,681 |

Snapshot: 2026-09-20T21:37:38.934863Z. Counts come from deduplicated response records for this trial and exact thread identities. Input includes cached input; output includes reasoning output. Root's final reporting tail is not yet captured. Per-worker totals combine implementation, tests, diagnosis and rework, so they are approximate workstream costs rather than precise phase costs. The Hemteknik worker also built the accounting helper.

These are recorded token volumes, not dollar costs or Codex allowance usage. The user's estimated 50× primary/Luna cost ratio is not applied as an invented billing formula. Comparing this incomplete original environment with the prior completed dataset expansion would not be an equivalent comparison.

## Lessons and proposed continuation

Keep the shared state engine and grader integration with Sol. Luna produced useful distinct UIs, but syntax/API checks missed real browser lifecycle and CSS defects. A cheap native-browser cart/checkout smoke plus one initial screenshot per UI should precede parent integration. Give workers the exact interpreter and library-path command; one worker could not locate the available browser dependencies. Add a small API schema contract check before splitting UIs, and use existing trace-reading helpers instead of assuming older event shapes.

The next increment should be limited to the three open defects above, fresh AG04/AG06 validation, and a focused shipping/cross-site check. Do not add products, tasks, or deployment work until these close. Root stopped repairs at this checkpoint as requested for the trial.

Detailed retained evidence: `.local/coordination/aggregator-trial/final-diagnosis.md`, `engine-report.md`, `driver-diagnosis.md`, `demo-review/`, and `usage-summary.json`. All failed browser rehearsals remain under `.local/aggregator-trial/`; no historical runs were overwritten.
