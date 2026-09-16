# Shared remote browser Ask

The control service now supports bounded agent turns in an existing manual
BrowserGym session. The agent does not reset the environment or create a second
browser. Human and agent actions share the same page, storage and journal.

## Ownership and lifecycle

`POST /api/manual/sessions/:id/ask` accepts a unique `request_id` and `goal`.
It durably claims agent control and returns immediately. Read the existing
session endpoint for progress and new frames. At most one controller can use a
session. Manual commands and another Ask are rejected while an Ask runs.
Repeating an accepted request ID returns its existing record without dispatch.

`POST .../interrupt` accepts the specific `ask_id`. It records interruption,
invalidates pending model output and aborts the model transport. An already
sent browser command finishes and retains its receipt before human control
returns. Cancellation cannot undo a click already dispatched. No model or
browser action is retried. Transport failures may have unknown billing; their
reservations remain charged against the local allowance.

The browser stays open after an answer, model error, interruption or step limit.
An uncertain browser-pipe failure closes it without replay. A native environment
terminal state prevents further actions. Close saves the complete session ZIP;
normal session inactivity/maximum-age limits still apply between turns.

## Policy and evidence

`scripts/shared_browser_policy.py` uses the existing BrowserGym AX adapter,
action descriptions and literal-call parser from the packaged runtime. This is
an explicitly new `browsergym-json-action-v1` policy protocol, not an unchanged
benchmark cohort. A strict JSON envelope contains one action call. Answers use
`send_msg_to_user(text)`; they are captured without closing or stepping the browser.
No model-supplied Python is evaluated directly.

Every decision gets a fresh observation. Only the current user request, observed
page and recent recorded human/agent activity enter the prompt. Reference task
goals, state journals, authorization expectations and grader outputs are not
prompt inputs. Historical content remains context, not new authorization.

The Node transport retains exact requests, response bodies, HTTP status, usage,
routing, timing, reservations and outcomes in `ask-UUID.json` beside the original
trace files. Interrupted requests remain present. Browser steps identify their
actor and retain exact model inputs/outputs; answers and parse failures also have
lifecycle records. The final archive includes the Ask records. Session summaries
expose user-facing answers and action summaries, never reasoning or private
reference state as chat input.

Arbitrary Ask goals have `evaluation: null`. The original fixture's final checker
may run on close, but is explicitly a reference diagnostic: it does not establish
success or authorization for a different user request, or for mixed human/agent
work. Historical manual-only traces are unchanged.

## Deployment and limits

The control container, not the page/browser child, needs the existing dedicated
demo `OPENROUTER_API_KEY`. The browser process still receives no inference,
control, invitation or worker credentials. No new external service is needed.
The same SQLite daily budget used by the demo is reserved before dispatch.
Reasoning is enabled; configured output ceiling defaults to 4096. Seven-provider
allowlist and one routing session ID per browser session are retained; provider
stickiness does not prove cache hits. Search remains disabled.

Limits: 12 model calls per Ask, 30 Ask turns per browser session, 100 browser
actions per session, 100 KB request bytes, and existing daily budget/call caps.
Unknown costs, HTTP/format failures and unexpected reported costs stop the turn.
There is no token streaming in this increment. Progress and new screenshots are
polled while a remote Ask is active and the page is visible. No Blob operations.

## Reproducible validation

- `node --test deploy/daylight/tests/shared-browser.test.mjs`
- `PYTHONPATH=. .venv/bin/python scripts/test_shared_browser_policy.py`
- `npm run build --prefix deploy/daylight`
- `.venv/bin/python scripts/smoke_shared_browser.py`

The browser smoke uses the actual invitation handler, control service, packaged
full Tricky site and BrowserGym, with a fake HTTP model transport. It is scripted
integration validation and incurs no paid model calls. It checks same-browser
human navigation and agent follow-up, interruption, malformed output, continued
use after errors, complete mixed-actor archives and null Ask grades.

Rollout uses `deploy/control/shared-browser.override.yaml` after the existing
full-site overrides. `.local/control/ask.env` contains only the dedicated demo
inference credential and selected model settings. Site assets, the immutable
package, worker image and existing data volumes are retained. Restart the worker
with the control container because it shares the control network namespace.
Check for active sessions/jobs immediately before this switch.

Read-only history remains invitation-owner scoped. Completed mixed sessions are
listed with the existing manual-session history; their downloaded ZIP has the
full Ask records. A global cross-machine trace library is separate work. A
process crash is not resumable: the session is marked interrupted, and original
request files remain on the PC; an incomplete session may lack a finalized ZIP.
