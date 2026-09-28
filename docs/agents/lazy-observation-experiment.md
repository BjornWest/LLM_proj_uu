# Lazy browser observations: isolated experiment

2026-09-26. **Experimental, not adopted by the standard harness or deployed.**
No model calls, training, production state changes, or modifications to BrowserGym.

Code: `experiments/lazy_observation/prototype.py` and `run.py`.
Performance evidence: `.local/lazy-observation-v5/`.
Final expanded acceptance: `.local/lazy-observation-boundaries-v2/`.
The prototype bytes are identical between these two cohorts; the runner gained
additional negative tests, scoped snapshot copying and process-group timeout cleanup.

## What it does

- Uses Chromium CDP directly for a depth-1 AX overview and targeted node/ancestor/
  child queries, without a full DOM snapshot or automatic screenshot.
- Keeps explicit document-generation references. Reload/navigation invalidates
  old handles. Caches loaded nodes, but rechecks watched nodes rather than trusting
  the absence of AX change events. Unknown regions remain explicitly unknown.
- Revalidates the selected target and its ancestor semantics before executing a
  native Playwright action. A temporary per-target data attribute bridges the CDP
  node to a locator; it is removed afterwards. There is no page-wide BID marking,
  forced click, action replay or target substitution.
- Retrieves target geometry with `DOM.getBoxModel` on demand.
- Reuses our existing BrowserEvents observer for transient notifications. There
  are no task/site-specific selectors in the prototype or private grader reads.
- Preserves global multi-term substring search with an explicitly labeled **full
  AX fallback**. Scoped search filters that full public tree by descendants; it
  does not yet reduce browser-side search work. Missing cached nodes are never
  treated as absence of a match.

The targeted protocol is experimental in Chromium. `Accessibility.enable` is
required for stable AX IDs and has its own browser cost. The installed Chromium
supports the methods exercised here; no cross-browser/version promise is made.
Protocol source: https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/pdl/domains/Accessibility.pdl

## Results

Median wall times in milliseconds (four alternating full/lazy samples for refresh
and action paths; one cold overview, wide-branch and global-search call per page):

| Operation | 1,126 AX nodes | 6,127 AX nodes | 21,127 AX nodes |
|---|---:|---:|---:|
| Full BrowserGym capture, including DOM/AX/screenshot | 242.2 | 701.7 | 2,977.0 |
| Shallow lazy overview, after enable | 9.7 | 17.6 | 52.7 |
| Recheck one known/watched control plus event drain | 6.7 | 6.6 | 6.8 |
| Revalidate and click a known control | 52.4 | 50.3 | 58.7 |
| Recheck watched state after the click | 7.0 | 7.2 | 6.5 |
| Global search, full-AX fallback | 43.0 | 442.9 | 1,744.6 |
| Fetch wide stress branch, present 20 children | — | 19.3 | 69.0 |

The cold overviews fetched 8/9/9 AX nodes. Enabling accessibility separately cost
1.0/5.6/1.4 ms. Returned node count is not a byte/token bound: child-ID lists can
be long. Wide-branch queries fetched **all 500/2,000 immediate child records** even
though only 20 were presented. CDP child queries lack native offset/limit. This
matters for extremely broad pages; presentation pagination is not extraction
pagination. A previous depth-2 candidate fetched too much on this fixture and
failed the initial-fetch gate; that evidence remains in v4.

These operations do different amounts of work: lazy refresh covers the explicitly
watched control, not every page node. The numbers are **not** an end-to-end agent
speedup or equal-completeness whole-page observation comparison. Global search
still pays to obtain the full tree. No screenshot is included in lazy timings;
an explicit screenshot tool remains necessary when requested.

The performance driver uses a known DOM selector to bootstrap its watched test
control, solely to separate update cost from discovery cost. This is not an agent
capability. Discovery is measured separately through global search; an actual
agent may instead expand branches. The correctness driver discovers action targets
through AX search and scope, then acts through the prototype.

## Frozen source and isolation

