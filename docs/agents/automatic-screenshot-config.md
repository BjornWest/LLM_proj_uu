# Disable automatic screenshots

Implemented locally, 2026-09-27. Default behavior remains enabled. This option
skips taking automatic screenshots, rather than taking them and omitting the PNG.

CLI: add `--no-screenshots` to an existing episode command. A completely offline
smoke example is:

```sh
.venv/bin/python -m intent_browser.cli smoke --headless --no-preview --no-screenshots
```

Python:

```python
run_episode(env_factory, backend, metadata, trace_screenshots=False)
```

For callers already configuring the observation pipeline:

```python
ObservationPipelineConfig((), full_capture_only=True, trace_screenshots=False)
```

The pipeline setting now applies to native fallback and human-handover capture,
including initial reset, fresh decisions, transition/guard captures and background
capture. Previously it only controlled the lightweight/static observation path.
A runner `trace_screenshots` value overrides the pipeline setting without mutating
the supplied frozen config; `None` inherits it, or defaults to `True` without a
pipeline. The runner setting is inherited by delegated root/helper episodes.

The distinction is intentional:

- AX/DOM observations and their JSON/text logs continue normally.
- The screenshot field/reference is `None`; no automatic PNG is written.
- The explicit `screenshot` tool remains available and takes a fresh image when
  requested. Its result is delivered and saved normally. Tool definitions do not
  change during the episode.
- Video recording remains separately controlled by `record_video` / `--video`.
- Screenshot-based live preview/replay loses automatic per-step images. Use
  `--no-preview` as well when that viewer is unnecessary.

Metadata records `trace_screenshots` and its automatic-observation-only scope.
Native BrowserGym capture is wrapped per environment/call; there is no global
Playwright/BrowserGym patch. Unsupported custom `_get_obs` overrides without the
reviewed pipeline fail explicitly instead of silently taking screenshots anyway.

## Acceptance

- `scripts/verify_screenshot_config.py --output NEW_DIR`: seven independent browser
  cases, concurrency two, mock inference only. Covers default enabled, ordinary
  disabled, static pipeline, full fallback, inherited pipeline setting, human
  handover and dynamic background capture.
- `.local/screenshot-config-v2/report.json`: all seven pass. Each disabled case
  observes exactly one screenshot operation, solely for the explicit screenshot
  tool; zero automatic screenshots/PNGs, including before the first request and
  after the scripted browser action. The image reaches the next model input;
  request tool definitions remain identical. Raw AX/DOM logs remain available.
- `.local/screenshot-config-unit-v2.log`: 62 tests plus 10 subtests, including
  configuration validation, root/helper inheritance and existing capture/vision/
  delegation/clarification regressions.
- `.local/screenshot-config-cli-v1/`: legacy CLI smoke passed, no automatic PNGs.

The initial v1 browser suite exposed a reset-only omission in human capture. Its
failed artifacts remain; v2 includes that correction. No paid calls, environment
source changes, worker restart or Vercel deployment were performed.
