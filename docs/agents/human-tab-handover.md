# Human tab handover (opt-in local integration)

The agent can yield a challenged tab to a human, continue in another tab, and
inspect the returned tab later. Local implementation and scripted browser tests;
no model or production deployment validation is claimed.

## Use

The explicit CLI mode needs visible Chromium and disables helpers:

```bash
.venv/bin/python -m intent_browser.cli run \
  --open-internet --human-handover --headful --no-subagents \
  --url https://example.com/ --goal 'Your information-only task here' \
  --env-file .env
```

This command makes real model requests using the configured endpoint. It is an
entrypoint, not a request to run another model episode. Existing run authorization
and cost limits still apply. Controls appear inside the BrowserGym conversation
window. The printed loopback panel is a diagnostic fallback. When the agent yields a tab, select **Start helping**,
work in that Chromium tab, then select **Finished** (or **Cancel handover**). The
panel signals ownership only: it neither clicks page controls nor verifies success.
Use the fresh Chromium context created by the harness, not your personal profile.

For direct callers:

```python
from intent_browser.open_internet import open_profile, with_human_handover
from intent_browser.human_handover import HumanHandoverController
from intent_browser.human_handover_ui import HumanHandoverUI
from intent_browser.observation_pipeline import ObservationPipelineConfig

profile = with_human_handover(open_profile(base_profile))
controller = HumanHandoverController()
with HumanHandoverUI(controller) as panel:
    print(panel.origin)
    run_episode(
        env_factory, backend, metadata,
        harness_profile=profile,
        human_handover=controller,
        human_handover_ui=panel,
        observation_pipeline=ObservationPipelineConfig((), full_capture_only=True),
        # Other ordinary episode options, including output/context/turn limits.
    )
```

`base_profile` must use native tool batches, incremental AX, and no helpers. A task
adapter must adopt the resulting exact profile as usual. Create a fresh controller
for every episode; the UI and runner must share that same controller object. No
credentials are passed to the panel. Its HTTP handler checks loopback Host, Origin,
random header token and handover-cycle identity. It is not a remotely exposed UI.
The embedded controls use separate capability-authenticated endpoints accepting
the private chat page's opaque origin; opaque origin alone grants no access.
HTTP signals keep working while synchronous model I/O blocks the Playwright owner
thread. Control/status text is not inserted into model-facing chat messages.

For this testing profile, the prompt explicitly requests immediate human handover
on verification challenges, leaving the challenge tab open and continuing useful
work in another tab. If handover created a blank workspace, reuse it. This prompt
is recorded through ordinary harness instructions metadata; ordinary profiles are
unchanged.

## Human chat delivery

The opt-in runner attaches to BrowserGym's private user-input callback after reset.
Actual human messages become distinct `user` messages after pending tool results;
the initial goal and arbitrary benchmark-inserted `chat.messages` are not promoted
to new human instructions. Duplicate messages entered separately remain separate.
Capture sequence, original text, timestamp and exact request-span delivery evidence
are retained. Capture alone is not evidence that a model received the message.

When a message arrives during generation, the owner thread processes the callback
upon returning from model I/O. Pending actions/final replies are marked
`human_message_pending` and not executed; the new input is delivered on the next
decision. The model response and usage remain recorded. This does not cancel the
HTTP request or undo an action already executing, and does not bypass limits or
automatically recover unrelated model/transport errors.

## Tool and lifecycle semantics

- `handover_tab(tab_id, reason)` yields an agent-owned tab; it must be last in a
  batch. If it was selected, the runtime selects another agent-owned tab or creates
  a blank workspace. That fallback is explicitly traced.
- This profile's `tab_focus(tab_id)` uses stable IDs, replacing index-based focus.
  Closed IDs are never reused. Human-owned tabs cannot be selected. Returned tabs
  are captured freshly before resuming agent ownership. Focus selection does not
  call `bring_to_front`, allowing the human to keep their visible tab.
