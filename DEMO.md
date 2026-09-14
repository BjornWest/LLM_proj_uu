# Daylight: a small browser-agent demonstration

Open **http://localhost:8879**. The website is on the left; the distinct browser-extension-style **Daylight sidebar**
is on the right. **Chat** answers questions about the page and recorded activity.
**Tasks** runs a browser task when you press **Take care of it**. The toolbar
sidebar button collapses/reopens the assistant. This is a local extension mockup,
not an installed browser extension.
No native browser windows open. After a run, **Use page** returns to the
interactive site with its current reservations and other state intact.

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
- **Booking:** “Book the first available room in Ångström on Tuesday for 30 minutes, for 3 people.”
- **Preferences:** “Set my email updates to monthly and turn off product tips.”

Try different quantities/products, delivery choices, available booking times, or
email settings in **Live agent** mode. **Scripted rehearsal** only follows the
unchanged example; it runs real browser actions but makes no model calls.
Navigation between the three pages preserves the local session and conversation.
**Start fresh** clears them and creates a new local session.

These are fictional pages with normal, clearly labelled controls. Orders,
bookings and preferences live only in this Python server's memory. Restarting it
clears them; saved traces remain. There are no real payments or accounts.


## Study-room calendar and chat

The default page is a TimeEdit-inspired room finder. It has building, day,
duration, group-size and earliest-start filters, a calendar of available slots,
a booking confirmation and **My reservations**. The server rejects overlaps,
rooms that are too small and intervals extending beyond availability. The built-in
“first available” goal means earliest start, with room-name order breaking ties.
Its verifier uses availability before the run, including earlier reservations.
A room task ends on the first accepted reservation, whether correct or wrong;
the independent verifier checks the result afterward. This is a single-reservation
environment boundary, not evidence that the model chose to stop. Run another
task for an additional reservation.

Try these in **Chat**:

- “When are rooms in Ångström available on Tuesday for 3 people?”
- “Which Ekonomikum room has space for four people?”
- After a task: “What did you book, and what steps did you take?”

Then use **Tasks** with the built-in booking example, or edit it to request another
building, time or group size. Custom task goals still have null automatic
verification; inspect their page result or saved state.

The three buildings are Ångström, Ekonomikum and Blåsenhus, with **fictional rooms
and availability for 15–17 September 2026**. This is not connected to UU/TimeEdit.
The layout takes inspiration from [UU’s public student booking guide](https://www.uadm.uu.se/byggnadsavdelningen/lokaler/Selfservice_students.pdf),
which describes location filters, time intervals and calendar selection. This
prototype does not implement UU’s actual access rules or reservation quotas.

Chat has no browser tools and cannot execute changes. It receives text and form
values from the displayed page, or the latest saved browser observation while
watching an agent. Its run context includes the trusted task goal, recorded
activity, source (live/scripted), progress and errors. It does not receive hidden
state, expected outcomes or verifier results. While a task runs, the answer is
based on a snapshot and may lag subsequent actions. Up to eight prior conversation
messages are included; a fresh demo clears the conversation.

Each chat turn is its own trace under `runs/`, linked by conversation ID and,
when applicable, the related browser episode. The **Response record** link opens
it in the shared viewer. Exact requests, raw responses/errors, usage, routing and
page-context text are saved. Metadata labels it `read_only_chat`; browser-action
count is zero and evaluation is null. This is conversation, not an LLM judge.
Browser tasks and chat share the existing separate $3 Daylight ledger.

## What is connected

`intent_browser/demo.py` supplies the local state, controller, budgeted backend
and task hooks. `demo_rooms.py` supplies fictional availability and server-side
booking validation; `demo_chat.py` supplies read-only conversation and its logs. `environments/demo/` contains the dashboard and websites.
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
OpenRouter session ID per trace. Each browser task sends at most 12 requests, with 128 output tokens each.
Each chat question sends one request with up to 512 output tokens. Both use
reasoning disabled and no client retries. Browser tasks append a brief Python-call
format reminder after the page text; the exact enriched request is logged and
`demo_action_format_reminder` is recorded in metadata. Chat does not use that
reminder. This is a demo prompt change, not a change to the shared action parser. Parallel is not enabled.
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


## Original v1 development checks, September 14 (before the sidebar/calendar update)

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

## Sidebar/calendar checks, September 15

The three updated scripted UI rehearsals passed, with desktop/mobile layout
checks. Ten focused demo tests cover chat context isolation, exact logging,
transport errors, room capacity, overlapping bookings, changing first availability
and rejection of a valid reservation in the wrong building.

Live checks answered an Ångström availability question, completed the built-in
09:00 Å101 reservation, accurately described its recorded steps, and correctly
reported that no Ekonomikum booking existed. A separate custom request booked
E112 at 09:30–10:30 for three people. Its automatic evaluation stays null because
the goal is custom. Returning to the interactive page preserved that reservation.

Earlier development failures remain saved: two XML-format action responses,
and a run which booked five times instead of stopping after the requested first
reservation. The demo subsequently gained the explicit action-format reminder
and the single-reservation episode boundary described above. The successful
final run therefore does **not** establish that the model independently stopped
or avoided overbooking. Its selected reservation still passes the independent
state check. Existing calibration harness/protocols were not changed.

This check set used 26 requests and reported **$0.02169236**, with $0.154694 reserved
and no cost alerts. Each exact request/response matches the Daylight ledger;
source fingerprints and the different runtime phases are preserved in
[config/demo_sidebar_validation.json](config/demo_sidebar_validation.json).
Other user-triggered demo calls in the shared ledger are outside this check set.
