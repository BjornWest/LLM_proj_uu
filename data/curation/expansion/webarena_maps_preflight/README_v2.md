# Maps preflight v2: current entry point

Use **`run_v2.py`** for future execution. V1 code, README and `offline-validation.json` are preserved byte-for-byte as reviewed history. Neither version has run a browser yet.

After root explicitly makes the full original site and dependencies available:

```bash
CURATION_FROZEN_RUNTIME=.local/curation-expansion/frozen-runtime-v1 \
  .venv/bin/python data/curation/expansion/webarena_maps_preflight/run_v2.py \
  --execute-local-13030 \
  --output .local/curation-expansion/maps-site-preflight-v2
```

The five cases now run in separate subprocesses, with default concurrency **2** (`--workers 1..4`). Each child activates and fingerprints the frozen runtime independently and has a fresh BrowserGym context, trace and output. There is no model budget because no model is called. The parent rechecks its source closure after completion; drift makes the aggregate unknown. Each child has a 300-second process timeout; the isolated process group is terminated on timeout so browser descendants do not remain running. The original site's service processes are neither children nor targets of this cleanup.

The same `--case`, `--query`, `--from-place` and `--to-place` options apply. `--single-case` is an internal child mode; normal invocation dispatches even one selected case through a subprocess. Duplicate case names and unsafe path components are rejected. Existing output directories are never reused.

Evidence now lives under `OUTPUT/workers/CASE/CASE/`, including that child's report, HAR and traces. `OUTPUT/workers/CASE/source-before.json` is the child's source capture. `OUTPUT/report.json` aggregates original child reports and exit status; separate child stdout/stderr files remain under `OUTPUT/workers/`. Raw task outcomes remain null and no task is accepted.

V2 fixes the reviewed gap where `summary.error=null` could hide a nonfatal browser action error. Any nonzero or missing/invalid `action_error_count` makes the site diagnostic unknown; it never turns an infrastructure failure into a model failure. Existing HTTP/schema/mode/UI checks remain unchanged.

All source, fidelity and unsupported-check limitations in `README.md` still apply. Source-supported selectors and the exact deployed read-only POST path need first-run confirmation. No server-side network isolation or tile-recovery claim is made.

Offline checks:

```bash
python3 -m unittest data.curation.expansion.webarena_maps_preflight.test_preflight_v2 -v
python3 -m py_compile data/curation/expansion/webarena_maps_preflight/run_v2.py
```

This executes 20 tests: the preserved 12 v1 checks plus eight revision checks. The process-isolation test launches three tiny local Python processes, confirms distinct PIDs/outputs and observed peak concurrency 2, and never imports a browser. Failure/timeout tests likewise use tiny local Python children. No service, network or model calls occur.
