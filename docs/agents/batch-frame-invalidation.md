# Batch guard invalidation on changing frames

Local repair, 2026-09-26. No deployment, model rerun, or automatic action replay.

## Observed failure and scope

The real-web episode `20260926T173025Z-0aba0072`, decision 14, contains a valid
native reload proposal. The initial `document_signature` frame scan raised
`TargetClosedError` before creating `batch_calls`. The proposal and raw response
survived, but there was no per-call execution record. Continued child-frame events
and later main-tab closure support a frame lifecycle race; exact frame identity
was not recorded, so the original cause remains unconfirmed.

The local Chromium reproduction removes a child iframe while its evaluation is
pending. The original signature comprehension raises `Frame was detached`, while
the main page remains usable. This demonstrates the same guard vulnerability,
not a reproduction of Cloudflare or of its exact `TargetClosedError` subtype.

## Current behavior

`document_signature` returns only complete signatures. It checks tab/frame-set
changes during capture, and classifies known Playwright frame/context-loss errors
as `DocumentScanInvalidated` only while the active page/browser remains open.
An active main-target closed error, actual page/browser closure, and unrelated
JavaScript failures remain fatal. The diagnostic retains the original error,
page/frame indices, main/active flags, detachment and closure state.

The runner records every validated proposal even if the initial scan fails:

- Before dispatch, invalidation produces `not_executed`, stops the remaining batch,
  and returns ordinary tool feedback. The next turn captures fresh observation and
  may choose another action. No old action is automatically tried again.
- After an action completes, invalidation preserves that action's recorded feedback
  and effects. Only later calls are skipped.
- A fatal guard error retains proposals and their dispatch status before terminating.
  Exceptions during actual dispatch retain `failed_effects_unknown` semantics;
  neither zero `browser_step_count` nor a missing receipt proves no effects.
- `action_dispatch_started` distinguishes attempting the tool executor from
  successfully returning a browser step. It is not proof of a website commit.

This remains a conservative whole-context guard. Busy independent tabs can still
invalidate a batch. Human-owned tab isolation is a separate opt-in integration;
this change does not establish safe concurrent human/agent control. Continuous
page churn can prevent progress, and unrelated observation-extraction failures
remain technical failures.

## Reproduction and evidence

```bash
.venv/bin/python -m unittest tests.test_batch_guard
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python scripts/verify_batch_frame_race.py --output .local/frame-scan-NEW
```

Choose a new output directory; the script rejects existing output. Its five cases
run with at most three independent browser processes: original guard failure,
initial/pre-dispatch invalidation, post-dispatch invalidation, and closed-page
failure. Actual BrowserGym runner checks use native full-capture mode and an
HTTPX scripted transport, not an inference service. Frame disappearance is induced
inside the real Playwright evaluation; runner action/feedback/evaluation paths are
not mocked. Evaluation precedes environment close. The fixture reads its button BID
through the driver, so this is execution validation, not model capability evidence.

Saved evidence: `.local/frame-scan-v1/browser-v3/report.json` with per-case traces,
source hashes and artifact hashes. Earlier `browser` and `browser-v2` attempts
failed in test-profile setup (missing profile options); they are retained separately.
Regression log: `.local/frame-scan-v1/regression.log` (120 unit tests).
Nine existing native-batch browser scenarios are in
`.local/frame-scan-v1/batch-regression/report.json`.
