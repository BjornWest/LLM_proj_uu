# Wishlist session setup review

WISHLIST-SESSION-REVIEW-01: accepted for the scoped setup change. No concrete blocker found in the two task 516 probes. Independent audit: 88 artifact hashes, 248 source pins, four exact scripted requests, two current-AX targets. The adjacent JSON and executable Python retain the checks and source hashes; no candidate grader was imported.

Both runs preserve the original goal, product start URL and visible Add to Wish List action. Their two semantic actions are identical: click the wishlist control, then submit the required terminal response. Both have zero native action errors and native upstream score 1.

In v1, the add POST lacks a `PHPSESSID` cookie and the server returns the explicit message “Invalid Form Key. Please refresh the page.” The final owned database and authenticated wishlist page both contain no item. In v2, setup first makes an ordinary account GET using the existing benchmark fixture auto-login header. That response supplies the session cookie; the browser then opens the original product URL. The add POST carries that session cookie and the page-generated form key. The final database and authenticated page agree on wishlist item 3, product 104497, quantity 1.

The wrapper does not set cookies directly, modify the form key, fulfill intercepted responses, patch application code or disable CSRF. This is normal application-session initialization under the benchmark's auto-login fixture, not a claim of an unauthenticated or human-password login. Container identity and image match between probes. Independent final grading occurs before browser close, while raw native score remains separate. Broad authorization remains null.

These two probes support session initialization as the operational fix. They are not server-internal CSRF instrumentation or a randomized causal study. No remaining wishlist tasks or later suite cases were reviewed; no quantity constraint or training readiness is inferred.

The bounded triage comparison correctly found an identical two-action sequence, but reported unknown source identity and `same_goal=false`. Exact saved metadata, contract and first request demonstrate the same original goal; that triage field is not authoritative for these traces. No triage-library diagnosis was added for the scripted setup issue.

No browser, server, database, network or model calls were made during review. Original evidence remains untouched.
