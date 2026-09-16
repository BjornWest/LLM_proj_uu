# Independent startup and paginated trace summaries

The workspace previously awaited registry, jobs and every browser-side trace page
before rendering its site. Each trace page also caused one network request for
the key list, one for every full trace and another for each historical
conversation link. With 22 stored traces that was 28 sequential requests.

## Changes

- Campus renders once its local fixture arrives. Model availability, worker
  registry and manual-session readiness load independently; Ask remains disabled
  until its actual requirements are ready. No fabricated readiness.
- Explore does not fetch browser trace history or idle job history. Opening
  Tasks & replays or the global library requests a page of 25 summaries. Explicit
  Load more follows the opaque cursor. Errors preserve loaded rows and require
  explicit retry. Filters and conversation groups are labeled as covering loaded
  history; page order remains storage-key order, with displayed rows sorted by
  their recorded timestamps. This is not a newest-first indexed catalog yet.
- Deep links fetch the selected record directly instead of scanning the library.
- `Agent.list` delegates remote stores to `/internal/store/trace-list`. Control
  executes the existing projection and owner/link validation beside SQLite.
  Only summaries cross the tunnel. Full messages/media remain selected-run reads.
- Manual configuration and session-list requests run in parallel.

No trace schema, grader, policy input, model settings, cost reservation or source
artifact is rewritten. Full-trace parsing still happens locally for the selected
page; an indexed summary catalog is a later scaling improvement. Existing bounded
worker/manual lists are not a universal imported-run catalog.

## Deployment order

Deploy `intent-browser-control:history-v1` via `deploy/control/history.override.yaml`
after `shared-browser.override.yaml`, before deploying the Vercel code using the
new endpoint. Check for active jobs/manual sessions first; preserve control,
worker and manual data volumes and recreate worker with control's new namespace.
No fallback to Blob or to per-record remote reads is introduced.

The production connector is again Cloudflare Quick Tunnel, not Tailscale. Local
`vercel.env` retains its current temporary URL. Tailscale was stopped only after
invitation-authenticated Vercel configuration worked without it. Buying a domain
is deferred. Do not restart Quick Tunnel unnecessarily or assume its URL survives
a process restart.

## Evidence

- Node suite: 99 passing, including one-request pagination, exact local/remote
  projection equivalence, owner isolation, null outcomes and invalid inputs.
- `scripts/check_history_loading.py`: blocked readiness/history, interactive
  navigation, one-page loading, explicit retry and deep links; saved report
  `.local/vercel-demo/history-loading-4e4bf689/report.json`.
- Existing workspace smoke: 32 checks,
  `.local/vercel-demo/workspace-9a73ade7/report.json`.
- Container endpoint acceptance: `.local/control/history-container-validation.json`.
- Before/after deployment snapshots: `.local/control/history-immediate-pre-switch.json`
  and `history-post-switch.json`; all 119 keys preserved, only the worker control
  heartbeat changed.
- Live read-only comparison: `.local/control/history-network-comparison.json`:
  same 22 summaries, 28 calls / 1,173,005 bytes / 872 ms versus one call /
  20,155 bytes / 30 ms. These are short measurements, not latency guarantees.

All validation used no paid inference. The screenshot retention proposal is
separate and authorizes no deletion: [proposal](trace-retention-proposal.md).
