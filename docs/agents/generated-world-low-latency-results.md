# Generated-world low-latency capture: implementation and scripted timings

Claude Code, 2026-10-14. Branch `claude/generated-world-low-latency-20261014`
(base `main` `cd96b17`): `3ec267b` (harness), `b5a9de6` (scripted tooling).
Goal: [goal brief](generated-world-low-latency-goal.md); plan and decisions:
[plan](generated-world-low-latency-plan.md). No model, provider or cloud calls;
every episode below is scripted (`metadata.tags` contains `scripted`) and
explicitly ungraded because task outcomes were not under test. Not yet reviewed
by Codex; not adopted by any suite caller.

## What changed

Runtime defaults v2 selects, for adapters that declare
`supports_agent_fast_capture`, a generated-world fast path
(`agent_budgeted_targeted`); see [runtime defaults](runtime-defaults.md#generated-world-agent-custody-v2).
In short: agent-only custody without new policy tools; the normal token-budgeted
AX overview built from one unmarked AX read; background full capture during
inference; targeted pre-action checks; deferred final post-action capture;
page-settle readiness instead of the fixed 0.5 s sleep; Playwright `slow_mo` 0;
lazy overview packing; fact recording bound to the background capture.

What the model sees is unchanged except for BID numbering and one or two empty
structural nodes per page that only BrowserGym's temporary marking made
visible. Delivered decision overviews were compared turn by turn with the
native run of the same journey: identical apart from BID numbers, ref offsets
caused by those nodes, and an occasional extra entry that fits because the BIDs
are shorter. Lazy packing gave byte-identical output to eager packing on 128
real-page cases (4 budgets, repeat on/off, continuation pages) plus synthetic
unit tests.

## Method

`scripts/generated_world_latency.py` runs the prepared B14 recipe (walking shoes,
two shops) with its frozen world code and this branch's `intent_browser` and
`training` packages, through `run_episode`, shared Chromium and (where noted)
the fact recording package. An offline journey backend waits a fixed simulated
inference time, then returns the next step of a 24-turn journey shaped after the
live B14 trajectory: 13 AX searches, 4 clicks, 3 gotos, select, back, a
fill+press batch and a final answer. `scripts/analyze_latency_trace.py`
reproduces the segments of the live B14 analysis from `events.jsonl` (it gives
the live trace's 6.94 s median gap). Local workstation (24 logical CPUs, WSL);
episodes ran under `scripts/run_bounded_job.py`. Sequential isolated runs
separate component timings from contention (the CLAUDE.md isolation exception);
four concurrent episodes approximate the live suite's concurrency. One episode
per cell: these are diagnostics, not a latency distribution.

Evidence: `.local/coordination/claude-generated-world-latency-20261014/`
(`isolated/`, `concurrent4/`, `matrix-summary.json` per folder,
`extraction-benchmark/`, `regressions/`).

## Results

Baseline = the live run's configuration: native capture, fact recording,
screenshots, synchronous recording, `slow_mo` 1000 ms, 0.5 s settle.
Fast = auto selection on this branch with fact recording. Medians in seconds.

| Run | Harness gap (response → next request) | Response → first tool | Decision observation | Click | Goto | Wait after inference |
|---|---:|---:|---:|---:|---:|---:|
| Live B14, Vast RTX PRO 6000, 114 turns | 6.94 | 2.10 | 1.94 | 4.57 (mean) | 3.96 (mean) | — |
| Baseline, isolated, 0 / 2 / 5 s inference | 3.42 / 3.34 / 3.41 | 0.83 / 0.81 / 0.86 | 0.77 / 0.76 / 0.75 | 2.13 / 2.14 / 2.15 | 2.89 / 2.85 / 2.88 | — |
| Fast, isolated, 0 / 2 / 5 s inference | 0.44 / 0.43 / 0.44 | 0.16 / 0.15 / 0.15 | 0.11 / 0.11 / 0.11 | 0.17 / 0.18 / 0.20 | 0.56 / 0.56 / 0.58 | 0.39 / 0.018 / 0.019 |
| Baseline, 4 concurrent, 2 s inference | 3.48–3.68 | 0.88–1.00 | 0.85–0.87 | 2.19–2.23 | 3.01–3.05 | — |
| Fast, 4 concurrent, 2 s inference | 0.46–0.49 | 0.16–0.20 | 0.12–0.13 | 0.19–0.24 | 0.73–0.77 | 0.018–0.019 |

Whole 24-turn episode at 2 s inference: 138.7 s baseline versus 65.8 s fast
(isolated). With zero inference the background capture cannot hide behind the
request (0.39 s wait), which is the expected floor.

Decomposition (isolated, 2 s inference, earlier runs on the same journey):
removing fact recording from the baseline alone cut the median gap from 3.14 s
to 1.05 s (decision capture 0.66 → 0.23 s). The native provider adds roughly
0.4 s of browser work per capture, at about 2.4 captures per turn. The fast path
without facts measured 0.39 s; with facts 0.40–0.44 s. The fact probe and join
now run inside the overlapped background capture.

Fast-path counts per 24-turn episode: 24 background captures overlapped all 24
requests; 12 targeted action checks; 10 deferred final post-action
observations; 12 readiness waits, all `ready` (median 0.04–0.05 s); zero
invalidated decisions; zero action errors in any run.

### Overview extraction benchmark (B14 pages, 406–2,608 raw AX nodes)

| Step | Today | Chosen |
|---|---:|---:|
| Tree fetch | native capture with screenshot 160–410 ms | unmarked raw AX 15–63 ms |
| 1,000-token overview processing | 15–96 ms (4,000 tokens: 128–205 ms) | lazy pack: same output, a few ms plus index build |
| BIDs | marking ~45–50 ms on every capture | known from prior DOM snapshot; first-seen overview candidates assigned (≤50 at 1,000 tokens) |
| Node-by-node `getChildAXNodes` | — | rejected: 125–135 ms |

## Fact recording

Same probe, now executed once inside the background capture's public revision
bracket and normalized against that capture's DOMSnapshot and AX tree (no render
attestations, `DOM.getDocument`, `describeNode` or second DOMSnapshot). On the
same journey the native and pipeline providers produced identical distinct
source sets (5, 31, 4 and 5 sources) with equal occurrence bindings, and the same
three delivered policy records carry fact projections. The decision overview is
staged against the decision AX read and re-bound to the validated background
capture before acknowledgment. Post-action transition renders that the fast
path defers are recorded as `post_action_capture_deferred`, not as missing
facts; none of them was delivered to the model.

## Validation

- 25 new unit tests (`tests/test_generated_world_fast_capture.py`).
- Focused existing suites: 206 passed; 5 failures in
  `tests/test_runtime_defaults.py` CLI cases fail identically on unmodified
  `main` (missing automatic-grading attachment), unrelated to this change.
- Real-browser regressions for the existing live-web fast path: targeted actions
  17/17 (explicit config) and 17/17 (runtime defaults); dynamic overlap 18/18.
  Both drivers needed the now-mandatory `allow_ungraded` escape and `scripted`
  tag to run on current `main`.

## Not done yet (adoption)

1. `scripts/comparison_suite.py` and the website_world case functions hard-code
   `observation_pipeline='native'`, force screenshots and synchronous recording,
   and use the native recording wrapper. They need the mode from the caller spec,
   `recording_runner(capture='pipeline')`, and a supported replacement for
   `watch_browser_steps`' instance `env.step` override.
2. Adapter declaration in current `main` (`NativeWorldTask`,
   `ComparisonSkuTask`). Prepared recipes pin generation sources, so this goes
   with new recipe preparation. The benchmark driver declares it on the frozen
   B14 adapter and records that it did.
3. Qwen backends: remove the page snapshot from the capacity/freshness path
   (agreed: never withhold a request; validate afterwards and tell the model),
   replace the hosted backend's SIGALRM watchdog with a thread-safe deadline, and
   declare background completion in a reviewed subclass.
4. Remaining harness costs on the critical path: about 23 custody/identity guard
   operations per turn (several open a fresh CDP session), the full AX index
   build (~33 ms on a 2,200-node page) and per-tool observation artifact writes.
5. Codex review, then integration by Harness; measurement on the rented-GPU host
   (the live host ran the same scripted actions about 1.6–2× slower than local).
