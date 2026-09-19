# Independent manual-site lease review

Review requested under DATA-EXP-BROWSE-01 before deployment. This review uses
source and saved artifacts only: no new browser calls, leases, resets, model
calls or production changes. Backend owns implementation and release.

**Current status: BROWSE-REVIEW-01 closed for the repaired source**
`31b5ced342e724d2b92f8e4dd714fa5d988aa145f2cc6f07d966908316215622`.
Deployment and fresh live-site acceptance remain backend-owned. The initial
finding below is retained as history; see closure evidence at the end.

## Initial release finding: BROWSE-REVIEW-01

The initial browser driver adds `X-Daylight-Lease` as a context-wide header and
uses `context.route` to reject off-origin requests. Installed Playwright's
Chromium network implementation explicitly skips user interception for redirected
requests (`crNetworkManager.js`, lines 309–318). The initial broker forwarded
upstream `Location` unchanged. Therefore that route callback alone cannot enforce
the stated boundary for an external redirect. The globally configured credential
also makes such a redirect a potential credential exposure. This is a missing
boundary check, not a claim that an upstream fixture has emitted an attack or that
this review performed a browser exfiltration test.

Backend added a same-origin redirect check during review. Its first implementation
still accepted these values:

```text
///outside.invalid/path
////outside.invalid/path
http:////outside.invalid/path
```

Python `urljoin` resolved them under the canonical origin, but Node's WHATWG URL
parser resolved them to `http://outside.invalid`. Passing the original raw
`Location` through would preserve that difference. Reject ambiguous forms or
forward only a validated, normalized destination, with explicit regression tests.
Preserve ordinary same-origin account/forum redirects; never retry the upstream
request after a blocked redirect because it may already have changed state.

Evidence: `.local/manual-sites/independent-lease-review-v1/redirect-parser-comparison.json`.
This comparison is pure URL parsing and used no browser or HTTP calls. Finding
remains open in this initial review; closure must identify the repaired source and
its checks rather than overwrite the historical result.

## Boundaries supported by source review

- Only two configured WebArena slots can be acquired. Each is exclusive; busy or
  resetting slots reject acquisition. Callers cannot select a reset command or
  upstream URL through the broker API.
- Revocation clears the token before reset starts. New acquisition waits for reset
  completion. Active proxy requests drain before reset; timeout/reset failure
  quarantines the slot. An old token cannot release a newly leased generation.
- Expiry and broker startup lead to reset, not reuse of prior server state.
- The pinned clone helper checks exact container identity, owner/site labels,
  image, mounts and port bindings. It recreates whole containers.
- Browser headers contain a lease credential, not the broker administrative
  credential. The proxy removes that lease and caller authorization before
  injecting the fixed upstream fixture account header.
- Manual controller APIs are owner-scoped. Browser commands claim a request ID
  before dispatch, reject stale frames and do not automatically replay uncertainty.
- Startup, close and command-failure paths attempt release. A failed release
  retains the broker's exclusive lease until expiry; local code does not treat
  the site as reusable. Shutdown also requests release.
- Generic sessions reject Ask in both controller and driver, do no task setup or
  grading, and export only the trace subtree. The private launch file is outside it.

These are scoped implementation observations, not a general network-sandbox or
hostile-site security certification. Browser timeout, proxy lifetime and application
side effects remain separate facts; a failed response does not prove no write.

## Saved evidence checked

The two `pool-native-v1` reports each contain eight passed assertions. Their saved
database values independently represent a mutation and return to the original
baseline: shopping wishlist empty → one item → empty; forum biography original →
test text → original. The source asserts immediate old-token GET/POST rejection,
rejection of another occupant, a distinct next token and continued old-token
rejection after reuse.

The reports preserve assertion names and database values, not raw HTTP receipts or
execution source snapshots. This audit checks their internal consistency and the
test's actual predicates; it does not independently replay the native requests or
retroactively certify the current source as the version used for those tests.

Four saved WebArena UI archives were inspected: two local and two container cases,
25 members each. All archive hashes match their reports; member names are unique
and non-traversing. All four have null grading, no task preparation and zero model
attempts. For the two local cases, exact archive members/bytes equal the saved
original trace trees, and the actual private launch-token value is absent from
every member. Container original trees/token files were not accessed in this
review; those two checks remain unknown for that pair rather than inferred.

Machine-readable results, artifact hashes and copies of the audit-time sources:
`.local/manual-sites/independent-lease-review-v1/report.json`. That source snapshot
contains the first redirect guard; it is distinct from earlier source inspected
before the guard existed. Historical reports and ZIPs remain unchanged.

## Repair closure

The repaired broker rejects ambiguous slash/scheme forms, malformed URLs,
credentialed destinations and external origins. It sends only the normalized,
validated absolute canonical `Location`, rather than the original ambiguous
header. Duplicate Location headers are rejected. A blocked redirect returns 502
without repeating the upstream request; the request may already have had effects.
Broker provenance now captures its source hash at module load.

Independent recheck: 24 pure URL-parser cases agree with the expected decisions;
all eight accepted normalized destinations resolve to the canonical origin under
Node's WHATWG parser. The focused existing redirect unit test also passes. These
checks made no browser, proxy or lease calls.

The five saved Chromium cases in `.local/manual-browse/redirect-v2/report.json`
match the current broker source hash. The ordinary relative redirect reaches `/ok`
with HTTP 200; external, protocol-relative, triple-slash and scheme-slash cases
return 502. The foreign trap records zero requests. The recorded upstream list
contains exactly the five initial requests plus the accepted `/ok` redirect,
with no lease header forwarded. The test script uses the context-wide lease header
and no Playwright route guard, so this is evidence for the proxy boundary itself.

Closure record and repaired source snapshot:
`.local/manual-sites/independent-lease-review-v2/report.json`. The original v1
review and parser counterexamples remain unchanged. This closes the identified
redirect defect, not every possible network-isolation property or deployment
acceptance requirement. No remaining blocker was found in this scoped review.
