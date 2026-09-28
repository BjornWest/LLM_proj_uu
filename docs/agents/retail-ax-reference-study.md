# Real retailer AX versus procedural storefronts

Follow-up: [IKEA/Uniqlo captures and the dense-layout implementation plan](retail-ax-layout-expansion.md)
extend this study with a concrete renderer/world-dependency map. The original
captures and comparisons below are retained unchanged.

Read-only inspection, 2026-09-25. **Both supplied product pages produced genuine
BrowserGym captures. No user-assisted capture is needed for this comparison.**
No inference, cart operations, purchases, account login or personal browser profile.

[Local side-by-side trees and screenshots](http://localhost:8876/retail-ax-comparison.html).
Reference URLs: [Elgiganten](https://www.elgiganten.se/product/mobiler-tablets-smartklockor/mobiltelefon/apple-iphone-18-pro-smarttelefon-256gb-black/1141337)
and [Amazon ASIN B0FTCWXD9K](https://www.amazon.com/dp/B0FTCWXD9K).
The original full Amazon URL is retained in the evidence. Its captured product
was an **iPhone 17 Pro Max, renewed, US version** despite the search-query URL
mentioning iPhone 18. These are page-architecture references, not identical-SKU
or matched-product difficulty comparisons.

## Measured shape

Counts below use the current harness's retained semantic nodes, not raw HTML,
framework classes, ignored AX wrappers or verbose extraction metadata. Real pages
are the post-scroll captures; Elgiganten's optional cookies were rejected first.
Local pages are initial product views of the same authored footwear fixture.

| Page/state | Semantic nodes | Interactive-role nodes | Headings | Max depth | Median depth | Largest immediate child count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Elgiganten, product | 1,285 | 196 | 32 | 16 | 9 | 77 |
| Elgiganten, specifications expanded | 1,880 | 213 | 44 | 16 | 7.0 | 125 |
| Amazon, product | 621 | 181 | 39 | 7 | 4 | 89 |
| Our department design | 139 | 24 | 6 | 8 | 5 | 9 |
| Our boutique design | 87 | 16 | 3 | 9 | 5 | 9 |
| Our technical design | 107 | 20 | 3 | 8 | 5 | 6 |

Interactive-role counts include links, buttons and selection/input roles; they
are **not** a count of independently tested working actions. Full-document AX
includes off-screen content, accessible frames and menu options. Viewport-visible
controls alone would be a different measurement. Some generic wrappers with no
semantics are already removed by the harness.

The real pages have approximately **4.5–15 times** as many semantic nodes as our
current designs before expanding specifications. But depth alone is misleading:
Amazon is shallower than our boutique. Width, number of meaningful branches,
repeated controls, option complexity and competing commercial actions matter.

## What survives non-verbose rendering

**Elgiganten:** a large product subtree (1,145 nodes, 1,740 with specifications),
not merely a large footer. It includes a substantial gallery, related-product
buying controls, competing payment/subscription choices, trade-in, delivery/pickup,
comparison content and long product information. Seven cart buttons share the same
accessible label, across main-product controls and accessories. Controls therefore
need surrounding context to identify the intended item. There are 14 repeated
named-control groups, versus zero in our three examples. Specifications expansion
adds 595 nodes and 12 headings without increasing maximum depth.

**Amazon:** broad global navigation and surrounding content dominate the captured
state. The main product subtree has 133 nodes—much closer to our department
main's 96—while the whole page has 621. Four purchase-option radio groups cover
storage, colour, carrier and condition; a fifth group is the gallery. Some option
labels combine selection, price, scarcity or shipping restrictions. The current
colour could not ship to Sweden, so this is not a normal purchasable US checkout
state. Many of its headings belong to the footer, not product sections.

**Our pages:** one small, easily located buying area, two images, a few facts,
little surrounding commerce and mostly unambiguous labels. They have useful base
structure differences, but the page remains unusually clean. Product complexity
also differs: a simple authored shoe versus real phone content contributes to the
gap. This sample cannot isolate layout alone or establish training difficulty.

## Important state and delivery distinctions

- Elgiganten initially exposed only a 16-node cookie-dialog tree. Rejecting optional
  cookies exposed the actual product tree. Counting the first tree as the page
  would reverse the conclusion. The button click is recorded.
- Initial Amazon product capture had 625 nodes, settling to 621 after scrolling.
  A second fresh session for disclosure inspection returned a seven-node
  “Continue shopping” interstitial despite HTTP 200. It is retained and excluded
  from product metrics. We did not click through it, evade it or infer the cause.
- Both were fresh headless Chromium contexts, 1440×1000, BrowserGym 0.14.3, without
  imported storage. Location/session/stock/experiments affect the returned content;
  this is a dated sample, not a universal reference count. Scroll coverage was a
  bounded 7,200 pixels followed by returning to the top, not a promise of loading
  every possible lazy widget. Read-only specifications were opened in a second
  successful Elgiganten session. Menu expansion did not run because its exact
  control was not uniquely visible at that point.
- The current standard profile is `core-tools-v12-ax-reuse`, compact incremental
  AX, `verbose=false`, a 1,000-token initial overview and 1,500-token query budget.
  Elgiganten/Amazon/local department overview examples returned 15/13/17 items at
  928/935/946 local-Qwen-tokenizer tokens. **The agent is not initially sent the
  entire 1,285-node tree.** It uses search/traversal to retrieve other regions.
- Full non-verbose node projection is included for structural inspection, alongside
  actual budgeted overview/search examples. The full projection is an audit
  reconstruction, not one tool response or model request. JSON field names, refs,
  values and semantic states remain in non-verbose mode; verbose controls extra
  extraction identity metadata. CSS class names are not the target.

## Recommended next implementation

**Subsequent scope decision, 2026-09-25:** place full product comparisons primarily
on the planned third-party sites; reserve retailer warranty/location surfaces
without inventing their unfinished data contracts; defer monthly plans; prefer
real generated product destinations for surrounding links. See the
[layout catalog decisions](../procedural-commerce-layout-catalog.md#scope-decisions-after-real-page-review--2026-09-25).
The recommendations below identify reference capabilities, not authorization to
implement every feature immediately.

Use these as **two different dense base-design briefs**, not the same design with
more padding or dummy wrappers:

1. A department/electronics architecture with several genuine purchase alternatives,
   contextual accessory controls, a large gallery, nested description/comparison
   content, and expandable specifications.
2. A broad marketplace architecture with a large navigation/search shell, a compact
   but multi-axis variant/buying region, delivery restrictions in offer context,
   merchant/condition information and substantial surrounding recommendations/footer.

Build meaningful shared capabilities first, then renderer-specific realizations.
Repeated cart buttons must add their own product. Comparison selectors must change
comparison content. Delivery/variant options must query actual world facts.
Do not add nonfunctional controls just to reach a node target, or put benchmark
labels/answers into ARIA text. Regional size labels should bind to canonical SKUs
through a scoped size guide; country eligibility stays separate (recorded in
[shopping challenges](../shopping-comparison-challenges.md#regional-size-representation--added-2026-09-25)).

Tune **region composition and state changes** as well as page size: number of
nearby alternatives, repeated labels, gallery controls, fact groups, option axes,
related-product cards and navigation branches. Inspect branch-local depth and
breadth, placement of price/variant/delivery information, and AX changes when
sections open. Keep a small-store distribution too. These two samples motivate
larger worlds; they do not justify making every retailer equally large or fixing
one numerical target for all designs.

The existing contract-testing approach still applies: independently check product
selection/commercial logic, every advertised control realization, then bounded
layout × capability compositions. This report does not modify the current site
implementations, certify imports or deploy copies of either retailer.

## Evidence and reproduction

Capture script: `scripts/inspect_retail_ax.py`. Offline comparison and native AX-tool
examples: `scripts/analyze_retail_ax.py`. Output root:
`.local/retail-ax-study/20260925-v1/` (ignored generated evidence).

- `urls.json`: exact supplied URLs.
- `capture-v2/`: successful initial real + three local page captures.
- `disclosures/`: second real sessions; Elgiganten specifications, Amazon interstitial.
- Each state: raw AX, non-verbose projection, outline, screenshot, role/depth metrics,
  actual initial overview; per-run source/artifact hashes and actions.
- `analysis-v1/`: structural regions, proper multi-term search outputs and input hashes.
- `capture/`: failed first launch because this shell lacked the existing local
  `libasound` path. No website capture from that attempt is counted.

The first capture script incorrectly used a literal pipe to express alternative
search terms in some example queries. Original outputs are retained; the offline
analysis uses the actual list-of-terms API, and the reusable script is corrected.
This affects the sample search queries, not AX captures, projections or counts.
Source copies for both executed capture versions are retained in their output
roots. These are observation inspections, not model episodes or pass-rate tests.

```bash
LD_LIBRARY_PATH=$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python scripts/inspect_retail_ax.py \
  --urls .local/retail-ax-study/20260925-v1/urls.json --local \
  --output .local/retail-ax-study/NEW-CAPTURE
```

Two isolated browser sessions run concurrently. No inference credentials or paid
services are used. Repeating the command fetches the live pages again; saved trees
are preferable for repeated structural/tool analysis.
