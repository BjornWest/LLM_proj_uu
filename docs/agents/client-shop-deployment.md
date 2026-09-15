# Client-rendered shopping deployment

The standalone `/shop` and `/shop?dp=w` routes deliver the reviewed shopping
fixture directly to the human's browser. Workspace links open a new tab with
`noopener noreferrer`. Existing remote manual controls and worker tasks remain
separate. No PC browser, model call, Blob access or server transaction occurs in
the inspection page. This first release covers shopping and its warranty variant,
not every site in the registry.

## Assets and state

`environments/inspection_shop/dist` contains the exact 64 public fixture files from
the reviewed portable-v2 shopping build. `manifest.json` pins every byte and keeps
upstream identity/license uncertainty. It includes no privileged task manifest,
verifier, credentials or previous trace. The production build checks these hashes
and copies only these files into private function assets. The original React/DOM
components and bundle are unchanged. HTML adds a bootstrap and a small toolbar
above the original root; the toolbar does not overlay or clip the site.

The bootstrap redirects the fixture's localStorage API to tab-scoped
sessionStorage, separately for clean/warranty. State survives reload and resets
explicitly. A deliberately duplicated tab may inherit a copy of browser session
storage; ordinary independently opened tabs are separate. `__intentEmit` keeps
local state/checkout records; native click/change events are also recorded. The
download includes actor/runtime, unknown independent evaluation, no model,
condition and event order. It is not a BrowserGym trace and is not automatically
uploaded to the trace library. Recording is capped at 1,000 events and visibly
marked limited thereafter. Reset starts a new local record; download first to
retain the previous one. Closing the tab can discard this inspection state.

## Access and cost

Every initial HTML/asset request authenticates the invitation locally using the
existing signed cookie; it does not consult SQLite or Blob. Known hashed dataset
assets use `private, max-age=86400, immutable` plus ETags. Shared Vercel CDN caching
is disabled for these authenticated responses. HTML stays no-store; the small
bootstrap/style revalidate so release changes are picked up. Cached assets remain
on a previously authorized browser; logging out cannot retract already downloaded
bytes, but uncached/conditional requests still require authentication.

The complete uncompressed bundle is 18,154,799 bytes (mostly product images), not
the initial page payload. Largest file is 2,638,263 bytes. Serving 100 complete
cold downloads would transfer about 1.82 GB before compression; ordinary browsing
usually fetches fewer images and repeat visits use the browser cache. Delivery
still consumes Vercel requests, function work and transfer on cache misses; no
promise of unlimited free usage. There is no per-click server logging or polling
from this standalone page. No Blob dependency and no new hosting account/domain
are required. User requested warnings before future approaches likely to be
expensive; preserve this constraint for higher-volume uploads/replays/live video.

The root deployment remains private; `public/` still contains only robots.txt.
The entire bundle is included in the deployment, so inspection asset delivery
does not depend on the PC/tunnel being online. Workspace worker status/history
can still depend on the PC. Direct `/shop` access does not.

## Isolation

This audited standalone fixture cannot be embedded (`frame-ancestors 'none'`,
X-Frame-Options DENY). Its response CSP blocks fetch/XHR, frames, forms, objects
and popups while allowing required scripts/styles/images, browser storage and
local downloads. The workspace opens it without an opener. This is a bounded
deployment of a pinned fixture, not a general-purpose security boundary for
arbitrary untrusted dataset JavaScript. Future generic or prompt-injection site
hosting still needs an isolated origin and a reviewed bridge. Do not weaken this
page to embed it beside the dashboard without revisiting that design.

## Verification

`npm run build && npm test` in deploy/daylight checks the full API suite. New
inspection cases validate all 63 non-HTML asset hashes, invitation-before-cache
behavior, private caching, forbidden paths and zero store operations.

`scripts/smoke_client_inspection.py` runs an actual handler and ordinary Chromium
without inference. It checks clean checkout, unchanged warranty insertion,
reload/reset, independent tabs/conditions, download semantics, blocked API fetch,
workspace launch/opener isolation and no agent/manual-browser POSTs. The initial
passing report is `.local/client-rendering-study/browser-16c48ff4/report.json`
(17 checks); use the release snapshot's final report for publication evidence.

No worker/container restart is needed. Publish an exact committed snapshot so
concurrent tool/replay UX work is not accidentally bundled.