- `new_tab` and `tab_close` are managed by the custody layer and end the batch.
  Unsolicited popups do not auto-select. Popups with human or unknown openers retain
  human custody. Closing the active tab cannot silently redirect a pending call.
- Ordinary tools still operate on the pinned agent tab. Their schemas stay constant
  throughout the episode; ownership denial is explicit tool feedback.
- `proceed_action(confirmation_id)` is always advertised in this opt-in profile.
  It is the only call allowed in its batch and resolves to one previously blocked
  action, with its exact saved arguments. It cannot authorize a different action.
- Human completion/cancellation appears as a bounded recent-transition list in
  tab observations. It is not injected as an instruction or a correctness grade.

## Target and capture guards

BrowserGym ordinarily updates `env.page` on focus, mouse and page events. This mode
intercepts that per-environment callback, pins the selected Page, and ignores human
focus for targeting. Before trusting cached page liveness it pumps queued Playwright
callbacks using BrowserGym's existing `context.cookies()` idiom; returned cookie
values are discarded. All Playwright calls remain on the browser owner thread.

Native BrowserGym DOM/AX/screenshot extraction operates on the real selected Page,
through a narrow observation view whose context tab list contains only that Page.
Other tabs' titles are not evaluated. The ordinary tab fields are then populated
from controller metadata (last captured display titles/URLs, not live page content).
Native load waits and document guards likewise inspect only the selected tab.
Event-feedback capture excludes other tabs and does not retrospectively recover
human-only events when a tab returns. An already-open selected tab installs its
observer if missing, recording the capture gap.

A decision records its stable tab ID, custody cycle, capture document signature and
full public AX digest. Fresh guards compare identity/custody/document before every
dispatch. In the `localized-proceed-once-v1` guard, read-only AX/data/image inspection,
explicit `goto`, waits and tab selection/creation/handover can proceed on fresh
content despite unrelated AX changes. Existing reference/target validation still
applies. Other actions check changes to public AX content/structure, including
shared-storage changes. Same-URL document
replacement, ownership loss and invalid targets still cancel pending calls with
`not_executed` feedback. Calls are never automatically replayed. Ordinary native
batch navigation/target guards remain in place. All tab-control calls end the batch
so subsequent dependent tools require a new observation/model decision.

When public content changed, tool feedback includes bounded before/after evidence
and semantic section paths. Relationships are `target`, `same_section`, `elsewhere`
or `page` for an action without a BID. These are structural relationships, not a
claim that distant changes are harmless: a cart total elsewhere can matter. The
model decides relevance. Raw extraction identifiers are omitted from the preview;
complete changes are retained in a `human-change-*.json` artifact. Omitted changes
are counted, and normal fresh AX inspection remains available.

For a still-valid target, this feedback issues a `confirmation_id` for the exact
blocked action. `proceed_action` consumes it before checking or dispatching. It
allows further **content** changes for that single attempt without asking again;
it never skips tab ownership, handover-cycle or document checks. BID targets must
retain their captured AX/DOM identity and role, exist and not be disabled at the
fresh check. Invalid targets receive no actionable confirmation. Checks do not
make a website transaction atomic with the capture.

Only the latest confirmation is pending. It survives read-only inspection and
waits, but a subsequent browser mutation or newly delivered human instruction
clears it. Navigation or custody changes invalidate its bound context. An attempted
confirmation is consumed on success, failure or rejection; it cannot replay an
action. This confirms the model's intention despite evidence changes, **not** user
authorization for new effects. Traces retain both the proposed proceed call and
the resolved original action, linking the initial step/tool ID and change artifact.

## Evidence and limits

Fresh human-tab capture now makes at most three complete observation attempts
when `DocumentScanInvalidated` reports a frame/document race. The selected Page,
tab ID and custody cycle stay pinned across attempts; recovery never calls
`env.step`, replays a click, or silently switches to another tab. Each accepted
observation still requires matching full frame/document signatures before and
after native BrowserGym extraction. A recaptured new document does not validate
an old decision ticket. Closure, custody changes and unrelated extraction errors
remain failures. This is an attempt bound, not a hard wall-time deadline; native
BrowserGym extraction retains its own retry/timeout behavior.

