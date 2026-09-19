# Incremental AX context

Local development profile: `core-tools-v7-context`. It replaces neither frozen
cohorts nor production workers implicitly. `core-tools-v6-ax` remains the explicit
repeat-full-overview baseline. No paid inference was run for this increment.

## Common presentation contract

AX search, traversal and current-page changes use `AXContext` and the same controls:

| Control | Default | Meaning |
|---|---|---|
| `verbose` | false | Include extraction diagnostics; never required to discover meaningful page state or omissions. |
| `repeat` | false | Resend already delivered fields/text; otherwise unchanged nodes are short references and changes contain only changed fields. |

`ax_search` and `ax_read` retain the earlier query, subtree scope, neighborhood and
pagination parameters. New `ax_changes(offset=0, verbose=false, repeat=false)`
lets the model inspect/continue current updates or request a repeated structural
overview. Automatic updates use the same defaults, configurable per episode with
`--ax-verbose` and `--ax-repeat`. These are separate controls: verbose is not a
request to repeat all page text.

### Node fields and structural radius

`ax_read(node_ref, view="node", radius=0)` reads **only the node's own fields**
(name/value/state), not text stored in its descendants. Zero is the default;
existing node-text pagination remains `text_offset` / `next_text_offset`. Results
explicitly say `scope=own_fields_only`. A node with children supplies an expansion
hint even when its own fields are unchanged. This does not claim its children or
subtree have been read.

For example, a paragraph often has an empty name with its sentence stored in a
StaticText child. Rereading the paragraph with `repeat=true` does not retrieve that
child; expand the region instead.

```json
{"node_ref":"d1n42","view":"node","radius":1}
```

- **0:** own fields only, no implicit expansion.
- **1:** focus plus immediate parent, children and same-parent siblings.
- **2–8:** expand those same relations again, up to the requested radius.

A sibling counts as **one hop** in this API, deliberately unlike ordinary
parent-child edge distance (where it would take two). Thus radius 2 can include
sibling children, grandparents and parent siblings. Distinct root/frame trees
without a common captured parent are not treated as siblings. Relations reflect
the indexed public AX hierarchy, not raw DOM nesting or pixel distance.

Positive-radius results are unique, focus first and then breadth-first rings, with
`distance` on each item. Newly discovered neighbors follow captured tree order.
They use the same previews, `verbose`, `repeat` and acknowledged-delivery tracking
as every other context tool. Already-known entries remain short references plus
distance. Full fields of a truncated neighbor are retrieved separately with
`view=node,radius=0`; radius never silently adds unbounded full text.

The existing 20-node default/50-node maximum and result-token budget still apply.
Use `offset` / returned `next_offset` with the same radius for subsequent pages;
requesting a radius does not guarantee all matching nodes fit in one response.
`text_offset` is only for radius 0. A positive radius with any other view is an
explicit error rather than silently ignored. New page/reference changes retain
the existing freshness rules.

Other views are unchanged: `children` (the default view) lists direct children;
`subtree` uses `depth`; `ancestors` goes upward. `neighborhood` with `context` is a
window of neighboring rows in **flattened preorder**, which can cross structural
boundaries; it is not the new radius. Use `view=node,radius=1` to get actual siblings.
The separate v6 profile has no radius parameter; its schemas remain unchanged.

### Search limits and multiple terms

`ax_search` defaults to 5 results, maximum 20, and zero neighboring nodes. Results
also share the 1,500-token result budget, so a page may contain fewer entries;
continue with `next_offset`. `ax_read` defaults to 20 nodes, maximum 50, under
the same token budget. Neither cap limits how much captured AX is searchable.

In v7, `query` accepts a literal phrase or a list of up to eight nonempty literal
terms/phrases (each at most 256 characters, an input-validation limit rather than
a context-size measurement). `match="any"` is the default; `match="all"` requires
every term in the SAME node's searchable role/name/value/state. It does not join
terms from separate children or perform semantic/fuzzy/regex expansion.

```json
{"query":["reviews","ratings","feedback"],"match":"any","scope_ref":"d1n42","limit":10}
```

The native tool schema includes concrete single-string and real-array examples.
Multiple terms must be an actual array value, **not JSON array text inside a
string**. The outer tool-call `arguments` field is serialized JSON as required by
the API; after decoding that envelope, `query` must still have the intended type.

```json
{"query":"reviews"}
{"query":["reviews","ratings"]}
```

