# Opt-in open-web background capture

2026-09-27. Shared runner integration of the earlier isolated experiment.
Default profiles and existing frozen runs remain unchanged. This version is for
new, explicitly labeled development runs, not a claim of complete real-web
coverage or demonstrated Qwen performance.

## Adoption

Use the existing open-internet/human-handover profile with stable frames and no
helpers. `OpenInternetTask` explicitly permits the new decision observations.
Other task adapters must separately declare `supports_dynamic_preview = True`;
`supports_observation_pipeline = 'native_full_only'` alone is insufficient.

```python
profile = with_human_handover(
    open_profile(standard_profile(helpers=False)),
    stable_frames=True, compact_tabs=True,
    wait_for_human=True,  # retain the experiment's agreed human policy
    capture_timeout_mode='diagnostic',
)
pipeline = ObservationPipelineConfig(
    (), full_capture_only=True, dynamic_preview=True,
    shallow_depth=2, preview_node_limit=64,
)
# Existing run_episode arguments, human controller/UI and terminal instruction
# remain required as before. Supply observation_pipeline=pipeline.
```

`full_capture_only` selects the native *backing capture*, rather than the older
static-origin fast path. `dynamic_preview` additionally changes the pre-request
observation only. Set `dynamic_preview=False` to restore native decision capture.
The default is false. No site-specific signal or privileged task state is used.

The exact `ChatCompletionsBackend` class supports model I/O off the browser thread.
A subclass must redeclare `supports_background_completion = True` after its hooks
have been reviewed for thread safety. A wrapper that accesses Playwright or a
thread-bound budget database is not eligible. Undeclared wrappers, or backends
with `requires_browser_thread=True`, use the existing native foreground capture.
Do not simply set the flag to bypass this review.

## Lifecycle and public observations

1. Existing pacing/human waiting runs before a fresh decision preview.
2. Capture shallow main-document AX over CDP, without whole-page marking,
   DOMSnapshot, geometry or screenshot. The existing tokenizer-based overview
   budget still controls delivered text; depth 2 and 64 captured preview nodes
   are the recommended initial settings.
3. The normal conversation builder and policy-delivery machinery retain the
   exact preview, prompt, HTTP request and response. The full AX index and its
   delivery ledger are not replaced by the incomplete preview.
4. Model HTTP runs on one worker thread. Native full capture stays on the
   original Playwright owner thread. Await both before using any tool result.
5. Check tab custody/cycle and main-document identity, and compare preview
   semantics against that document in the full capture. Namespace by frame,
   backend DOM identity and semantic role; inline text can share DOM identity.
6. Index full capture for AX queries, recording it as a **background artifact,
   not policy-delivered text**. Create the dispatch ticket from this validated
   snapshot. Existing fresh mutation/target/frame/custody/chat guards remain.

The preview provides orientation **without clickable BIDs**. The model can use
`ax_search`/`ax_read` to obtain targets from the completed full capture. This is a
real policy-input difference from full decision overviews; evaluate it as such.
No new tool schema, target ID fabrication or invisible model request is added.

Preview/document/custody invalidation consumes the proposal: every proposed call
gets a `not_executed` result with `background_preview_invalidated`. A subsequent
normal model decision may continue. There is no automatic action replay or paid
request retry. Native capture failures that are not document invalidations still
end the episode after preserving the model result and error. HTTP failures retain
the exact attempted request and raw response where available.

A tab returned by the human uses the established native full recapture/resume
path before inference. Pending trusted chat during capture blocks actions and
is delivered on the next normal request. A late page change after background
capture still needs the existing fresh mutation guard; background validation is
not a substitute for that guard.

## Timing and limitations

Each step's `observation_pipeline` records `overlapped`, optional dynamic `mode`,
backend/prefetch start/end offsets, durations, barrier duration, background artifact
and error/invalidation. Offsets are monotonic seconds relative to entry into
`complete`. Backend duration includes HTTP scheduling/response processing; it is
**not a measurement of server decoding or TPS**. The existing step request time
is the whole barrier, not additive with the nested capture/backend durations.

Reset/setup and post-action capture are still native and blocking. Full mutation
guards and recording still cost time. The first reset is not made progressive by
this change. A fast model must wait for the background capture. Depth limits do
not bound the entire CDP response size when a document has many shallow siblings;
the node cap bounds only the retained preview. Child-document coverage remains
explicitly unknown in the preview, and Windows cross-origin capture limitations
remain unchanged. No claim of atomic whole-page capture is made.

Preview capture uses the existing bounded/diagnostic deadline policy. Diagnostic
mode reports overruns and continues; it does not impose a new hard timeout.

## Validation

Offline validation uses the real `run_episode`, `ChatCompletionsBackend` with
HTTPX MockTransport and real browser sessions. It does not contact a provider or
external site. See `.local/dynamic-overlap-integration/acceptance.json` for final
source/artifact fingerprints and exact passed cases. Earlier probe/matrix outputs
are preserved separately, including mock response-parser fixture failures.

```bash
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python -m scripts.verify_dynamic_overlap \
  --output .local/dynamic-overlap-integration/new-linux

# Windows CDP transport, separate headless browser owned by the test:
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python -m scripts.verify_dynamic_overlap \
  --output .local/dynamic-overlap-integration/new-windows --windows --case click
```

Use a new output directory. Linux cases use bounded concurrency 2. Windows
transport tests are separately scoped; large timing comparisons run sequentially
to avoid benchmarking competing captures. Existing browsers are not restarted,
repositioned or used as test subjects. No deployment is performed by this work.

Final acceptance: 44 focused unit tests; 20 saved browser cases with 539 artifact
hashes verified; an additional search/click run imports the frozen release copy.
The three Windows cases cover search/click, document change and late mutation.
No paid inference occurred.

A sequential pair on the 21,040-node fixture measured request start from decision
capture start at 5.969s foreground versus 0.514s overlapped. Delivered observation
text was 1125 versus 893 tokens (local Qwen3.8 tokenizer; not complete requests).
The policy inputs differ, so this is scheduling evidence, not a capability or
throughput comparison. The 0.15s mock waited for background capture as intended.

Frozen handoff: `.local/dynamic-overlap-integration/release/manifest.json`.
