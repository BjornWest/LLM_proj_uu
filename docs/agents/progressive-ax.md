# Progressive accessibility-tree exploration

For the incremental successor with shared metadata/repetition controls, see
[incremental AX context](incremental-ax-context.md). This document retains v6's
full-overview behavior as a comparison profile.

Implemented locally as opt-in `core-tools-v6-ax`. Existing flat-tree profiles
remain unchanged. No production rollout or new model run is implied; benchmark
adapters must explicitly adopt and validate this profile before relying on their
policy-exposure labels.

## Interface

Default budgets: **2,000 tokens per overview**, **1,500 per AX tool result**, using
an explicitly supplied local tokenizer.json. Counts cover selected observation
text or serialized tool JSON, not whole requests, accumulated history, reasoning
or tool definitions. Metadata records tokenizer hash/budgets and marks the old
character limit as not applied. There is no automatic tokenizer download.

Small semantic trees are delivered in full if they fit; otherwise a breadth-first
overview supplies roles, names, BIDs, parent references and child counts. AX refs
have form `ax:<snapshot>:<index>` and are distinct from actionable BrowserGym BIDs.

- `ax_search(query, role=null, scope_ref=null, limit=5, context=0, offset=0)`:
  literal case-insensitive search of the complete captured semantic tree. Role
  is an optional exact filter; role-only queries are supported. `scope_ref`
  restricts matches AND optional neighbors to that subtree, including its root.
- Each match includes parent reference, up to three nearest ancestor breadcrumbs,
  sibling index, BID if present, excerpt and count of earlier ancestors omitted.
  Duplicate labels can therefore be distinguished without full neighborhoods.
- `ax_read(node_ref, view="children", depth=1, limit=20, offset=0, context=2,
  text_offset=0)`: children, subtree, ancestors, neighborhood or full node text.
  Ancestors are nearest first; neighborhood means semantic preorder, not pixel
  adjacency. Node text is token-paged. Search can return `suggested_text_offset`
  for a match deep inside a long text node.

Find a section, search within its ref, then inspect a selected match/parent. Pass
the resulting BID to click, without display brackets. Result limits are upper
bounds; budgets may return fewer entries. Follow `next_offset`/`next_text_offset`;
reduce context if an entry cannot fit. Search supports up to 20 matches and 8
neighbors per side; traversal up to 50 entries and depth 8. Full ancestors remain
accessible through pagination.

## Snapshot, limits and evidence

Each decision captures a fresh observation after any pacing hook. Queries read
that captured snapshot, never private grader state or live DOM evaluation. They
do not call `env.step`, receive rewards or retry mutations. Queries consume a
model-decision step but not a browser step.

Semantic content/topology, URL and real DOM identities determine snapshot refs.
Regenerated synthetic text-node IDs do not invalidate unchanged references;
changed trees/replaced real controls do. Stale refs return structured tool errors.
This does not eliminate page changes during inference or make BIDs immutable.

Full original observations remain separate. `ax-result-NNN.json`, `steps.jsonl`
and policy-delivery evidence retain queries, results and exact delivered spans.
Snapshot IDs identify semantic state, not raw artifact bytes. Results bypass the
generic feedback truncator and join the existing native tool conversation.

The index skips ignored/presentational nodes and redundant static text, like the
flat renderer. It cannot find content absent from captured AX or traverse a site
without navigation. Full capture/index/search still process the tree locally:
this bounds model input, not extraction time/memory for a million-token document.
Reference metadata can cost more tokens on small pages. Overview quality and
model-level efficiency need evaluation.

## Configuration and checks

Install the optional `context` dependency group. CLI options:

```text
--harness-profile core-tools-v6-ax
--ax-tokenizer-file training/.cache/qwen38-tokenizer/tokenizer.json
--ax-overview-tokens 2000
--ax-result-tokens 1500
```

Programmatically pass `AXConfig(...)` to `native_tools_profile` with
`parallel_tool_calls=None, compact_feedback=True, timeout_feedback=True`.
Navigation still requires explicit allowed origins. This adds no screenshot,
subagent or batched-action tool.

58 focused unit/regression tests pass. Real BrowserGym scripted validation with
HTTPX mocked inference is in `.local/preflight/ax-explorer-v4/report.json`:
duplicate-label locations, scoped search, omitted distant control retrieval,
traversal, exactly one intended mutation, stale-ref errors, no browser steps for
queries, exact delivery and evaluation-before-close. Earlier v1 failure evidence
is retained; it exposed synthetic text-node identity churn.

Read-only Qwen/Qwen3.8-27B tokenizer measurements on four saved Books observations:
`.local/review/ax-exploration-v2/report.json`. One full AX tree has 84,822 tokens,
its former selected text 17,944, and its new overview 1,995. The short initial
tree illustrates overhead: 604 flat AX tokens versus 1,983 overview tokens.
These are observation-text measurements, not request savings or success claims.
No inference calls or original-artifact changes were made for this increment.

```bash
.venv/bin/python scripts/verify_ax_explorer.py --output NEW_DIRECTORY
.venv/bin/python scripts/measure_ax_exploration.py \
  --trace .local/preflight/webarena-navigation-v1/traces/20260919T141104Z-d5da67f7 \
  --output NEW_DIRECTORY
```
