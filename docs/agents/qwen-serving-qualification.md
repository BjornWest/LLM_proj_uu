# Fresh Qwen serving qualification adapter

`training/scripts/qwen_suite_qualification.py` prepares the producer side of
Evaluation's private Qwen caller. It serves only read-only `GET /qualification`
on a separate IPv4 localhost port. vLLM retains its ordinary `/health`,
`/tokenize`, `/metrics` and `/v1/chat/completions` routes.

This is source preparation, not an allocation, model-dispatch release or proof
that a new stack works. The module cannot create a capability, download weights,
run generation diagnostics, allocate a VM or stop billing. It consumes existing
actual evidence; the complete worker must collect that evidence before using it.
The local deletion watchdog remains required and should run through its CLI
`main()` in its own process, with a fresh receipt path for every invocation.

## Evidence and publication

The bound JSON has schema `qwen-fresh-instance-binding-v1` and exactly these
fields:

| Field | Value |
| --- | --- |
| `runtime` | Absolute path/SHA256 pin to Evaluation's reviewed `qwen_suite_runtime.py` |
| `capability` | Pin to the immutable actual `serving-stack-capability-v1` receipt |
| `deployment` | Pin to a fresh measured deployment with `passed=true`, `synthetic=false` |
| `launch` | Pin to this attempt's `serve_qwen_suite.py` installed-source receipt |
| `raw_base_url` | IPv4 localhost origin, normally `http://127.0.0.1:8000` |
| `qualification_base_url` | Different IPv4 localhost origin, normally port8001 |
| `dispatch_approval` | Null, or pin to the separately granted finite Qwen approval |

The measured deployment retains Evaluation's identity/compatibility/session/
allocation/deadline fields. It also supplies `launch_receipt` pointing to the
same launch pin, and `serving_process` with `pid`, Linux `/proc/PID/stat`
`start_ticks`, and `/proc/sys/kernel/random/boot_id`. Capture these immediately
after launching the owned process, rather than discovering an arbitrary server
already occupying the port. The serving session equals that launch's fresh
`attempt_id`; PID survives the entry point's exec into vLLM.
The deployment also binds canonical distinct `run_id`/`instance_id`, actual
`server_context=262144` and true measured `vision_configured`,
`native_tools_configured`, `exact_request_counter`. Fresh startup reads raw
`/v1/models` and verifies the served repository and context.

All three original proof pins must contain `passed=true`, `synthetic=false`,
their respective `proof_kind` (`qualification`, `deployment`, `processor`) and
the same `fingerprint` as the capability. Missing proof fields are not accepted
as legacy authority. The separately approved dispatch record must bind the
current run/instance UUIDs, allocation/deadline, duration and finite `case_ids`;
its pin and cases are retained in the published live contract for audit.

The adapter checks the process birth identity and actual listening socket
ownership before and after live raw HTTP200 health. An empty health body is
valid. A process-title change is allowed; PID reuse, an unrelated server on the
selected IPv4 port, a wildcard instead of its private binding, health failure, changed source or
proof files, and expired rental fail closed. vLLM frontend descendants are
supported through Linux process ancestry. Missing `/proc` permissions are an
explicit launch blocker. The normal direct-owner listener check does not scan
all host processes.
Other listeners on different IPv4/IPv6 addresses are outside this ownership
check; they do not prove or invalidate the selected IPv4 endpoint.

The supported launch profile is native262144, E4M3 KV, MTP3, block1664, aligned
BF16 Mamba/FP32 SSM, 20GiB CPU LRU prompt offload, retained thinking, native tools
and explicit image geometry. Measured backend names must be resolved, not `auto`.
The complete argv must equal the reviewed serving constructor, including the
canonical pinned HF snapshot/config. Extra flags, argparse abbreviations,
`--flag=value` overrides, alternate templates/config files and model revisions
are refused. The adapter imports that constructor from the adjacent frozen
`serve_qwen_suite.py`; package its approved compiler/parser/patch dependencies
together, rather than copying this file alone.
Runtime lock, installed kernels, effective official assets and both installed
patches still need the worker's actual measured deployment proof. A JSON label
or source receipt is not a substitute for those measurements.

`publish` emits `instance-readiness.json` and `qualified-serving-live.json` in a
new0700 private directory with0600 files. Existing outputs are refused. The
exact pinned Evaluation consumer validates the published contract. Only after
the service binds successfully and publication validates does the CLI emit
`adapter-ready.json`. Failed preparation may leave an incomplete private
directory; absence of `adapter-ready.json` is terminal for startup, not a reason
to consume any previous readiness file.
Its status is `listening_at_publication`, with the adapter's PID/birth identity;
it is an observation, not ongoing readiness. Normal exit emits
`adapter-stopped.json`. A stop during startup cannot emit successful readiness.
Supervisors must check the actual service and process rather than trusting an
old ready file.
Stop receipts are written only into a directory created by that invocation. A
failed second start cannot add receipts to a live or abandoned earlier run.

