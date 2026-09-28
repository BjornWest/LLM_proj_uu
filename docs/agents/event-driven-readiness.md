# Event-driven readiness and application lifecycle signals

2026-09-26. Implemented as an **opt-in core helper**, `intent_browser/readiness.py`.
The standard runner, BrowserGym's default 500 ms delay, generated-world source,
and deployed application have **not** been changed. This is tested infrastructure
for replacing that delay, not a deployed rollout or a whole-suite certification.

Evidence: `.local/readiness-v4/`; reusable browser driver:
`experiments/readiness/run.py`. No model calls, cloud charges or shared-site changes.

## Contract

Arm a watcher **before** dispatching one action. It can observe:

- A public DOM condition: exact text, checked state, attribute value or match count
  inside an explicitly selected region. Conditions describe the requested public UI
  state, never a hidden expected answer or grader predicate.
- An optional application operation scope: `begin` before debounce/request/work,
  `end` after the UI update, or `end(..., false)` when the operation failed.
- Both, in which case **both must be satisfied**. A premature application signal
  cannot override an unmet public condition.

Completion additionally requires no `aria-busy=true` in the selected region or
its ancestors and two animation-frame callbacks followed by rechecking conditions.
This is an opportunity for rendering, not proof that every asset has painted or
that future asynchronous changes are impossible. Multiple matching operations
must all finish. Already-pending matching operations are included when arming.
Unrelated operation scopes and DOM activity outside the selected region do not
prevent completion.

The result has one of these statuses:

| Status | Meaning |
|---|---|
| `ready` | The selected completion contract was met at observation time. |
| `pending` | Deadline reached with a tracked operation or busy UI still pending. |
| `unknown` | No sufficient contract/evidence, lost scope, new document, unsupported frame or interrupted observation. |
| `failed` | A matching application operation explicitly reported failure. |
| `cancelled` | The observation wait was explicitly cancelled/closed. |

Every result leaves `task_success: null`. Readiness is neither a success grader
nor evidence that a click caused a requested transaction. An initially satisfied
public condition is recorded as such; it is not proof of action effect.

With **neither condition nor application signal**, a scoped quiet interval returns
`unknown`, not `ready`. The default experimental quiet interval is 50 ms; it is a
bounded observation opportunity, not a disguised reliability promise. When an
explicit application signal is expected but missing, quietness does not substitute
for it. The wait ends unknown at its deadline.

## Application integration

A generated site's frontend can optionally wrap the shared request/render helper:

```javascript
async function updateCart() {
  const lifecycle = globalThis.__intentReadinessV1?.app;
  // Start BEFORE any debounce timer or request. No task IDs, rewards or expected
  // answers belong here: this just identifies an ordinary UI operation.
  const operation = lifecycle?.begin('cart');
  try {
    const response = await fetch('/cart', {method: 'POST', body: cartPayload()});
    if (!response.ok) throw new Error('Cart request failed');
    renderCart(await response.json());
    lifecycle?.end(operation); // after application state AND its DOM update
  } catch (error) {
    renderCartError(error);
    lifecycle?.end(operation, false);
    throw error;
  }
}
```

If the framework schedules rendering asynchronously, await that rendering step
before ending. Keep a debounced operation pending across the delay, not merely
across the eventual HTTP request. Handle every error/cancellation path so operations
do not remain pending indefinitely. A cancelled/superseded operation can be reported
as failed (`end(id, false)`); there is no implicit request cancellation, replay or
successful-cancellation inference in this API.

The optional global API adds no DOM/AX controls or visible wrapper. Without
instrumentation, ordinary site behavior still runs through optional chaining.
Signals are only as accurate as the implementation supplying them; pair them with
a public condition where useful. They are a scheduling aid, not a model-only oracle.
The current generated-world sources are deliberately untouched while their own
implementation evolves; this contract can be added to their common frontend helper.

Host-side usage:

```python
from intent_browser.readiness import Readiness, ReadinessSpec

readiness = Readiness(page)  # can install before initial navigation
result = readiness.perform(
    lambda: page.get_by_role('button', name='Add to cart').click(),
    ReadinessSpec(scope='#cart-region', signal_scope='cart', timeout_ms=2000),
)
# Decide how to proceed using result['readiness']['status']; never treat
# pending/unknown as success, and never automatically repeat the click.
```

For uninstrumented sites, supply a public condition instead:

```python
ReadinessSpec(
    scope='#preferences',
    condition={'kind': 'checked', 'selector': '#marketing', 'expected': False},
)
```

Conditions must be selected from intended public behavior, not privileged verifier
knowledge. `text` means trimmed DOM text; `count` counts DOM matches, including hidden
matches. These conditions do not replace Playwright visibility/actionability checks.
The API does not infer transaction success or guess which arbitrary page element
should change after a generic click.

