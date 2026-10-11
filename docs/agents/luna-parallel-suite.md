# Luna34 parallel evaluation

Evaluation owns `scripts/luna_suite.py`. It consumes the exact finite request in
`.local/coordination/luna34-parallel-20261011/request-v1.json`; this is not an
open-ended model runner. No task authoring, world draw or model retry is included.

Each of the 34 cases retains its accepted recipe, source root, native reference,
public request, memories and scope. Nine configurable instances use their original
family acceptance roots, not a subsequently merged producer root. Project imports
use a restricted raw-source loader: historical bytecode is ignored and preserved.
The shared bridge is a separately pinned dependency under `_luna_transport`, so
its approved concurrency code does not replace the recipe's native source files.

Harness owns the bridge release. An explicit `EpisodeConcurrency`/`SuiteEpisode`
admission covers one policy session plus at most one formatter session per case.
Session IDs, replay, request directories and caches remain separate. A canonical
global subscription lock participates across builds; arbitrary private lock paths
must not bypass it. Instantiate the quota guard from this same frozen namespace.
The pool serializes fresh quota admission, not inference. Both window fields must be reported; explicit null means no applicable window.
Every non-null window must have more than 1% remaining. Missing or conflicting
views, malformed windows and both-null responses hold dispatch. The strict shared
normalizer also requires explicit ordinaryUsageAllowed=true, a known included-usage
plan and the required legacy view; a reported individual limit must clear the floor.
In-flight usage cannot be reserved exactly; no claim
of a provider-side reserve is made. There is no credit or API fallback.

The policy uses GPT-6 Luna, medium effort, 200 steps, and a 120,000-token estimated
complete-next-request boundary. The Qwen local counter plus opaque-reasoning usage
receipts is explicitly an estimate, not a Luna tokenizer. Provider input, output
and cached tokens remain separate evidence. One optional native-answer formatter
uses the same Luna model with low effort. The 180-second provider watchdog and
10,800-second authorized episode lifetime are retained, with zero retries.
The HTTP client allows admission, provider time and failed-request cleanup
(3,680 seconds at concurrency 34; minimum 1,960 without the cleanup allowance).
Quota queue time is separate from provider time; an HTTP disconnect does not cancel
a queued dispatch. The independent whole-case watchdog terminates its process tree.

Before dispatch, the supervisor registers all new run roots in the existing
viewer registry under a file lock and preserves all older roots and grade entries.
The existing native consumer attaches `AutomaticGrading`; the wrapper rejects a
missing contract or changed prose before model use. Policy cleanup precedes the
consumer's native grading. Canonical, sidecar and actual current HTTP projection
must agree before a successful terminal notification. Infrastructure and task
verdicts are distinct; null broad-effect authority stays unknown.

The supervisor starts all 34 independent bounded child trees concurrently, with
separate browser processes, environments, traces and output directories. Each
child is capped at 2 GiB/512 tasks within the shared 12 GiB/no-swap slice and CPU
pool. The supervisor uses 2 GiB/512 tasks, including bounded import preflight.
An independent watchdog inside each case scope stops that whole scope if the
supervisor dies or the authorized lifetime expires; dispatch checks also reject a
dead supervisor. These limits are ceilings, not
reservations: capacity failures are retained, never silently retried or serialized.
`capacity.jsonl` records observed live-environment states and cgroup memory, task
and CPU counters; launcher receipts include shared-memory and cleanup evidence.
A SIGKILL with a shared OOM counter increase is recorded as possible memory OOM;
that correlation does not uniquely identify a case. Watchdog and supervisor
interrupts remain distinct, and unattributed kills are reported as unknown causes.
Successful graded exits keep their verdict if a later suite signal arrives.
Confirmed OOMs, suspected OOMs and launcher refusals have separate terminal counts;
unreadable shared counters are explicit. The supervisor itself must be bounded.

Completion subscriptions are registered before dispatch: each episode, suite
milestones 10/20/30/34, and final completion. Process success does not imply task
success. The supervisor delivers terminal notices through the retained transactional
Events outbox. Evaluation inspects subscribed completed results, not live policy
turns. All original accepted traces and grades remain unchanged.

The actual policy profile disables optional helper agents and data/Python tools:
the Python sandbox is not qualified for this suite. Required clarification and
site discovery remain available, and consumer conversation/capture configuration
is preserved. Results record this deviation for later comparisons.

Source/import checks and saved scripted grades are reusable evidence. New wrapper
source requires independent Claude review before dispatch; checks themselves make
no provider calls. Source readiness does not authorize more than this exact suite.
The review receipt also binds the entire launch configuration, excluding only its
own proof pointers, so adding review evidence cannot create a circular hash.

The supervisor unit tests need the separately pinned Events helper. Set
`LUNA_EVENTS_HELPER` to its accepted file when `scripts/episode_events.py` is absent
from the checkout; otherwise those tests explicitly skip. The three-file caller
release does not include that helper or the separately pinned episode runtimes.
