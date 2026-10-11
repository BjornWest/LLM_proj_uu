# Opt-in shared tokenizer infrastructure

This prospective local service shares immutable tokenizer vocabularies across
independently started processes. It does not share conversations, AX state,
reasoning receipts, counters, budgets, browsers or worlds. The supervisor owns
service startup/shutdown; a client may attach late or close without stopping
others. Existing profiles, explicit input counters and qualified remote
processor/server counters retain their default behavior.

## Start one bounded host

No downloads occur. Install/pin model assets separately using the existing
model-tokenizer instructions. Create a private directory, an explicit manifest
and an absolute Unix socket path. For example, from the repository root:

```bash
mkdir -p .local/tokenizer-host
chmod 700 .local/tokenizer-host
python3 - <<'PY'
import json
from pathlib import Path
from intent_browser.shared_tokenizer import asset_digest
asset = Path('.local/model-tokenizers/qwen3.8-27b-1d4bf0f2/tokenizer.json').resolve()
Path('.local/tokenizer-host/assets.json').write_text(json.dumps([
    {'path': str(asset), 'sha256': asset_digest(asset), 'normalization': 'raw'}
]))
PY
python3 scripts/run_bounded_job.py --memory-mib 2048 --tasks 128 -- \
  timeout 3600 .venv/bin/python -m intent_browser.tokenizer_service \
  --socket "$PWD/.local/tokenizer-host/tokens.sock" \
  --manifest .local/tokenizer-host/assets.json --max-clients 4
```

The CLI emits one JSON line with `ready: true` only after socket permissions and
`listen` are complete. Supervisors must wait for that line (with a finite startup
deadline); socket-path existence alone is not readiness. Socket paths are limited
to 107 encoded bytes. Keep this foreground owner alive while rollouts use it. Restarting the service
invalidates existing clients; requalify/recreate them before another model
request. A stale existing socket is rejected rather than automatically removed.
After an unclean process death, confirm its owner is gone before removing that
socket yourself. Client code cannot stop the service or load arbitrary files.

Each manifest item has exactly `path`, `sha256`, `normalization`. Qualification
keys include the file SHA-256, normalization, protocol and exact tokenizers
0.23.2 implementation. Qwen and MiMo use `raw`; the existing GLM counter uses
`ascii-json`, retaining its qualified JSON-reserialization workaround. Assets
are loaded from verified bytes once per key, not re-read on requests. Unknown
keys, different normalization/version and corrupt or missing assets fail.
The manifest must admit both the AX and policy tokenizer keys: an AX tokenizer
always uses `raw`, even when GLM full-request counting uses `ascii-json`. These
may be two keys for one file, or separate files. Missing either key fails before
model dispatch; do not assume the policy asset alone covers AX operations.

## Attach to AX and full-request sizing

```python
from dataclasses import replace
from intent_browser.shared_tokenizer import SharedTokenizerConfig
from intent_browser.standard_profile import standard_profile

service = SharedTokenizerConfig('/absolute/private/path/tokens.sock')
profile = standard_profile()
profile = replace(profile, ax_config=replace(profile.ax_config,
                                           shared_tokenizer=service))
# Pass this profile to the existing run_episode(..., harness_profile=profile).
```

The runner passes this opt-in configuration to its default model-matched
counter. Alternatively select it explicitly:

```python
from intent_browser.model_input_budget import model_matched_input_counter
counter = model_matched_input_counter(backend, assets_root=local_official_assets,
                                      shared_tokenizer=service)
```

Caller-supplied counters bypass default selection exactly as before. For a
qualified remote official processor counter, keep passing that explicit
counter; sharing an AX tokenizer does not replace or certify it.

Registered model/template/processor validation still runs locally. Request
templates, flags, tool-schema insertion order, image sizing and opaque reasoning
accounting remain unchanged. Only text encode/decode/count operations use RPC;
images, histories, model requests and usage receipts are not stored in the
service. Opt-in provenance records transport, tokenizer digest/version and
normalization in AX profile and input-count metadata. Default-off provenance
and request results stay unchanged.

## Bounds and failure behavior

