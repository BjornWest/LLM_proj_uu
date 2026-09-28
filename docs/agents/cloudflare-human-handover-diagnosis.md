# Cloudflare human-handover diagnosis — 2026-09-27

Status: read-only research and saved-network review. No new live challenge attempts,
browser changes or inference. Manual interaction failed to clear the challenge;
the exact server-side rejection reason is unknown.

## Evidence

Episode: `.local/real-web-supervised-wait-v1/runs/20260927T132405Z-9ed75229`.
HAR SHA256: `e39271a9bce7f7ec0b284116b8c5e0a5d744a19fd31f52b6d8fd74f4a31395cc`.
Sanitized derived reports are `challenge-network-review.json` and
`challenge-cookie-review.json` in that cohort directory. Original HAR is unchanged;
do not publish its cookie values or opaque challenge URLs.

- Captured browser: Chromium 125.0.6422.26, Linux, controlled by Playwright.
- Eight Prisjakt responses returned HTTP 403 with `cf-mitigated: challenge`.
- Nine responses set nonempty `cf_clearance` cookies, including six from Prisjakt.
  They have future expiry, Domain/Path, Secure, HttpOnly, SameSite=None and
  Partitioned attributes. None of the eight challenged requests includes that
  cookie in its recorded Cookie header. This is a diagnostic lead, not proof of
  cookie rejection: HAR alone does not contain cookie-store state, browser rejection
  reasons or Cloudflare's clearance level/verdict.
- Eight PAT endpoint 401s and eight challenge-subdomain DNS failures are not
  independently evidence of a broken challenge. Cloudflare documents both as
  expected/nonfatal cases.

## Documented mechanism versus hypotheses

