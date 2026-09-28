# Procedural commerce: AX-first design revision

2026-09-22. Local development only; no deployment or model inference. Supersedes the first MVP's claim that its three retailer branches constituted three distinct base designs. Historical runs and their source hashes remain unchanged.

## Why the first test was insufficient

HTML ancestry histograms measured differences that need not survive Chromium accessibility extraction or harness formatting. The new review fixes commercial content and retailer identity, captures actual BrowserGym AX plus the harness observation text, and checks observable regions, information order, controls and interactions. Different hashes are insufficient. See the revised [design rubric](../procedural-site-variation-rubric.md).

The old implementation remains the `legacy-catalog` family. Its `legacy_style` choice (`catalog`, `boutique`, `specifications`) is now separate from merchant identity for landing/results/product presentation. Its existing `compact`/`expanded` detail variation remains available. The prior common checkout is deliberately reused while the discovery/product architectures are made distinct; no claim of four unique checkout flows.

## Reference inspection

We inspected public retailer pages for patterns, not reusable task environments. Raw HTML was downloaded for IKEA and MUJI into ignored `.local/research/retail-layouts-20260922/`, with URLs, statuses, sizes and SHA256 in `manifest.json`. Merchant assets and prose are not copied into the synthetic renderer. These are original schematic pages inspired by common navigation patterns.