`human_tab_capture_invalidated` events retain the attempt, capture stage and scan
detail. Recovery records `human_tab_capture_recovered`; exhausted capture records
all three failures in `document_scan_detail` on the failed decision and lifecycle
event. These diagnostics are trace evidence, not extra policy instructions.

Local reproduction and acceptance: `scripts/verify_human_capture_race.py`, with
baseline and repaired artifacts under `.local/human-capture-race-v1/`. These are
synthetic Chromium frame races and scripted runner responses, not a new retailer
or model episode. The original v3 real-web trace remains unchanged; its final
failing scan branch was not retained, so the synthetic reproduction establishes
the failure mechanism rather than proving that exact historical branch.

Raw transitions keep human/agent/browser actor labels, sequence, timestamp and
handover cycle. Runner records where it **observed** each transition (step/model or
tool association); observation time does not assert the event happened at that
instant or was caused by that tool. Arbitrary DOM events are not reliably attributed
to humans versus scripts. Raw proposals, exact requests, tool results, target tickets
and policy-delivery records remain in the episode trace. Evaluation still precedes
close; human participation does not promote safety/training labels.

This is cooperative interactive control, not exclusive OS-level input isolation:
people should use only yielded tabs. Cookies/storage/server state remain shared.
The guard detects resulting visible AX/document changes, not every invisible server
state change. Highly dynamic pages can still conservatively cancel mutations,
with the explicit one-use path above for valid targets. Native capture
errors can still terminate a run rather than risking a stale action. Fast/background
partial capture and subagent concurrency are intentionally not enabled in this mode.
The local version-pinned BrowserGym integration is not a general cross-version API.

Validation commands (new output paths required):

```bash
.venv/bin/python -m pytest tests/test_human_tab_tools.py tests/test_human_handover.py tests/test_human_chat.py
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python scripts/verify_human_tabs.py --output .local/human-tabs-NEW
```

The controller tests use pytest-style functions; use `python -m pytest` to collect
them. The current combined adoption adds `tests/test_human_chat.py` and
`scripts/verify_human_chat.py` (new `--output` directory required). Evidence under
`.local/human-tabs-v2/` distinguishes this increment from the historical v1 suite.
Localized change/proceed acceptance is under `.local/human-tabs-v3/`; its scripted
fixtures also test further changes after confirmation, duplicate/failed attempts,
target replacement/removal/disable, reload, closure, human custody and new chat.

The browser suite uses real native clicks through a separate CDP connection while a
scripted model response is pending. No external sites or inference APIs are called.
Seven cases cover human focus+popup+completion, owned-tab denial, shared-storage
content changes, human-tab closure, active-target closure, same-URL reload and
cancellation. Fake responses test execution/ordering, not model judgment about when
to request human help. Historical setup failures and the initially reproduced cached
liveness bug are retained separately under `.local/human-tabs-v1/`.

## Loaded-page capture latency repair (2026-09-27)

The v4 open-web case exposed the limitation of attempt-count recovery: native
BrowserGym visibility marking waits up to one second *sequentially per frame*,
and its own extraction loop permits five attempts. Three outer attempts did not
bound elapsed time. Ordinary hidden frames alone do not reproduce the warnings;
the controlled stress fixture deliberately suppresses IntersectionObserver
callbacks. The exact phase distribution of the frozen live stall is unavailable.

`intent_browser/native_capture.py` now supplies the human-tab native capture path.
It uses the pinned upstream marker, starts each frame's normal marking before
collecting visibility results, and preserves parent-before-child BID assignment,
the original one-second visibility timeout, warnings and frame content. A private
copy of the native `_get_obs` function globals substitutes phase instrumentation
and this marker; installed packages and global BrowserGym functions are unchanged.
Normal APIs and all policy tool schemas remain unchanged.