The generated storefront comes from the prior profiling snapshot under
`.local/generated-browser-profile-v3/source`, not the evolving world-generator
checkout. Synthetic 500/2,000-card additions create ordinary articles/headings/
text/buttons; they are not generated products or valid commerce offers. One extra
test checkbox supplies a known state change. All commerce state snapshots remain
unchanged. BrowserGym 0.14.3 / Playwright 1.44.0, local headless Chromium, viewport
1280×900, no slow_mo, fixed wait, inference or recording in the timed paths.

Each test owns a fresh browser and generated runtime. Independent correctness
cases run in parallel; latency cases run in isolation, alternating operation order
to reduce warmup bias. Source manifests and exact profiler/prototype copies are
retained per output. No shared live world, lease, browser or server was used.

## Acceptance and differences

Two independent final correctness runs each pass **27 assertions**. They cover:

- Unloaded deep content and open-shadow-root discovery; hidden text exclusion and
  later visibility; inserted content; multi-term and scoped duplicate-label search.
- Correct scoped native click, child traversal, checkbox/input feedback, and a JS
  property-only input change that need not emit a DOM MutationObserver event.
- Targeted geometry, relabel/ancestor/disabled-target rejection, removed watched
  nodes, and an obscured click timing out without force, replay or mutation.
- A short-lived status announcement surviving its removal via existing feedback.
- Same-URL reload and new-document reference invalidation.
- Explicit rejection of multi-frame lazy use; independent full BrowserGym capture
  still sees the iframe control. **Automatic fallback routing is not implemented.**

All three performance fixtures also pass search completeness against separately
captured BrowserGym content, meaningful-node content and control-property parity,
four checkbox transitions and unchanged commerce state checks.

**Raw tree shape is not identical.** BrowserGym's temporary ARIA marking exposes
otherwise ignored empty wrappers. The controlled fixture adds 12 empty generic
nodes plus one empty LabelText node under full capture; performance fixtures add
three generic nodes plus one LabelText. Exact differences are retained. Content
comparison excludes only unnamed/valueless generic and LabelText wrappers;
interactive properties are independently compared. This does not certify the
current harness's flattened ancestry/ref formatting, which needs a shared canonical
view before adoption. Search currently uses raw nonignored AX semantics, so its
counts can include redundant static text that the production AX index collapses.

Current boundaries:

- Main-frame lazy execution only; frames require full-capture handling.
- No general DOM/AX mutation completeness guarantee. Polling explicitly says that
  unloaded regions may have changed. Watched-node revalidation is O(watch count)
  CDP calls and has not been scaled to hundreds of watched controls.
- Target checking is not atomic with a later Playwright click; changes during
  actionability waiting remain a race to investigate, also relevant to the current
  runner. No guarantee against arbitrary adversarial page timing is claimed.
- No full subtree `extract_page` bridge, closed-shadow action support, production
  BID compatibility, batch guard integration, model-facing tool schema or grader
  lifecycle integration. None was silently changed.
- No model/task success rate or RL throughput conclusion follows from these tests.

Earlier attempts remain: v1's about:blank/set_content fixture did not run the
existing secure-context event initialization; v2/v3 exposed raw wrapper-tree
differences; v4 exposed width despite a depth limit. These failures informed the
final scope and are not erased or relabeled as passes.

## Recommendation

Proceed to an **opt-in shared observation backend**, retaining full capture as a
reference/fallback. Keep current tools and meaningful AX semantics, represent
partial coverage explicitly, refresh specific targets for action guards, and route
global search/subtree export to complete extraction when needed. First validate
frame transitions, model-facing hierarchy, event/readiness behavior and sparse
cache invalidation; then run paired model episodes. Do not promote this prototype
as the default or claim the old cost vanished for arbitrary global searches.

## Reproduction

```bash
.venv/bin/python experiments/lazy_observation/run.py \
  --source .local/generated-browser-profile-v3/source \
  --output .local/lazy-observation-NEW

# Correctness only, two independent browsers in parallel:
.venv/bin/python experiments/lazy_observation/run.py \
  --source .local/generated-browser-profile-v3/source \
  --output .local/lazy-boundaries-NEW --correctness-only
```

An existing repository checkout can replace `--source`; only intent_browser and
the procedural-commerce package are copied. Using different source is a new
experiment, not a reproduction of the saved hashes. Outputs must not exist. A
180-second process-group deadline bounds each case; failed evidence is retained.
