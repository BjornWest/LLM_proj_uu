# Independent consent-popup designs

2026-09-26. [View the three designs and AX outlines](http://localhost:8876/review-cookie-popups.html).

Implemented on the five local product-review publications. The reusable module is
`environments/site_consent/`; other retailer and merchant-review runtimes are not
wired to it by this increment. No deployment or model calls.

## Designs and behavior

| Design | AX structure | Necessary-only path |
| --- | --- | --- |
| `bottom-banner` | Nonmodal region at the bottom; underlying page remains in AX; preference fieldsets with checkboxes | One visible button |
| `center-modal` | Native modal dialog; underlying page inert; preference fieldsets with switches | One visible button |
| `side-drawer` | Native modal dialog at the side; preference purposes in separate native disclosures | Manage preferences, then Reject optional cookies |

All offer accept-all and custom choices. The three optional purposes are audience
analytics, personalised recommendations and advertising. Initial values are off;
necessary storage is always enabled. No analytics or advertising requests are made:
these are simulated permissions with real persisted choices, not real tracking.

The popup is independent of the article layout, product facts, review scores and
publisher name. `design_for(seed, site_id)` uses its own versioned hash stream.
Every design works with every review layout: the native suite tests all nine
combinations. A design is stable on one site throughout navigation.

`Runtime(..., consent_design=None)` keeps the earlier popup-free behavior by
default. The human preview launcher now defaults to `--consent-design sampled`;
`none` or any explicit design is also supported. A fresh preview manifest records
each assignment. The seed is not derived from task outcomes or hidden answers.

## Persistence and diagnostics

A necessary, HttpOnly, SameSite=Strict session cookie identifies the browser on that
runtime. Cookie names are unique per runtime, which matters because HTTP cookies
are not port-scoped on localhost. Reloads, page navigation and new tabs in the same
browser context retain choices. Separate browser contexts and separate runtime
instances do not inherit them. Server restarts intentionally start fresh consent
state; this is an in-memory development runtime, not durable account storage.

A persistent **Cookie settings** button reopens preferences. Unsaved edits and
Close settings do not alter committed values. Escape on an undecided modal leaves
it open; after an existing decision it can close settings without changing state.
The banner permits browsing without a decision. “Undecided” remains distinct from
an explicit rejection, even though both initially have optional purposes off.

Only a successful server commit closes the popup. Requests carry a session token
and revision; malformed choices, cross-session tokens, unexpected browser origins
and outdated revisions are rejected. A network error leaves the interface open and
the previous choice unchanged. There are no hidden retries. This is a local
simulator boundary, not an audited production consent-management system.

`Runtime.consent.snapshot()` is privileged Python access, **not an HTTP route**.
`site-consent-journal-v1` retains session ID, committed preferences, decision and
revision, and every accepted event with sequence/time/design/action. CSRF tokens
are omitted. The preview writes snapshots beside its manifest on clean shutdown.
This provides outcome facts for future task diagnostics; it does not assign reward,
claim that a purpose was authorised, or establish that the model saw/read the popup.
Policy-input exposure still needs the harness's exact delivered observation.

## AX impact

Same footwear article, same underlying data, directory layout:

| Design | Initial AX nodes / controls | Preferences open AX nodes / controls |
| --- | --- | --- |
| Banner | 631 / 105 | 659 / 109 |
| Center modal | 13 / 5 | 41 / 9 |
| Drawer | 12 / 4 | 36 / 12 |

The small modal trees are expected: native `showModal()` makes the background inert.
These are semantic AX counts, not model context token counts. Drawer preference
captures have all three purpose disclosures opened. The banner totals include the
article underneath. Opening settings does not itself establish consent.

## Evidence

- 79 unit/HTTP tests across consent, product-review and merchant-review modules.
- Nine isolated native browser cases / 109 checks, bounded concurrency two.
- Scripted checks cover custom/accept/reject, reload/navigation, reopen/cancel,
  transport failure, fresh contexts, same-context tabs, mobile width and JS errors.
- One browser case explicitly verifies separation across localhost ports.
- HTTP/unit tests cover origin/session/revision rejection and absence of a public
  state endpoint. No model performance or training-readiness claim.

Artifacts: `.local/product-review-sites/consent-v1/acceptance/`; source/public-input
verification: `.local/product-review-sites/consent-v1/validation.json`.
Current live preview: `.local/product-review-sites/preview-v5/manifest.json`.
Earlier previews and AX reports remain historical. Product export hash unchanged.

```bash
.venv/bin/python -m pytest environments/site_consent environments/product_review_sites environments/merchant_reviews -q
LD_LIBRARY_PATH=$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python scripts/verify_review_consent.py --output NEW_DIRECTORY
```

For integration elsewhere, mount the two local UI assets and consent-commit route,
call `begin()` for HTML requests, inject its markup and set the returned session
cookie, and keep the snapshot private. The existing review runtime is the concrete
adapter. Its CSP allows same-origin script/style/connect only; no third-party
assets are needed. This adapter contract can later be extracted into a common HTTP
wrapper when another site actually consumes it.