If a string parses as a valid 1–8-term JSON array but the **literal search has no
matches**, the result includes `query_notice` with code
`array_encoded_as_literal_string`, an actual-array example when it fits the token budget and
`search_was_reinterpreted=false`. When the example is too large, `example_omitted=token_budget` keeps the
concise explanation without duplicating the input. The notice is normal tool
feedback, not hidden verbose metadata. It does not execute a second search, change the retained tool
arguments, retry a request, or advance delivery state for hypothetical matches.
The policy must explicitly submit a new call if it intended multiple terms.
A successful literal match gets ordinary results, without treating its input as a
mistake. Invalid/non-string/oversized array-looking expressions are not guessed
or coerced. The v6 schema and single-string semantics remain unchanged.

Role/subtree filters apply to every term. Nodes appear once, in tree order, with
`matched_terms`; the result limit is shared across terms, not multiplied per term.
Case-insensitive duplicate terms are collapsed. A newly requested excerpt from a
previously previewed long node remains deliverable; repetition controls do not
silently suppress a different matched passage. Existing single-phrase callers and
the separate v6 schema remain supported.

Concise output retains node ref, role/name/value when new, BID, parent/position,
child count, semantic AX properties (including checked, disabled, expanded, etc.),
partial-text/coverage notices and pagination. Raw AX IDs, backend DOM identities,
snapshot hashes and extraction counters are diagnostic metadata. No arbitrary
semantic AX property is discarded as "metadata". Default/empty fields are omitted;
cleared fields are explicitly signalled in deltas.

Historical browser-event feedback follows the same verbose metadata convention.
Errors, uncertain timeout effects, transient notices, capture gaps and nonzero
omissions stay visible. Historical AX differences and distinct action events are
preserved: they can describe something that disappeared before the current page
capture, and two matching commit messages can represent two separate commits.
Verbose `ax_changes` also exposes the latest capture diagnostics. External Parallel
web-search results are a separate provider format, not indexed as AX nodes.

## Delivery and identity

Short refs (`d1n42`) are tied to a document and real DOM node identity when available.
An unrelated page change does not invalidate every ref. New documents/routes reset
the ledger; replaced/removed nodes cannot silently inherit an old reference. Nodes
without reliable DOM identities use conservative parent/content/position matching.
An identity observed to disappear is retired even if it later reappears. This is
not a guarantee against DOM changes occurring during model inference.

The presenter separately retains:

- Acknowledged node fields and structural membership, for changes since delivery.
- Pending query/update fields that will be co-delivered in the next request.
- Full-node token ranges and search excerpts actually selected, independent of
  shortened previews. New text queries can reveal new excerpts of a known node.
- Traversal visits: root, view, offset, returned count, snapshot and controls.
  Original calls/results remain recorded in trace steps and policy spans.

Only results that fit the presentation budget enter the pending ledger. The runner
advances it after a returned completion and matching retained policy-input spans.
Rendering a transition/final screenshot artifact alone does not count as delivery.
`discard_pending()` abandons unconfirmed visit effects; `reset_delivery()` must be
called if a future conversation manager removes context. Current history remains
append-only, with preserved reasoning and no silent compaction/retries.

Initial page updates are bounded structural overviews. Later updates affect visited
nodes/regions: changed fields, moved/reordered nodes, removed refs and new immediate
children. Unvisited descendants stay accessible through search/traversal; the marker
is deliberately `visited_content_unchanged`, not a claim that the entire website is
unchanged. Large update sets retain undelivered changes and expose continuation.
Initial/repeated overview continuation explicitly requests `repeat=true`; pending
delta continuation restarts at offset zero because delivered changes leave the queue.

Search/traversal keep short references to previously delivered nodes so result
membership/order remains understandable. Repeating a request can fit additional
previously unseen entries because known entries are cheaper. Follow the returned
offset rather than assuming page sizes are fixed. Use `repeat=true` for rereading.

## Usage

```text
--harness-profile core-tools-v7-context
--ax-tokenizer-file training/.cache/qwen38-tokenizer/tokenizer.json
--ax-overview-tokens 2000
--ax-result-tokens 1500
```

Programmatic equivalent: `AXConfig(tokenizer_path, incremental=True)` passed to
`native_tools_profile(parallel_tool_calls=None, compact_feedback=True,
timeout_feedback=True, ax_config=...)`. Native schemas include matching controls.
Existing certified task adapters still require explicit adoption; no readiness or
exposure labels are promoted by this change.

## Evidence

17 context tests plus 58 existing AX/native/delivery/feedback/navigation tests pass,
run in independent parallel groups. Cases cover changed fields beyond previews,
unseen content, discarded pending delivery, partial text, navigation, replacements,
reordering, removal/reinsertion, bounded multi-page deltas and CLI profile wiring.

