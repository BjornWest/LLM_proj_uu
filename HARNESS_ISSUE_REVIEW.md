# Harness review after private demo preparation

The Vercel demo was prepared and pushed first, at `12cca8c`. The existing Python harness and calibration fixtures were not changed. This review independently checked saved artifacts and installed source; it made no model or browser calls.

## Findings checked

| Issue | Independently checked evidence | Next change |
| --- | --- | --- |
| Observation capture precedes wrapper pacing | All 12 W01 requests match the budget ledger. Five failed Close IDs occur in the exact delivered AX text. Minimum observation age at dispatch is 9.09–9.15 seconds; pacing totals 100.94 seconds. | Introduce a pre-observation pacing boundary, then capture fresh BrowserGym observations before constructing the prompt. |
| Repeated successful additions | The second Add repeats the first successful Add before any stale-control error. | Keep separate from timing. Test improved generic action/effect history only after isolating pacing in a new cohort. |
| Chaos blur/submit race | Installed frontend hash matches the curation record. Source emits input on blur and discards interactions while its async handler is occupied. R01 has seven requests, three noops and zero DOM action errors. | Scripted ordinary fill-then-click reproduction; instrument event admission before deciding on a versioned fixture repair. The historical causal branch is not directly observed. |
| Incorrect seeded arithmetic | Pinned bundle matches. Independent Number/BigInt comparison reproduces 1,018 wrong first updates out of 1,024 seeds and first four-way counts [1023,0,0,1]. Math.imul comparison produces [262,252,243,267], with zero first-update mismatches. | Version any arithmetic repair and rerun fixture/diversity checks. Exact integer arithmetic alone does not certify PRNG quality or shuffle independence. |
| Misleading efficiency summaries | W01 has five action errors despite no fatal episode error. R01’s three noops and extra save are real agent work. | Separately report pacing, model request/response time, browser action time, action-error count, noops, model calls and server commits. Preserve raw upstream efficiency scores. |

The machine-readable local review is `.local/preflight/harness-issue-review.json`; the independent RNG calculation is `.local/preflight/harness-rng-review.json`. Historical artifacts and curation-owned reports were not rewritten.

## Concrete next harness increment

1. Add an optional readiness/pacing hook before observation capture. The current wrapper sleeps inside `complete(messages)` after the runner has already saved the page and built messages. Split that responsibility without moving budget reservation ahead of fingerprint validation or weakening no-retry accounting.
2. After readiness, obtain a fresh observation and save a distinct decision-time artifact. BrowserGym 0.14.3 exposes `_get_obs()` internally; a small version-pinned adapter is preferable to injecting a fake `noop` action that changes action counts/task lifecycle. Preserve the original post-action artifact and do not overwrite historical observation references.
3. Validate ordering with a fake clock and a scripted expiring-control page: wait → fresh capture → exact prompt → fingerprint validation/reservation → one dispatch. Report observation age. Refreshing after pacing cannot prevent a control expiring during model inference itself, so do not claim it eliminates every stale-target failure.

Only then freeze a new protocol for any model comparison. Do not silently rerun W01, change its goal, repair Chaos fixtures mid-cohort, or reinterpret old seeds. The new Vercel demo already rejects stale page actions, but that separate client runtime is not validation of a BrowserGym fix.

## Source reviews

- [Joint curation findings](data/curation/JOINT_ISSUE_REVIEW.md)
- [W01 report](data/curation/AUTHORIZED_PILOT.md), episode `20260914T223008Z-09770682`
- [R01 report](data/curation/ACCOUNT_PILOT.md), episode `20260914T224519Z-8edf02e6`
- [RNG source review](data/curation/CHAOS_RNG_REVIEW.md)
- Current `intent_browser/runner.py`, `data/curation/run_authorized_pilot.py`, and installed BrowserGym `core/env.py:_get_obs`
