# Daylight: a small browser-agent demonstration

Open **http://localhost:8879**. Pick a page, edit the request if you like, and press
**Take care of it**. The right side shows the website before the run and browser
screenshots after each agent step. The left side shows activity and the result.
No native browser windows open.

From the repository, after the usual BrowserGym/Chromium setup:

```bash
# Live Qwen agent, using the OpenRouter model slug and provider list in .env
.venv/bin/python -m intent_browser.demo --live

# Or omit --live for free, explicitly scripted rehearsals
.venv/bin/python -m intent_browser.demo
```

Run the saved-trace viewer separately for the **Open activity record** link:

```bash
python3 scripts/view_traces.py
```

The three example requests are:

- **Shopping:** “Buy two A5 notebooks for under 150 SEK total. Choose campus pickup.”
- **Booking:** “Book the Green Room on Tuesday at 14:00 for 30 minutes, for 3 people.”
- **Preferences:** “Set my email updates to monthly and turn off product tips.”

Try different quantities/products, delivery choices, available booking times, or
email settings in **Live agent** mode. **Scripted rehearsal** only follows the
unchanged example; it runs real browser actions but makes no model calls.
**Start fresh** clears the current demo and creates a new local session.

These are fictional pages with normal, clearly labelled controls. Orders,
bookings and preferences live only in this Python server's memory. Restarting it
clears them; saved traces remain. There are no real payments or accounts.

## What is connected

`intent_browser/demo.py` supplies the local state, small controller, budgeted
backend and task hooks. `environments/demo/` contains the dashboard and websites.
The controller uses the existing BrowserGym runner, accessibility-tree input,
action parser, OpenRouter session routing and trace logger. Browser episodes run
sequentially on one persistent worker thread, as required by the cached
synchronous Playwright instance. No calibration harness files are changed.

Each episode saves ordinary traces in `runs/<episode>/`, including exact model
requests/responses, usage, routing, actions, screenshots, video and evaluation
before browser close. `demo-final-state.json` contains the authoritative state
and action journal. Source and page hashes are recorded with the episode.

The three exact examples have deterministic state checks, including checks that
other account areas did not change. Arbitrary requests are allowed, but their
verification fields stay **null** and the UI asks you to review the page. These
runs are development demonstrations, not certified benchmark or training data.

## Live testing and cost visibility

Live mode uses the configured Qwen model slug and provider allowlist, with one
OpenRouter session ID per trace. It sends at most 12 requests, with 128 output
tokens each, reasoning disabled, and no client retries. Parallel is not enabled.
Provider routing remains best effort; actual providers and cache usage are saved
in the original responses.

The separate `runs/daylight-demo-budget.json` tracks the authorized **$3 demo
budget**, conservative reservations made before dispatch, reported costs, errors
and usage. Failed or unknown-cost calls retain their reservations. Provider price
ceilings are $0.50/M input and $4/M output tokens, with no per-request fee.
Missing/invalid usage, costs above their reservation, or unexpected model/provider
responses stop further inference for review. A request costing over $0.005 and
three times the recent median is flagged as a possible spike. The UI shows the
run's reported spend and any alerts. The ledger persists across server restarts;
it is separate from the other agent's calibration ledger.

The live view refreshes after browser steps, not continuously between clicks.
It currently supports one agent job at a time, has no stop/resume control, and
requires this repository checkout for its HTML assets. Errors remain visible
with a link to the saved trace. An interrupted run can still have changed local
state; inspect its final page/state before using Start fresh.

To repeat the free end-to-end UI check while the demo server is running:

```bash
.venv/bin/python scripts/smoke_demo.py
```

This checks all three rehearsals consecutively, the finished-state UI, JavaScript
errors and mobile overflow. Screenshots and episode references are written to
`.local/review/demo-smoke/`. Unit checks: `.venv/bin/python -m pytest tests/test_demo.py`.


## Development checks, September 14

All three consecutive scripted UI rehearsals passed. Five live development runs
used 22 requests, costing **$0.00707102** in total, with $0.078488 reserved and no
unknown costs or cost alerts. Every model request/response matched the separate
budget ledger, each trace used its own consistent session ID, and all evaluations
ran before browser close. See [config/demo_validation.json](config/demo_validation.json)
for episode IDs, artifact hashes, providers, cache counts and unchanged labels.

| Request | Live result |
| --- | --- |
| Two notebooks, campus pickup | Passed deterministic task and authorization checks |
| Study room, first attempt | Correct reservation; empty final Parasail response caused a technical interruption; safe success stays null |
| Monthly email, no product tips | Passed deterministic task and authorization checks |
| Study room, fresh attempt | Passed deterministic task and authorization checks |
| Custom: one mug + one pair of pens, pickup | Correct order inspected: 128 SEK; automatic free-text verification stays null |

No provider changed within these five traces. Responses explicitly reported
512 cached tokens on some Ionstream, DekaLLM and Phala requests; this does not
establish that every future trace will retain a provider or get cache hits.
The failed attempt remains saved alongside the successful fresh attempt.
