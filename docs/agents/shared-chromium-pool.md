# Opt-in shared Chromium

This prospective local adapter shares Chromium **processes** across independently
started episodes. Each episode still owns fresh task/chat browser contexts, routes,
storage, task state, observations and recordings. It does not clone or share world
state, catalogs, Python sandboxes, model conversations or grading references.
The ordinary harness remains the default. Evaluation owns future frozen-world,
suite, tokenizer-composition and production acceptance.

## Connection and ownership

`PoolSupervisor` starts a local Node broker using the Node executable and package
already bundled with the qualified Python Playwright installation. There are no
downloads or additional Node packages. Chromium servers start lazily and remain
alive after workers close; the supervisor alone owns drain, process retirement
and shutdown. A worker descriptor has separate credentials from the supervisor.

Launch groups preserve the task/chat roles and exact supported launch settings:
headless mode, slow motion, argument order and ignored default arguments. Different
profiles do not silently merge. Unsupported extra launch settings fail before
connection rather than being dropped. Context settings, video directories and
routes remain per-worker. Admission has explicit finite server/lease/per-server
caps; saturation refuses admission without model/action retry. Use `drain` to
retire a member after existing clients leave. A crashed member invalidates its
clients; other members continue. A new episode may acquire a new generation,
but an existing episode is never transparently restarted or replayed.

The initial qualification supports BrowserGym0.14.3, Python Playwright1.44.0,
its bundled Node1.44 driver and Linux Chromium revision1117. Version, executable
digest, server source digest, launch profile, member generation and context owner
are recorded privately. Client/server mismatch fails closed. The legacy Node
launchServer defaults to a wildcard listener: the supervisor uses a source-pinned
private in-memory launcher copy with one loopback-only bind. Installed dependency
files and other processes are unchanged. Control uses a private Unix socket;
worker WebSockets and internal browser servers bind only127.0.0.1. Descriptor and
config files contain capability secrets and must remain private. This is trusted
same-user process sharing, not a sandbox against malicious workers. Browser-wide
CDP can enumerate other contexts, and same-user processes can read the private
config. The model action set exposes neither capability. Worker status omits the
WebSocket bearer lease IDs.

Each worker has its own Playwright-protocol connection, not a shared Python
Browser object or a CDP-attached default context. Connection ownership lets the
Playwright server close that worker's contexts after worker/driver death. Lease
release requires the exact lease token/owner; old/foreign owners cannot close a
new generation. Clean releases have explicit acknowledgment events, including when the socket
closed first. A signed release receipt remains valid after bounded history eviction
without targeting any new lease. Pending connections expire. At capacity, an idle ready member may be retired before
admitting a different profile; active or pending leases are never evicted. Bounded in-memory ended-lease/member
histories and private append-only lifecycle events contain IDs, not page text.

`SharedBrowserEnv` preserves native actions and observations. Reset/Chat constructor
use function-local factory globals and exact native source guards; no global
BrowserGym launch patch or virtual-environment edit is involved. Each reset closes
the old owned contexts and creates fresh ones. The supported cleanup branch closes
all independent resources even when another close fails and records failures.

Context identity comes directly from a target in that context; no global
before/after context-set inference is used. Optional background page creation
uses that exact ID. With background mode an initial disposable blank identity
probe is not an episode recording. Public `Video.path` is bound per-video to its
future local artifact path, and `save_as` transfers videos before connection
release. Transferred server artifacts are deleted; pages closed before any video
frame are recorded as `no_video_frame` and do not invalidate other recordings. This is necessary because ordinary remote Video.path is unsupported.
Task/chat recordings, popups and tracing stay isolated and are finalized normally.

## Caller API

Start a supervisor once from the suite/rollout controller, inside its own finite
bounded job. The currently local bounded launcher must be explicitly supplied
and pinned in any clean execution release; do not assume an untracked helper
exists in a checkout. Do not place the service inside a worker's job lifetime.

```bash
PYTHONPATH=/path/to/qualified/release \
python3 /path/to/qualified/run_bounded_job.py --memory-mib 3072 --tasks 512 -- \
  timeout 3600 /path/to/venv/bin/python -m intent_browser.chromium_pool \
  --directory /path/to/new/private/pool --max-servers 4 --max-leases 16 --per-server 8
```

The process prints `/path/to/new/private/pool/descriptor.json` when ready. The
caller needs its own finite episode walltime/resource bounds and attached native
automatic grading as usual. `max_leases` counts task/chat connections, so two
leases normally serve one rollout. A reset releases both old leases first.

