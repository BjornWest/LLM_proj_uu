# Interactive demo API and saved history

This extends the browser-side Daylight demo. It does not change BrowserGym,
the PC worker, or the active curation runtime. All routes retain invitation
authentication and same-origin POST checks.

## Interactive turns

`POST /api/start` with `{ "mode": "assist", "goal": "the current user message" }`
creates one turn and returns its trace `id`. Use `assist` for questions which
may require navigation or filters, as well as explicit action requests.
The older `chat` mode remains a one-request, read-only compatibility endpoint;
merely changing its prompt cannot make the old client execute tools.

For up to 12 decisions:

1. Wait for pacing and any previous navigation to finish, then capture the
   current iframe using `snapshot` from `client/observation.js`.
2. `POST /api/step` with `{ id, observation, conversation?, activity? }`.
3. If `error` is present, stop. Otherwise the full validated `action` is
   `click`, `select`, `check`, `fill` or `done`. Execute it with the original
   capture. Never replay it automatically after an error or disconnection.
4. Wait for actual navigation/render readiness before the next capture. A
   fixed 150 ms delay does not establish document readiness on a slow link.
5. `POST /api/event` with `{ id, result: { description, error?, page_after,
   state_after, events, stop?, stop_reason? } }`. Continue only when the result
   status is `ready`. Record `done` through this endpoint too.

`answer` is the user-facing text for a `done` action. Intermediate action
messages are not evidence of completion. State receipts remain explicitly
untrusted client evidence: `evaluation` is null and training eligibility false.
Existing first-accepted-booking termination is a client/runtime boundary and
must be labelled as such, not a learned model stop.

Navigation links and selects already work through the tool implementation.
The original complaint about being unable to click Study rooms is explained
by the old chat system instruction: "You cannot click or make changes in this
chat." `assist` explicitly permits navigation/filtering while distinguishing
availability questions from authorization to reserve or buy. This instruction
is not a deterministic authorization verifier.

The client must lock conflicting manual/task input while a decision is pending
and release it afterward. Exact delivered observations, request/response and
client receipts are saved. A failed final server write must not deliver an
unlogged action. Closing a tab before posting a receipt leaves an incomplete
record; it must not be presented as success.

## History

`GET /api/traces?limit=25&cursor=...` discovers existing and new browser-side
demo traces directly from private storage, without needing remembered IDs.
The opaque cursor is optional; limit is 1–100. Follow `has_more`/`cursor`.
Ordering is by storage key, not chronology: sort collected rows by
`created_at` for display, without treating one page as the latest global page.

Rows include goal, mode, status, runtime, timestamps, steps, dispatched model
attempts, reported cost sum, unknown-cost attempts and the original download
`url`. Zero reported cost differs from no reported cost (`null`). Ready,
pending, error and interrupted-client traces are retained as recorded.
`GET /api/traces/{id}` returns the original full JSON.

This increment is **owner-scoped** and covers the browser-side demo. Existing
BrowserGym jobs remain at `/api/harness/jobs`. A unified team library and
local/external ingestion are subsequent work; these are not silently enabled
by this endpoint. No public Blob URLs or worker credentials are returned.

## Validation

From `deploy/daylight`, run `npm run build` and `npm test` (33 tests at this
increment). From the repository root:

```bash
.venv/bin/python scripts/smoke_demo_interactive.py
```

The scripted real-browser check starts at Campus Supply, follows Study rooms,
sets Building/Day/People/Duration, answers with zero persisted changes, and
separately makes exactly one explicitly requested booking. It checks all
requests/receipts and owner history. Evidence uses a fresh directory under
`.local/vercel-demo/interactive-*/`; 35 checks passed in the first run. No
model inference is used, so this validates control execution and persistence,
not model reliability.