The approximately one-second loaded-page target is separate from navigation,
action delays and inference. A five-second shared capture budget covers all outer
attempts and protocol waits. Exceeding it raises `CaptureDeadlineExceeded` and
ends the episode; no partial observation or stale screenshot is delivered and no
action is replayed. One additional second is allowed for best-effort cleanup.
This is not a process-level real-time guarantee: synchronous Python CPU work is
checked at phase boundaries. Playwright 1.44.0 connection cancellation is explicitly
pinned; a cancelled await does not undo a command already sent to Chromium. The
runtime does not continue action execution after a deadline failure. Native
best-effort DOM-loaded waits also share one second, instead of waiting up to three
seconds for each advertising frame; subsequent guarded full capture remains required.

Every capture records phase/frame timings, warnings, the target and an overrun
flag. Local full-capture measurements (not renderer load or model wall time):

| Fixture | Original native capture | New guarded capture (two samples) |
| --- | ---: | ---: |
| Main document | 0.146 s | 0.167 / 0.147 s |
| 16 hidden child frames | 1.404 s | 0.728 / 0.718 s |
| Nested, cross-origin frames (5 total) | 0.475 s | 0.309 / 0.319 s |
| 32 children with suppressed visibility callbacks | 35.186 s | 2.502 / 2.442 s |

The large stalled fixture still exceeds the target, explicitly. All four matched
native AX semantics, BIDs, element visibility/geometry and DOM-document counts.
The same unknown/default visibility values remain when callbacks are suppressed;
faster capture does not make those values more accurate. Blocked frame evaluation
and blocked screenshot RPC probes returned deadline errors at approximately
5.01 seconds; subsequent explicit diagnostic reads and cleanup succeeded.
Evidence: `.local/human-capture-latency-v1/release/report.json` (47 combined browser cases).

Action reporting is separate: `human_tab_action_execution_completed` is emitted
when native action code returns, before waiting, grading or capture. The batch
record retains `action_execution`. `browser_stepped:false` means `env.step` did not
return a full observation, **not** that the action had no effect. A post-dispatch
capture failure now reports `action_completed_observation_unavailable` when that
native evidence exists, or `failed_effects_unknown` without it, rather than
`not_executed`. This is execution evidence, not a task-success verdict. The model
is instructed to inspect fresh state and not automatically repeat the action.

The v4 source snapshot and trace are unchanged. All repair validation is local,
using scripted responses; no new paid or real-web episode certifies this version.

## Supervised wait and compact tab context (opt-in, 2026-09-27)

```python
profile = with_human_handover(
    open_profile(base_profile), wait_for_human=True, compact_tabs=True,
)
```

Both options default to false. Existing concurrent profiles retain their policy,
workspace selection and tool descriptions. Freeze a new source/profile closure
before using these options; historical model traces are unchanged.

`wait_for_human=True` is a supervised **single-current-tab** profile. Its static
schema retains tab tools but describes and rejects new-tab/close/other-tab
selection requests. `handover_tab` yields the current tab and pauses inference
until the human chooses Finished or Cancelled through the existing controls.
The runtime posts a clearly attributed help notice to the native conversation
window. It pumps browser callbacks without policy actions, page capture or model
calls. Human waiting is outside the five-second capture deadline. There is no
implicit timeout: return, cancel, close the tab, or stop the episode explicitly.
Closing the tab ends with an error, without a replacement workspace.

The tool result distinguishes `human_return: complete` from `cancel`. Both require
a fresh same-tab observation; neither proves verification passed. Human input
continues through the existing trusted chat delivery path. A custody change
inside capture still rejects that capture, rather than accepting old evidence.

`compact_tabs=True` emits one tab snapshot followed by field deltas or short
unchanged references. State identity includes active tab and complete tab values,
so focus changes cannot hide behind an unchanged controller revision. New
handover/return/error-related custody transitions appear once; raw observations
and event logs retain full state. Reasons are sent when changed, rather than on
every subsequent state transition.

Rendering a transition or pre-dispatch observation does **not** advance this
baseline. `tab_context_constructed` records the exact projection only when it
enters append-only conversation history; HTTP dispatch/acknowledgment remains
separate policy-delivery evidence. Prior messages are never rewritten. This
retains prefix stability but does not promise provider caching.

