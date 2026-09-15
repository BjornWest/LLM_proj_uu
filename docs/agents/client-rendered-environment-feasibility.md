# Client-rendered environment inspection

Status: investigation completed September 15, 2026. No deployment or production
runtime changes. This assesses **human exploration**, separate from agent runs.

## Recommendation

Add an Explore mode that renders the existing fixture assets in the teammate's
browser. Keep Watch/Ask as separate worker executions with fresh, explicit state.
Do not imply that a worker inherits the exploration browser's cart, settings,
navigation or cookies. Local rendering could support another agent transport in
the future, but implementing that transport is not needed for this request.

Start with Tricky shopping, then membership and privacy. These can be inspected
without a Chromium process on the PC. Chaos can also render in the user's
browser, but keep its real stateful server on the PC/container. That still avoids
screenshot capture and transmission for every interaction.

## Current sites

| Site | Feasibility and changes | Remaining boundary |
|---|---|---|
| Campus | Already client-rendered and interactive. | Its demo transport is separate from BrowserGym. |
| Tricky shopping / P07 | Low environment effort. Existing built assets already work with browser-local cart and checkout. Add controlled hosting, reset, variant selection and manual event capture. | Inspection checkout is a local simulation; the default no-op journal hook supplies no independent grade. |
| Authorized warranty / DEV-W01 | Same shop assets and warranty condition; no second renderer needed. | Keep its distinct task contract for worker runs. Exploration itself has no authorized-goal grade. |
| Tricky music / P11 | Small state-adapter change. Initialize subscription storage and implement the existing activation hook locally before the main bundle runs. | Membership component only; no full Spotify shell or audio. Preserve all activations, not just the last overlay. |
| Tricky health / P10 | Moderate state-adapter work. Initialize the exact privacy/appointment state and persist Save/cancel effects for reloads. | Only home/privacy/appointments routes exist. Scheduling lacks a doctor catalog; unsupported links do not become functional through hosting. |
| Browser Agent Chaos | Moderate integration work. Serve its existing frontend and proxy only the required session/mount/interaction routes to the existing containerized server. | Per-owner session isolation, route allowlisting, lifecycle cleanup and font delivery must be implemented; do not publish the entire CLI API. |

These are relative effort estimates, not delivery commitments. The original
components do not need a visual rewrite. Most production work is hosting,
session isolation, reset, authentication and distinguishing exploration records
from verified worker traces.

## Browser evidence

All probes used ordinary headless Chromium and existing packaged fixture assets.
Python started local asset servers; **no BrowserGym environment was created**.
There were no model calls, real purchases, deployments or existing-session
changes. Headless Chromium here is test automation for a normally rendered web
page, not a screenshot transport to the user.

Evidence directory: `.local/client-rendering-study/`.

* `probe.py` / `report.json`: clean and injected P07/P10/P11 loads; ten fresh
  contexts, including four with prototype browser-only hooks. Plain P11 and P10
  fail because `window.__intentEmit` is absent. With the prototype hooks, both
  P11 conditions support a purchase and preserve it across reload; both P10
  conditions support cancellation while retaining the other appointment across
  reload. All successful hook cases have zero page errors and zero external
  requests. Privacy Save/discard fidelity was inspected in source, not exercised
  by this probe.
* `shop_probe.py` / `shop-report.json`: two fresh plain-page cases, clean and
  warranty. Search for Dell, add product 24, navigate to cart, checkout and reload
  all work without any initialization hook. Exact expected cart IDs and purchase
  persistence are checked. The initial probe attempted to click product 24 from
  the homepage's top picks before searching; those two selector timeouts are
  retained, not counted as rendering failures or passing interaction tests.
* `chaos_probe.py` / `chaos-report.json`: a fresh isolated packaged Chaos server
  and ordinary browser load the confirmshaming page. Clicking the visible decline
  control produces the server's success screen with zero page errors. HTTP
  requests and raw events are retained. External font requests were blocked, so
  this does not claim pixel parity with the font-complete harness. One challenge
  is tested, not all seven or a private deployed proxy. The raw success screen is
  not an independent verifier result.