Transport is same-user Linux AF_UNIX, with a 0700 parent and 0600 socket plus
peer-UID checks. It is intended for trusted local rollout processes, not a public
network API. Requests/responses never include prompt text in diagnostic errors.

Defaults are four simultaneous request handlers, four allowlisted asset entries,
30-second request deadline, 16 MiB frames, 4 MiB aggregate UTF-8 input text,
one million aggregate transferred output/input IDs (count-only results are
not limited by token-ID count) and 256 batch entries. Asset files are
limited to 64 MiB each. Configure finite handler capacity for your workload
before acceptance (`--max-clients`, maximum 128). An accepted connection waits
for a handler within the same finite request deadline; one accepted waiter and
the 16-entry kernel backlog bound pending admission. Linux queue-full connection
admission waits within the client deadline, before any request bytes are sent;
this never retries an executed RPC. No implicit request retry or local
fallback occurs. Handler threads and the socket backlog are bounded. Native tokenizer computation is bounded by admitted
input/output sizes and job resources; the I/O/completion deadline does not
preempt an in-progress Rust operation. The outer finite supervisor timeout owns
whole-service termination. Admission observes owner stop at 50ms intervals.
Terminal diagnostics have at most 100ms additional I/O grace with no further
encoding. Already-disconnected queued clients are dropped before native work;
a disconnect during native computation cannot preempt it.

There is no global text/result cache. AX previews use an episode-owned cache
bounded to 512 entries and a conservative 1 MiB size charge, never caching full
token lists. Short previews and candidate result sizes are batched; long node
reads remain explicitly paged. Token IDs, decode flags, budgets, returned entries
character offsets and delivery acknowledgments must match the local path.
Single and batched encodings retain native token offsets for fact-provenance
node paging. New preview clients must share their parent client’s service instance. Full-request counts
always contact the service, even when AX previews are cached.

Unavailable/mismatched service, oversized requests and transport deadlines are
explicit infrastructure errors, with safe cause codes (`bound`, `asset`,
`protocol`, `saturated`, `timeout`, `unavailable`, `connection_closed`, `internal`). Oversized
UTF-8 text or escaped wire payloads can fail before an over-context count is
available; this is a service-bound failure, not a model task verdict. AX
speculative count batches exceeding a bound are counted individually and lazily
so that a valid truncated prefix can still return. Do not automatically downgrade the tokenizer,
replay committed browser actions, or call models again to recover. Frozen
recipes and existing runs never opt in merely because a service starts.

## Qualify before future suite adoption

Use installed assets and the repository's bounded launcher. Run independent
test shards concurrently with separate logs:

```bash
python3 scripts/run_bounded_job.py --memory-mib 2048 --tasks 128 -- \
  timeout 120 .venv/bin/python -m pytest -q tests/test_shared_tokenizer.py
python3 scripts/run_bounded_job.py --memory-mib 2048 --tasks 128 -- \
  timeout 120 .venv/bin/python -m pytest -q tests/test_shared_tokenizer_official.py
python3 scripts/run_bounded_job.py --memory-mib 2048 --tasks 128 -- \
  timeout 120 .venv/bin/python scripts/benchmark_shared_tokenizer.py \
  --asset .local/model-tokenizers/qwen3.8-27b-1d4bf0f2/tokenizer.json \
  --workers 4 --output /absolute/new-memory-report.json
python3 scripts/run_bounded_job.py --memory-mib 1024 --tasks 64 -- \
  timeout 90 .venv/bin/python scripts/benchmark_shared_ax.py \
  --tokenizer "$PWD/.local/model-tokenizers/qwen3.8-27b-1d4bf0f2/tokenizer.json" \
  --output /absolute/new-latency-report.json
```

Official tests require all installed registry assets; inspect skips rather than
treating missing assets as qualification. Benchmarks write exclusive new output
files. Memory uses fresh independent processes and Linux private clean/dirty
pages; workers and service are reported separately and summed. This measures
one vocabulary per worker, not full browser/world/rollout memory or 34-worker
capacity. AX latency uses a synthetic captured tree, with no browser rendering
or navigation. Future Evaluation owns actual suite composition, grading/viewer
acceptance and adoption. Chromium and immutable-world sharing are separate
increments described in [shared rollout infrastructure](shared-rollout-infrastructure.md).