- [IKEA product page](https://www.ikea.com/us/en/p/poaeng-armchair-birch-veneer-knisa-light-beige-s59305928/): image gallery before product selection, delivery/availability sections, several product-information destinations and substantial lower-page content. This motivates independent media, purchase and details regions.
- [MUJI product page](https://www.muji.us/products/polypropylene-wide-storage-case-white-gray-shallow-b7s7033): long descriptive product identity, product disclosures and extensive footer navigation. The downloaded static HTML contains multiple native disclosures; this is not a claim that all are initially visible to a browser agent.
- [Crutchfield category](https://www.crutchfield.com/g_37900/Bookshelf-Speakers.html): search results expose filter/sort and comparison-oriented organization. Direct download returned 403; only retrieved search text supports this reference. No claim to have captured its full rendered AX.
- [John Lewis product page](https://www.johnlewis.com/john-lewis-electric-kettle-1-5l/navy-blue/p5523668): retrieved search text exposes description and delivery sections. Direct download timed out; it was not a full rendered-page inspection.

Actual merchant AX was not captured. Their source HTML is reference material only. Synthetic acceptance below must stand on our own real browser evidence.

## Composition contract

`presentation.py` resolves `retailer_designs` and `presentation_options` once per Runtime using independent named hashes. No resampling on reload. Commercial generator/engine and expected answers are unchanged. Defaults retain the legacy family for existing callers; `--design-set ax-v2` explicitly selects the new portfolio. Adapter provenance and private diagnostics record resolved designs/options.

Per-site choices include `nav_expanded`, `image_count`, `title_style`, `details_presentation`, and the legacy-family `legacy_style`. Applicability is explicit: department supports inline/disclosed details, boutique uses linked details, technical uses disclosure, and legacy remains inline. Unsupported combinations are rejected before the HTTP runtime starts; legacy_style is only accepted for the legacy family. Image count and title richness alone do not meet the stronger structural variation rubric. Full two-axis variation per page role remains future work. New product-specific fields can extend public facts later; the renderer must not fabricate unsupported attributes merely to lengthen titles.

`/products/ID/details` is a public, read-only same-retailer route. Cart, quote, checkout and receipt reuse the existing authoritative engine. The primitive HTML forms preserve their field names and endpoints. Nothing in presentation may change authorization, price, inventory or the meaning of an optional extra.

## Search correction

The old search required a contiguous case-insensitive substring across product name/category/attributes. That means reordered words such as `lamp Nordvale` could fail even though both occurred in the product. Search now requires every query term, in any order; category filters still combine with the query. Empty and no-match cases remain explicit. This is a reproduced limitation, not proof of the exact cause of the user's report. Native browser checks should cover both Enter and button submission.

## Evidence

Final local evidence is recorded below. This is bounded environment acceptance, not model-performance certification.

## Local previews and reproduction

The new portfolio preview uses **explicit showcase settings** to make the contrasts easy to inspect. Ordinary seeds can still vary title richness, navigation expansion and image count. The showcase is not evidence that every randomly drawn pair is equally different.

- [Aggregator](http://localhost:43395/)
- [Department-market Nordhem](http://localhost:42013/) — [same product example](http://localhost:42013/products/product-001)
- [Editorial Vardagslagret](http://localhost:37005/) — [same product example](http://localhost:37005/products/product-001)
- [Technical Teknikgården](http://localhost:33367/) — [same product example](http://localhost:33367/products/product-001)

The example can legitimately be out of stock at some retailers. No commercial world was resampled to improve the demo. Live preview state is shared within this preview process; scripted acceptance uses isolated fresh Runtimes. Existing legacy previews remain separate.

```bash
# New preview, with deliberately contrasting settings rather than random settings.
python3 -m environments.procedural_commerce.runtime --seed 7 --scale small \
  --design-set ax-v2 --presentation-profile showcase \
  --output .local/procedural-commerce/my-new-ax-preview

# Same supported commerce tasks through the normal BrowserGym runner, scripted.
.venv/bin/python -m data.curation.procedural_commerce.mvp.verify_browser \
  --design-set ax-v2 --output .local/procedural-commerce/my-new-ax-commerce \
  --workers 2

# Matched retailer/world comparison through actual accessibility extraction.
.venv/bin/python -m data.curation.procedural_commerce.mvp.verify_accessibility \
  --output .local/procedural-commerce/my-new-ax-comparison --workers 2
```

The earlier `ax-v2-browser-acceptance/` cohort passed against an intermediate renderer; the owner subsequently split the document builders without changing business logic. `ax-v2-browser-final/` is the fresh final-source commerce cohort. Earlier results remain historical. Shared harness code was not changed by this revision.

## Final validation

- **74 offline tests pass** (focused procedural commerce and curation tests).
- **10/10 final-source scripted BrowserGym commerce cases pass**, zero action errors. Nine expected safe outcomes and the intentional unauthorized-extra rejection. Evidence: `.local/procedural-commerce/ax-v2-browser-final/suite.json`; 650 artifact hashes and relevant runtime hashes checked by `ax-v2-commerce-final-summary.json`.
- **Matched AX review: six gates pass**, with four isolated browser sessions and at most two parallel processes. Evidence: `.local/procedural-commerce-ax-acceptance-20260922-final2/summary.json`.
- 24 raw AX snapshots, 24 exact harness-formatted observations (48,000-character cap, not 48,000 tokens), and 24 normalized trees retained. No inference request is claimed from this AX-only inspection.
- Partial-word Enter submission, reordered words, empty search and no-match button submission pass for the aggregator and all three retailer architectures.
- Frozen new renderer SHA256: `de9602467de78521e3206777ae5b157b15197b7fa9cb2850cd77d07156400a69`.

The matched AX fixture holds Nordhem identity, two-product catalog and commercial facts constant across designs. It adds one explicitly noncommercial public attribute sentinel to prove information availability. The department title/description expose it immediately; the boutique link and technical disclosure hide it initially and reveal it after the corresponding native action. This does **not** claim that every public fact is hidden before those actions, nor that every task requires inspecting that field.

Concrete observations from saved trees:

| View | Department | Boutique | Technical |
|---|---|---|---|
| Landing navigation regions | 2 | 1 | 1, nested under sidebar |
| Product images in matched fixture | 2 | 1 | 1 |
| Partial search result structure | article + list; complementary sidebar | article + list; no complementary region | table, 2 rows and 5 column headers; complementary sidebar |
| Detail discovery | already exposed | linked detail page | native Specifications disclosure |

The live showcase deliberately uses **two** boutique images; the matched acceptance uses one. Settings are retained in each artifact, not inferred from the brand name. Title and image differences are presentation-factor evidence, not sufficient proof of architecture diversity on their own. Landing structures remain simpler than large real-world retailers; product facts remain sparse. Checkout/cart HTML is still shared.

Earlier AX test-development failures are retained: the initial attempt reported no visible searchbox; a later helper-edit error accidentally returned None instead of runtime keyword arguments. The latter was a validator defect, not a missing Runtime API. It now has a regression and retains original traceback information. These cases are not model failures.

No paid model/search inference, production deployment, shared harness changes or Git publication occurred. Public web reference fetches were ordinary read-only HTTP browsing. The prototype still needs human design review and later model calibration; AX differences alone establish neither difficulty nor generalization.
