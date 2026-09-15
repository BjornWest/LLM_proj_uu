# Site workspace

The authenticated `/` and `/workspace` entry points organize the reviewed task
registry by site and collection. `/workspace/replays` lists the current invitation's
BrowserGym jobs and original browser-side traces. `/demo` retains the original
Campus dashboard; `/harness` retains the full research controls.

## Execution

- Campus supports ordinary manual browsing with the browser agent in a sidebar.
  Ask uses the existing OpenRouter assist protocol. Each complete response and
  action receipt is saved before the next step. Manual controls lock during the
  turn; failed writes or changed documents stop it without automatic retry.
- **Try this task** submits an actual worker job, explicitly classified as `task`
  and requiring `live` execution. There is no scripted fallback. The worker uses
  its configured OpenRouter model. Its availability, budget and request limits
  still apply. Offline workers leave jobs queued.
- Fixed tasks submit their exact registry goal and revision. Session-generated
  goals are omitted from the request and display a pending objective until the
  worker prepares the actual session.
- External dataset sites expose remote tasks and recorded evidence. The manual
  exploration controls described below become available when the manual-session
  backend is enabled. The sample Fieldnotes bookshop and
  all sample runs remain in the separate local design preview only.

## Remote manual exploration

The MANUAL-SITES-01 frontend increment is prepared for coordinated backend
publication. It uses `/api/manual/config` and the invitation-scoped session API;
it does not create sessions just by opening a site or loading history.

Choose a website setup, including its clean/injected condition, and select
**Open website**. Click the screenshot to interact. While the image has focus,
Tab, arrows, Enter, Escape and Backspace control the remote browser; Shift+Tab
leaves those controls. **Send text** types into the remote page's focused field.
The key menu also supports selecting all field text and moving to the previous
field. Scroll and image refresh are explicit commands. One command runs at a time.

**Check sessions** reads recorded metadata to recover after a stale frame,
uncertain response or page reload. It does not repeat a command or capture a new
frame. Close the current session before opening another site; a new session uses
an isolated browser. Unsent text remains local.

Manual sessions appear as **Manual / Not graded** in site and global history.
The read-only summary provides the finalized original ZIP when available and
keeps reference fixture evaluation separate as diagnostic evidence. Manual
exploration invokes no model. External Ask remains unavailable, and task launches
start separate agent runs with fresh state.

Frontend contract validation: `.venv/bin/python scripts/smoke_manual_workspace.py`
uses mocked manual API responses and screenshots. It does not validate actual
BrowserGym execution.

Actual integration validation: `.venv/bin/python scripts/smoke_manual_workspace_live.py`
starts the isolated `tests/manual-server.mjs` fixture with its real package and
BrowserGym driver. It checks the workspace's Music membership Buy click,
Electronics shop scroll/keyboard controls, session isolation, read-only history
and original ZIP. This is scripted validation with no model inference. The
backend owns the full variant/container acceptance and coordinated publication.

## Chat activity

**Full screen** fills the browser viewport with the site and sidebar. Use the
sidebar's **Exit full screen** button or Escape to return, including when the
website has keyboard focus. The page, chat draft and earlier sidebar visibility
are preserved.

Enter sends a chat request; Shift+Enter inserts a new line. Composing text with
an IME, holding Enter, blank input and disabled controls do not submit requests.
You can draft while Daylight works. Sending a message (or pressing Enter)
interrupts the current run and starts a new turn with the new instruction and
the current page. A pending model response cannot execute its old action. An
already executing browser action and its receipt settle before the new turn
captures a fresh observation. Applied changes remain on the page.

The interrupted trace keeps its original goal, requests, late response and cost;
the new trace links back with `continuation_of`. Already dispatched inference may
still finish and incur cost. A failed interruption write stops locally and shows
that the replacement was not started. Sending is briefly disabled during that
handover; typing remains available and unsent drafts survive it.

Browser actions appear as compact, expandable **Browser tool** cards inside both
chat timelines. They show execution and record-saving status separately from
assistant replies. Expanded details use that step's exact pre-action target and
recorded action. Tool display entries never enter the model's chat history.
Browsing earlier activity preserves the workspace chat's scroll position.

## Recorded evidence