Local acceptance: `.local/human-wait-v1/browser-long-wait/report.json` checks
Finished, Cancelled, closure, a wait longer than the capture deadline, HTTP human
controls, no waiting-time model calls, fresh changed content, constant tools,
exact snapshot reconstruction and unchanged prior message prefixes. All model
responses are scripted. Default concurrency regression is recorded separately.
Offline saved-v4 ablation (`scripts/measure_tab_context.py`) reconstructs all 70
states and changes no non-tab text: Qwen local full-request estimate falls from
100,134 to 76,681 input tokens (23,453 fewer). This is a counterfactual formatting
measurement, not a new rollout, success result or measured cache improvement.

## Stable-frame capture for open-web churn (opt-in, 2026-09-27)

The next supervised profile can also pass `stable_frames=True` to
`with_human_handover`. Default/older profiles retain the whole-frame-tree guard.
This addresses the v5 failure in which a successful native capture was discarded
because an unrelated child document changed, and repeated captures exhausted the
shared five-second deadline. It does not increase that deadline.

The new path reads the CDP frame tree/loader identities and main document identity
instead of evaluating JavaScript serially in every frame. After successful native
DOM/AX extraction it projects only documents whose identity and ancestor chain
remained stable across extraction. It preserves the main page, surrounding content
and every stable child; newly attached, replaced or removed child documents are
explicitly incomplete. A later fresh capture can restore them. This is temporary
observation coverage, not removal or modification of website source.

The exact main page, URL (including fragment), document and custody must still
match. Main changes retry observation within the existing bound. A same-Document
DOM rewrite is a content/target change; existing fresh AX and target-identity
checks still apply. These observations are not atomic snapshots of all page state.

A partial capture adds a visible `FRAME COVERAGE` notice. It does **not** establish
that omitted content is empty, irrelevant, or safe. Omitted child nodes and DOM
records are removed from the policy snapshot, references between DOM documents
are remapped, and visibility/geometry is recomputed from retained documents.
Frame-container BIDs are not actionable when their child content is missing.
The pre-projection native DOM/AX is retained separately as
`frame-capture-native-*.json.gz`; exact included/omitted frame evidence stays in
raw observations and `human_tab_frame_coverage` events. Screenshot pixels still
show the entire viewport at their capture time, including possibly omitted
frames; the scope notice makes that distinction explicit.

Pending element actions must have a BID in the captured stable documents, and
that frame plus every ancestor must still have the recorded identity. Replacement
of the target frame rejects the action even at the same URL, and `proceed_action`
cannot override this. Existing fresh target/backend-node and content checks remain.
Unrelated child identity changes no longer cancel navigation or stable-document
inspection simply because the global frame list differs.

Limits: native extraction itself is still full-page and bounded. This increment
fixes whole-tree guard invalidations after successful extraction; it does not
make every native extractor failure or continually blocked renderer recoverable.
Five-second capture failures, closure, custody loss and unrelated errors remain
explicit failures, with prior committed actions preserved and never replayed.
The approximately one-second target is not a guarantee. No new real-web/model
run is evidence for this version; acceptance is scripted against local fixtures.
See `.local/scoped-capture-v1/acceptance.json` for exact current source/evidence.

## Bounded child RPCs and teardown (stable-frames-v2, 2026-09-27)

The v6 failure occurred during a redundant native capture before `ax_search`,
not during inference or the AX query itself. With `stable_frames=True`,
`ax_search`, `ax_read` and `ax_changes` now query the captured snapshot. Custody
and main-document checks remain live; browser mutations still require fresh
capture plus target/document/content validation. `captured_ax_query` and the
batch member's `observation_reused` record this distinction. A captured AX result
is not a claim that the current live DOM is unchanged.

