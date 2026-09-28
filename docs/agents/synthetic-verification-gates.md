# Synthetic verification gates

Status: opt-in offline simulation implemented and scripted-tested, 2026-09-27.
Existing real-web trials and frozen worlds remain unchanged. Official Turnstile
widget integration and a user-LLM completion tool are not implemented.

## Purpose and Cloudflare reference

Train detection, clear requests for assistance, custody transfer and resumption
after a user finishes verification. The simulated user may be an LLM with a
narrow tool for completing a gate in our own environment.

Cloudflare provides Turnstile test sitekeys for predictable pass/fail outcomes,
including a visible forced-interaction test. Test keys work on localhost and
produce dummy tokens; testing requires matching test validation credentials.
These test widgets do not reproduce every production interstitial challenge or
its anti-bot decisions. See the official
[testing documentation](https://developers.cloudflare.com/turnstile/troubleshooting/testing/)
and [Turnstile overview](https://developers.cloudflare.com/turnstile/).

Use the official widget as an optional integration/reference check. For scalable,
offline world generation, prefer an explicitly simulated local verification
component with comparable visible/AX states, independent of Cloudflare network
availability. Record which implementation a world uses; neither is evidence that
the agent can solve or bypass production verification.

## Proposed contract

- Sample gate presence, trigger route/action, display design, delay and clearance
  scope independently where appropriate. Support page-entry interstitials and
  embedded gates, with versions pinned in the world manifest.
- Runtime owns pending/active/completed/cancelled/expired state, bound to episode,
  site, session and a particular challenge instance. Clearance permits site
  access only; it does not authorize purchases, consent or account changes.
- Agent requests help through the same handover interface used with a human.
  The simulated user receives the request and relevant visible challenge context,
  not hidden task answers or grader state.
- Only the simulated-user execution channel receives a proposed
  `complete_verification(challenge_id)` capability. It cannot target another
  episode or grant arbitrary clearance. The browser-agent tool set must not
  expose this capability, nor may a click/hidden field/direct URL bypass the gate.
- Deterministic runtime validates the call and changes gate state. An LLM decides
  how to respond as the user; its prose does not itself establish completion.
  Include unavailable/declined/cancelled user responses where sampled.
- Pause agent inference during a wait-mode handover. Return control explicitly;
  the agent gets a fresh observation and must not assume that a user reply or
  Finished signal necessarily removed the gate. Keep concurrent-tab behavior a
  separately selected mode.

## Outcomes and diagnostics

Grade the original task and its authorization constraints. Track encounter,
request, user action, clearance, return, fresh capture and resumption separately
as procedural diagnostics, with event IDs and timestamps. Do not automatically
reward requesting help or penalize alternative valid routes. Any dedicated
handover-contract task must declare its outcome requirements explicitly.

Test representative designs against one shared gate state machine: correct and
wrong challenge IDs, duplicate completion, expiry, cancellation, cross-session
isolation, reset, route enforcement, blocked direct agent completion, pending
gate after a misleading user reply, and exactly-once action resumption. Provide
a scripted user first for reproducible acceptance; add the user LLM without
changing clearance semantics. Avoid requiring a full seed × layout test matrix.

Ownership at implementation: coordinate generator parameters with Product and
the user-simulator/custody interface with Backend; Curation owns page binding
and evidence review. No ownership transfer or shared-runtime edits in this note.

## Implemented MVP and use

`environments/site_verification/` owns the bounded sampler and thread-safe runtime.
Connected shopping accepts `verification=sample(comparator_ids, seed=..., probability=...)`.
The publisher exposes `--verification-probability` and `--verification-seed`; omitting
these preserves the existing runtime. Its saved `verification.private.json` and
provenance hash pin the sampled settings. Sampling is independent per site ID:
adding/reordering comparator sites does not resample existing ones. Defaults are
25% presence in the sampler, two designs (interstitial/embedded), and entry versus
discovery activation. Publication remains disabled unless explicitly selected.
Retailers, review sites and the search index never receive this comparator sidecar.

Example additive options on the usual new-world publication command:

```sh
.venv/bin/python -m environments.connected_shopping --pin PIN_DIRECTORY \
  --comparison-coverage COVERAGE_JSON --comparison-profiles PROFILES_JSON \
  --verification-probability 0.35 --verification-seed 9 --output NEW_DIRECTORY
```

A discovery gate permits the landing page until a deeper route is visited. Once
active it covers the whole site, including the home page and POST routes. A page
entry gate covers every content route immediately. It returns HTTP 403 without
invoking the underlying page renderer: no hidden product payload leaks beneath
the panel. Existing consent static assets can still load; consent mutations are
blocked while verification is pending. Runtime-scoped HttpOnly cookies isolate
site/browser sessions even when different local sites share the same hostname.

The trusted integration obtains the pending `(session_id, challenge_id)` from
`Runtime.verification_gates[site_id].snapshot()`, then calls `resolve(...)` on
that particular object. This **must remain outside the policy toolset and HTTP
routes**. A future simulated-user host must bind that handle to its active episode
and user handover, and expose only the selected challenge to the user responder.
There is no agent-accessible complete endpoint, no clickable bypass and no user
LLM yet. The rendered status link simply reloads the exact URL, preserving query
parameters. A user reply or repeated status check alone changes nothing.

Clearance is per browser session/site/runtime; duplicate completion is idempotent,
expiry and reset invalidate it, and cancellation permits a new challenge on the
next request. A newly constructed runtime supplies a new episode boundary. A host
that reuses runtimes must reset its gates as well as its other session state.
The current immutable challenge/clearance TTLs are configurable seconds; no
artificial delay, retry frequency or probabilistic bot score is implemented.

Private journals record server challenge creation, served gates, user completion,
expiry/cancellation/reset. A served gate is **not** evidence the model received
its text, requested help, or acted correctly. The harness must establish those
from exact delivered observations and tool records. Outcome graders are unchanged.

## Acceptance

```sh
.venv/bin/python -m pytest environments/site_verification/test_verification.py -q
.venv/bin/python -m scripts.verify_synthetic_verification --output NEW_EVIDENCE_DIRECTORY
```

Nine unit/HTTP checks cover seeded independence, gate lifecycles, simultaneous
completion, absent/incorrect/cross-session capability, direct-route enforcement,
default behavior and separate consent cookies. Four isolated native Chromium
cases run with bounded concurrency (both styles × triggers), capture blocked and
resumed AX/screenshots, preserve the requested URL, and reject a fresh second
browser session. AX captures here are Chromium full AX, not claims about exact
harness policy delivery. Current evidence: `.local/synthetic-verification-v2/report.json`.
A separate 14-site connected laptop world checks three comparators gated and all
11 other sites accessible: `.local/synthetic-verification-world-v1.json`.
No model/API calls, external widget calls, deployed changes, or old-world resets.


Additional two-tab acceptance: `.local/synthetic-verification-concurrency-v1/report.json`.
A trusted scripted completion while the second tab retains typed retailer content
leaves both tabs untouched until the blocked tab reloads; that reload reveals the
comparator, and reset blocks it again. This checks native browser/session behavior,
not the harness custody or user-LLM integration. No public-web/model calls.


BrowserGym presentation acceptance: `.local/synthetic-verification-ax-v2/report.json`
uses the frozen trial-1 AX projection source with two local scripted cases. The
interstitial has 10 nonverbose semantic nodes (349 Qwen tokenizer tokens for the
full reconstructed projection); embedded has 16 nodes (546 tokens). These are
projection-text tokens, not complete request sizes. Both block product facts and
reveal them only after trusted clearance plus reload. Earlier AX-v1 read the same
AX hash from the shared checkout; v2 explicitly imports the frozen package.
Existing consent/comparator regressions: 26 checks pass. Full handoff:
`.local/coordination/synthetic-comparator-verification/handoff.md`.
