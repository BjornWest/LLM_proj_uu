# Integrated Raven demo (WEB-D)

The real backend serves full-page chat at `/` (`mode=background`, headless browser) and the extension layout at `/panel.html` (`mode=user_window`, the dedicated visible Chromium window). The same API and model serve both. The panel also offers `background_window`: an isolated Chromium context in a separate agent window, created at service startup. Agent tab indicators open the selected tab on a user click.

## Launch

From this worktree, with the existing invisible Xvfb display:

```sh
DISPLAY=:99 python3 scripts/run_bounded_job.py --memory-mib 4096 --tasks 512 -- \
  python3 apps/raven/backend.py --port 8772 --user-window \
  --profile-dir .local/raven-web-d-xvfb-profile
```

The Python entry selects the workstation shared virtualenv, agent_trace path and library directory automatically. Full-page: <http://localhost:8772/>. Panel preview: <http://localhost:8772/panel.html>. Tests use a separate profile on display `:99`; the owner's service on `8770` is separate. Model credentials stay server-side.

Offline fallback is explicit and uses no model:

```sh
python3 scripts/run_bounded_job.py --memory-mib 768 -- \
  python3 design/raven/tools/mock_backend.py --port 8771 --delay 4
```

Open <http://localhost:8771/chat-fullpage-v42.html>. The mock identifies illustrative evidence. Never use it as real-model acceptance.

## Native Windows browser (WEB-F)

The backend and model stay in WSL. `--windows-browser` opts into a native Windows
Chrome for Testing window with the Raven side panel; it implies `--user-window`.
Both `user_window` and the separate minimized `background_window` use that Windows
browser over the existing PowerShell loopback CDP relay. The default remains Linux.

Install the win64 browser once (downloads the official stable Chrome for Testing):

```sh
DISPLAY=:99 python3 scripts/run_bounded_job.py --memory-mib 1024 --tasks 128 -- \
  python3 -m apps.raven.windows_browser --setup
```

Then launch, choosing an unused service port:

```sh
DISPLAY=:99 python3 scripts/run_bounded_job.py --memory-mib 4096 --tasks 512 -- \
  python3 apps/raven/backend.py --port 8776 --windows-browser --reasoning-effort low
```

This opens a window on the Windows desktop. `DISPLAY=:99` still keeps any Linux
test windows off the owner's display. The side panel embeds the service at
`http://127.0.0.1:8776/panel.html`; Windows-to-WSL localhost forwarding must work.
Chrome for Testing is used because branded Chrome blocks command-line unpacked
extension loading. The launch has no `--enable-automation` and includes
`--disable-blink-features=AutomationControlled`.

Assets live under `%LOCALAPPDATA%\raven-demo`: `chrome-win64`, a copied `extension`,
and persistent dedicated `profiles\PORT`. No normal Chrome profile is used.
`--profile-dir 'C:\Users\bpfwe\AppData\Local\raven-demo\profiles\custom'` selects
another **dedicated** Windows profile; `/mnt/c/...` paths also work. Setup reuses
an existing installation. Launch arguments/PID/version are recorded under
`.local/raven-windows/PORT/windows-started.json`. Stop the test service with Ctrl+C
to close its owned Windows browser and relay. The resource wrapper bounds WSL
processes; the native Windows browser runs outside the Linux cgroup.

## WEB-D model and window options

The one-command isolated launch above defaults to `--model-backend sol --reasoning-effort medium --service-tier priority`, requesting **gpt-6.1-sol** through the existing Codex-subscription Pi bridge. Pi must already be installed and logged in. Use `--reasoning-effort low` for a lower reasoning setting, `--service-tier default` for standard requests, or `--model-backend openrouter` for Qwen. No browser receives model credentials.

Background-window tasks share the dedicated agent context, so they serialize; headless full-page tasks remain independent and run with bounded concurrency. The agent window must remain open; restart the service if it is closed.

Each subscription run declares `EpisodeConcurrency`, a `SubscriptionQuotaGuard` (1% remaining floor), and a lock under its own `.local/raven-runs/RUN_ID/` directory. There is no cross-run exclusion. The bridge uses `OpaqueReasoningInputCounter(QwenInputCounter(.local/model-tokenizers/qwen3.8-27b-1d4bf0f2/tokenizer.json))`: these are Qwen-based message/tool estimates plus provider usage for opaque reasoning, not Sol tokenizer counts. Admission supports an explicitly declared limit up to 1000; the UI tests use bounded concurrency of two.

