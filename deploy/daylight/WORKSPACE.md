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
- External dataset sites currently expose remote tasks and recorded evidence.
  They do not support manual remote takeover. The sample Fieldnotes bookshop and
  all sample runs remain in the separate local design preview only.

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

Original browser-side traces expose their unchanged JSON in a text-only details
view with an authenticated download. Portable curation bundle import remains a
separate backend increment; this workspace does not execute uploaded HTML or
introduce another export format.

## Local validation

```sh
npm --prefix deploy/daylight run build
npm --prefix deploy/daylight test
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