## Implementation and cleanup

MutationObserver, input/change listeners, application lifecycle notifications and
two render-frame callbacks wake the waiter. It does not repeatedly capture AX/DOM,
intercept fetch, patch application timers, wait for all network traffic to disappear,
or run a short-interval polling loop. It inspects the chosen region on notifications.
High mutation volume can still cost CPU; no large-concurrency throughput claim is made.

All API use stays on the owning Playwright thread. Installation also supports plain
HTTP benchmark origins and about:blank: IDs use `crypto.getRandomValues`, not the
secure-context-only `crypto.randomUUID`. Tickets are document-bound. Navigation
returns unknown rather than carrying an old completion signal into the next page.
A caller should establish the new document and await its relevant public condition
without replaying the original navigation/action.

The action runs exactly once. Native errors propagate after cancelling its wait.
Timeout cancels observation subscriptions, **not** the underlying website request;
that operation may still finish later. Listener/frame/timer cleanup is tested.
There is a 16-waiter bound and a 1,024-pending-operation bound per document to expose
leaking lifecycle instrumentation rather than growing without limit.

The readiness deadline starts after the native action returns; its time is separate
from the Playwright action timeout. Browser-level `elapsed_ms` includes time since
arming; Python `wait_seconds` measures the wait call only. This JS deadline cannot
interrupt a frozen renderer/main thread: keep an outer episode/process watchdog.
The experiment has a 180-second process-group deadline and retains failure logs.

## Validation

Two independent Chromium suites run in parallel. The final source is frozen and
hashed into the output directory. Each suite covers immediate controls, fast and
slow local HTTP responses, debounce-before-request, irrelevant continuous activity,
nested and pre-existing operations, early completion signals, request errors,
missing signals, timeout with eventual single completion, navigation, cleanup,
invalid config, lost scopes, frames appearing before/during a wait, public attribute
and count conditions, insecure origins and pre-navigation installation.

Latency comparison runs separately in isolation, alternating the order of fixed
500 ms and event-driven waits, with three samples per condition/mode. Both modes
use the same fixture and Chromium; the fixed mode waits 500 ms **without** checking
completion. An independent fixture state read records whether the update actually
finished at observation time. No model or inference delay is involved.

This compares waiting policies, not full BrowserGym step time. No AX extraction,
screenshot, recording, verifier or background-prefetch work is included. Current
results are available in `performance/result.json` and the local report. Earlier
v1–v3 artifacts are retained as earlier source versions, not pooled into the final
acceptance. In particular, v2 corrected a fixture reference to `window.status`
so the scoped continuous-activity test really mutates the page.

## Measured result

Final acceptance: **72 boundary assertions** across two fresh suites, plus 15
completion assertions across **30 timed trials**. All pass; source closure matches.
Median extra wait after the native action, three trials per mode/scenario:

| Scenario | Fixed wait | Event-driven wait | Update complete when fixed / event observation returned |
|---|---:|---:|---:|
| Immediate checkbox | 501 ms | 29 ms | 3/3 / 3/3 |
| 80 ms HTTP response | 501 ms | 96 ms | 3/3 / 3/3 |
| 850 ms HTTP response | 501 ms | 862 ms | 0/3 / 3/3 |
| 650 ms debounce + 80 ms request | 501 ms | 746 ms | 0/3 / 3/3 |
| 80 ms response with unrelated continuous mutations | 501 ms | 112 ms | 3/3 / 3/3 |

The adaptive path is faster on fast updates and deliberately slower on slow ones,
because the fixed wait observes incomplete state in those cases. These fixture
results do not establish general reliability on all websites.

## Adoption boundary

The normal BrowserGym environment currently waits/captures internally, so calling
this helper **after `env.step()`** would be too late to improve that observation.
It must run after native action execution and before readiness-dependent capture
or final grading, with the fixed delay explicitly disabled in that new profile.
The browser-owning thread used by the shallow/background-AX prototype is a suitable
integration point, but that combined path has not been wired or certified here.

Before changing defaults, validate that combined ordering, event-feedback retention,
navigation/popup/frame handling, final grading and real generated-world operations.
Observe snapshot invalidation while asynchronous work is pending. The current
prototype rejects multiple frames rather than silently claiming whole-page readiness.
CSS-only/property-only changes without relevant events may not wake a condition
waiter; an application signal or further observation is needed. Background tabs may
throttle render callbacks. Timeouts remain visible rather than becoming hidden waits
or mutating action retries.

## Reproduce

```bash
.venv/bin/python experiments/readiness/run.py --output .local/readiness-NEW
```

The output must not exist. The script freezes its helper/fixture driver, starts
fresh local HTTP servers and browsers, runs parallel correctness then isolated
latency comparisons, and verifies source closure. No environment credentials or
external services are used; the insecure-origin test is fulfilled inside Playwright.