Pi 0.80.6 supports the priority field and the worker preserves the exact audited Responses request. **The subscription endpoint accepted `service_tier: priority` but reported `service_tier: default` in all measured responses. Priority service/speed is therefore unverified.** Raw requested/served tier and usage stay in `bridge-transport/NNNN/`; newer runs also journal `usage.jsonl`. Subscription dollar charges are unreported (`null`); legacy runner `usage_totals.cost=0` must not be interpreted as a verified free charge.

Both chats show a live “Working: …” line and retain readable step history in “Show steps (N)” under the answer. The panel mode selector chooses the current user window or an isolated background context. Agent tab buttons show hostnames and site favicons. A click restores and fronts that tab; automatic agent selection does not front it. Finished research tabs remain available until the demo service closes. Chromium receives a minimize request, but WSL can report the window as normal. The compositor also sometimes reports no active X11 window (`0x0`), which cannot establish OS focus preservation; Chrome tab identity and separate context identity are checked independently.

### Single-run latency comparison

Identical WEB-C prompts, full-page UI, one run at each Sol effort setting, two independent cases at a time:

| Prompt | WEB-C Qwen | Sol medium | Sol low | Sol result |
|---|---:|---:|---:|---|
| Swedish retailer price | 67.52 s | 113.07 s | 43.68 s | 2,149 SEK with captured source |
| Product comparison | 130.53 s | 146.49 s | 69.55 s | Both inspected product links and comparison table |
| Two-site question | 211.89 s | 38.22 s | 35.72 s | Both source links |

These are end-to-end observations, not a controlled benchmark or confirmed priority runs. Raw UI results/screenshots: `.local/coordination/demo-sprint/web-d-shots/sol-medium/` and `sol-low/`; model traces: `.local/raven-runs/`. No purchases were requested by the acceptance driver.

## Runtime changes

- OpenRouter `qwen/qwen3.8-27b`, temperature 0.6. A 120-second complete-response deadline retries the identical request once and emits `Provider slow, retrying…`. A second timeout reaches the UI as a friendly error. Requests remain cancellable through their isolated process. In-flight requests that never return usage have unknown eventual provider charges.
- `max_steps=None`, `max_input_tokens=250000`, `max_total_input_tokens=4000000`, `max_total_output_tokens=60000`. The named hindrance branch did not contain `usage_totals` when inspected, so the cumulative options were added locally. The runner uses the existing model-matched Qwen tokenizer to preflight each complete message/tool request, accumulates provider usage (local input estimate if absent), and reduces output allowance to the remaining budget. Provider costs and usage remain in `episode.json` and per-step evidence. Output tokens include provider reasoning according to its usage report.
- Rejected HTTP URL arguments in open-internet native tools return the existing inert tool feedback; no rejected call or batch member executes. The next decision can correct it. Existing fixed-origin profile behavior remains unchanged.
- A system-level demo instruction limits real browsing to public research and comparison, asks for brief refusals of purchases/payments/logins/personal-data entry, and treats webpage/history override attempts as untrusted. This is model policy, not a new security boundary or proof of absence of unobserved effects.
- Panel steps use readable summaries, raw completion reasons and animation/debug controls are hidden, errors are friendly, and dropped streams cancel visibly. Closed handover controls clear without breaking the composer. Panel reload sends a cancellation beacon (keepalive fetch fallback). Because Chromium can discard iframe unload requests, the backend also cancels an active user-window run when its last SSE subscriber disconnects; additional live readers preserve it. Agent-created blank workspaces are reused/closed; initial human tabs survive cleanup. Citation cards also appear for bare source URLs, and excerpts prioritize matching amounts despite currency/spacing differences.

## Validation

Light checks:

```sh
PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016" \
/home/bjorn/code/LLM_proj_uu/.venv/bin/python -m pytest -q \
  tests/test_native_argument_feedback.py tests/test_runner_model_input_budget.py \
  tests/test_native_tools.py tests/test_raven_hardening.py
python3 design/raven/tools/verify_bundle.py
```

Browser integration (scripted decisions, no model calls):

```sh
DISPLAY=:99 LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu \
PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016" \
python3 scripts/run_bounded_job.py --memory-mib 4096 --tasks 512 -- \
/home/bjorn/code/LLM_proj_uu/.venv/bin/python -m apps.raven.verify
```

