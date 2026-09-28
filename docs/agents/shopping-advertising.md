# Frozen advertising in connected shopping worlds

Implemented locally; no deployed release or model evaluation claimed. Product owns
`product_world/advertising.py` sampling and validation. Curation owns
`connected_shopping/advertising.py` rendering, connected runtime binding and the
optional review-page decoration hook. No new organic catalog entries or grading rules.

Launch a **new** runtime with `python -m environments.connected_shopping`, the ordinary
`--pin`, `--comparison-coverage`, fresh `--output`, and optional
`--advertising PATH/advertising.public.json`. Omission preserves previous behavior.
The sidecar must validate against the exact world and match published site IDs,
kinds and families before servers start. Runtime deep-copies it, saves a public
artifact, and records its canonical digest/version in `provenance.json`. Saved JSON
formatting can differ from the input; canonical digest and byte hashes are distinct.

Ads have visible/accessible Advertisement labels, advertiser names, canonical item
prices and working sponsored links to exact retailer SKUs. Banner and inline blocks
sit outside organic cards, comparison forms and report corpora; sidebar placements
use a separate complementary landmark. Ads may mention products absent from a
comparator's organic coverage. They never affect sorting/filter counts, comparison
membership, review text/ratings, or editorial evidence. Clicking a relevant ad is
not intrinsically a failure. No tracking scripts or external resources are added;
rejecting optional cookies does not remove contextual ads.

First publication: `.local/connected-shopping/preview-v10-advertising/manifest.json`,
index http://localhost:38599, PID30560. Uses frozen footwear-depth/pin-v1 and
shopping-ads/pin-v1; v9/task41201 remain unchanged. Four comparators and five of six
product-review sites contain 18 ads. Six ads are footwear products. The current
version uses the same frozen site campaign on all of that site's pages; per-page
campaign targeting/rotation is not implemented.

Validation:
- 26 tests across advertising binding and conformance, including malformed/foreign
  sidecars, organic membership, exact links/prices, review exclusion, no-ad identity.
- Two native BrowserGym journeys cover comparator banner/inline and review
  banner/sidebar, labels in nonverbose AX, optional-cookie rejection, mobile layout
  and native ad click to exact SKU. No model calls.
- All 1,402 independent source-to-page conformance cases pass, including 26 review
  articles/1,632 exact reports; ads do not alter those facts.
- Saved outputs: `.local/connected-shopping/advertising-native-v1/report.json` and
  `.local/connected-shopping/advertising-conformance-v1/report.json`.

Reproduce native checks with `python -m scripts.verify_shopping_advertising
--runtime RUNTIME --output NEW_DIRECTORY`; use the workstation's documented native
browser library path when launching outside the CLI. These are privileged scripted
checks, not task/model success evidence. User task binding and independent global
reference equality are Product-owned follow-up checks.

## Accepted local example

The separate advertising preview is http://localhost:38599, with task card
http://localhost:40495/task.html. Footwear comparison: http://localhost:42509;
footwear reviews: http://localhost:34835. Runtime output is
`.local/connected-shopping/preview-v10-advertising/`. Previous v9 origins remain live.
Product independently checks exact sidecar/corpus/coverage binding, visible ad facts,
retailer destinations and unchanged global reference. Curation's ad browser journeys
and 1,402 ordinary page checks pass; these are scripted checks, not model results.
