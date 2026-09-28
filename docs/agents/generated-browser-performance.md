# Generated-world browser performance and runtime boundary

2026-09-25. Local scripted profiling only: no model calls, purchases, GPU work,
production deployment or shared runtime changes. Source was copied before testing;
the generator remained free to change independently.

## Current architecture and RL readiness

The execution chain is **training callback → our `run_episode` harness →
BrowserGym `BrowserEnv` → Playwright → Chromium → website**. BrowserGym does not
wrap the model/harness. It implements the browser environment the harness calls.
`reset`, `step` and `close` are outer entry points, but our runner also uses
`env.unwrapped.page`, context/action mapping and the version-pinned private
`_get_obs()` refresh. BrowserGym supplies DOM/AX extraction, BIDs, action helpers,
active-page handling, task lifecycle, screenshots and observation fields.

The generated commerce runtime is independently usable with Playwright already:
`environments/procedural_commerce/runtime.py` has no BrowserGym dependency. One
`Runtime` deep-copies its world, creates an in-memory `CommerceSession`, binds
four local HTTP origins (aggregator and three retailers), and starts four server
threads. There is no database/container per episode. Private state and evaluation
stay accessible to trusted Python callers, not through the public website routes.
Individual requests construct detached views and rendering context; profiling of
larger catalogs may later justify immutable public-view caching.

The inspected native training bridge is **not yet a generated-world integration**:
`training/browser_training/project_harness.py:ProjectFactory.create` only admits
P11-clean, and `training/scripts/project_browser_worker.py` selects that task and
an older explicit harness profile. It launches a Python subprocess with a frozen
source/site closure, passes model requests through a socket to the training
callback, and receives raw model responses. This machinery can be reused, but
pointing it at generated worlds requires a task/session factory and reward mapping.

An immediate integration would freeze world + task + renderer/harness revisions,
give every sibling its own Runtime and browser context, publish only the trusted
goal and ordinary page observations to the policy, and evaluate that sibling's
private snapshot at termination. Existing commerce `generate_task`/`evaluate`
support compare/prepare/purchase contracts. This does not qualify every newer
product/task-intent branch or prove that all generated tasks are feasible.

## Method and provenance

Reproducer: `scripts/profile_generated_browser.py`; requires existing local
BrowserGym/Chromium/tokenizer and `psutil` (7.2.2 installed for measurement).

Primary evidence: `.local/generated-browser-profile-v3/`. Additional dense
concurrency: `.local/generated-browser-dense-concurrency-v1/`.
Their manifests retain source and installed BrowserGym hashes, tokenizer hash,
profiler copy/hash and machine configuration. BrowserGym 0.14.3, Playwright 1.44.0,
24 logical CPU threads, approximately 25 GiB WSL RAM. Source snapshots were
unchanged across cases. Closure reports list the deliberately synthesized empty
`environments/__init__.py` as different from the checkout; this is an import-package
marker, not a changed renderer. No original source files were patched for timing.

Instrumentation wraps extraction functions **inside each diagnostic process only**.
Each episode has a fresh world and BrowserGym-owned Chromium. Tests use seed 7,
headless mode, 1280×900, `slow_mo=0`, no video, real BrowserGym step/capture, our
AXContext and Trace writers. Three no-op steps isolate extraction overhead; two
actual navigations visit the product and cart pages. All final world snapshots
equal their initial snapshots and all final-suite action errors are empty.
The native action parser is bypassed only for these trusted fixed Python scripts.
No agent task success is asserted or inferred from these diagnostics.

The scale comparison uses the current dense storefront with small/large catalogs.
The separate stress fixtures append 500 or 2,000 synthetic article/heading/text/
button groups to the rendered page. These are explicitly **not extra generated
products**. They measure a controlled broad-tree shape; other depths, frames,
styles, asynchronous mutations and actual purchase interactions need further cases.
Stress content disappears on the two subsequent navigations, whose timings are
kept separate from stationary dense-page timings.

