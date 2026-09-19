# Complete-site manual browsing

This increment adds generic `browse.*` sessions for the four complete Tricky sites
(shop, health, news, music) and the cached WebArena Verified shopping/forum apps.
It is separate from the 203 review objectives and existing graded worker tasks.
No objective, task-specific setup, model request or grade is assigned on open.
Both `evaluation` and `reference_evaluation` are null for these sessions. Existing
legacy sessions retain their explicitly advertised Ask capability; generic
browsing is manual-only in this increment.

Vercel hosts the invitation-protected controls and catalog. A PC BrowserGym process
provides the actual page image and native click, text, key, scroll, Back, Forward
and Reload actions. Screenshot refresh is a separate operation. Tricky also
retains its faster client-rendered inspection links. Both use the same pinned
complete application assets; neither generic browser removes routes to fit a
particular grader. Arbitrary external URL entry and script execution are absent.

## Isolation and cleanup

Tricky gets a fresh browser context and local complete-site server per session.
WebArena includes databases, so a fresh context is insufficient. One dedicated,
unmounted cached container per WebArena site is exclusively leased, supporting
one visitor per site initially. There are still two manual browser slots total,
and one active manual session per invitation owner. Busy/resetting sites reject
new opens; they never share the fixture account with another visitor.

`scripts/browse_pool_server.py` runs on the host, using the reviewed clone reset
helper in `data/curation/manual_sites/clones.py`. It is a private lease proxy:

1. A ready slot issues a random browser lease to the authenticated PC controller.
2. Browser requests must carry that lease. The proxy selects exactly one clone,
   strips controller/lease headers and injects only its upstream fixture account.
3. Closing, expiry, failed setup or uncertain browser execution revokes access.
   Already forwarded requests drain before reset; no POST is retried.
4. The exact owned container is removed and recreated from its pinned cached image.
   Reset failure quarantines the slot. It becomes available only after successful
   initialization. Restart also requires resets before any slot is available.

The proxy has a separate administrative token, never passed to the browser.
Only the short-lived browser lease enters its context, through a controller-owned
launch file outside the exported trace directory. It never appears in public
session JSON or the original ZIP. The control/browser containers have no Docker
socket. Browser requests are restricted to the leased origin and cached assets;
service workers are blocked. The proxy is local infrastructure, not an external
service required during GPU rollouts.

Manual idle/total limits remain five/fifteen minutes; the broker additionally
expires orphan leases after twenty minutes. A revoked token cannot address a
later visitor's database, including while a previous browser is shutting down.
Failed release stays exclusively leased until expiry. The next controller also
revokes saved leases when marking old sessions interrupted.

## Portable deployment

The immutable existing package supplies BrowserGym/runtime and complete Tricky
assets. The additional generic browsing driver is a functional wrapper, not a
new task adapter. WebArena clones use cached upstream images and complete local
databases; no network download occurs when resetting them. App/image/runtime and
reset-report fingerprints accompany browsing traces. Relocation needs those
images, package, host broker/reset helper, an explicit private browser origin and
PC control configuration. Vercel is optional for local rollouts.

Private local configuration lives under `.local/browse-pool/`: `config.json`,
`token`, `control.env`, and per-reset evidence. Do not commit their credentials.
The canonical browser origin must match the clone initialization and be reachable
from the browser container. Changing hosts requires coordinated recreation, not
changing URLs under a live lease. See [clone setup](manual-site-clones.md).

Before replacing production control, inspect active manual sessions and worker
jobs, preserve the SQLite/manual/worker volumes, and recreate the existing worker
because it shares the control network namespace. Do not replace benchmark
services on 7770/9999/18999 or any research/evidence clones. Do not run Compose
with `down -v`. The WebArena pool is a separately scoped pair of containers.

## Acceptance entrypoints

- `python3 -m unittest tests.test_browse_pool`: exclusive leases, revocation before
  drain, stale-token rejection, expiry, failed reset and actual HTTP forwarding.
- `npm --prefix deploy/daylight test`: owner checks, no Ask in generic sessions,
  startup-failure cleanup and existing control regressions.
- `scripts/verify_generic_browsing.mjs OUTPUT`: actual four Tricky browsers.
- `scripts/verify_browse_isolation.mjs OUTPUT`: simultaneous distinct carts,
  same-session persistence and fresh-session reset.
- `scripts/smoke_generic_browsing_live.py --output NEWDIR [--webarena]`: actual
  workspace/API/BrowserGym native clicks/navigation, null grades and original ZIPs.
  WebArena mode requires the separately configured pool and exclusive ownership
  of those test slots. It must never target shared benchmark services.

Mock UI checks, local browser acceptance, container acceptance and production
availability are separate evidence. None is a model evaluation or a certificate
that all 203 catalog tasks are runnable or correctly graded.

HTTP redirect containment is enforced at the proxy too: Playwright routing alone
is insufficient for redirects. Malformed slash/scheme forms are rejected; accepted
Location values are normalized to an absolute validated canonical URL before
forwarding. The real-Chromium redirect test intentionally omits a Playwright route
guard and confirms that foreign targets receive no requests. Source redirects,
not application page content, are constrained by this isolation wrapper.

The production Compose overlay is `deploy/control/browse.override.yaml`; append
it after the existing library overlay. The host broker must also be running:

```sh
python3 scripts/browse_pool_server.py --config .local/browse-pool/config.json \
  --state .local/browse-pool/state-v2 --token-file .local/browse-pool/token \
  --bind 0.0.0.0
```

The broker's state-directory lock rejects a duplicate instance. Its startup
resets both owned clones; do not launch a second broker with another state directory
against the same clones. This WSL setup does not install boot autostart for the
broker; after a host restart, restore it before expecting WebArena availability.
Missing broker access makes those sites unavailable, rather than using shared apps.

Production native checks use `scripts/smoke_generic_browsing_live.py --origin
https://browseragent.vercel.app --container worker-control-1 --output NEWDIR`,
and a separate invocation with `--webarena`. They create real manual sessions
using the local test invitation, and close them; there are no model requests.
Run only while those owner/site slots are free. Local/container checks additionally
exercise another invitation's denial of access to state, images and ZIPs.
