# Omdömeskollen: merchant-review website

2026-09-25. Local read-only review application, integrated with the product agent's
deterministic review export. No model calls or deployment changes. This is an
original synthetic site inspired by Trustpilot's information architecture, not an
import of Trustpilot or a reproduction of its scoring system.

[Live local site](http://localhost:42503/) ·
[Example company](http://localhost:42503/review/store-001) ·
[Reference and generated AX evidence](http://localhost:8876/merchant-review-site.html).

## Delivered pages and interactions

- Home: prominent company/category search, category discovery, grouped company
  cards and recent customer experiences.
- Search: company name/domain/category matching, category filter, sorting by name,
  rating or review count, eight companies per page, genuine empty results.
- Company profile: identity, overall average and count, navigation to sections,
  recent-review highlights, company details, five-star distribution and company
  response count. Related company links reference actual profiles.
- Review list: twenty reviews per page, keyword/star/topic/date filters and
  newest/oldest/highest/lowest sorting. Filter and pagination state lives in the URL.
  Overall statistics always describe the complete corpus, not the visible subset.
- Review permalink: full text, rating, reviewer handle, experience/publication dates
  and an expandable company reply when one exists.
- Categories and methodology pages are working routes. No decorative account,
  submission, reporting or voting controls that silently do nothing.

The preview contains eight generated stores and 384 reviews, 48 per store. It uses
authored positive/negative/mixed star priors to make the differences inspectable.
Those preview assignments are illustrative, not calibrated merchant behavior or a
training sampling policy. No copied real customer text, avatars or retailer ratings.

## Real-page inspection

Inspected [Trustpilot home](https://www.trustpilot.com/),
[Elgiganten search](https://www.trustpilot.com/search?query=elgiganten),
[Elgiganten profile](https://www.trustpilot.com/review/www.elgiganten.se) and
[Zalando profile](https://www.trustpilot.com/review/zalando.se).
Saved BrowserGym AX and viewport screenshots, rejected optional cookies, and used
bounded scrolling. The returned documents reported HTTP **403**, despite rendering
recognizable homepage/search/profile content. These are observed rendered reference
states, not evidence of unrestricted functional access to Trustpilot. No bypass,
login, review submission or remote company-contact action was attempted.

Observed patterns: search-led home, category and company lists, broad profile
summary, sidebar rating histogram, related companies, dated review cards, replies,
filters and pagination. We reused these structures with our own content/branding.
Accounts, platform-business advertising and proprietary scoring are outside this
first read-only implementation.

Retained non-verbose semantic AX nodes in this sample:

| Page | Trustpilot reference | Generated site |
| --- | ---: | ---: |
| Home | 906 | 276 |
| Search results | 261 | 57 |
| Company profile | 809 / 816 | 578 |

Search counts are not matched-result comparisons: the generated search example
returns one company. Generated profile has 88 interactive-role nodes and maximum
depth seven. Its actual initial overview is 947 local-Qwen-tokenizer tokens, not
the complete 578-node audit reconstruction. These are structure measurements, not
agent difficulty or end-to-end performance results. The live preview uses different
star priors from the browser acceptance corpus, so its detailed counts can differ.

## Data ownership and generation

Product owner implements `environments/product_world/reviews.py`:

```python
world = generate_store_world(seed=42, store_count=8,
                             focus_families=['footwear', 'laptops'])
export = generate_reviews(world, seed=42, as_of='2026-09-25',
                          reviews_per_store=48, config=None)
```

Export version `merchant-review-export-v1`; the website consumes **only**
`export['public']`, containing `as_of` and `companies`. Company IDs equal store
retailer IDs. Each company includes name/domain/category, complete reviews and
derived statistics. Each review has a stable ID, fictional handle, stars, title,
body, topic, dates and optional reply. Public source validation rejects mismatched
statistics, bad dates, duplicate IDs and unexpected fields.

The generator supports global and per-company star weights, topic weights and reply
probability, with 0–200 reviews per company. Separate store/review random streams
preserve corpus prefixes when counts grow or unrelated stores change. Seed/config
and priors stay in private provenance. The renderer does not generate facts.

Current prose is short reusable topic/sentiment templates, permitted for this first
version. There are no verified-purchase badges or claims about specific SKUs. Dates
respect experience <= publication <= reply <= world date. Review count, histogram
and arithmetic mean all derive from the same complete corpus. Empty corpus means
`null`/“Not rated,” never a zero-star company. Display rounding is half-up to one
decimal; the full mean remains in public statistics.

### What this evidence means for future tasks

Reviews are imperfect fictional testimony, not a hidden merchant-safety oracle or
proof of actual events in the commerce engine. Tasks can objectively ask about a
rating/count threshold, dated complaint frequency or what reviewers report. We must
not grade a statement that a merchant is objectively safe solely from star priors.
Likewise, opening the review page is a procedural diagnostic, not an outcome reward.

Later, if reviews need to correlate with merchant practices, establish a shared
merchant profile or historical-experience model upstream, sample testimony with
noise/selection bias, and render text from those facts. Do not infer hidden merchant
truth backwards from generated prose or quietly add renderer-specific facts.
Correlations, recency trends and user trust preferences are not implemented here.

## Runtime and integration boundary

`environments/merchant_reviews/` owns the validated corpus, presentation and small
loopback HTTP server. No remote assets, scripts, database or runtime network fetches.
Native forms and links provide browser actions; CSS is local. Each runtime owns a
copied immutable-in-practice corpus and a bounded private HTTP access log. Public
routes never expose full generation exports/private priors. POST is rejected.
The access log records requests, **not** confirmed model exposure or comprehension.

`Runtime(export['public'], website_bindings=...)` accepts explicit company-to-site
URL bindings. Without one, the reserved `.test` domain is displayed as identity,
but no broken “Visit website” action is offered. New store layouts, shared index
registration, Vercel and task/grade adapters remain separate integrations. Do not
bind a generated merchant to an unrelated existing retailer merely to make a link
work. We have not integrated the store-first offers with commerce in this change.

## Verification and evidence

32 tests pass: 22 site/contract tests and the product owner's 10 generator tests.
Two isolated native-browser rehearsals pass: normal corpus and empty corpus,
27 named checks total. They cover search, category routes, profiles, all initial
profile links, stable summary under filtering, selected review IDs after filters,
sorting/pagination, permalink/reply reading, empty results, unique DOM IDs and
390-pixel viewport width. No model capability claim or new curated task readiness.

- Real references: `.local/merchant-reviews/reference-v1/`.
- Final browser cases: `.local/merchant-reviews/acceptance-v2/` (v1 retained before
  increasing page size to twenty and recent highlights to four).
- Preview manifest/export: `.local/merchant-reviews/preview-v2/`.
- Final hash check: `.local/merchant-reviews/validation.json`.
- Coordination: `.local/coordination/merchant-reviews/product-contract.md`.

```bash
.venv/bin/python -m environments.merchant_reviews --port 42503 \
  --output .local/merchant-reviews/preview-NEW
# Or consume an existing versioned export:
.venv/bin/python -m environments.merchant_reviews --export /path/reviews.json \
  --bindings /path/company-origin-map.json --output .local/merchant-reviews/NEW

.venv/bin/python -m pytest environments/merchant_reviews \
  environments/product_world/test_reviews.py -q
LD_LIBRARY_PATH=$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python scripts/verify_merchant_reviews.py \
  --output .local/merchant-reviews/acceptance-NEW
```

Choose an unused port and new output directories. Public and private generation
exports are retained locally for reproducibility, never served by the review app.

## Identity variation — 2026-09-26

The CLI now samples a name from eight authored fictional identities using a separate
seeded namespace: Omdömeskollen, Kundkompassen, Handelsröster, Butikspanelen,
Köparblick, Omdömesplatsen, Kundspegeln and Handelsintryck. `--site-id` supplies stable
identity; `--site-name` can explicitly override the display name. The resulting
identity is retained in the preview manifest. Search results, headers, page titles,
permalinks, methodology and error pages all use that instance's name. No module-global
branding, rating changes or layout changes accompany a name change. Existing Python
callers retain the old default name unless they supply `site_name`.

[Renamed instance: Kundspegeln](http://localhost:35971/), consuming the exact same
384-review public payload as the original preview. The original server and evidence
remain unchanged. Twenty-three merchant-site tests pass, including simultaneous
runtimes with different identities and consistent names across routes. This does
not register those names in the shared world search index; future discovery entries
must consume the same identity rather than sampling a second name.