The measured cycle comprises step (including observation), transition rendering
and recording, a fresh decision observation, decision presentation and recording.
This reproduces that capture/presentation pattern, not the complete run_episode
model loop: inference, request construction, full feedback tools and grader costs
are excluded. Three repetitions per isolated case, two per dense-concurrency case;
this is a short diagnostic, not a throughput SLA or tail-latency certification.

## Measurements

Median stationary timings, seconds:

| Page | Raw AX nodes | Fixed wait | Step including capture | Decision refresh | Both trace writes | Measured cycle |
|---|---:|---:|---:|---:|---:|---:|
| Current small | 719 | .5 | .697 | .196 | .104 | 1.017 |
| Current large | 1,125 | .5 | .748 | .215 | .152 | 1.152 |
| Current large | 1,125 | 0 | .250 | .218 | .146 | .634 |
| +500 synthetic cards | 6,126 | 0 | .732 | .697 | .570 | 2.275 |
| +2,000 synthetic cards | 21,126 | 0 | 3.098 | 3.136 | 1.992 | 8.914 |

Component medians need not sum to the median of complete cycles. Raw AX node
counts are structural measurements, **not context token counts**. The automatic
overview remained capped at 1,000 Qwen-tokenizer tokens; full capture still grows.

On the 21,126-node stress page, per-capture frame marking took about .107 s,
DOM extraction .836 s, AX extraction 2.017 s and screenshot capture .083 s.
There is only one frame: this is distinct from the historical cumulative
IntersectionObserver timeout. These phase times include transport/Python processing,
not just work inside Chromium. A separate cProfile diagnostic is retained to
investigate that distinction; its overhead must not enter this timing table.

The separate CPU diagnostic (`dense-cpu.prof`) identifies millions of calls in
Playwright's recursive `from_maybe_impl` and `_replace_guids_with_channels` walkers,
as well as Python JSON streaming. Greenlet/event-loop profiling attribution and
profiler overhead mean its cumulative timings are not a browser-versus-Python
percentage breakdown. It does establish concrete Python work worth investigating;
the AX phase cannot be described simply as page rendering time.

A follow-up **serialization-only** alternating experiment on one retained 12.88 MB
raw observation took .844–.845 s with `json.dump` streaming small chunks into gzip,
versus .354–.355 s serializing once and writing the resulting string. All four
outputs have exactly identical decompressed bytes and equal compressed size
(743,649 bytes). Gzip file hashes differ as expected from header timestamps/names.
Evidence: `serialization-diagnostic/report.json`. This preserves information but
adds a temporary full JSON string allocation. It is a candidate, not a change to
the production writer or a complete-pipeline speedup measurement.

World startup took .014 s (small) and .032 s (large); initial browser reset,
including navigation/capture, approximately .66–.68 s for these two fixtures.
Removing the fixed wait saved approximately its configured duration in this
read-only test. This is **not** acceptance for universally removing readiness
waiting on asynchronous sites.

Parallel fresh episodes, separate processes/worlds, zero configured wait:

| Page | Sessions | Wave wall time | Short scripted episodes/minute |
|---|---:|---:|---:|
| Current large | 1 | 3.97 s | 15.1 |
| Current large | 2 | 4.02 s | 29.8 |
| Current large | 4 | 4.38 s | 54.9 |
| Current large | 8 | 4.78 s | 100.4 |
| 21k-node stress | 1 | 22.21 s | 2.70 |
| 21k-node stress | 2 | 23.57 s | 5.09 |
| 21k-node stress | 4 | 25.27 s | 9.50 |

These rates include process startup and cleanup and concern tiny scripted episodes,
not model rollouts. The two page groups use different repetition counts; compare
scaling **within**, not between, the groups. No additional swap-out was observed
within sampled waves. Four dense sessions achieved about 3.5× single-session
throughput, with individual steps getting slower. Eight ordinary-page sessions
achieved about 6.6×. This does not determine the optimal RL concurrency, since
inference duration, GPU memory pressure and longer-lived histories are absent.
Summed child RSS reached 9.78 GiB for eight ordinary sessions, but double-counts
shared memory; minimum whole-host available RAM was still 12.17 GiB. Do not use
summed RSS as unique physical memory per episode. Other workstation activity was
not stopped or isolated.

