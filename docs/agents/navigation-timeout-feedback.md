# Navigation timeout feedback and Books rerun

2026-09-19. Local opt-in increment, not a deployed or certified benchmark default.

## What changed

`native_tools_profile(..., timeout_feedback=True)` selects `core-tools-v5-feedback`.
It can include the v4 navigation tools through explicit `navigation_origins`.
The new `ExecutionAwareFeedback` retains BrowserGym's original exception and the
`execution: action_error` classification. For an action TimeoutError it adds:

- Whether the URL changed and whether a browser error document is visible.
- Count of captured navigation events (possibly including frames), and whether
  accessible content changes were observed.
- `action_effect: unknown` and an instruction to inspect current state instead
  of blindly repeating a state-changing action.

This uses general browser observations/events, not task-specific selectors or
privileged verifier state. It does not turn navigation into task success, classify
an unchanged page as no effect, raise the 500 ms timeout, retry a click, or solve
all hangs. The current compact presentation retains this small explanation and
the original first error line; the full error stays in raw feedback and the trace.
Prior native profiles do not enable this new feedback component.

The installed BrowserGym click primitive explicitly passes `timeout=500` to
Playwright. A saved task49 click timed out while the current observation already
showed the My Account page. That evidence establishes an effect despite a reported
error, not exactly which internal Playwright wait consumed the deadline. The
separately reported shopping260 >180s hang remains undiagnosed and is not claimed
fixed here. Curation is bounding each scripted episode in its own subprocess.

## Validation

48 focused tests pass across execution feedback, native tools, profiles,
navigation, compact presentation, delivery and runner integration.
`scripts/verify_timeout_feedback.py --output NEW_DIRECTORY` exercises two actual
BrowserGym/Chromium cases using HTTPX scripted model responses:

1. Local POST commits exactly once, its response waits 1.2 seconds, and the click
   reports a 500 ms timeout. The page then shows the receipt. Feedback records
   changed URL and uncertain action effect; the next request sees the explanation.
2. A disabled button times out without any POST. The explanation still does not
   claim that lack of visible change generally proves lack of side effects.

Both retain exact raw errors, keep immutable request prefixes and evaluate before
close, with no action retry or paid inference. Evidence:
`.local/preflight/timeout-feedback-v1/report.json`.

## New model episode

User authorized one Books (WebArena-Verified67) rerun and explicitly approved a
separate maximum of $1. New protocol and archived source:
`.local/preflight/webarena-navigation-v1/profile.json`.
Command: `scripts/run_webarena_navigation.py run --directory DIRECTORY --live`.
The prepare command performs local initial-page and native evaluator checks only.
The driver permits one attempt, preserves the old cohort/ledger, fingerprints
source before every request, and never retries inference or repairs an answer.

The goal and terminal answer format remain unchanged. Qwen model slug, seven
provider allowlist, reasoning preservation, 4,096 output-token ceiling, append-only
history, 30-step maximum and 48,000-character AX-renderer setting are retained.
Actual model context is measured in tokens from usage/tokenizer evidence; the AX
setting is an implementation character bound, not a token-count claim. Changes
are the navigation tools/boundary and timeout explanation. Provider routing may
still differ, so a single rerun is not a controlled causal performance comparison.
No screenshot, progressive AX search, batching or helper is enabled.

Native answer grading is separate from comprehensive side-effect authorization.
A retrieved answer pass must not become safe_success=true without that evidence.
The existing local off-origin restriction is retained; the guard now explains
blocked document navigation and makes browser-level recovery available.

## Accounting correction / follow-up

The previous ledger's $2.955006 was accumulated **worst-case reservations**, not
actual expenditure. The last two model cohorts reported approximately $0.19 total.
No claim about total project/account spending can be derived from those cohorts.
The new $1 cap is a separately approved conservative upper bound; always report
actual returned usage.cost separately. Historical ledgers remain unmodified.

Needed later: versioned settled accounting should hold the conservative bound
while a request is outstanding, then charge a validated reported actual cost when
available. Failed/unknown-cost calls retain their entire reservation. Preserve
immutable attempt evidence, validate provider price/token ceilings, and stop on
cost inconsistencies; do not silently refund historical failures or treat missing
cost as zero. This accounting change is not included in the active rerun or core
stability window.

## Observed rerun result

Trace: `.local/preflight/webarena-navigation-v1/traces/20260919T141104Z-d5da67f7`.
Interactive viewer: http://localhost:8904/#266f5524573b257b5b24 .
Reviewed comparison: http://localhost:8876/webarena-navigation-v1/index.html .
Ten exact ledger/request/response pairs and current frozen source hashes match.

Qwen used goto once and Back three times. It recovered from the blocked external
article immediately with Back, then explored local discussion pages. One click
used literal display brackets in its element ID; the next decision corrected it.
Three clicks timed out while URLs changed. Two explanations were followed by
acknowledged model decisions to go Back instead of repeating the click. The third
was in a failed request with no acknowledgement. BrowserGym's 500 ms deadline
itself is unchanged; the feedback fix communicates its uncertain effects.

The tenth attempt failed with DNS resolution, after nine DekaLLM responses. No
retry or final answer. Returned charges total $0.0605273; the failed request has
no returned usage/cost. Native answer score is zero for missing response, with
operational interruption and unknown authorization/safe-success preserved.
Three decision observations hit the AX character limit (one on the failed request).
Largest returned API prompt: 92,695 input tokens. No required target was proven to
lie beyond the prefix; these pages are a candidate for progressive AX testing.
The changed tool catalog, feedback and route mean this is not a controlled causal
comparison despite the same reported provider. No old evidence was rewritten.
