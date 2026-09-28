# Observation consistency and screenshot readiness experiment

2026-09-26. Opt-in experimental paths only. Normal runner, generated-world code,
BrowserGym defaults, worker and deployment are unchanged. No model calls.

## Document and freshness contract

A document is one loaded page in a browser frame. A reload can replace a document
without changing its URL. In-page filtering usually keeps the document but changes
its contents. Document identity and content freshness therefore need separate
checks; old element references cannot be trusted merely because the URL matches.

Background and foreground extraction must use the same public AX representation.
Neither can promise a permanently current tree on an independently changing page.
The relevant guarantee is equality at a defined validation boundary, followed by
action-time target validation. A detected mismatch invalidates the old observation;
it must not silently retarget or replay a mutating action.

`BackgroundBrowser(..., strict=True)` now adds a full foreground CDP AX comparison
before consuming the prefetched snapshot. It compares all raw node fields including
focus, ignored nodes, properties, values and child/parent relationships (node-array
order normalized). It retains existing document, epoch, DOM-event and action-target
guards. A mismatched snapshot raises `ObsoleteObservation`; explicit fresh capture
recovers. Shallow DOM revision is checked before publication and shallow semantics
are compared with corresponding full nodes. Already delivered messages never mutate.

This intentionally expensive mode is a correctness reference. DOM MutationObserver
events are insufficient: direct `input.value`/`checked` assignments, CSSOM changes
and focus can alter AX without a DOM mutation. The earlier guarded-cache mode and
its speed measurements remain historical and are **not** strict-mode measurements.
Strict mode incurs another full read; it does not establish the earlier overlap
speedup with complete freshness. Before promoting a faster cache policy, establish
a sufficiently complete generated-application revision contract and compare it
against this reference, including asynchronous rendering and asset-driven changes.

There is still a sampling boundary: a change after validation can invalidate any
observation, foreground or background. Existing targeted action checks help reject
changed targets; they do not freeze the entire website. Multi-frame documents
remain unsupported by this prototype. This is not an application lifecycle or
background-AX integration in the production runner.

## Screenshot-only gate

`experiments/readiness/visual.py` provides `wait_visual` and `capture_visual`.
Call after ordinary application readiness and only when a screenshot is requested.
Checks are scoped to visible, viewport-intersecting elements in a selected region:

- no public `aria-busy` in the region or ancestors;
- images loaded successfully and decoded;
- document font loading complete (conservative document-wide check);
- finite animations finished;
- sampled layout/text/control values and selected styles stable for three frames.

Capture checks signatures and document identity before and after screenshot. A
detected change retains the image as uncertain evidence with `unknown`, never as
a ready screenshot. Initial failed/unknown/pending readiness produces no screenshot.
The subsequent integrated experiment explicitly opts into `allow_uncertain=True`,
which saves a requested image with its uncertain status instead. Capture now keeps
the caret unchanged to avoid Playwright's temporary CSS injection; this refinement
is covered by the integrated regression evidence rather than the original v3 hash.
No action, load, scroll, asset fetch or screenshot is automatically replayed.

Visible canvas, video, SVG, CSS background images, pseudo-element content and
infinite animations return `unknown` in this narrow prototype. They require other
evidence before claiming stability; they do not disappear from the page. Region
element limits and offscreen/missing regions also return unknown. Images must
already have been requested by the application; this is not a lazy-load scroller.
The saved screenshot is the viewport; readiness claims cover only the selected
region. Activity outside it can still appear in the image.

This does not prove pixel invariance: a brief change and reversal between samples,
future updates, omitted CSS properties and unsupported rendering can evade sampled
signatures. It is a bounded screenshot aid, not a universal rendering oracle.
The JS deadline cannot kill a frozen renderer; retain an outer process timeout.

## Scripted evidence

Current retained result: `.local/readiness-consistency-v3/`, **49 checks pass**
(26 AX, 23 visual), including exact foreground equality on **20,024 AX nodes**.
Four stale AX cases (value, checkbox, CSSOM, focus) retained an unchanged DOM stamp
and were rejected by strict full-tree comparison. The historical background suite
also passes 56 checks across two independent browser sessions; its speed tests
were not rerun. All this increment's calls are scripted/local, zero model calls.

Run independently in two browser processes, no inference:

```bash
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python experiments/readiness/check_consistency.py \
  --output .local/readiness-consistency-NEW
```

Reports retain source hashes and reject a changed source closure. Cases cover
unchanged foreground equality, property-only values and checkbox state, CSSOM,
focus, DOM edits, same-URL reload, mutation during background capture, explicit
recovery, no action replay and a synthetic 2,000-card tree. Visual cases cover
delayed local images/fonts, image pixels, finite/infinite animation, broken assets,
busy deadlines, offscreen controls, unrelated animations, content changes and
identical-content document replacement during capture.

Earlier failed v1 fixture assertions are retained: an unscoped text search also
matched AX text nodes, and an HTTP 404 with a valid PNG body still rendered as an
image. The corrected tests constrain the role and supply invalid image bytes;
these were fixture assumptions, not runtime repairs.

## Deferred teacher-data feature

See [assisted trajectory repair](assisted-trajectory-repair.md) for the requested
branch/restart/manual-action/hint workflow and separate raw versus SFT projection.
That feature is recorded for after readiness polishing; not implemented here.