New activity metadata separates Task/Ask from execution mode and runtime. Older
runs without explicit activity remain unclassified. Missing historical site,
collection, condition and task names stay unknown; the current registry does not
fill those gaps. Per-site and global views
use the same owner-scoped APIs. Browser-side trace pagination is exhausted before
chronological sorting; partial failures show an error instead of silently
claiming a complete history.

BrowserGym review embeds our existing authenticated harness renderer. Replay
controls select recorded steps, including distinct steps whose action strings
match. Decision observations belong to their exact pre-action step; latest
browser images represent post-step state. Browsing a replay does not enqueue a
job, invoke a model or recompute a verifier.

The list's Succeeded/Failed labels reflect the recorded `safe_success` boolean.
Partial requires an explicit grade and rubric. Missing safe-success remains
Unknown even when other individual outcome flags are present. Browser-side
requests without independent verification are Not graded. Runtime errors remain
visible as execution status, separately from grading.

Browser-side history groups turns by an explicit conversation ID. The workspace
and original demo keep that ID until Start fresh or a page reload. Interrupting
with a new message stays in the same conversation; each turn still has its own
immutable goal and original trace ID. Legacy turns are grouped only when their
recorded continuation/prior-activity link names another owned trace. Unlinked
historical turns remain separate; equal goals are not evidence of a session.
Mixed or missing recorded activity/site metadata stays unknown for the group.

Opening a conversation shows model bubbles on the left and user/tool bubbles on
the right, in turn order. Browser action labels use that step's pre-action
observation; transition feedback is a separately labelled detail. Interrupted
output and missing receipts are visible without implying execution. Exact JSON
stays behind collapsed evidence details, with authenticated original downloads
for every turn. Old per-turn deep links open their containing conversation.

The **Tools only** switch replaces conversation bubbles with a numbered,
chronological timeline of recorded actions. Replies (`done`) are excluded;
failed and unconfirmed execution remain explicitly labelled. Each step links
to its available-tool inventory. Inventory cards come from that exact request's
`tools` definitions or structured action enum, including unused capabilities;
changing the selected step preserves changing definitions. Page controls are
not treated as tools. Missing definitions remain unknown, distinct from an
explicit empty tools list. All definitions and arguments render as text.

BrowserGym jobs also show their published objective and recorded actions as
bubbles above the existing screenshot replay. The current job API does not
publish full model messages; this view does not invent dialogue or rationale. Portable curation bundle import remains a
separate backend increment; this workspace does not execute uploaded HTML or
introduce another export format.

## Local validation

```sh
npm --prefix deploy/daylight run build
npm --prefix deploy/daylight test
.venv/bin/python scripts/smoke_trace_tools.py
.venv/bin/python scripts/smoke_conversation_replays.py
.venv/bin/python scripts/smoke_workspace_ui.py
.venv/bin/python scripts/smoke_demo_chat_ui.py
.venv/bin/python scripts/smoke_chat_controls.py
.venv/bin/python scripts/smoke_chat_interrupt.py
```

The browser tests use the production handler and isolated temporary storage with
an offline model transport. Their screenshots and source fingerprints are written
to `.local/vercel-demo/`. They validate integration, not live model reliability,
and make no paid inference calls. `tests/workspace-server.mjs` is a test-only
server with seeded evidence; it is never part of the deployed entry point.

Conversation replay increment (local, pending coordinated publication): 71 Node
checks, 20 conversation browser checks, 31 workspace checks, 37 interruption
checks and 17 original-chat checks passed with offline transport and no paid
calls. Evidence under `.local/vercel-demo/`:
`conversation-replays-1cabbfd5/report.json`, `workspace-0d074d33/report.json`,
`chat-interrupt-96a29f55/report.json`, and `chat-ui-7321b7e7/report.json`.
The conversation test also creates a standalone local design preview from the
trusted rendered test DOM; it is not a saved-run export or production evidence.

Tool timeline increment (local, pending coordinated publication): 76 combined
Node checks, 19 tool-review browser checks and 20 conversation regression
checks passed with no paid calls. Evidence:
`.local/vercel-demo/trace-tools-d0f61c26/report.json` and
`.local/vercel-demo/conversation-replays-949a2ff6/report.json`.
The BrowserGym published-job inventory remains unknown until exact request
definitions are exposed; its existing recorded actions still form a timeline.