[Turnstile](https://developers.cloudflare.com/turnstile/) uses JavaScript challenges,
browser/API characteristics and behavioral signals. A checkbox is only part of
the interaction, not a promise that a human click overrides all other checks.
Cloudflare does not disclose the exact decision rule for this request.

[Supported browsers](https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/)
explicitly excludes Playwright-controlled browsers for production challenge solving.
That makes our browser environment a strong suspect, not an established causal verdict.

[Cookie documentation](https://developers.cloudflare.com/fundamentals/reference/policies-compliances/cloudflare-cookies/)
describes site/session bot-score and clearance cookies. This is different from
reading the user's entire browser history. Lack of a rich personal profile is not
established as the cause; Cloudflare itself recommends private-mode troubleshooting.

[Challenge troubleshooting](https://developers.cloudflare.com/cloudflare-challenges/troubleshooting/challenge-solve-issues/)
documents the PAT/DNS cases above and recommends updated browsers, its compatibility
checker, and controlled browser/network comparisons.

## Next diagnostic, without inference

1. Manually try the same destination in an ordinary updated browser on the same
   machine/network, using a separate clean profile/private window. Do not import
   personal profile data into the agent browser.
2. Check our browser cookie-store/rejection diagnostics and Cloudflare's
   compatibility checker. Record only cookie attributes/names and rejection
   reasons, never values in public reports.
3. Compare an updated supported browser engine with the currently pinned engine
   under a separately validated harness profile. Change one variable at a time.
4. If ordinary browsing also fails, retain error code/Ray ID for the site operator.

Do not infer that fake pointer movement, profile history, or changing a user-agent
string will solve this. Synthetic gates/test keys validate our handover workflow;
they do not predict production Cloudflare acceptance.

## Follow-up: clearance meaning and local cookie check

Cloudflare's [JavaScript Detections documentation](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/javascript-detections/)
explicitly states that `cf_clearance` can contain either a passed or failed JS
detection outcome. Its name/presence alone does not prove that the interactive
challenge was passed. We have not decoded or established our cookies' outcomes.

A local headful Playwright/TLS diagnostic on the same Chromium 125.0.6422.26
successfully stored and transmitted a synthetic cookie with Secure, HttpOnly,
SameSite=None, Partitioned, Domain and Path attributes. Both the local HTTP server
and CDP observed it; HAR captured it correctly. An ordinary nonpartitioned cookie
served as a control. No blocked-cookie reasons were reported.

Reproducer/evidence: `.local/cloudflare-cookie-diagnostic-v1/check.py` and
`report.json`. The test used a temporary self-signed local TLS origin, permitted
certificate errors, and synthetic values only. It was standalone Playwright, not
the full BrowserGym configuration, and did not contact Cloudflare. Thus it rules
out universal lack of support for these cookie attributes in this installed
browser/recorder, not the remaining production/context-specific possibilities.

## Manual live follow-up

User authorized one manual-only session, then reported verification still failed.
Evidence: `.local/cloudflare-manual-diagnostic-v1/{events.jsonl,review.json,started.json,finished.json}`.
It used actual BrowserGym with the preceding run's frozen OpenWebTask navigation
routing and context settings, without model calls or repeated AX capture.

Both captured search requests included `cf_clearance` in CDP outgoing headers,
with no cookie exclusion reason, and still received 403 `cf-mitigated: challenge`.
The cookie-store check also found it. Thus cookie loss was not reproduced in this
session; the older HAR absence cannot establish failure to send. Interactive
clearance success and Cloudflare's server-side decision remain unknown.

No HTTP 429 was captured; this does not establish absence of IP-based restrictions
or future reputation effects. The session was stopped following the user's concern
about repeated attempts. No further challenges were launched. The next useful
comparison would be ordinary updated-browser behavior on the same network, rather
than more retries in this identical automated environment.

## Windows Chrome comparison

The user reported normal browsing/search worked without verification in fresh
private Windows Chrome 152.0.7977.83. Launch evidence:
`.local/cloudflare-normal-browser-v1/started.json` (no network instrumentation).

A separately authorized fresh private profile on the same Windows Chrome version,
launched with `--enable-automation` and loopback remote debugging, then attached
through Playwright CDP, failed according to the user. No model or BrowserGym ran.
Playwright navigated to the home page; the user searched and attempted verification.
Two captured searches returned 403 challenge responses despite transmitting
`cf_clearance` with no recorded exclusion. `navigator.webdriver` was true.
Evidence: `.local/cloudflare-windows-automation-v1/{started.json,ready.json,events.jsonl,review.json}`.
Debugging transport used a loopback-only WSL/Windows stdio bridge, not a LAN listener.

This strengthens the automation-environment hypothesis and shows old Chromium,
WSL and BrowserGym are not necessary for the observed failure. It does not isolate
Playwright itself: the automation flag, remote debugging and attachment changed
together, and timing/fresh profile differed. No claim of exact server detection
mechanism or reliable workaround is warranted. Session stopped after the user's
report; no further trials started.

## Final authorized flag comparison

The user authorized one last attempt omitting `--enable-automation`. Windows Chrome
152, private fresh profile, loopback debugging and Playwright CDP attachment were
retained; no navigator/fingerprint overrides were injected. Launch command inspection
confirmed the flag was absent. Before navigation `navigator.webdriver` was false
(true in the preceding flagged trial). The user reported that this attempt worked.

Evidence: `.local/cloudflare-windows-no-automation-flag-v1/` contains launch
arguments, source hashes, sanitized network events and `review.json`. The diagnostic
was stopped after the report; this exhausts the requested final attempt.

This implicates the flag or the behavior/signals it enables, rather than Playwright
attachment alone. It does not identify which signal Cloudflare used. The runs have
different fresh profiles and timings, are a single pair rather than a randomized
experiment, and have no server-side verdict details. No full BrowserGym agent run
was tested in the successful configuration. Historical evidence/default harness
settings remain unchanged; any runtime adoption needs a separate opt-in profile
and validation, not an assumption of universal challenge compatibility.

## Published access rules checked after diagnostics

On 2026-09-27 the user requested a model-only access test and explicitly asked
whether it violated site rules. No model run was started. Prisjakt's terms were
then checked; they restrict automated collection/analysis but expressly reference
limited crawling permissions in robots.txt. Their application to ephemeral
user-directed assistance was not resolved as a legal conclusion.

At the user's request, the actual `https://www.prisjakt.nu/robots.txt` was retrieved
via Chrome: HTTP 200, text/plain, 2026-09-27T14:09:40Z. Direct HTTP/research-tool
reads had failed; no challenge was solved or product data collected in the file
read. Saved text and retrieval metadata:
`.local/prisjakt-robots-review-v1/robots-browser.{txt,json}`.
Saved-text SHA256: `b2397f9e0a56395dd987ccfbe28e51fbbf68ee5fb9aa469da16de26716929ff4`.

The wildcard group disallows `/search?*`, `/go-to-shop`, `/redirect.php`, account
paths and several filter/pagination patterns. No blanket disallow is present for
the wildcard group; homepage and ordinary `/produkt.php?p=...` product URLs are
not excluded by the listed patterns. MSIECrawler, HTTrack and DataForSeoBot are
separately disallowed entirely. The file contains no specific user-directed-agent
exception. Thus it does not support the proposed automated search flow, while a
claim that robots.txt disallows every product-page read would also be inaccurate.

Sources: https://www.prisjakt.nu/information/anvandarvillkor and
https://www.prisjakt.nu/robots.txt . The Robots Exclusion Protocol's technical path
rules and legal permissions are distinct; Prisjakt's express reference makes
the rules relevant but does not by itself settle all permitted uses of data.