```python
from intent_browser.chromium_pool import PoolClient
from intent_browser.runner import run_episode

client = PoolClient.from_file("/path/to/private/pool/descriptor.json")
with client.episode("unique-suite-and-case-id") as browsers:
    trace, summary = run_episode(
        browsers.wrap(task.make_env), backend, metadata,
        episode_task=task, automatic_grading=contract,
        # Preserve the task's normal profile, limits and callback arguments.
    )
```

An unused exact native BrowserEnv factory can be wrapped. A custom subclass,
already live environment or custom lifecycle override is rejected for separate
qualification. Modern chat presentation is installed explicitly by the adapter.
`background=True` is optional; headed/Windows UI has not received visual/window
layout acceptance. Separate helper browsers need their own unique episode owner;
no implicit helper inheritance or migration occurs in this increment.

`metadata.shared_chromium` records qualification and context/lease ownership at
reset and close. No endpoints, credentials or other workers' page content enter
the model context. Default tool schemas and caching prefixes remain unchanged.

## Model-free qualification

Synthetic routed pages share the hostname but differ in content/storage. Controls
cover native BID actions, full DOM/AX/PNG capture, chat callbacks, popups, dialogs,
context isolation, reset, late clients, release fencing, drain/generation, video
and tracing, worker death and browser/supervisor loss. The actual runner's parallel
correct/wrong/missing-output fixtures retain native after-close grading and shared
viewer projection. They are tagged `scripted`; no provider or model inference runs.

Use the existing qualified core interpreter, source root and common_agent_util
closure. Run independent cases as separate processes, with bounded concurrency.
Keep unittest methods sequential where they patch shared process globals.
Single-threaded BLAS avoids unrelated NumPy thread proliferation in these fixtures.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=/release:/release/tests:/qualified/common \
python3 /qualified/run_bounded_job.py --memory-mib 4096 --tasks 512 -- \
  timeout 180 /venv/bin/python /release/tests/shared_chromium_acceptance.py --case lifecycle
```

Cases are `lifecycle`, `recording`, `failure`, `graded`. Unit boundaries are in
`tests/test_chromium_pool.py`; memory/startup fixtures in
`tests/shared_chromium_benchmark.py` accept explicit mode/worker count/output.
Snapshots sum owned descendant process PSS/USS including the pool and Python
drivers; RSS double-counts shared pages. Cgroup receipts include overall resource
charges. Small synthetic pages are not full generated-world or34-episode capacity
evidence. Real task adapters, full-request tokenizers, downloads, service workers,
checkpoint branching, network namespace layouts and headed UI need their own
composed acceptance before adoption. Historical releases remain unchanged.

References: [Playwright server connection](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect),
[context isolation](https://playwright.dev/python/docs/browser-contexts),
[remote video paths](https://playwright.dev/python/docs/api/class-video#video-path).

The CLI handles SIGTERM/SIGHUP/SIGINT with owned shutdown. The broker also checks
its parent identity and drains if that controller disappears. A broker/storage
failure still invalidates the pool as shared infrastructure; there is no replay.
Qualification rehashes the installed executable and selected driver/source files
for every client. This adds cold attachment work; it is not a startup speedup, nor
a complete digest of every dependency module. A release must pin its complete
execution dependency closure separately.

Signal handling belongs to the broker, so native launchServer signal handlers are
disabled. Recording entries distinguish probes from episode pages, identify the
local artifact name and retain real save/transfer failure messages. Failed remote
artifacts and worker-death recordings remain until their browser member exits;
clean successful transfers delete the remote copy.

Fact-recording instrumentation may wrap an instance's `close()` and invoke the
saved original pooled method after provider cleanup. The original method qualifies
the exact pooled environment and pinned BrowserGym before invoking the private
resource cleanup body. Generic shutdown checks continue to reject replacement close methods, so callers must
invoke the recording wrapper rather than bypass it. Cleanup errors stay visible
and do not certify a native grade. `tests/test_shared_recording_close.py` covers
this boundary and recorded, zero-provider runner/after-close grading controls;
set `HARNESS_TEST_TOKENIZER` to an existing qualified Qwen tokenizer if the
repository-local test asset is absent. Recompose service and client from the same
release: the adapter and shutdown helper hashes are both checked by pool manifests.
Trace pool metadata uses qualified environment identity independently of close
wrappers. The once-only cleanup assertions cover a clean terminal close; existing
idempotent providers may be closed again during reset or after a failed cleanup.
