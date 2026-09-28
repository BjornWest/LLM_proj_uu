# Isolated dynamic-page overlap prototype

2026-09-27. This is an offline feasibility experiment, **not** the deployed or
shared runner. The active Windows v4 run was neither restarted nor hotpatched.

Location: `.local/open-web-overlap-v1/`. `source/intent_browser/` contains a copied
harness plus experimental `dynamic_preview_experiment.py`; verification imports
that directory explicitly. `baseline-source.json` records the original copy;
`acceptance.json` records the final experimental source and 90 artifact hashes.
Main-checkout runner/pipeline/HumanBrowser remain unchanged by this increment.

## Behavior tested

- Fresh, depth-limited main-document CDP AX preview, without native marking,
  DOMSnapshot, screenshot or geometry. Delivered preview explicitly says partial;
  child-frame contents are unknown. It provides orientation, not clickable BIDs.
- Simulated model I/O in a worker thread while ordinary full HumanBrowser capture
  stays on the browser owner thread. No concurrent Playwright use across threads.
- Wait for whichever finishes last; retain the mock response even if capture
  fails, and retain capture evidence if the backend fails.
- Validate main document/custody before and after capture/completion, and compare
  each delivered preview node's projected semantic values against the main-frame
  full capture. This is not a general proof of whole-page atomicity.
- A full fresh guard still checks mutations after the overlapped capture. The
  late-change test deliberately demonstrates why this remains necessary.

Preview normalization excludes ignored containers: native BrowserGym marking can
promote those to generic AX nodes, even on an unchanged page. Main-frame namespace
and semantic role are also required when matching backend DOM IDs: InlineTextBox
and StaticText records can share the same DOM ID. Earlier failed probes remain in
`results/overlap-{100,101,102}`; they are not passed cases or source-site defects.

Nine final functional cases passed with at most two parallel browser sessions:
sequential/overlap controls, fast model, preview text change, main-document change,
human ownership change, capture failure, late content change, and backend failure.
For late change the historical snapshot is retained, but the fresh dispatch guard
rejects the stale action state. No actions are automatically replayed.

## Loaded-page timing sample

One fresh sequential/overlap pair on the same 3,000-product fixture (21,040 full AX
nodes, three cross-origin child frames). The timing pair ran sequentially to reduce
contention between measurements; the user's separate active run still shared the
workstation. These are samples, not a throughput benchmark.

| Phase / interval | Sequential | Overlapped |
| --- | ---: | ---: |
| Initial preview | 0.354 s | 0.327 s |
| Full native capture | 3.031 s | 2.971 s |
| Simulated model completion | 0.700 s | 0.700 s |
| Model starts, measured from preview start | 3.385 s | 0.327 s |
| Both complete and snapshot validated, from preview start | 4.119 s | 3.333 s |

Both modes receive the same 1,937-token preview content using the local Qwen3.8
tokenizer (serialized content only, not complete requests). That is an experimental
preview format, not a new production context budget. Full native capture continues
to include DOM and screenshots; nothing is falsely reported as complete in preview.

These timings **exclude BrowserGym reset/setup**, which still performs its native
initial capture. They also exclude a subsequent full mutation-dispatch guard. This
isolates scheduling feasibility rather than claiming the complete episode now
starts in 0.327 s or that real model decoding takes 0.700 s. The short mock finishes
before large capture, so the barrier correctly waits rather than dispatching early.

## Before adoption

Keep current real runs on their frozen validated runtime. Production integration
still needs an explicit profile/capability gate, runner pending/full-observation
lifecycle, partial AX presentation/reference behavior and exact request/response
logging through the real backend. Snapshot-only query behavior and fresh guards
must be distinguished; no general mutation-detection replacement is implemented.
The experiment does not qualify Windows CDP cross-origin completeness, every real
website, arbitrary popups, preview hierarchy tooling, or actual Qwen performance.

Reproduction (uses installed dependencies and local fixtures only):

```bash
PYTHONPATH= LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python .local/open-web-overlap-v1/verify.py \
  --case overlap --products 3000 --tag=-new
```

Outputs are exclusive per case/tag; use a new tag and never overwrite old evidence.
No paid model request, external website or current browser session was used.
