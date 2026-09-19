# Browser navigation and proposed helper agents

2026-09-19. Navigation is a local opt-in development capability, not deployed or
certified for existing benchmark adapters. Helpers are a **proposal only**.

## Implemented navigation

`native_tools_profile(navigation_origins=(origin_a, origin_b),
parallel_tool_calls=None, compact_feedback=True)` selects
`core-tools-v4-navigation`. It retains the existing native tools, append-only
conversation, reasoning preservation, feedback and independent final evaluation.
It adds `go_back()`, `go_forward()`, `reload()` and `goto(url)` as formal tools.
Back does not need an element ID and works from a Chromium navigation error page.
Reload can resubmit state; successful navigation does not establish authorization.

The trusted experiment configuration supplies exact HTTP(S) origins: scheme,
host and port. Paths may vary within an allowed origin. No subdomain wildcards,
URL credentials, relative URLs or file/javascript/data URLs are accepted by goto.
The configured origins appear in the tool description and trace metadata. Policy
text and a page cannot enlarge the list. Multi-site tasks can list multiple origins.
The CLI exposes `--harness-profile core-tools-v4-navigation` with repeatable
`--navigation-origin http://127.0.0.1:PORT`.

After trusted task reset and before the first model call, the runner validates the
starting origin and installs a Chromium document-navigation boundary. A CDP Fetch
request-stage check covers redirect hops, in addition to the Playwright route
check for initial link/navigation requests. Failed navigations are recorded and
produce ordinary action-error feedback; they are not automatically retried.
The runner installs the profile's BrowserGym action mapping so new tools really
execute through the same step/observation/evaluation lifecycle.

**Scope limits:** this is a single-tab, HTTP(S) document-navigation boundary for
controlled task sites, not a complete hostile-site network sandbox. Subresources,
fetch/XHR, WebSockets and server-side effects are not restricted by this boundary.
Trusted task reset happens before the guard. Existing active service workers are
rejected and guarded navigation bypasses service workers. Non-HTTP navigation
caused by arbitrary page code is not claimed covered by the HTTP interception.
New windows have their first navigation blocked and terminate the episode before
another policy request. They are not silently closed/replayed/re-targeted. A
separate tab-management capability and isolation review are required before
using this profile for tasks relying on new tabs or arbitrary real websites.
Existing site controls/assets are not removed. Do not claim the single-tab profile
supports every task on those sites.

Legacy/default tool catalogs and profile descriptions are unchanged. Existing
adapters must explicitly adopt the new profile and freeze new evidence; none was
silently certified. Historical requests, results and paid cohorts remain intact.

### Offline checks

```bash
.venv/bin/python -m unittest tests.test_navigation tests.test_native_tools tests.test_harness_profiles -q
.venv/bin/python scripts/verify_navigation.py --output NEW_DIRECTORY
```

The browser script creates separate loopback fixtures. It exercises native request
schemas through HTTPX MockTransport and real BrowserGym/Chromium: back/forward,
reload, two allowed sites, a two-hop off-origin redirect, a blocked link, recovery
from error pages, exact request retention, immutable conversation prefixes and
evaluation before close. A separate new-window case must stop with a technical
error and zero requests reaching the popup target. No model calls or shared
benchmark mutations. Evidence: `.local/preflight/navigation-v3/report.json`.
The initial v1 attempt is retained separately; its popup-closing callback caused
Playwright cleanup warnings. V2 stops unsupported new-tab episodes without closing
a page from its creation callback. V3 additionally retains the final transition
observation and completed-tool evidence before reporting that technical boundary.

See [timeout feedback and separately budgeted Books rerun](navigation-timeout-feedback.md) for the next local increment.

## Helper-agent design for discussion — not implemented

Current runtime metadata reports `subagents: disabled`. There is no spawn tool,
helper inference loop, helper context or helper browser. The coding assistants
working on this repository are separate from the browser agent under evaluation.

Previously agreed: keep no-helper as a configuration; use general-purpose helpers
with a parent-written task/system message and optional template; do not invent
specialist roles without a purpose-built model. Review real delegation traces
before expanding usage. Tools and context implementations stay composable.

User-confirmed direction (2026-09-19); implementation remains deferred:

- A helper always gets its own conversation. The parent writes its task and optional
  system instructions and chooses which public evidence to attach. Never attach
  hidden grader state, expected answers or credentials.
- The **main agent chooses whether a helper gets its own browser**, according to
  the work delegated. Parallel exploration of different parts of a site is a
  supported design requirement, not something to prohibit globally. Snapshot-only
  assistance remains an option rather than a mandatory first mode.
- Helpers **inherit the parent's effective tool registry by default, except tools
  that spawn further subagents**. Do not maintain a second hand-written tool list:
  future harness additions must inherit automatically. Capability exclusions may
  be configured later; tools requiring a browser need an explicit unavailable
  result when the parent selected a no-browser helper. Inheritance never expands
  the parent's authorization, origin boundary or budget.
- Distinct browsers can share backend/account state, just as ordinary human
  browsers do. Make that sharing visible to the parent and helper. Do not claim
  a new browser context clones the site's database/cart/bookings. Authentication
  and cookie initialization need an explicit per-session contract.
- Minimize races without serializing all browsing: exclusive ownership of each
  browser/page, fresh observations before acting, shared action/commit notices,
  and coordination for potentially conflicting writes. Generic tools cannot prove
  that arbitrary website actions touch disjoint resources. Any write lease or
  conflict mechanism must state its coverage, not promise transaction isolation.
  Parallel independent page reading should remain possible.
- Traces must be connected **and easy to inspect independently**. Every helper
  trace needs stable root/parent/child identifiers, delegated prompt, its own
  complete observation/action/request history and costs. The viewer should offer
  parent/child links and standalone replay; do not require reading the whole
  parent transcript to understand one helper. A parent summary is not a substitute
  for the child's full evidence.

Remaining proposed details for later implementation:

- Suggested configurable initial limits: two active helpers, four total launches,
  delegation depth one, per-helper steps/time, and a shared episode budget covering
  every parent/helper call. No nested delegation initially; keep all limits visible.
- A parent can collect or cancel a helper. Cancellation prevents new actions but
  cannot undo one already sent. Retain late response/cost evidence. A helper returns
  findings with evidence references, uncertainty and any actions it performed;
  the parent must refresh the page before acting on old element IDs.
- Store a linked child trace with exact tool catalog, prompt, supplied evidence,
  requests, responses, usage and actions. Append a concise returned result to the
  parent's history rather than copying the entire child conversation. Preserve
  reasoning inside each conversation using the selected replay policy.
- Final grading covers the whole episode, including helper side effects. A helper
  saying it succeeded is not verifier evidence. Helper usefulness is an evaluation
  question, not an assumed improvement.

Numerical limits and exact race-control protocol remain proposals. Parent-selected
browser ownership, inherited tools except spawning, parallel browsing, and linked
yet independently viewable traces are user requirements. Do not implement helpers
as part of the navigation-feedback increment.
