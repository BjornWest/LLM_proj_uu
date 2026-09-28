# Actionable BIDs in bounded dynamic previews

Dynamic preview now defaults to `preview_bids=True` in
`ObservationPipelineConfig`. Set it false to retain the v1 no-BID preview for
comparison. This is local implementation, not a production deployment or model
performance result. Tool schemas remain unchanged.

## Behavior and lifetime

The shallow AX query and existing node cap are unchanged. Only main-document
nodes already included in that bounded preview are considered. The helper
resolves their backend DOM identities with at most eight concurrent read-only
CDP requests on the browser owner loop, then assigns/reuses native IDs in one
ordered browser evaluation. It does not walk the whole DOM or inject an AX ARIA
carrier. The native BrowserGym numeric counter and version-pinned frame-ID
allocator are shared with the later full capture.

Connected standard HTML elements intersecting the viewport with non-hidden
computed visibility are eligible. Text/document nodes and iframe owners are
excluded; child documents remain outside the preview. Shadow-DOM elements can
be resolved directly. This is a viewport eligibility check, not proof that an
element is unobscured or a click will succeed. Normal action validation remains.

An existing DOM element retains its BID across fills, clicks, reordering and
other same-document updates. New elements get new IDs. A new document resets the
allocator; numeric values can repeat across documents, so document/frame/custody
identity remains essential. A site's preexisting BID on first preparation is not
adopted. An incompatible allocator is not repaired or trusted.

The preview is a proposal, not action authorization. Background full capture
must agree on each preview node's semantic/backend identity AND its assigned
BID. A renamed BID, replaced node or ambiguous mapping rejects the pending
proposal before dispatch. Native duplicate repair can change an ID; that causes
re-observation instead of retargeting the action. Existing freshness/custody
checks and full stable-frame capture still run.

Allocation is normally once per surviving element; validation is not once per
page. Every preview resolves/checks its bounded candidates again. Existing full
post-action captures also still walk the page: this increment does not claim to
remove those scans or to make the entire capture cost one-time.

## Acceptance

- `.local/preview-bids-browser-v1/report.json`: 17 real local-browser checks,
  including fresh allocation, reuse, fill, new/replaced controls, hidden/offscreen
  exclusions, shadow DOM, untouched child frames, full native capture compatibility,
  frame namespacing, duplicate repair and navigation.
- `.local/preview-bids-overlap-v1/report.json`: 18 actual runner + HTTPX mock
  browser scenarios, two independent workers. A first-response click uses only a
  BID found in the actual user observation and commits exactly once without
  ax_search. BID tampering and same-label node replacement while decoding cause
  zero dispatched actions. Existing document/custody/content invalidation,
  transport/backend failures and overlap behavior remain covered. No paid calls.
- `.local/preview-bids-final-tests.log`: 59 tests / 10 subtests pass, including
  preview/full BID agreement, ambiguity rejection, unchanged full-tree visit
  ledger and bounded policy presentation.

## Latency and remaining coverage limitation

Sequential alternating previews, fresh Linux headless browser, no inference or
recording in timing. Warm medians exclude the first sample per mode. Depth 2,
64-node cap, six samples per mode:

| Page | No-BID preview | BID preview | IDs provided |
|---|---:|---:|---:|
| Live Prisjakt | 20.6 ms | 25.4 ms | 2 container IDs |
| 3,000-product fixture | 108.4 ms | 130.1 ms | 13, including Search and Commit |

Evidence: `.local/preview-bids-latency-v1/report.json`. First calls are retained
separately; the older mode ran first and paid cold-cache cost, so first-call values
must not be interpreted as a BID speedup. The assignment subphase is about 5 ms
warm on Prisjakt / 21 ms on the fixture.

Prisjakt's depth-2 preview exposes wrappers, not its actual search box. A separate
depth-5 probe (`.local/preview-bids-latency-depth5-v1/report.json`) gives 42 nodes,
9 IDs and 24.1 -> 39.0 ms warm previews; it reveals “Skrolla ner till Prisjakt” but
still not the search box. Neither depth nor node cap was silently increased in
the runtime. IDs make controls already present in the preview actionable; they
do not solve wrapper-heavy shallow coverage. Choosing informative visible controls
for the preview is a separate next increment.

All evidence pins runtime source hashes. No Windows-CDP latency claim, real model
run, worker restart or Vercel deployment in this increment.