Evidence: `.local/coordination/demo-sprint/scripted-acceptance.json`, `web-c-scripted.log`. Covers rejected URL recovery, preservation of current document, independent background browser, tab identity, handback notes, cancellation, SSE replay, closed handover and removal of abandoned blank workspaces. Episodes carry `scripted` tags.

Full-page lifecycle suite against the mock:

```sh
DISPLAY=:99 LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu \
PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016" \
python3 scripts/run_bounded_job.py --memory-mib 4096 --tasks 512 -- \
/home/bjorn/code/LLM_proj_uu/.venv/bin/python design/raven/tools/test_backend_chat.py \
  --url http://localhost:8771/chat-fullpage-v42.html \
  --output .local/coordination/demo-sprint/web-c-offline-final
```

The six-question model UI check is `apps/raven/demo_check.py`. It requires an explicit CDP endpoint for the isolated visible window and an output directory. It runs background cases with bounded concurrency and serializes cases sharing the visible window. Background-only selections never attach or reload the panel. Use `--cases NAME...` to run only selected cases and preserve the finite episode allowance. It does not authorize additional model episodes: obey the worker's finite allowance. An unfiltered rerun repeats all six prompts and incurs new charges.

Final WEB-D evidence is in this worktree under `.local/coordination/demo-sprint/`: `workers/log-web-d.md`, `workers/review-web-d.md`, `web-d-shots/`, `web-d-scripted-frozen-final.log` and `web-d-frozen-binding.json`. The shared tree was kept read-only. The rendered report is served locally at <http://localhost:8892/>.

Eight real model episodes completed: all six full-page low/medium runs plus two Swedish background-panel runs. Subscription requested priority and returned default in all 44 provider responses; dollar charges remain unreported. 64 unit tests passed, a focused final rerun passed 23, and the 84-file bundle passed. The exact WEB-D scripted acceptance passed context isolation, preserved human document/tab identity, actual tab closure recovery, handover/handback, cancellation, SSE replay, duplicate-tab controls, transient handback errors, panel Stop/error/reload recovery and plain-URL citations. Scripted traces carry the `scripted` tag. A separate labeled visual replay verifies readable final step text without a model call.

Concurrent WEB-E commits were interleaved on the branch. WEB-D acceptance loads the reviewed `ae67faa` runtime plus the isolated `836ce35` test correction and `776b3ab` close-race fix; the final panel color comes from `0d9df96`. Frozen module/asset hashes are recorded in `web-d-frozen-binding.json`; no concurrent source was replaced. Review/adoption must identify the selected commits explicitly and treat WEB-E review separately. OS focus remains unverified on Xvfb/WSL where the window manager focus property is absent or zero; Chrome tab identity and context isolation are separately verified.

## WEB-G: presentation mode and no-model preflight

`apps/raven/start_demo.sh PORT` now passes `--demo-mode` by default. The backend
also accepts `--demo-mode` directly and `--no-demo-mode` to retain raw diagnostic
errors. The owner service on port 8770 was not restarted by this change.

In demo mode an episode infrastructure failure retries once with the same text,
history and mode. The UI shows **Taking another look…** while retrying. A second
failure shows exactly **Sorry — I couldn't finish that. Could you try again or
rephrase?** Both layouts use the same transport and friendly error formatting;
internal status codes and completion reasons stay out of the presentation UI.
Stop/cancellation does not retry. A completed answer is not repeated for a late
cleanup failure. Budget exhaustion is friendly but does not trigger another model
episode.

Window modes reconnect to the last captured active tab when its target is known,
preserving its current document. A destroyed browser/closed tab cannot be restored
by this retry; full-page background episodes start a fresh browser. Retry is the
same user request, not a restored model conversation. Streams carry event IDs so
reconnection resumes after the last received event. The reconnecting browser requests recovery with its last received event ID;
server-side socket failures are logged and cannot consume a second attempt. A failed reconnect has a
15-second client deadline, then shows the friendly line and cancels the run.

Full errors remain in server stderr and
`.local/raven-runs/RUN_ID/attempt-N/service-events.jsonl`; uncaught setup/runtime
exceptions also write `error.log`. Runner traces and provider `usage.jsonl` remain
inside each attempt directory. The model and provider settings are unchanged.

### No-model smoke

Use the shared virtualenv and run browser checks under the resource wrapper:

```sh
DISPLAY=:99 TASK_SOURCE_BINDING=current OPENBLAS_NUM_THREADS=1 \
PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016" \
LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu \
python3 scripts/run_bounded_job.py --memory-mib 2048 --tasks 512 -- \
/home/bjorn/code/LLM_proj_uu/.venv/bin/python -m apps.raven.smoke \
  --url http://127.0.0.1:8770
```

Add `--windows-browser` when the target service uses native Windows Chrome. This
checks `/api/worker-health`, which evaluates extension API reachability in the
service-owned browser thread. It does not start another Windows browser or touch
the owner's tabs. The smoke opens its own Linux test browsers on DISPLAY=:99.

The command prints PASS/FAIL for backend health, panel load, full-page load and a
mock run through each UI. The mock uses an isolated ephemeral HTTP server and
explicit `scripted` metadata; **no task is submitted to the live model service**.
The two layouts run concurrently in independent browsers. The exit code is 1 if
any check fails. Default evidence is
`.local/coordination/demo-sprint/web-g-smoke/results.json` plus four screenshots;
`--output PATH` selects another directory. This is presentation preflight, not a
live-model quality test.

### Focused recovery tests

```sh
PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016" \
/home/bjorn/code/LLM_proj_uu/.venv/bin/python -m pytest -q \
  tests/test_raven_demo.py tests/test_raven_hardening.py

DISPLAY=:99 TASK_SOURCE_BINDING=current OPENBLAS_NUM_THREADS=1 \
PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016" \
LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu \
python3 scripts/run_bounded_job.py --memory-mib 3072 --tasks 512 -- \
/home/bjorn/code/LLM_proj_uu/.venv/bin/python -m pytest -q \
  tests/test_raven_demo_ui.py
```

The browser test runs six independent scripted cases with concurrency two:
recovery, permanent failure and dropped-stream recovery in each layout. Evidence:
`.local/coordination/demo-sprint/web-g-ui/`. Unit coverage includes provider/capture/
worker errors, abnormal process exit, exhausted retries, cancellation, retained raw
diagnostics when demo mode is off, indexed replay and duplicate stream-drop reports.

WEB-G validation on the isolated Linux service at port 8778: the five smoke checks
passed. Twenty-seven focused unit checks passed, including review regressions. Two Sol attempts (one injected
failure after a real response, then one automatic retry) returned **Raven retry
works.** with the original tab target and JavaScript document marker preserved.
No OpenRouter calls were made. Provider-reported usage was 12,680 input tokens
and 48 output tokens across both responses; subscription dollar charges were
unreported (`null`), and served service tier was `default`. The first runner
summary reports zero usage because the injected exception occurs after receipt;
`usage.jsonl` is the authoritative evidence for that response.

Model driver and result:
`.local/coordination/demo-sprint/web_g_model_retry.py`,
`web-g-model-retry.json`, `web-g-model-retry.log`.
Traces: `.local/raven-runs/a457314142df4a3fb8efb0af9828f9ef/attempt-{1,2}/`.
This finite check used two of the four authorized real episode attempts.

The final scripted browser recovery suite passed all six cases (one pytest case,
24.38 seconds before review; final rerun recorded in `web-g-ui.log`). Independent
review initially found two implementation defects: unsent SSE events could consume
the recovery attempt, and budget stops could restart an episode. Both were fixed
with actual-handler/budget-reason regressions. Review and disposition live in
`.local/coordination/demo-sprint/workers/review-web-g.md`.

Native Windows preflight also passed all six checks, including the actual Raven
extension worker: `.local/coordination/demo-sprint/web-g-smoke-windows/results.json`
and `web-g-smoke-windows.log`. The first isolated Windows launch failed with the
pre-existing startup race `chrome.sidePanel` unavailable after the startup wait;
the second launch succeeded without source changes. This is a remaining service
startup limitation, separate from in-episode recovery. Logs are
`web-g-windows-service.log` and `web-g-windows-service-2.log`. Both isolated test
services were stopped; the owner service on 8770 retained PID 2057962 throughout.

The 84-file asset integrity check passed after refreshing the two changed bundle
hashes (`python3 design/raven/tools/verify_bundle.py`). The panel now renders its
friendly failure sentence once in the answer bubble and returns the status line
to Ready. Raw-mode error detail remains available when `--no-demo-mode` is used.