Two unsuccessful profiler startups are retained: v1 lacked psutil, v2 sent `pass`
through BrowserGym's default high-level parser and correctly failed the zero-error
gate. v3 explicitly maps trusted diagnostic Python directly; all 20 cases passed.
The seven additional dense-concurrency cases passed as well. They are not task
rewards or production certificates.

## Changes worth prioritizing

1. **One deliberate full capture boundary per decision**, with lightweight action
   evidence between calls. Preserve capture-after-pacing, fresh state after any
   intervening mutation, immediate error/event capture and final private grading.
   Do not reuse a pre-inference observation blindly after a slow request.
2. **An explicit rollout recording mode.** Keep exact policy inputs, responses,
   tool results and outcomes; make duplicate full raw snapshots and automatic
   screenshots configurable. Requested images stay current and available. Buffered
   recording needs a bounded queue/backpressure, not unlimited RAM growth. No
   existing recording default was changed in this investigation.
3. **Measure AX/DOM transport before rewriting extraction.** A small policy
   overview currently still entails full local extraction/indexing. Lazy CDP
   traversal or delta capture is a larger semantic change: search completeness,
   role/name changes, frames, layout and stale handles need parity tests. DOM
   MutationObserver alone does not cover every relevant browser/AX state change.
4. **Use explicit training delay settings** with event/readiness acceptance. Keep
   actionability checks and bounded late updates; avoid hardcoded sleeps intended
   for human viewing. The current profile deliberately used zero slow_mo.
5. **Reuse foundational resources after measuring their marginal cost.** Share a
   browser-process pool with fresh contexts, immutable assets/catalog templates,
   tokenizer instances and code imports. Context isolation does not isolate server
   state. Keep mutable inventory/carts/orders per rollout, and groups reproducibly
   initialized. Browser pools have shared crash/resource domains; do not put an
   unlimited number of contexts in a single browser. No pooled-browser speed or
   memory improvement was measured here.

Four HTTP listeners per world are currently cheap and preserve genuine distinct
origins. Later multiplexing can share event loops/listeners but must preserve site
origin/storage semantics and isolate world identities. Path prefixes alone are not
a replacement for browser contexts or server state isolation. Do not route through
Vercel/tunnels for local or GPU-hosted rollouts; co-locate this runtime with browser
workers, with private grading alongside it.

## Detaching from BrowserGym

A direct Playwright deployment is feasible but not currently a drop-in switch.
The useful reusable boundary is our public browser observation/action interface,
with task reset/reward handling outside it. Keep the same tool schemas, BIDs/live
handles, AX hierarchy/search, feedback, tab/navigation behavior and image semantics
in training and deployment. BrowserGym components can remain dependencies while
the Gym lifecycle becomes optional. Existing open-internet mode already works
through BrowserGym without benchmark scoring.

Replacing `BrowserEnv` alone while copying its full extraction/recording pipeline
would retain most measured costs. Prototype one shared optimized browser adapter,
test against BrowserGym, and only then choose whether to retain a thin Gym wrapper
for RL. A separate demo-only observation implementation risks training/deployment
drift for little demonstrated performance benefit.

## Reproduce

```bash
.venv/bin/python scripts/profile_generated_browser.py \
  --output .local/generated-browser-profile-NEW

.venv/bin/python scripts/profile_generated_browser.py \
  --source .local/generated-browser-profile-v3/source \
  --output .local/generated-browser-dense-NEW \
  --skip-isolated --concurrency 1 2 4 --concurrency-extra-cards 2000 --repeats 2
```

Outputs must not exist. Initial latency comparisons run serially to avoid resource
competition; concurrency waves intentionally run independent cases in parallel.
The profiler refuses new waves below its conservative available-memory check.
