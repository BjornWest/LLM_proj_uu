# Raven full-page backend chat (WEB-B)

The v42 full-page entry uses the Raven API v1 transport. Submission includes the current local conversation ID, prior turns and `mode: "background"`. There are no automatic reply timers or canned replies. Captured sources render as inline citation cards, with a source footer for evidence not explicitly marked in the answer. Stop, conversation switching and stream failure cancel the backend run. Creation/cancellation races ignore late output.

Conversation history remains an explicit localStorage adapter, `window.RavenConversations.getContext()`, rather than a backend conversation store. Replay uses the existing restoration flag so messages are saved once. Existing browser conversations are preserved; a fresh browser starts empty.

Navigation events update the site name, captured favicon and progress indicator above the chat. The current site link opens a new tab. Clicking elsewhere on the indicator toggles the visited-sites disclosure; its links remain accessible after completion. Background mode never embeds the agent browser. Manual helper-raven controls still demonstrate visuals; they do not create backend subagents.

## Offline demo and acceptance

From the worktree root:

```sh
python3 scripts/run_bounded_job.py --memory-mib 1024 -- python3 design/raven/tools/mock_backend.py --port 8767 --delay 4
```

Open <http://localhost:8767/chat-fullpage-v42.html>. The offline mock performs no network/model/browser calls and explicitly labels all evidence as illustrative. Each of three site events and the final event follows `--delay` seconds; include `[error]` in the composer or start with `--error` to demonstrate failure. The mock favicon is a local placeholder. Stop cancels the scripted worker.

Run the browser checks in a second shell:

```sh
LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu \
PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016" \
python3 scripts/run_bounded_job.py --memory-mib 4096 -- \
/home/bjorn/code/LLM_proj_uu/.venv/bin/python design/raven/tools/test_backend_chat.py \
--output /home/bjorn/code/LLM_proj_uu/.local/coordination/demo-sprint/web-b-shots
```

Cases use two independent browser contexts concurrently and save Playwright traces, screenshots and `m1-results.json`, classified with `metadata.tags=["scripted"]`. Cases cover full flight/three site changes/landing/Markdown/citations; reload without duplicates and follow-up history; cancellation; error; cancel before creation response; conversation switching; early completion during takeoff; and dropped-stream cancellation. The full case's third site arrives after the old ten-second completion deadline.

## Backend integration

`raven-transport.js` is a standalone browser client with `start(payload, {onEvent,onError})`, returning `{runId,ready,close,cancel}`. It also implements `focusTab`, `tabs` and `handback`. Task streams close at the first terminal event. A lost SSE stream fails visibly and cancels the run rather than reconnecting to a replay and duplicating output. Backend request errors are shown in the conversation and return the Raven to its perch.

WEB-A owns `apps/raven/` in its separate worktree. Serve these `design/raven/outputs/raven/` assets with that backend after integration. No API key reaches the client.

For read-only cross-worktree verification, `.local/coordination/demo-sprint/web-b-backend-preview.py` imports WEB-A's backend and sets only its in-process `ROOT` and `ASSETS` globals to this worktree, so static files and runtime output use WEB-B paths. It does not change WEB-A source. Start it through the bounded launcher with the shared venv, the library/PYTHONPATH settings above and `TASK_SOURCE_BINDING=current`; use `--port 8768`. The local `.local/coordination/demo-sprint/web-b-real-browser.py` runs one real question through the actual UI, preserves the full SSE payload and screenshots under the acceptance output directory, and records the backend episode as a model run, not scripted.

M1 passed all seven browser cases. M2 used both authorized attempts: first failed before inference with `TypeError: arg 5 (closure) must be tuple`. After WEB-A fixed that environment adapter, the second attempt showed Google → Example Domain site events and six model decisions, then terminated because the model requested `view-source:https://example.com/`, which the harness rejects with `ValueError: Only absolute HTTP(S) URLs without credentials are allowed`. The UI rendered the backend error and landed without JavaScript errors. There is no successful real final answer/citation acceptance yet; no further model runs are authorized by this task. Provider-reported charges sum to **$0.01424797**. Evidence is in `web-b-shots/m2-attempt-2/` and the local trace `.local/raven-runs/e61891dd14594155ac51d99ea814beb7/20261019T182507Z-21634243`. The real test service was stopped; the offline demo remains available. Final review/commit disposition is recorded in the worker log.

## Asset provenance

The native geometry, motion banks, compact demo and vendor licenses remain the imported assets. `manifest.json` retains source snapshot hashes while updating current-byte hashes for the backend client changes and recording added files. `validation.json` describes the historical import checks; it is not rewritten as new browser/model evidence. Use `python3 design/raven/tools/verify_bundle.py` for current asset integrity.
