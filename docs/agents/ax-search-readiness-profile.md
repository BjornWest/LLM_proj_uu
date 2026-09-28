# AX search readiness investigation

## Findings

`AXExplorer.capture` / `AXContext.capture` need the merged AX tree, URL and open
page URLs. AX supplies text/roles/state, semantic topology, backend DOM identity,
frame identity and BrowserGym IDs. Search does not consume DOMSnapshot, geometry,
focus or screenshots. Removing those fields from the exact same snapshot yields
identical query output in all ten tested full snapshots.

There are two current dependencies that are broader than search itself:

1. BrowserEnv's native path marks documents, obtains DOMSnapshot, obtains merged
   AX, extracts focus/geometry, cleans marking and obtains screenshots. The
   dynamic preview waits for this entire capture, not an AX-ready milestone.
2. After backend completion, runner.py adopts the full observation and calls
   `ax_explorer.capture(obs)`. Full AX acquisition overlaps decoding, but semantic
   indexing is still done after decoding. Building an index is much slower than
   issuing a query on an existing index for the large synthetic page.

The real-web shallow preview deliberately strips actionable BIDs and instructs
use of full-tree search. An initial ax_search is therefore partly encouraged by
our interface; this investigation did not count how frequently models choose it.
Starting with search does not negate decoding/capture overlap: the preview may
already let the model formulate a useful query while the full index is prepared.

## Measurement

Local diagnostic script and complete retained sources/results:
`.local/ax-search-readiness-v1/probe.py`, `report.json`, and the two
`*-index-profile.txt` cProfile reports. No shared runtime edits or model calls.

Five alternating pairs per site, sequential timing isolation, explicit GC before
timed capture. Same loaded browser/page within each site. Both modes retain
native marking, all-frame merged AX and native cleanup. No screenshots, recording
or model inference in reported search readiness. Recording is flushed outside the
measurements. Query uses a short list of literal terms with normal bounded output.
Index configurations and queries are in the script; tokenizer is local Qwen3.8.

| Site | Full capture → search-ready | AX-only prototype → search-ready | Index build, full / AX-only | Actual query, full / AX-only |
|---|---:|---:|---:|---:|
| Live Prisjakt: 5,377 AX nodes, 4 frames | 545 ms | 418 ms | 31 / 34 ms | 7 / 12 ms |
| Static 3,000-product fixture: 21,010 AX nodes, 1 frame | 1,518 ms | 1,256 ms | 432 / 493 ms | 16 / 15 ms |

Readiness is capture + index, before query. Entries are independent medians;
sums of median components need not equal median readiness. Live page changes are
allowed; this is not a byte-equivalence comparison across successive live captures.
Recorded same-snapshot parity tests isolate dependency equivalence instead.

Full-capture phase medians (nested frame timings excluded from sums):

| Phase | Prisjakt | 21k-node fixture |
|---|---:|---:|
| Mark/BID preparation, frame handling and visibility wait | 154 ms | 98 ms |
| DOMSnapshot | 114 ms | 221 ms |
| Merged AX acquisition and BID decoding | 158 ms | 618 ms |
| Focus + DOM geometry extraction | 24 ms | 86 ms |
| Cleanup | 60 ms | 20 ms |

AX-only avoids DOM/focus/geometry work. It does not eliminate marking, cross-frame
merging, data transfer, native JSON decoding or the Python semantic index.
The CPU profile shows repeated JSON serialization/hash preparation and Python
node/index construction in indexing, not a slow literal substring search. The
large index profile has 24,038 calls to the `encoded` helper; these include
per-node properties/identity and full snapshot signatures. Index snapshot reuse
and incremental display bookkeeping must be preserved before optimizing them.

## Recommended next increment

1. Stage a full AX search index during the existing decoding overlap, rather than
   building it after decoding. Separate index preparation from adoption and policy
   delivery acknowledgment: do not mutate the active visit ledger while a prior
   request is in flight.
2. Introduce a search-ready capture phase before DOM/geometry/screenshot work.
   Prioritize a pending AX search when that phase is ready. Simply reordering AX
   ahead of DOM while retaining the current all-work barrier does not help.
3. Keep or lazily obtain DOM/geometry for consumers that need it. Native stable
   frame projection currently also uses DOMSnapshot to prove frame coverage and
   exclusions; that dependency needs an AX-native equivalent before general
   open-web adoption. A cheap result must not imply unobserved frames were empty.
4. Profile and reduce index reconstruction/hash work, maintaining exact search,
   stable refs, ancestry, duplicate-label distinctions and acknowledged history.
5. Consider bounded parallel child-frame AX reads / overlapping visibility
   completion only after the above. Chromium still performs AX/layout work;
   concurrency is not evidence of lower latency. This experiment retains the
   original sequential all-frame extraction and visibility completion.

The AX-only code is a measurement prototype, not an installed fast mode or
permission to click from unvalidated snapshots. It omits human custody and
stable-frame projection wrappers. Required integration tests include navigation,
frame replacement/detach, stale/reused BIDs, consent overlays, nested frames,
mutation during decoding, pending policy acknowledgment, and exact output parity.
No new caller options, deployment or production readiness are claimed.
