# Control storage cutover — 2026-09-15

Production `https://browseragent.vercel.app` now uses the PC SQLite service via
an authenticated temporary tunnel. Code release: `7c3bfa2`. The Blob-backed
worker was stopped before migration; the new worker polls loopback instead of
Vercel. Client idle polling is 60 seconds, hidden tabs do not poll, and full demo
trace listings refresh on explicit history entry/action completion rather than
every minute. Active-run progress polling remains.

## Evidence and preserved data

- Canonical export: `.local/control/snapshot-20260915-v2`, manifest SHA256
  `cf0cb8118f5ad2ee781f4066900b05910c304c0d095ed37e3099670291e7628c`.
- 58 original application objects, 6,161,733 raw bytes: 27 demo traces, three
  harness jobs inside their control record, 28 harness artifacts, one daily
  budget and one earlier diagnostic. Every imported raw JSON hash matched.
- All 58 values and the complete key set were independently read through the
  authenticated tunnel and compared to the snapshot. Full job grades, nulls,
  steps and goals were preserved. No verifier was rerun or label changed.
- Production checked all 22 demo traces belonging to the operator account,
  all three harness jobs, and byte-identical downloads of their three ZIPs.
- An isolated `/storage-check` proved conditional writes reached SQLite; it
  created one new synthetic diagnostic, without changing trace/budget records.
- After the user reported Blob quota exhaustion, production config, job list
  and trace list still returned HTTP 200. Current operation does not require
  Blob. The old source store was never written to or deleted during migration.
- No model calls or new agent jobs were used for migration validation.

Reports: `config/control_storage_validation.json` and the referenced files under
`.local/control/`. Local tests: 58 Node tests, 30 workspace browser checks,
six controlled-clock polling checks, and five container checks with network
disabled. These are storage/UX tests, not new model performance evidence.

The first export started before the conservative 120-second deployment drain
check completed and was not selected for cutover. A new v2 export was made after
the drain; all 58 byte hashes were identical. Both copies remain with an explicit
v1 rejection note. Total migration reads: 116 objects and four inventory lists;
zero Blob mutations. Do not silently present the preliminary copy as the final
drained snapshot.

## Running services and limitations

- `worker-control-1`: non-root SQLite service; `worker_control-data` volume.
- `worker-worker-1`: unchanged image
  `sha256:6884c2834fc5e294507ef8bd294768a9b982f3badecc75f2824a3e1cff33caff`,
  original `worker_worker-data` volume and fixture mounts retained. Fifteen
  tasks advertised, using `HARNESS_URL=http://127.0.0.1:8894` in the control
  service's network namespace. No production WorkArena catalog addition.
- Temporary cloudflared process: `.local/control/tunnel.pid` and `tunnel.log`.
  Connection variables: `.local/control/vercel.env`; server configuration:
  `.local/control/control.env`. These contain secrets and are ignored by Git.
- The user set Production control URL/token and disabled maintenance. The
  proposed `DAYLIGHT_MIGRATION_OWNER` fallback was never implemented or needed;
  any remaining variable with that name has no effect.

The PC and tunnel must remain running. Docker restarts the service/worker, but
the current quick-tunnel process is not a persistent named tunnel and its URL
can change after restart. Update the Production URL and redeploy if it changes.
Do not silently fall back to Blob or roll back to a deployment with a separate
writable budget. The existing JSON layout and 100-job cap remain; a universal
local/external trace catalog is still separate work.

Use [the control service runbook](../../deploy/control/README.md) for migration,
backup and restart details. Keep the verified snapshot and imported closed DB;
back up later SQLite changes using a consistent backup or a stopped service,
not a copy of an open WAL database file alone.