The hooks in the prototype are deliberately small and are **not a production
state contract, grader, or complete replacement for the native adapter**. They
were installed before scripts executed using Playwright's initialization helper.
A deployed inspection page would load an application-owned bootstrap script in
the HTML before the unchanged site bundle, without Playwright. No changed bundle
or production bootstrap has been built in this investigation.

Packaged frontend sizes (all files, uncompressed; not initial transfer size):

| Fixture | Files | Bytes |
|---|---:|---:|
| Shopping | 64 | 18,154,799 |
| Membership | 2 | 577,277 |
| Privacy | 3 | 846,122 |

The inspected package is `.local/environment-packages/portable-v2`, manifest
SHA256 `fd9bbd6656133354cea05b8c76cee9edf21d85a81137e5c5ef678755f1f0ee1b`.
Source hashes and browser errors are retained in the reports. The package is
private harness input; publishing it as a web root would expose privileged files.

## Hosting options

Vercel can deliver ordinary HTML/JS/CSS without Blob. Its CDN supports static
assets on all plans: <https://vercel.com/docs/caching/cdn-cache>. That does not
mean unlimited bandwidth or that protected site content should bypass invitations.
Keep the current private access requirement; route/bootstrap changes must preserve
it. Browser caching can avoid repeated transfers without persisting anything in
Blob. Do not introduce public shared caching for personalized data or responses
that establish access.

Alternatively, the PC/container can serve the exact same assets through the
existing private gateway/tunnel. Once downloaded, local scrolling, typing and
React state changes do not wait for remote screenshots. The PC must remain on
for loads and any backend-dependent actions. Vercel delivery makes static
inspection less dependent on PC availability, but is not what makes rendering
local. The existing Vercel deployment's catch-all function routing means asset
delivery needs deliberate implementation; copying files alone is not enough.

For Chaos, retain the packaged server rather than porting its session/event stores
into serverless functions during this increment. Its CLI also exposes admin,
event, declaration and score endpoints; the existing server is not safe to expose
wholesale merely because the UI is local. Use session-scoped routes through the
existing private control service. The production proxy is not tested yet.

Use a separate site origin or equivalently constrained iframe/document boundary.
Do not grant arbitrary dataset scripts access to the dashboard's authenticated
API. Existing bundles assume absolute paths (`/assets`, `/shop`, `/health`,
`/spotify`) and use browser storage, so mounting them beneath arbitrary URL
prefixes requires routing or a versioned build change. State must be scoped per
exploration/condition; two copies sharing unqualified localStorage keys can leak
state across tabs or clean/injected variants. Test reset and reload explicitly.

## Acceptance before deployment

1. Use exact versioned visual assets; record any bootstrap/build differences.
2. Exercise search/cart/checkout, all membership plans, privacy Save versus
   Close, cancellation, reload and reset using native browser interactions.
3. Test owner access, iframe isolation, condition/tab state isolation and route
   boundaries. Preserve unsupported original controls honestly; do not add fake
   functionality or change deceptive controls to make them easier.
4. Record manual interactions as human exploration with unknown independent
   grade. Keep telemetry off the rendering critical path where possible and
   expose failed recording explicitly. Do not manufacture BrowserGym observations
   or silently discard manual history.
5. Launching Watch/Ask starts a separate identified worker browser. Never claim
   that local inspection state was transferred unless a later explicit mechanism
   implements and validates it.

The standalone asset/bootstrap package must also run from a loopback server on a
rollout instance without Vercel, Cloudflare or internet dependencies.

## Other datasets

MiniWoB is mostly browser-side and is a plausible later inspection addition, but
episode initialization/seed/reward UI needs a launcher. Existing 125-task asset
load evidence does not establish a full manual lifecycle for every task. The IKEA
fixture remains only a SusBench injection/callback diagnostic. Full SusBench and
WorkArena depend on external live services; hosting our files does not recreate
them. WebArena needs its application/database stacks, DoomArena is an attack
layer, and WebLINX is recorded data. Preserve unknown upstream license metadata;
technical hostability is not blanket redistribution or training clearance.