The capability stays historical and immutable. Fresh readiness expires at the
original allocation plus approved duration; a monotonic bound also prevents a
backward wall-clock jump extending the adapter's life. Every live response
rechecks current process, health and evidence. HTTP responses are noncacheable;
failures produce503 with an error type, without exposing private evidence.
The server admits at most eight connections, handles them independently, and
closes each after an overall15-second budget or the remaining rental, whichever
is shorter. Slow partial headers cannot block another case or the main deadline
loop. Shutdown closes active connections; handler threads cannot keep the
process alive. Raw health/metadata reads have an overall10-second budget clipped
to both clocks, use direct numeric IPv4 HTTP without proxies/redirects, and do
not read a health response body. Real vLLM health latency remains a live-host
acceptance item.
Above eight connections, overload receives a bounded HTTP503 response; it does
not authorize retries or a higher active-episode cap. The proposed four active
case threads make at most four simultaneous readiness calls. More concurrent
callers require a separately qualified finite connection cap.

The adapter validates the recorded constructor arguments and consumes the
worker's measured deployment. It does not attest that a live Python process
executed those bytes or inherited that environment: the worker must bind the
actual executable, sanitized environment, helper source hashes, installed
patches and served snapshot before marking its deployment passed. Process-title
changes make live cmdline text insufficient for that purpose. Real vLLM model
metadata and startup behavior remain unqualified. Those collector/worker gates
are required before runtime use; receipt-only mock controls are not evidence of
them.

```bash
/opt/qwen-runtime/suite-browser/.venv/bin/python -I -B \
  /opt/qwen-release/training/scripts/qwen_suite_qualification.py \
  --binding /private/qwen-runs/RUN/fresh-instance-binding.json \
  --binding-sha256 EXACT_BINDING_SHA256 \
  --output /private/qwen-runs/RUN/fresh-serving
```

This command uses no credentials. It generates no tokens and repeats no burn-in.
It cannot be used until actual capability/processor/deployment parity exists for
this exact fingerprint. First-time qualification of the new profile and the
collector/allocating SSH worker remain separate work. Subsequent compatible
instances can reuse that capability after fresh measured startup checks.

## CPU controls

The tests use fake proof files and a local mock raw server. They demonstrate
producer/consumer composition, not actual qualification. They verify empty-body
health, an actual Linux socket-owner check, unrelated PID rejection, stale
evidence and process-birth rejection, monotonic expiry, strict profile binding,
private no-clobber publication, unavailable HTTP503, no mutation routes and no
generation calls during reuse.

When testing from an isolated tree without Evaluation's caller, supply its
exact frozen source export:

```bash
QWEN_TEST_RUNTIME_SOURCE=/ABSOLUTE/REVIEWED/qwen_suite_runtime.py \
QWEN_TEST_RUNTIME_SHA256=EXACT_CALLER_SOURCE_SHA256 \
  python3 scripts/run_bounded_job.py --memory-mib 1024 --tasks 128 -- \
  timeout --kill-after=10s 90s training/.venv/bin/python -B -m pytest \
  -q -p no:cacheprovider training/tests/test_qwen_suite_qualification.py
```

The default is `scripts/qwen_suite_runtime.py` in the test's Git tree. Tests that
need that external source explicitly skip if absent; the pin/security controls
remain runnable. A test against an unreviewed caller candidate is preparation,
not source adoption. Do not replace the caller's independent review or actual
native-world/grade/viewer/recording acceptance with these mock HTTP results.
The source hash is checked before loading the external test input. The default
hash names Evaluation's Claude-reviewed `47aa96f` background-completion runtime:
`35b5d8aa7bcf54f6940e41aa355a3e63288d0b5e51ad7ce4a9b729013d98d563`.
Integrate the Training pin update only with this caller runtime; a standalone
older caller tree deliberately fails the source gate. The inherited private
opt-in `rental_bounded` submitted-read policy, default `bounded_request` behavior
and hosted timeout stay separate.
Its ordered counter projection remains
`e818865d35a1a4cd9c6d3abc1c3fa02786cad1cb8eb89bd57b870f2ae6b8c27e`.

Bind the new full runtime path/hash in the caller, worker, measurement and fresh
qualification inputs. An unchanged counter projection permits capability reuse
only when the complete measured compatibility fingerprint and proof scope also
match; it does not permit copying old session/readiness/deadline receipts.
The exact source gate in `qualify_qwen_wire.py` uses the same reviewed hash;
`measure_qwen_host.py` imports that loader even when reusing a capability.
Update that pin together with the test default, not only the live binding JSON.
Supply the exact release hash when deliberately testing a revised caller, and
pair future runtime releases with a test-default pin update. Require zero skips
for composition acceptance; a missing source and exit0 are not qualification.
