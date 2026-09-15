# Remote manual session recovery

The September 15 user report described a frozen Medical records navigation,
an apparently ineffective Check sessions button, and a stuck music screenshot.
Read-only production inspection found:

- Two health sessions had ended with `ValueError: Browser left supported health
  routes`; their ZIP traces were available. The last saved image remained shown.
- The saved music session was already finished. A newer ready health session held
  the one-session-per-owner slot, disabling a new music session.
- The old CSS assigned `cursor:wait` to every disabled remote surface, including
  finished/error screenshots. This made a closed browser look busy.

This increment changes only frontend status/recovery and tests. It does not add
Medical records, change the native fixture/verifier, alter historical outcomes,
or close any real user's session during diagnosis.

## UI semantics

`Refresh session status` (formerly Check sessions) reloads config and saved session
metadata. A visible timestamp describes its purpose. It never captures a new
image or replays an action. `Refresh screenshot` is the separate explicit capture
operation. An unavailable image remains explicitly unavailable after a metadata
refresh; status alone cannot make it clickable.

Finished/error/interrupted frames are labelled saved screenshots, with a default
cursor. A busy cursor is limited to loading/command states. Unknown outcomes still
block further commands pending a successful status refresh. The UI never retries
a mutating action. Idle expiration retains the existing five-minute backend rule.

If another site owns the current session, its name and status are shown with
`Go to active … session` and `Close … session`. The latter sends exactly one close
for that current session ID, and is unavailable while its state is busy/uncertain.
It does not close the historical session pictured on the selected site. Opening
a replacement browser remains a separate explicit action.

The health scope note lists Home, privacy settings and Appointments. Profiles,
Medical records and scheduling are not implemented in this fixture. Unsupported
navigation still ends the native session; friendly recovery text explains why,
and an expandable field preserves the exact original error. A new session starts
fresh rather than silently restoring or replaying the previous page's actions.

## Evidence

- `.local/manual-recovery/sessions-before.json`: read-only owner-scoped production
  metadata retained privately; no production action/close/model call was made.
- `scripts/smoke_manual_workspace.py`: 27 mocked-API frontend checks, including
  the exact closed-music/active-health shape, one close to the correct target,
  metadata-only refresh, raw error preservation and non-busy closed screenshots.
- `scripts/smoke_manual_workspace_live.py`: 15 actual-handler/BrowserGym checks
  across isolated P11 and P07 sessions; no inference. Positive native actions,
  owner isolation, artifacts, null grading and close semantics still pass.
- Current Node suite: 76 checks. Publication uses an isolated committed snapshot;
  no control/worker restart is needed.

Extending direct client rendering to music/privacy is separate from this
remote-session diagnosis. Chaos additionally needs its existing server and a
session-scoped proxy; full unsupported upstream routes are not created merely by
hosting their current fixture assets.
