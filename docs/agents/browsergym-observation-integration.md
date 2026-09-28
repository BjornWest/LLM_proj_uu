# Opt-in BrowserGym observation integration

The previously experimental shallow/background reader now has an opt-in bridge to
`run_episode`. Ordinary runs and deployed workers retain their current defaults.
This is BrowserGym 0.14.3 integration, not a replacement browser driver.

## Controlled pages

```python
from intent_browser.observation_pipeline import ObservationPipelineConfig
from intent_browser.standard_profile import standard_profile

profile = standard_profile(helpers=False)
config = ObservationPipelineConfig(
    static_origins=("http://127.0.0.1:YOUR_PORT",),
    trace_screenshots=False,
)
run_episode(..., harness_profile=profile, observation_pipeline=config)
```

Use actual trusted origin strings, without paths. A task adapter must additionally
set `supports_observation_pipeline = True` and support the selected harness profile.
This declaration is an explicit adoption of partial observations, missing automatic
images/DOM snapshots on the fast path, and exact selected-input grading semantics.
Existing benchmark certificates are not silently promoted.

Fast capture requires the current main-document response to prohibit scripts through
CSP (`script-src`, or its default, plus element/attribute overrides). It also requires
an explicitly listed origin, one page/frame, complete resources, no active animations,
and no unsupported content. Header policy is attached to the current navigation,
not remembered indefinitely by URL. Other pages use native BrowserGym capture and
are labeled `native_fallback` in the saved observation.

The initial CDP depth defaults to **1**, matching the shallow prototype. A larger
`shallow_depth` is available for experiments, but wide trees can already return
thousands of nodes at depth 3. The preview may contain only document structure;
search/traversal then obtains the omitted content.

The capture sequence is:

1. BrowserGym marks native element BIDs; a depth-limited CDP AX capture forms the
   preview. It is token-budgeted and explicitly incomplete. It never enters the
   full-tree index or reports omitted nodes as removed.
2. The model receives that preview. Only backends explicitly declaring
   `supports_background_completion = True` on their own class can overlap completion
   with capture. Browser work remains on its original thread. Subclasses must opt
   in separately after checking budget/thread-local hooks. Other backends capture
   first, then dispatch sequentially.
3. The browser owner captures full AX and validates the preview against it. BrowserGym
   BIDs and existing stable AX context references are retained. Only regenerated
   negative Chromium layout-node IDs are normalized for this comparison; real DOM
   identities, names, values, properties and child counts/order remain checked.
4. Tools wait for full capture. If the document/revision changed, execution stops
   with a technical error rather than acting on the stale decision. An already sent
   model response/request/usage is retained even if background capture fails.
5. Batches retain their existing fresh-target/document guards. Browser events are
   kept; partial AX does not generate a fictitious full before/after diff. Full
   context is available to search, traversal and extraction tools.

Native marking still scans the DOM; the bridge is not constant-cost with page size.
Full AX serialization/indexing and trace writes also still cost time. The previous
experimental timing table is **not** a measurement of this runner integration.

## Readiness and screenshots

For eligible no-script pages, the fixed post-action delay is replaced with a public
body/readiness gate (including busy-state and animation-frame checks). The normal
BrowserGym wait/validate/observe order is retained. A navigation into an unsupported
scripted page restores the normal fallback delay. For a known application, callers
can supply `readiness_by_action` with `ReadinessSpec` values and a named
`readiness_contract`. Begin/end signals must bracket actual application work.
No custom condition or quiet interval is proof of task success.

Pending/unknown/failed completion is recorded as uncertain action feedback. The
original action is never replayed. Native action errors remain errors.

Requested screenshots use the visual gate for assets and sampled viewport layout.
The image is still retained when readiness is uncertain, with that uncertainty
included in its result. Canvas/video, excessive region size and other unsupported
visual content are not declared ready. Target positioning reads only the requested
control's viewport rectangle. `trace_screenshots=False` disables automatic images
on the fast path only; native fallback preserves its native recording behavior.

## Open internet: explicit full capture

Open-internet use is supported only with:

```python
config = ObservationPipelineConfig((), full_capture_only=True)
profile = open_profile(standard_profile(helpers=False))
task = OpenInternetTask(start_url, goal, headless=False, har=True)
task.supported_harness_profiles = (profile.name,)
# OpenInternetTask declares adoption of native-full-only integration.
run_episode(..., episode_task=task, harness_profile=profile,
            observation_pipeline=config)
```

This uses the integrated runner, normal full BrowserGym extraction and the requested
screenshot gate. It does not inject the revision/readiness tracker into retail pages,
skip their normal waits, use background capture or claim its speedups. Popups, tabs,
redirects, native action feedback, HAR and fresh-context isolation remain supported.
It is suitable for a qualitative browser run, not evidence of open-web performance
improvement. Helpers remain unsupported in this opt-in integration in either mode.
No CLI/deployment default was changed; use the explicit Python runner argument.

## Trace/provenance

- Decision artifacts retain exactly the delivered partial/full observation.
- Background full AX is a separate artifact, never substituted into the earlier
  request. A rejected full capture is also saved when comparison fails.
- Existing policy-delivery records bind the exact message spans. Data extraction
  receives the full execution observation reference when it differs from the preview.
- Automatic screenshot omission is represented as null, never a fabricated image.
- `observation_capture_phase` events retain marking, CDP and cleanup wall times.
- `observation_pipeline.backend_completion_seconds` measures the backend call;
  `prefetch_seconds` includes full capture/validation/artifact saving. They may overlap.
  The legacy `request_seconds` field measures the barrier until both settle, and its
  altered meaning is explicitly recorded for opt-in episodes.
- Evaluation still precedes environment close. Unknown verifier outcomes remain null.

## Scripted acceptance

All commands below are local/scripted, with no inference or external-site requests.
Choose new output paths; existing artifacts are not overwritten.

```bash
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python scripts/verify_observation_pipeline.py \
  --output .local/pipeline-NEW --case generated
# Other cases: static, recorded, dense, fallback, capture, stale.

LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python scripts/check_pipeline_boundaries.py --output .local/boundaries-NEW

LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python -m scripts.verify_open_internet --observation-pipeline \
  --output .local/open-web-NEW
```

Current acceptance is collected under `.local/runner-pipeline-v7/`, with the
three-site/tab isolation rehearsal in `.local/runner-pipeline-v7/open-web/`. The collection
manifest pins the source files and records each report/artifact hash. Cases cover
normal/recorded/dense pages, scripted fallback, stale/capture-error response retention,
a generated storefront with independent final world-state checks, header changes,
frames, property updates, explicit async readiness and pending work without retries.
The two error cases intentionally have technical errors and unknown safe-success.
