# Recovering iframe-owner races after actions

2026-09-27; GLM-FRAME-ADOPTION-20260927. Local runtime repair, no live rerun or
service deployment. Original GLM trace remains unchanged.

## Observed failure

In `.local/real-web-glm-windows-v1/runs/20260927T172947Z-87c30f8a`, turn 50's
Apply click returned with no action error. During the following native capture,
four concurrent iframe-owner lookups overlapped a top-level Amazon navigation.
Playwright reported `Unable to adopt element handle from a different document`.
The run ended because this error escaped the observation invalidation path.

The click was already dispatched. `browser_stepped: false` means BrowserGym's
whole step failed to return an observation; it does not mean the click failed to
run. The saved `action_completed_observation_unavailable` feedback is correct.
Postcode update outcome remains unknown; the repair does not relabel that run.

## Repair

Only inside native `frame_owner_lookup`, recognized Playwright adoption and
frame-detachment errors become `DocumentScanInvalidated`. The existing capture
loop then pins the same Page/custody cycle, cancels pending marking work, removes
its temporary annotations and captures again from scratch. Failed cleanup stops
recovery. Old element handles, old document targets and the action are not reused.

There are at most three capture attempts within the existing capture deadline
policy. Diagnostic mode still monitors instead of enforcing that deadline.
Persistent races report observation unavailable with the action's execution
record intact; later decisions retain the existing runner behavior. This is not
an automatic model-request retry or browser-action replay.

Concurrent sibling results prioritize unexpected exceptions over recognized
invalidation: a coincident transport error cannot be hidden by an earlier
sibling's navigation race. Browser/context closure and other unrelated errors
remain errors. Custody checks still run before and after retry cleanup.

## Acceptance and limits

- 30 focused tests plus 8 subtests: narrow classification, frame coverage,
  timeout policy, human chat/custody, and mixed race/transport-error priority.
- Seven Linux browser cases: old-classification failure control, root navigation
  recovery, child detach, actual browser closure, persistent adoption errors,
  failed cleanup, and ordinary operation.
- Three Windows-CDP browser cases: root navigation recovery, child detach and
  actual browser closure.
- Every case executes exactly one Apply click. Recoverable cases continue with
  fresh observations. Persistent/fatal cases preserve post-action unavailable
  evidence. Evaluation precedes environment close.

The adoption case deliberately injects the exact saved Playwright error after a
**real root navigation while owner lookup is suspended**. It is a controlled
race reproduction, not a claim of reproducing Amazon's precise internal timing.
Detach and closed-transport cases use actual Playwright errors. No provider or
external website is called; model responses are scripted HTTPX responses through
the normal backend/runner. No original browser session was reused or restarted.

Evidence: `.local/frame-owner-race/linux-final/report.json` (221 artifact hashes),
`windows-final/report.json` (124), `units-final.log`, and `overlap-regression/report.json`.
Frozen source and adoption details are in `.local/frame-owner-race/release/manifest.json`.
Earlier `linux-1` reports predate the added cleanup-failure guard and stay historical.

```bash
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python -m scripts.verify_frame_owner_race \
  --output .local/frame-owner-race/new-linux

LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python -m scripts.verify_frame_owner_race \
  --output .local/frame-owner-race/new-windows --windows \
  --cases root_adoption detach closed_transport
```

Use a new output directory. Cases run with bounded concurrency two and isolated
browser sessions. This repair does not eliminate all real-web capture failures.
