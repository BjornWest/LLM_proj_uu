# Shared research interface: proposed ownership and sequence

User request, 2026-09-15: make the private Vercel deployment the team's entry
point for multiple training websites, live agent interaction, fixed-task
monitoring, and traces from deployment, local and external runs.

This is a planning handoff, not an implemented API contract. Preserve the
existing invitation protection and historical traces. Do not change active
curation cohorts, their budgets, or their frozen runtime files during UX work.

## Ownership

UX agent: website/task picker, chat and event history, live/replay controls,
trace browsing, requirement display, step feedback and follow-along controls.
Primary files are deploy/daylight/client/harness.html, harness.js and
harness.css. Coordinate before changing the existing browser-side demo or
shared API files. Build against agreed example events while APIs develop.

Harness owner: task registry and worker packaging, private trace ingestion and
indexing, team access rules, event transport, model response handling and
element-location capture. Primary files are intent_browser/team_worker.py,
deploy/daylight/lib/harness.mjs, deploy/daylight/api/index.mjs and deploy/worker/.
Core runner changes require focused regression checks and a new provenance
boundary. Keep graders independent of UI feedback and policy observations.

Curation owner: reviewed task goals, source/build identity, scenario coverage
and independent evidence review. UI work must not rewrite task contracts.

## First end-to-end increment

Expose the reviewed TrickyArena shopping fixture (P07), with clean and warranty
conditions, through the same BrowserGym worker as local validation. This is a
local synthetic site in the PC container; Vercel displays the remote browser.
It requires exporting its pinned fixture into the worker and adding task
selection, rather than deploying a second independently implemented storefront.
Preserve the exact goal and distinguish source site, condition and verifier.
Existing room and Chaos scenarios remain available.

Provide three clear activities:

- Ask the agent: free-form interaction where the environment supports it;
  unverified custom goals must retain unknown requirement outcomes.
- Watch a task: launch a trusted fixed-goal episode and observe live progress
  and verifier results; no goal entry is required.
- Replay a trace: inspect a recorded episode without inference or executing
  any of its actions again.

## Unified trace library

Record every deployed chat turn, attempted model request, tool decision,
action result, error and lifecycle boundary, including interrupted runs.
Preserve native runtime identity: the existing browser-side demo and
BrowserGym are distinct runtimes even when browsed in one library.

Keep immutable originals and derive a common browsing index. Reuse the
common_agent_util BrowserGym adapter and trace conventions where practical;
do not create a third authoritative trajectory format.

Add authenticated publication for local and external runs, including an
explicit backfill command for existing traces and optional publication after
future episodes. Uploads need stable IDs/hashes, duplicate detection,
resumable artifact transfer, and pending/partial/complete status. Local
originals must survive failed uploads. Do not make completion depend on a
viewer being connected. Do not automatically bulk-upload the existing corpus
before measuring storage size and checking publication contents.

The user requests a team-wide library. Implement explicit project-member
read access for shared research traces, while retaining ownership of writes
and excluding credentials/private worker controls. This intentionally extends
the current per-invitation job visibility; it must have access-control tests.
Feedback remains separately stored and cannot alter original outcomes.

## Interaction and event presentation

Streaming confirmed by the user: stream assistant text addressed to the user,
not internal reasoning or raw action JSON. Never execute a
partially streamed action; save the complete response and failures. Browser
progress streaming is separate from provider token streaming and can be
implemented first without changing the inference backend.

Show compact events for searches, commits/bookings and important failures.
Group routine clicks and typing in the default history, with all raw steps
available on expansion. A click on a purchase button is an attempted purchase;
only environment evidence can confirm the purchase. Do not claim a search
integration exists for controlled tasks where search is disabled.

Follow-along uses the actual action target and recorded browser viewport:
highlight it and keep it visible in the viewer. Allow follow to be paused
while inspecting history. Do not inject scrolling/focus actions into the
agent's browser just to animate the spectator view. Record target geometry
at the corresponding action/screenshot boundary, since BIDs and layouts can
change. Text AX input does not reveal which element the model 'looked at';
label action targets or explicit inspection targets accurately.

## Delivery order and acceptance

1. Agree on task, trace-index and presentation-event examples; build the UX
   shell alongside the P07 worker adapter and shared trace library.
2. Deliver P07 live watch plus replay and trace publication from one local
   run. Verify faithful originals, team permissions and unknown outcomes.
3. Add chat-facing streaming, concise event history and follow-along, with
   disconnect/error tests and exact saved request/response evidence.
4. Expand the registry to additional reviewed environments and external
   worker publication. Preserve build/grader/source provenance per run.

Use scripted/offline checks first. Any live test must state which existing
budget/key it uses; do not consume the independent curation sweep budget.
Container restarts and shared runtime changes must be coordinated around
active jobs. No UI should imply all benchmark tasks are already supported.