Child-frame marking/owner lookup/cleanup RPCs have a 0.5-second allowance inside
the existing aggregate five-second capture budget. Visibility completion retains
its native one-second allowance (1.1-second RPC bound). In scoped mode only, an
individual child timeout excludes that Frame and its descendants from policy
DOM/AX and target permission, while retaining usable main/other-child content.
If the timed-out child's document cannot be identified, all child documents are
conservatively excluded for that capture. `FRAME COVERAGE` explicitly reports
unknown content. Main-document timeout and aggregate exhaustion still fail.

An RPC cancellation cannot undo a browser command: a late marker may still run.
The excluded Frame therefore stays quarantined for its lifetime, including
same-Frame navigation; it is not automatically restored on the next capture.
A destroyed/replaced Frame can be freshly inspected. Native pre-projection
artifacts record the exclusion inputs for deterministic projection replay.
Screenshots remain whole-viewport pixels, not proof of accessible child content.
This is runtime observation coverage, not a reduced website or verifier shortcut.

Shutdown starts immediately after evaluation and logs each cleanup phase. Event
observer cleanup skips per-frame JavaScript/CDP detachment when the browser
context is being destroyed. Human-browser cleanup RPC phases are bounded (two
seconds each, five for BrowserGym close), with an owned-browser-close fallback
if normal close fails. These are RPC bounds, not a process watchdog around
arbitrary synchronous Python task cleanup. A close failure retains technical
error/unknown safety. The historical 128-second pre-close gap had no phase
instrumentation; per-frame cleanup is a plausible source, not an established
attribution for that specific trace.

Acceptance and the exact source snapshot are in
`.local/native-quarantine-v1/acceptance.json`. Tests use actual local Chromium and
scripted responses, including indefinitely blocked/late child marking, blocked
cleanup, document/custody changes and concurrent human handover. They do not
establish real-retailer success or a universal one-second latency guarantee.
Overnight adoption retains `wait_for_human=False, compact_tabs=True,
stable_frames=True`; only Curation owns the three separately authorized trials.

## Viewport-only screenshot guards (stable-frames-v3, 2026-09-27)

Overnight trial1 reached76 responses, then exhausted the aggregate native capture
budget before dispatching `screenshot`: marking2.35s + DOM1.53s + AX1.07s +
extras0.41s. This was accumulated useful work, not one stuck frame. The prior
cleanup repair bounded shutdown; it did not cause the capture failure.

With scoped capture enabled, screenshot batch guards now retain the existing AX
reference and obtain **fresh pixels** directly through the visual-readiness path.
They do not run native marking, DOMSnapshot, AX extraction or DOM geometry as a
prerequisite. `viewport_only_guard`, `viewport_capture_started/completed`, and
`observation_reused` distinguish the older AX reference from current pixels.
The screenshot path retains a five-second RPC budget, live tab custody/cycle and
main-document checks before and after capture. A changed document or custody
rejects policy image delivery; any already saved raw visual artifact remains
trace evidence, not a delivered image. Same-document visual changes are allowed;
existing visual-readiness unknown/uncertain labels remain explicit.

This does not make an old AX observation current or weaken later action guards.
Browser mutations, including those after a screenshot in a batch, still refresh
and validate their targets. Ordinary decision/transition observations still use
full native capture; a large page can still exhaust that separate five-second
budget. This increment eliminates unnecessary full extraction for screenshots,
not all remaining large-page extraction cost. No automatic action/screenshot
replay and no deadline increase. Non-scoped/default profiles retain their path.

Exact local acceptance/source: `.local/viewport-guard-v1/acceptance.json`.
Synthetic large-page, fresh-pixel, document/custody race, timeout and subsequent
mutation cases use actual Chromium plus mocked model responses; no new live
retailer or model call by Backend.

## Reuse marking eligibility during cleanup (stable-frames-v4, 2026-09-27)

Overnight trial2 failed on an ordinary decision capture, not a screenshot. It
marked69 frames, spent3.26s in pre-extraction and about1.10s extracting DOM/AX/
focus/geometry, then exhausted5s after only25 child cleanup calls. Those calls
cost about23–27ms each because upstream cleanup repeats frame-owner, sandbox and
BID lookups per frame. This is accumulated browser round-trip cost.

