# BrowserGym batch projection

Shared implementation: `common_agent_util` commit `0887af2`. The identical adapter
is pinned in `deploy/daylight/vendor/agent_trace/` with updated projection provenance.
Local viewers use the sibling package; the deployed control service needs its next
image/release to consume the new pin. Existing imported immutable bundles are not
rewritten. No model calls or production restart were performed for this change.

One model request/response is projected once. A batch adds ordered individual tool
and result entries, retaining model-decision index, batch ordinal, native call ID
and execution index. Status is completed, failed, skipped or unknown; failures use
the existing renderer's `error` status and retain `execution_status: failed`.
Skipped proposals are never counted as executed calls. Failed/unknown calls may
have effects; projection does not infer transaction success.

The execution summary distinguishes requests, tool records by status, evidenced
executions and returned BrowserGym steps. Browser-step counts separately identify
noops and terminal messages. Counts do not multiply model usage or costs across
members. For the live room-form example: four requests, eleven tools, eight
returned BrowserGym steps (seven interactions plus the terminal message).

Each action can link its recorded guard and post-action screenshot. Guard captures
are labeled review-only; requested screenshot captures link separately. Merely
having a screenshot is not proof that it was sent to the model. The consolidated
AX update is shown once at the previous batch boundary only when its exact text
exists in the next retained request's corresponding tool results. Otherwise the
viewer retains the ordinary selected/final observation without inventing delivery.
Historical events are separate from that current snapshot. Tool results show the
selected feedback once, rather than duplicating identical raw and presented JSON.

The artifact allowlist adds only numbered `batch_guard-observation-*` artifacts
and `image-*.png`; arbitrary files, HTML and path escapes remain disallowed. No
page actions are replayed by the viewer.

Triage preserves one timeline/usage row per decision and adds `batch_actions`.
Integrity checks consider unskipped members and exclude read-only context tools
from state-changing evidence. Batch comparison tokens encode ordered members and
skipped state, while unresolved targets remain specific to their source episode.
Selected AX is the only target-resolution source; guard snapshots are not promoted
to model-delivered evidence. No new claims about historical tool-result targeting
are made.

Validation:

- Common utility full suite: 29 tests, including legacy Civ5/session behavior and
  asset-safety checks.
- Triage and pinned worker projection: 44 tests.
- `scripts/audit_batch_projection.py`: ten saved episodes (nine scripted boundary
  cases plus the live Qwen room form), seven read-only browser presentation checks.
  Evidence: `.local/review/batch-viewer-v2/report.json`.
- The real room trace's ZIP projected through the pinned worker adapter exactly
  equals the local shared projection. Original evaluation/nulls preserved.
- Fresh triage at `.local/review/room-batch-triage-v2` has no false
  `completion_without_state_action` flag. Historical v1 remains unchanged.

The current local Qwen trace is available at
http://localhost:8911/#c2a6784bae5f396c1708 while that viewer process is running.
