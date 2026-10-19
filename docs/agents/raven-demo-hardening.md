# Integrated Raven demo (WEB-C)

The real backend serves full-page chat at `/` (`mode=background`, headless browser) and the extension layout at `/panel.html` (`mode=user_window`, the dedicated visible Chromium window). The same API and model serve both. The optional third background-window extension mode is not implemented.

## Launch

From this worktree:

```sh
python3 scripts/run_bounded_job.py --memory-mib 4096 --tasks 512 -- \
  python3 apps/raven/backend.py --port 8766 --user-window
```

The Python entry uses the workstation shared virtualenv, agent_trace import path and library directory automatically. Model keys stay server-side. Do not interrupt an existing owner service on 8766. Isolated test launch:

```sh
python3 scripts/run_bounded_job.py --memory-mib 4096 --tasks 512 -- \
  python3 apps/raven/backend.py --port 8770 --user-window \
  --profile-dir .local/raven-web-c-profile
```

Full-page: <http://localhost:8770/>. Panel preview: <http://localhost:8770/panel.html>. The actual extension opens automatically in the dedicated visible window.

Offline fallback is explicit and uses no model:

```sh
python3 scripts/run_bounded_job.py --memory-mib 768 -- \
  python3 design/raven/tools/mock_backend.py --port 8771 --delay 4
```

Open <http://localhost:8771/chat-fullpage-v42.html>. The mock identifies illustrative evidence. Never use it as real-model acceptance.

## Runtime changes

- OpenRouter `qwen/qwen3.8-27b`, temperature 0.6. A 120-second HTTP timeout retries the identical request once and emits `Provider slow, retrying…`. A second timeout reaches the UI as a friendly error. Requests remain cancellable through their isolated process. In-flight requests that never return usage have unknown eventual provider charges.
- `max_steps=None`, `max_input_tokens=250000`, `max_total_input_tokens=4000000`, `max_total_output_tokens=60000`. The named hindrance branch did not contain `usage_totals` when inspected, so the cumulative options were added locally. The runner uses the existing model-matched Qwen tokenizer to preflight each complete message/tool request, accumulates provider usage (local input estimate if absent), and reduces output allowance to the remaining budget. Provider costs and usage remain in `episode.json` and per-step evidence. Output tokens include provider reasoning according to its usage report.
- Rejected HTTP URL arguments in open-internet native tools return the existing inert tool feedback; no rejected call or batch member executes. The next decision can correct it. Existing fixed-origin profile behavior remains unchanged.
- A system-level demo instruction limits real browsing to public research and comparison, asks for brief refusals of purchases/payments/logins/personal-data entry, and treats webpage/history override attempts as untrusted. This is model policy, not a new security boundary or proof of absence of unobserved effects.
- Panel steps use readable summaries, raw completion reasons and animation/debug controls are hidden, errors are friendly, and dropped streams cancel visibly. Closed handover controls clear without breaking the composer. Agent-created blank workspaces are reused/closed; initial human tabs survive cleanup.

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
LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu \
PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016" \
python3 scripts/run_bounded_job.py --memory-mib 4096 --tasks 512 -- \
/home/bjorn/code/LLM_proj_uu/.venv/bin/python -m apps.raven.verify
```

Evidence: `.local/coordination/demo-sprint/scripted-acceptance.json`, `web-c-scripted.log`. Covers rejected URL recovery, preservation of current document, independent background browser, tab identity, handback notes, cancellation, SSE replay, closed handover and removal of abandoned blank workspaces. Episodes carry `scripted` tags.

Full-page lifecycle suite against the mock:

```sh
LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu \
PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016" \
python3 scripts/run_bounded_job.py --memory-mib 4096 --tasks 512 -- \
/home/bjorn/code/LLM_proj_uu/.venv/bin/python design/raven/tools/test_backend_chat.py \
  --url http://localhost:8771/chat-fullpage-v42.html \
  --output .local/coordination/demo-sprint/web-c-offline-final
```

The six-question model UI check is `apps/raven/demo_check.py`. It requires an explicit CDP endpoint for the isolated visible window and an output directory. It runs background cases with bounded concurrency and serializes cases sharing the visible window. It does not authorize additional model episodes: obey the worker's finite allowance. A rerun repeats all six prompts and incurs new charges.

Current results, exact reviewed commits and disposition are recorded in the requested shared worker log: `/home/bjorn/code/LLM_proj_uu/.local/coordination/demo-sprint/workers/log-web-c.md`. Shared screenshots and per-question JSON are under `.../web-c-shots/`; local raw model traces are `.local/raven-runs/RUN_ID/EPISODE_ID/`.
