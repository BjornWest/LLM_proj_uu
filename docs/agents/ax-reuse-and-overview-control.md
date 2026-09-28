# AX revisits and agent-selected automatic context

Local current profile: `core-tools-v12-ax-reuse`. This is a presentation change,
not an environment/grader change. Existing saved runs and explicitly selected
historical CLI profiles stay unchanged. No running worker or Vercel deployment
was restarted for this increment.

## Automatic context

The first observation defaults to a 1,000-token structural AX overview, reduced
from 2,000. Subsequent automatic updates remain incremental. Browser tools
(except the terminal message) accept optional `ax_overview_tokens`:

```json
{"url":"http://allowed-site/orders/123","ax_overview_tokens":0}
```

Allowed values are **0, 512, 1000, 2000, 4000**. These are local Qwen-tokenizer
budgets for selected AX JSON, not complete request limits. Zero means no AX node
listing; a small page header, action errors and independently captured action
events still arrive. The next-input limit, full raw AX capture and trace storage
are unchanged. This does not reduce BrowserGym capture work.

The choice applies to the next automatic update. Omission selects the profile
default. In a batch, the **last actually executed browser call** determines the
budget; query/Python/helper calls do not overwrite it, and skipped calls have no
effect. It is a presentation option, removed before calling BrowserGym. Original
native arguments remain in the trace; each executed action also records the
requested setting and the decision snapshot records its effective budget.

Skipping an initial overview acknowledges only its page header, not node fields.
A subsequent targeted query therefore does not unexpectedly trigger the omitted
overview. Unseen nodes remain searchable/traversable; changes to known nodes
remain available. `ax_changes(repeat=true)` requests a structural overview later.
`visited_content_unchanged` concerns visited nodes only; `no_nodes_visited` makes
the empty case explicit.

Instructions encourage zero when searching a known target next, 512 for light
orientation, and larger budgets only for demonstrated need. Search/traversal
retain their existing bounded result budgets and shared verbose/repeat controls.
All tool definitions remain constant within the episode. Model adoption and
task-performance effects have **not** been evaluated yet.

## Revisit reuse

Every revisit still captures current AX. An episode-local cache matches the full
indexed public AX by URL, role, complete name/value, properties, parent/child
topology and order. Volatile DOM/AX identifiers and BIDs are excluded from this
comparison. Any semantic difference forces ordinary fresh presentation; the
implementation does not deduplicate shared headers across different URLs.

Only previews acknowledged as delivered in this conversation can be reused.
An unchanged revisited node returns `reused_from` pointing to its earlier
description, plus its **current** ref, BID, parent and position. Old refs remain
invalid; `repeat=true` forces current descriptive content. Verbose requests also
return fresh extraction metadata. Partial previews do not become full-text
reads, and nodes never delivered are not marked known. Exact public AX equality
does not imply equality of hidden server state or successful transactions.

The cache holds at most 64 semantic page versions and is discarded on explicit
context reset. It never rewrites prior messages. Compact reference mappings have
some cost, so small pages may save little. This would not eliminate the 28
distinct-page overviews in the earlier WebArena 147 trace; the smaller/default-
optional automatic update addresses that separate problem.

## Validation

```bash
.venv/bin/python -m unittest tests.test_ax_reuse tests.test_ax_context \
  tests.test_ax_explorer tests.test_native_tools tests.test_native_batch \
  tests.test_open_internet tests.test_runner_pacing tests.test_delegation -q
.venv/bin/python scripts/verify_ax_reuse.py --output .local/ax-reuse-check-NEW
```

The browser script runs two independent local cases concurrently with scripted
HTTP model responses: unchanged revisit and same-URL changed content. It checks
fresh handles, one real saved mutation, a deliberately disabled control error,
zero-overview feedback, skipped/last-executed batch settings, constant schemas,
append-only requests, acknowledged policy spans, no private-state leakage and
evaluation before close. No inference or benchmark performance is claimed.
Output directories are exclusive; failed development attempts remain retained.

Current-policy task adoption keeps legacy single-observation exposure/avoidance
labels unknown. Reused references do not promote new exposure certifications.

Validated on 2026-09-21: 99 focused/regression tests passed (including data tools
and delegation). `.local/ax-reuse-validation-final/report.json` records two
parallel seven-decision BrowserGym cases, 12 checks each, zero network model
calls; all recorded runtime/script hashes matched after completion. The tiny
unchanged fixture's overview fell from 634 to 574 tokens; zero-overview updates
were 85–111 tokens including their headers/errors. These are fixture measurements,
not a projected saving on WebArena or a model-capability result.