Scoped capture now records exactly the frames it attempted to mark. Cleanup
applies the unchanged upstream unmark JavaScript directly to those eligible
frames, including their shadow DOM, without rediscovering eligibility. Newly
attached/unmarked or scripts-disabled frames are not evaluated; detached frames
are skipped, and quarantined frames stay excluded. Child RPC and aggregate
bounds are unchanged. Default non-scoped capture retains upstream cleanup.

The local old/new comparison includes16,64,96 and160 child frames in separate
browser sessions, two observations when the first succeeds. In the final
160-child pair, the previous cleanup exceeded5s; the candidate retained all161
documents in3.96/3.52s. At96 children, total capture fell from4.01/4.04s to
2.41/2.33s. These are synthetic local measurements under bounded parallel testing,
not a promise that every retailer page now fits5s. Complete old/new snapshots
where both succeeded match AX semantic fields and element geometry; ARIA marker
removal is checked on every retained frame. Timed-out contexts are not retried.

Exact source, evidence and limitations:
`.local/many-frame-capture-v1/acceptance.json`. Prior trial traces/snapshots remain
unchanged. This releases only the third of the already authorized three trials,
using concurrent human handover (`wait_for_human=False`), compact tabs and scoped
capture. A fourth model trial needs new user authorization.

## Bound guard RPCs and close resources independently (stable-frames-v5, 2026-09-27)

The third and final overnight trial answered after 69 responses. Before one
earlier fill, a successful guard capture was followed by a 123.832-second gap.
The live process recovered without intervention. The saved trace does not identify
the exact RPC: cookie/event pumping and CDP identity queries after capture had
neither deadlines nor phase events. A coincident child-frame navigation is not
proof of causation. Separately, the final BrowserGym close exhausted its five
seconds; browser fallback then completed in 0.169 seconds.

Scoped human-browser sync, identity and action-guard operations now each have a
two-second RPC budget. Events identify cookie pumping, opener lookup, CDP session
creation, frame tree, main document and session detachment. Each guard uses one
identity scan for main-document and target-ancestor checks. These checks still
reject navigation/custody races. A guard deadline is a technical error before
action dispatch, not permission to act on stale state or automatically retry.
This bounds the identified unbounded paths; it does not establish which one
caused the historical gap or guarantee that every healthy real-site guard fits
two seconds.

For the exact pinned BrowserGym 0.14.3 native close implementation, scoped mode
now attempts task teardown, chat context/browser close and task context/browser
close separately. A failure in an earlier resource does not skip the remaining
ones. Context close has five seconds to finalize HAR/video; other cleanup phases
have two-second browser-RPC budgets. These are per-resource bounds, not a single
five-second total or a watchdog around arbitrary synchronous Python/HTTP teardown.
Custom close overrides retain the original close path and browser fallbacks.
Large recordings can still exceed the context-close budget; failed finalization
does not certify their files.

`evaluation-before-close.json` retains the exact pre-cleanup evaluation.
`execution_error` and `cleanup_errors` distinguish execution from cleanup in the
summary; an already recorded `agent_finished` stays recorded. The existing final
technical-error/unknown-safety behavior remains conservative after close failure.
Historical trial artifacts and verdicts are not rewritten.

Offline acceptance/source snapshot: `.local/guard-stall-v1/acceptance.json`.
It covers blocked guard RPCs, navigation/custody races, partial shutdown failures,
frame projection regressions, and native HAR/video finalization in local Chromium
with mocked model responses. All three authorized real-web trials are exhausted;
this repair adds no inference and does not authorize another trial.

## Overlap sibling owner reads (stable-frames-v6, 2026-09-27)

A later Windows-Chrome/CDP trial completed a consent click, then exhausted the
next fresh capture's unchanged five-second budget. Preparation took 3.55 seconds
for 20 marked frames; DOM/AX/focus work consumed most of the remainder. The marker
bodies were mostly short, but owner inspection between them was sequential.
The Windows relay is an additional transport boundary, not an isolated regression
against the earlier Linux browser cohorts.

