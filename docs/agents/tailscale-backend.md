# Stable PC backend address

Current decision (2026-09-16): user deferred buying a domain and chose to return
to the existing Cloudflare Quick Tunnel for lower latency. Its authenticated
configuration and anonymous rejection were rechecked; local `vercel.env` now
selects Cloudflare. User must update Vercel Production and redeploy; until that
cutover is confirmed, the production Tailscale connector remains running. See
`.local/control/cloudflare-return-check.json`. Websites and browser worker stay
in Docker; only tunnel connectors were compared outside Docker. The setup below
is an available alternative, not a claim that Tailscale is the chosen connection.
Cutover subsequently confirmed: invitation-authenticated production configuration
returned 200 with Ask enabled after stopping `worker-tailscale-1`. The connector
is now stopped; its identity volume is preserved. The control service subsequently
moved to `history-v1`, so include `history.override.yaml` after the shared-browser
override if reusing the Compose recipe below; recreate the connector against the
current control namespace instead of starting its obsolete stopped container.

The optional `deploy/control/tailscale.override.yaml` runs a pinned Tailscale
connector beside control. It uses userspace networking and shares control's
network namespace so Funnel can reach `http://127.0.0.1:8894`. It does not mount
model keys, control tokens, the Docker socket, or browser/data volumes.

## Start and preserve identity

From the repository root, with the existing deployment's env files and package:

```bash
set -a
. .local/control/active-environment.env
set +a
docker compose -p worker \
  -f deploy/worker/compose.yaml \
  -f deploy/worker/compose.chaos.yaml \
  -f deploy/worker/compose.fixtures.yaml \
  -f deploy/control/compose.yaml \
  -f deploy/control/worker.override.yaml \
  -f deploy/control/manual.override.yaml \
  -f deploy/control/full-sites.override.yaml \
  -f deploy/control/shared-browser.override.yaml \
  -f deploy/control/tailscale.override.yaml up -d --no-deps tailscale
```

This starts only the connector against the existing control container. Initial
registration uses the browser approval URL emitted by:

```bash
docker exec worker-tailscale-1 tailscale --socket=/tmp/tailscaled.sock up \
  --hostname=daylight-backend --accept-dns=false --accept-routes=false
docker exec worker-tailscale-1 tailscale --socket=/tmp/tailscaled.sock funnel --bg 8894
docker exec worker-tailscale-1 tailscale --socket=/tmp/tailscaled.sock funnel status
```

Funnel may request a second browser approval. DNS/certificate provisioning must
finish before changing Vercel. Do not repeatedly register new devices to resolve
propagation delays.

The `worker_tailscale-state` volume retains the device identity, certificates and
background Funnel configuration. Preserve it; do not run `down -v`, log out, or
copy its secret identity into Git. Do not run two connectors from the same state.
The connector restarts with Docker unless explicitly stopped. Docker Desktop
must itself be running after Windows login. Recreating control changes its
network namespace: recreate both worker and Tailscale against the new control
container, after checking active work and preserving every existing data volume.

## Cutover and checks

The registered hostname is `https://daylight-backend.tailc7eb2d.ts.net`.
Before switching, test `POST /internal/manual/config` through normal public DNS:
anonymous must return 401; using the existing server-side control bearer token
must return 200 with `enabled` and `ask_enabled` true. Repeat after restarting
only the connector. These checks create no browser sessions or model calls.

Update only Production `DAYLIGHT_CONTROL_URL` and redeploy Vercel; preserve
`DAYLIGHT_CONTROL_TOKEN`. Verify invitation-authenticated production routes after
redeployment, then stop the old Quick Tunnel. Never fall back to the exhausted
Blob store. Local `.local/control/vercel.env` holds the current selected URL and
private token; do not print the file in logs.

An anonymous visit to the backend is expected to fail authentication. Group
members use the Vercel site, not this backend URL directly.

Verification on 2026-09-16: connector restart retained the hostname and Funnel
mapping; Google public DNS resolved the address, TLS hostname validation passed,
anonymous/invalid-token requests returned 401 and authenticated configuration
returned 200 with Ask enabled. Evidence is
`.local/control/tailscale-public-verification.json`. The workstation resolver
still had a negative cached result at that point, so the test used public DoH
resolution in its own process only, without changing system DNS or disabling TLS
validation. Production cutover and normal workstation resolution remain to be
checked after the user changes Vercel's URL. The old Quick Tunnel is still running.

## Availability and limits

The PC still needs power, internet and Docker Desktop. Windows AC automatic sleep
was changed from 15 minutes to Never; screen-off remains 5 minutes and battery
settings are unchanged. This setting is persistent, not tied to a hosting process.
Restore the previous AC sleep setting with `powercfg /change standby-timeout-ac 15`.
Evidence: `.local/control/windows-power-20260916T095948Z.json`.

The registered node currently reports key expiry on 2027-03-15. Reauthenticate
before expiry or deliberately configure this server's expiry policy in the
Tailscale admin console; startup persistence does not bypass expired credentials.
Funnel is a beta service with nonconfigurable bandwidth limits. It removes the
temporary hostname problem, not PC downtime or capacity limits. No paid plan or
model request is needed for this setup.

References: [Funnel](https://tailscale.com/docs/features/tailscale-funnel),
[background CLI persistence](https://tailscale.com/docs/reference/tailscale-cli/funnel).

## Diagnostic comparison, 2026-09-16

User approved an isolated `daylight-wsl-test` identity to compare a native WSL
userspace daemon with the Docker connector. Both used identical official 1.102.3
binaries. The live connector, Vercel URL, tokens and browser sessions were not
changed. The final interleaved run made nine config requests per connector and
three 1 MiB synthetic transfers per Tailscale connector, plus small payloads:

| Connector | Warm config median (8 samples) | First config | 1 MiB transfers |
| --- | --- | --- | --- |
| Docker Funnel | 97.5 ms | 657.3 ms | 2.12 / 1.32 / 2.60 s |
| Native WSL Funnel | 63.75 ms | 226.2 ms | 1.20 / 1.69 / 0.58 s |
| Existing Cloudflare Quick Tunnel | 24.05 ms | 154.3 ms | Not measured |

All 39 requests in the completed run succeeded; payload bytes were checked.
Earlier probes showed substantially higher Funnel delays, so these are short
observations, not latency guarantees. Different node identities/ingress routing
confound attribution to Docker alone. Native WSL reported destination-independent
NAT versus destination-dependent mapping in Docker; this is not proof of the
actual traffic route. All clients were on WSL, not Vercel.

Local evidence and reproducible scripts: `.local/control/tailscale-bench/`,
especially `native-comparison.json` and `native_compare.py`. Initial provisioning
failures are retained in `native-comparison-provisioning.log`: explicit
`--statedir` was required for the unprivileged native daemon's certificates, and
an early connection timed out during setup. The successful run followed completed
certificate provisioning. Do not describe those setup attempts as successful.

After measurement, native Funnel configuration was reset, the isolated WSL
daemon and both synthetic HTTP servers were stopped, and Docker's temporary
8443 endpoint was removed. Production 443 remains unchanged. The test device is
still registered but offline; its private state is only under `.local/`. No paid
calls, real browser sessions or database mutations were used for this comparison.