Two real BrowserGym scenarios run in parallel with mocked inference:
`.local/preflight/ax-context-v5/report.json` and its per-case reports. They verify
local checkbox changes, unchanged overview suppression, distant-node discovery,
repeat/verbose controls, identical-label DOM replacement, stale-ref rejection,
immutable conversation prefixes, exact acknowledged spans, query/no-env-step
accounting and evaluation-before-close. v1 fixture failures are retained: the test
incorrectly assumed a checkbox would appear in the bounded initial overview; the
corrected script discovers it through search. No model behavior is inferred.

Multi-term follow-up: 21 context tests plus the same 58 regression tests pass.
`.local/preflight/ax-context-v6/report.json` contains the two parallel real-browser
cases on the current multi-term source, including the exact native array-query
request and acknowledged result. Earlier source-pinned reports remain historical.

Read-only presentation comparison on retained Books/Reviews snapshots:
`.local/review/ax-context-v3/report.json` with tokenizer and source hashes. Using
the local Qwen tokenizer, unchanged updates take 46 tokens. The selected Reviews
subtree returns 26 entries/1,367 tokens versus v6's 13/1,409; revisiting those same
26 entries costs 492 tokens. Books returns 20/988 versus 14/1,413. These compare
context pieces, not total API requests, task success or causal model performance.

```bash
.venv/bin/python scripts/verify_ax_context.py --output NEW_DIRECTORY
.venv/bin/python scripts/measure_ax_context.py --output NEW_DIRECTORY
```

Limits: full browser AX capture/indexing remains local and unbounded by the model
token budget. This is per-episode memory; full snapshots/provenance remain in raw
traces. The new model cohort below uses opt-in budget settlement; historical ledgers remain unchanged.

## Development model rerun (2026-09-19)

`.local/preflight/ax-context-model-v1`: Books67 and Reviews163 ran concurrently
with current v7, 30-decision limits and verified-cost settlement. Both passed native
answer grading (29/20 calls; $0.1325807 total reported cost). Safety remains unknown.
Max reported input was 41,225/26,349 tokens. Detailed saved-input review and raw
search arguments: `.local/review/ax-context-model-v1/{report,context-review}.json`
and `findings.md`. All three model searches supplied array-looking strings rather
than arrays, yielding no literal matches; traversal recovered. Two Books clicks
timed out after 500ms while navigation completed. No mid-run repair/retry.

This is not a controlled comparison with v6: the old runs stopped at unreleased
reservation caps. The v7 unchanged-update measurements directly confirm suppression.
85 offline tests and both native positive/negative preflights passed before inference.

## Structural radius validation (2026-09-19)

25 context tests and 58 existing regression tests pass. New checks cover structural
parent/child/sibling membership, two-hop expansion, root separation, deterministic
distance order, duplicate exclusion, token-bounded pagination, acknowledgement,
changed siblings, partial text, metadata/repeat controls, schema limits and v6
rejection. Three independent real BrowserGym scenarios pass in parallel under
`.local/preflight/ax-radius-v2`, with mocked inference and exact policy request/result
checks. The radius case covers the empty-paragraph own-fields ambiguity, direct
text child and sibling discovery, plus second-ring expansion and deduplication.
All three reports' runtime source hashes match the completed implementation.

The first radius browser fixture (`ax-radius-v1`) expected a previously delivered
neighbor's name to be repeated; the runtime correctly returned an unchanged ref.
That failed fixture trace is retained; v2 checks the original ref and distance.
An initial long-text unit fixture was also enlarged to actually exceed its token
budget; no production text coercion or delivery bypass was introduced. No paid
model calls, deployment or historical trace changes. Stringified-array search
behavior from the previous model cohort is addressed by the subsequent guidance
and diagnostic increment below; no later model improvement is yet established.

## Search encoding guidance validation (2026-09-19)

28 context tests plus 58 existing regression tests pass. Four real BrowserGym
cases run in parallel under `.local/preflight/ax-search-encoding-v2`, using
HTTPX mock responses (zero paid calls). The added encoding case retains the exact
string query and empty literal result, delivers the notice in the matched tool
response, then executes a separately scripted real-array call. It also successfully
searches actual array-looking page text as a literal string. Query operations do
not step the browser, hypothetical array matches are not marked delivered, request
prefixes remain immutable, and evaluation precedes close. All four execution source
maps were rechecked against the completed implementation. v1 predates the bounded
example optimization and remains historical. A 512-token unit case checks that a
token-heavy array example is omitted instead of exceeding the tool result budget.

This fixes missing interface guidance, not a demonstrated model capability failure:
there is no new live Qwen result yet. On the next authorized cohort, inspect actual
array-valued queries, notice frequency, explicit recovery, unnecessary retries, and
radius usage. Do not infer success from the scripted correction, and do not silently
coerce future model queries or erase the original failed search.
