# Maps original-site preflight

Prepared for MAP-PREFLIGHT-03. **Offline-tested only; no browser or service execution yet.** Root owns data downloads, volume preparation, startup and permission to execute against `http://localhost:13030`. This package does not start, stop, reset or patch a service. It does not accept any benchmark task.

## Later explicit execution

Use a fresh output directory, after root establishes the original image and all local services are ready:

```bash
CURATION_FROZEN_RUNTIME=.local/curation-expansion/frozen-runtime-v1 \
  .venv/bin/python data/curation/expansion/webarena_maps_preflight/run.py \
  --execute-local-13030 \
  --output .local/curation-expansion/maps-site-preflight-v1
```

`--case homepage`, `--case search`, `--case car`, `--case bike` and `--case foot` can select individual cases; omission runs all five in fresh browser contexts. Optional `--query`, `--from-place` and `--to-place` configure diagnostic strings. Defaults use Carnegie Mellon University and University of Pittsburgh, within the intended Northeast data coverage. These are site probes, not fabricated original tasks or expected-answer labels.

The explicit switch is required even for homepage-only execution. The executable imports no BrowserGym or harness modules before that check. It activates the copied runtime before any `intent_browser` import, fingerprints source before/after and before each fresh observation/decision, and uses `core-tools-v3`, 12 steps, 48,000 AX characters, `slow_mo=0`, compact feedback, preserved reasoning replay and omitted parallel-call hint. The backend uses the existing local MockTransport scripted driver: no model API or paid calls.

## Evidence and limits

Each case uses the complete original site. Native `fill`, `press`, `click` and `select_option` actions require a visible control BID in the current delivered AX. Original source supports the query, directions, engine and result selectors. Explicit readiness waits precede fresh BrowserGym observation; there is no fake browser noop. Selectors remain unverified against the running application until the first execution.

The network guard permits GET/HEAD only to the exact local origin and the read-only POST path `/geocoder/search_osm_nominatim`. The cached controller action and rendered `data-href` support this POST; the exact deployed Rails path still needs runtime confirmation. Any different path is blocked and recorded; do not widen it automatically. The guard does not rewrite requests, supply alternate assets or contact external fallback services. It does not certify server-side closed networking, which requires root's container/network evidence.

Each case retains:

- Original embedded HAR including requested assets, homepage and response bodies; local authoritative evidence, not a credential-redacted export.
- Standard runner requests, decisions, screenshots and observations; an additional final stage HTML/screenshot/AX when capture is reached.
- Visible endpoint names and engine label, search-result text, tile image load diagnostics, route rows and SVG-path diagnostics.
- Private stage evidence separately from a whitelisted visible projection. The projection is a review aid, not evidence that an additional observation was delivered to a model.
- Source hashes, native targets and exact delivered AX, browser errors, blocked/failed requests, per-case report and suite report.

Mode checks bind the selected engine and URL to **`routed-car`, `routed-bike`, or `routed-foot`**. All three original services use `/route/v1/driving/`; that substring alone is insufficient. The latest corresponding response must be HTTP 200 with `code=Ok`, two waypoints, positive finite duration/distance and nonempty step geometry. The original UI uses `overview=false`, so requiring a top-level route geometry would be incorrect. The rendered summary must match the response duration rounded by the original minute rule; a previous successful response cannot hide a later failed response.

Successful diagnostics are called `observed`, not task completion or full site readiness. Dependencies, missing evidence, wrong/stale mode or browser errors produce `unknown`; task completion, authorization and safe success always remain null. DOM path/tile-load checks are only pointers: inspect screenshots before claiming actual correct rendering. Endpoint semantic identity, coordinates/object pages, distant-region routing, negative search controls and per-task grading remain unverified. Missing tiles remain a hold, not permission to remove the map.

The original tile snapshot is not certified a clean shutdown; retain root's startup/recovery evidence. See `data/curation/expansion/maps-tile-startup-review.json`. This CLI never removes `postmaster.pid`, resets WAL or changes databases.

## Offline checks

```bash
python3 -m unittest data.curation.expansion.webarena_maps_preflight.test_preflight -v
python3 -m py_compile data/curation/expansion/webarena_maps_preflight/run.py
```

Twelve tests cover dependency failure and missing evidence becoming unknown, mode-prefix discrimination, response schema/geometry, stale summary/latest-response rejection, private-field projection, exact request allowlist, and refusal of implicit live execution. No services or browser are needed for those tests. `offline-validation.json` pins the tested source and cached source archives.
