# PC control service

This service replaces frequent Blob reads/writes with SQLite on a persistent
volume. Vercel remains the invitation-protected frontend. It calls the control
service with a separate server-only token; the browser never receives that token.
The BrowserGym worker connects to the service locally, without Vercel or Blob.
Existing model, lease, authorization, receipt, interruption and budget logic is
reused. There are no automatic HTTP retries or fallback writes to Blob.

This first increment uses the existing JSON record structure, including the
100-job development queue cap. It does not yet implement the universal trace
catalog, large-scale database schema or live WebSocket notifications. Trace
artifacts are stored locally too; the original Blob snapshot is retained as a
backup, not used as a second writable store.

## Configuration

Use `.local/control/control.env` (mode 0600):

```dotenv
DAYLIGHT_CONTROL_TOKEN=<new random token, at least 43 characters>
HARNESS_WORKER_TOKEN=<existing dedicated worker token>
DEMO_DAILY_BUDGET_USD=<same value as Vercel>
DEMO_DAILY_CALL_LIMIT=<same value as Vercel>
DAYLIGHT_CONTROL_READ_ONLY=1
```

Do not put model/API keys in this service. It only stores state and grants
existing budget reservations. The worker retains its dedicated model key.
Vercel's client-demo inference key stays in Vercel.

The Docker image reuses the installed worker runtime (Node 22.23.2, including
experimental `node:sqlite`); building it needs no new packages or image pulls.
It runs as UID 10001, with a read-only root and writable `/state` volume.

```bash
docker build --pull=false -f deploy/control/Dockerfile -t intent-browser-control:local .
docker compose -p worker -f deploy/worker/compose.yaml \
  -f deploy/worker/compose.chaos.yaml -f deploy/worker/compose.fixtures.yaml \
  -f deploy/control/compose.yaml -f deploy/control/worker.override.yaml up -d control
```

The only published port is loopback `127.0.0.1:8894`. Worker and control service
share a network namespace so the worker can use `http://127.0.0.1:8894` without
weakening its HTTPS-origin validation. Preserve the existing `worker_worker-data`
volume and exact read-only fixture mounts when switching the worker.

## Test tunnel and Vercel configuration

A Cloudflare quick tunnel needs no domain/account, but has a temporary URL that
can change after restart. It is a development connection, not durable hosting.
Cloudflare documents no SSE support for quick tunnels; this increment uses HTTP.

```bash
.local/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8894
```

Configure these **server-only Production** variables in Vercel:

```dotenv
DAYLIGHT_CONTROL_URL=https://<assigned-name>.trycloudflare.com
DAYLIGHT_CONTROL_TOKEN=<same private control token>
```

If either is set, the application requires valid remote configuration and will
not fall back to Blob. Anonymous tunnel requests are rejected. Invitation owner
checks still happen on Vercel, and worker routes require the separate worker
token. Do not put control tokens in `NEXT_PUBLIC_*` variables or client files.

If the PC sleeps, loses internet, or stops the tunnel, reads/actions become
unavailable with an explicit error. Previously saved local data remains. A
named tunnel can replace the temporary origin later; the database and worker
do not depend on Cloudflare and can move to another host.

## Cutover — preserve the old store

1. Stop the idle worker; wait for any active task/model response to finish. Set
   `DAYLIGHT_STORAGE_MAINTENANCE=1` on the **old Vercel storage configuration** and
   redeploy the handler supporting this flag. It blocks mutations, including
   worker polling, while retaining authenticated reads. Wait at least the old
   function's maximum duration (120 seconds) for previously accepted calls.
2. With `BLOB_READ_WRITE_TOKEN` in local `.env`, export once to a new private
   directory. The script reads only `daylight/`, never writes/deletes Blob, checks
   source inventory before/after, and refuses pending model/worker work. Default
   read budget is 1,500 objects; inspect the count before increasing it.

   ```bash
   cd deploy/daylight
   node --env-file=../../.env migrate-storage.mjs export \
     ../../.local/control/snapshot-UNIQUE --confirm-writers-paused
   node migrate-storage.mjs import ../../.local/control/snapshot-UNIQUE \
     ../../.local/control/import-UNIQUE.sqlite
   ```

3. The importer validates every hash before creating an exclusive new database,
   preserves raw JSON bytes, and checks every imported byte hash. Never import
   over an existing/live database. Copy the closed database into the stopped
   control service volume as `state.sqlite`, owned by UID/GID 10001, mode 0600.
   Start control read-only and compare authenticated lists, grades and archives.
4. Point Vercel at the control URL/token and redeploy. With maintenance still on,
   verify owner isolation and historical traces. Remove maintenance, set local
   `DAYLIGHT_CONTROL_READ_ONLY=0`, recreate control, then recreate the worker
   with the combined compose files above. Quick-tunnel URLs must be checked
   after tunnel restarts. No model call is needed to test storage cutover.
5. Confirm worker requests go to loopback and no production path reads Blob.
   Retain the original snapshot and Blob store. Revoke the temporary migration
   token when verification is complete.

Once new writes occur, reverting Vercel to the old Blob store would lose the new
budget/trace state. Rollback requires another maintenance window and verified
reverse migration; never enable two writable backends.

## Backups and validation

Back up SQLite using its backup API or stop the service and copy the closed DB;
copying only an open WAL database file can omit committed data. Keep snapshots
outside the container volume as well. Moving a closed volume/database plus the
image and exact environment packages is sufficient for local/offline operation;
hosted inference and remote website access still require network connections.

Tests: `cd deploy/daylight && npm test`; browser polling check:
`.venv/bin/python scripts/check_control_polling.py`. These use fake inference,
temporary stores and local HTTP only. A test pass is not production cutover.

References: [Cloudflare quick tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/),
[Vercel Blob usage](https://vercel.com/docs/vercel-blob/usage-and-pricing).

## Optional manual browser sessions

The workspace can expose the existing packaged task sites through human-operated
BrowserGym sessions. Add `manual.override.yaml` with an absolute
`ENVIRONMENT_PACKAGE` path to the immutable package. This adds a separate
persistent manual-trace volume and Chromium resources; it needs no model key.
See [manual environment hosting](../../docs/agents/manual-environment-hosting.md)
for supported routes, lifecycle, deployment and validation details.