Scoped capture now overlaps sibling `frame_element`, `content_frame` and owner
sandbox/BID reads in groups of at most eight on Playwright's existing owner loop.
Marking and BID assignment remain ordered. The owner identity and scripts-enabled
sandbox checks are retained. Each owner has the existing 0.5-second allowance
after acquiring a concurrency slot; all work shares the five-second aggregate
budget. A timed-out owner is quarantined, with unresolved child coverage excluded
as before. No background thread uses a Page, and no browser action is replayed.
Default non-scoped extraction retains its serial path.

Read-only preparation has additional per-owner and batch timing events. Local
synthetic RPC-delay comparisons and a headless Windows relay fixture establish
the benefit for tested sibling-frame layouts; deeply nested frames, heavy DOM/AX
work or expensive visibility callbacks can still exceed the aggregate limit.

The relay tests also exposed a separate native extraction limitation on Chrome
152: cross-origin child content was absent in both previous and candidate paths.
`frame_documents` now records Playwright's frame count, and projection marks
`unresolved_browser_frames`/partial coverage if the root CDP identity tree lists
fewer frames. Unknown IDs are not invented. This reports the gap honestly; it
does not implement out-of-process child extraction or certify full Windows
multi-origin capture. The same-origin relay fixture preserves all child controls
and geometry. First-capture InlineTextBox expansion can differ; raw evidence is
retained rather than claiming byte-identical AX trees.

Acceptance and source archive: `.local/owner-batch-v1/acceptance.json`.
The historical consent click, observations and verdicts remain untouched.
No model calls or public-site navigation were used for this repair.

## Diagnostic versus bounded capture (2026-09-27)

New `with_human_handover(...)` test profiles default to
`capture_timeout_mode='diagnostic'`. This disables the custom aggregate capture,
viewport, identity/guard and child-read cancellation deadlines. Slow calls stay
pending for inspection; elapsed-time thresholds never authorize stale actions or
skip document/custody checks. Observation errors and browser disconnection can
still end an episode. There is no automatic replay of a committed action.

Select the mode explicitly at launch:

```python
profile = with_human_handover(open_profile(base_profile),
    stable_frames=True, capture_timeout_mode='diagnostic')
# For bounded unattended operation, use capture_timeout_mode='bounded'.
```

The CLI equivalent is `--human-handover --capture-timeout-mode diagnostic` or
`--capture-timeout-mode bounded` with the other required handover flags. The
profile name, description, runtime metadata and capture completion events record
the mode. Tools and policy instructions are identical between modes. This is an
episode configuration, not a tool/prompt change during inference. The direct
low-level `HumanBrowser` constructor retains bounded mode unless explicitly set;
ordinary benchmark profiles and frozen source snapshots are unchanged.

Both modes keep phase-start/completion timings and the one-second capture target.
Diagnostic mode adds `native_capture_budget_overrun` / `browser_guard_budget_overrun`
when the former deadline is exceeded. A timer on the existing Playwright loop
emits this while an RPC remains pending, without another thread using Page.
CPU-bound Python work can delay that event until control returns; this is not an
independent process watchdog. Individual owner-read durations remain in phase
events. Genuine indefinite waits require manual inspection/abort.

Bounded mode retains the five-second capture, two-second guard and short child
budgets. Cleanup remains bounded in **both** modes, including after manual abort.
The best-effort DOM load wait, native visibility callback allowance, browser-action
timeouts, model HTTP timeouts and episode/context limits are separate and are not
disabled by this option. This configuration targets the native observation and
human-tab guard path; it is not a claim that every harness subsystem is unbounded.

Offline evidence/source: `.local/capture-modes-v1/acceptance.json`. Deliberately
slow local captures and guard calls continue in diagnostic mode, emit overruns
before returning, and subsequently perform exactly one input update. The same
calls abort before mutation in bounded mode. Slow owner reads remain included in
diagnostic mode; bounded mode retains explicit quarantine. No paid run is included.
