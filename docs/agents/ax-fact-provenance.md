# Opt-in AX fact provenance

Harness-local implementation; synthetic and saved-browser-source acceptance only. Website recording and
browser exporter adoption remain a separate review boundary. No task readiness,
grading, model-run or screenshot-exposure claim follows from these records.

## Enable one episode

```python
path, summary = run_episode(
    env_factory, backend, metadata,
    harness_profile=profile,  # incremental AX plus policy delivery tracking
    record_fact_provenance=True,
    fact_source_provider=source_provider,
)
```

The default is `False`. Disabled episodes install no observer hooks, call no source
provider, write no fact artifacts and add no fact metadata. Enabled recording uses
the existing AX captures and original formatters; it neither fetches another AX
tree nor changes policy text or the tool inventory. The CLI flag
`--record-fact-provenance` enables private sidecars, but provides no Website source
adapter by itself: unavailable sources are recorded as unknown.

The trusted callback is `source_provider(env, observation, context)`. Context has
`snapshot_id`, model-decision `step`, and capture `coverage`. It must return a
JSON-compatible `ax-fact-sources-v1` packet:

```json
{
  "schema": "ax-fact-sources-v1",
  "sources": [{
    "id": "exported-native-run-id",
    "text": "exact raw AX field",
    "sha256": "UTF-8 SHA256 of text",
    "binding": {
      "snapshot_id": "context snapshot_id",
      "document_id": "actual document revision/backend identity",
      "frame_id": "actual CDP frame identity",
      "node_id": "actual raw AX nodeId",
      "field": "name"
    },
    "opaque_binding": {"occurrence_id": "private native identity"}
  }],
  "private_context": {},
  "mapping_inventory_complete": false
}
```

`field` is `name` or `value`. Existing `website_projection.direct_sources` records
and `fact_render_capture.harness_source_packet` match this interface. The callback
must attest the actual document/render/effective-state identity and its race with
the supplied capture; the harness checks snapshot, raw field, inherited frame and
text digest, but cannot infer private document/state truth. Do not call a standalone
helper that captures another AX tree and pretend it is the supplied observation.
Missing or incomplete native identity qualification must stay unknown.

The callback runs for each existing AX capture, even when public text is identical:
private effective state can change without changing a displayed scalar. Duplicate
identical source inventories reuse a private capture record. Export IDs need only
be unique within that inventory; allocated source IDs are trace/capture scoped and
retain `export_id` for the offline join. All opaque meanings remain in private
artifacts. Limits are 4,096 sources and a 16 MiB JSON packet; rejected packets are
unknown rather than a browser/action failure.

## Artifacts and delivery

| Artifact | Contents |
| --- | --- |
| `fact-capture-NNNN.json` | Scoped source fields, preserved opaque associations, capture step and unknown diagnostics. |
| `fact-output-NNNN.json` | Frozen projections into the actual generated AX output, source-capture link and output text hash. |
| `fact-policy-content-NNNN.json` | Explicit mapping from that generation to registered policy content; no guessing from matching prose. |
| `fact-delivery.jsonl` | Per-recipient retained-request confirmation and links to acknowledged historical outputs. |

Each uses `offset_unit: utf16_code_units`; spans are half-open. Text digests use
UTF-8. `output_path` locates a decoded string structurally inside policy JSON;
empty paths refer to policy text itself. `identity` maps ordinary string text;
`json_string` maps complete JSON escapes, decoded before comparison. No span may
split a surrogate pair or an escape. Policy records reference the selected output;
the ordinary policy source's provenance references its fact-policy artifact.
Capture records hash the raw AX and provider packet; delivery records hash the
exact ledger receipt and retain its message digest for independent joins.

Outputs are frozen before a subsequent capture or batch member runs. Registration
selects that exact generation object/artifact; equal text from another object or
model-authored prose earns no mapping. In batches, each member retains its own
output artifact. Up to 64 generation objects are cached; evicted mappings remain
unknown. Historical reference caches hold 256 refs per recipient and at most 16
content IDs per ref; omitted older links do not imply unseen content.

Only an aligned, acknowledged **retained request completion** confirms delivery.
Constructed requests, unacknowledged failures, rewritten spans and local completion
without a retained request do not qualify. The ledger does not claim to observe
HTTP dispatch. Subsequent receipts use compact `previously_confirmed` links rather
than rereading old projection files. The ordinary saved-request delivery consumer
must still independently validate retained messages and artifact hashes.

Unchanged/reused references link earlier acknowledged public output for the same
recipient. They provide **no new fact/state exposure credit**. A new private state
with an identical displayed value is not exposed just because a historical
reference was emitted. Aggregate unknown/unseen coverage cannot be certified from
these output maps without a complete, independently qualified producer inventory.

## Supported mappings and limits

- Structural previews and changed fields: only emitted name/value slices; clipped
  tails and omitted nodes receive no credit.
- Search and traversal: exact emitted fields, locations/neighbors, and literal
  match excerpts. Casefold-transformed excerpts remain unknown.
- Full-node token pages: actual tokenizer offsets and exact decoded slices, with
  complete escaped-character boundaries. Partial byte decoding stays unknown.
- Suppressed StaticText: only a unique exact substring under its indexed ancestor
  with actual unsuperseded AX `contents` name provenance. Duplicate children,
  independent aria names, compound/whitespace joins and InlineTextBox suppression
  remain unsupported.
- Browser/tab wrappers: exact whole-output embedding composes JSON string offsets;
  unsupported nested escaped pages remain unknown.

Recording failures retain a private error category/type and do not change tool
feedback or policy messages. This is an observational extension, not a browser
readiness or mutation retry mechanism. Producer facts, assertions and grader data
must not be inserted into model context by an adapter.

Checkpoint restoration is explicitly rejected while recording is enabled; it has
not adopted the new ledger. Screenshots are outside this scope. Actual Website
browser adoption and enabled-mode performance overhead are not yet qualified.

## Local checks

Focused suites are `tests/test_fact_provenance.py` and
`tests/test_runner_fact_provenance.py`. They use synthetic raw AX, the existing
local Qwen tokenizer, a fake environment and retained HTTPX MockTransport requests;
there are no browser/model/network calls. Tests cover byte-identical policy/tool
requests with recording off/on, batch generation identity, Unicode/JSON/token
pages, native normalizer joins, effective-state changes, ambiguous/invalid sources,
recipient isolation, failures and independently rechecked offline consumption.

The current source-pinned acceptance is under
`.local/coordination/fact-recording-implementation-20261007/synthetic-v1/`.

The released product slice additionally passes six saved source cases and 510
projection comparisons using `scripts/verify_fact_provenance_exports.py`. Supply
`--input-receipt` and a fresh `--output` directory. It reindexes only the host AX
snapshot labels from identical pinned raw captures; native document/frame/node
and exported run/occurrence/state/part identities remain unchanged. It launches
no browser and makes no network/model call. Its acknowledged/failed delivery
controls are synthetic; producer qualification and real policy exposure stay
unknown. Evidence: `saved-source-v2/validation.json` in the same coordination
directory. The earlier saved-source-v1 adapter exceeded the documented output
cache by delaying all registrations; its failure is preserved separately.

## Bracketing original native observations

A provider that attests render state across capture can explicitly pass
`fact_capture_observer=provider.observe`, alongside `fact_source_provider=provider`
and `record_fact_provenance=True`. Installation on the correct page stays the
caller's responsibility. With `observation_pipeline=None`, the runner brackets
its native `_get_obs` operation before reset, after actions and during refreshes.
The observer must return that exact raw observation; source recording failures
remain unknown and never cause capture/action replay. Disabled recording installs
nothing, even with the provider arguments configured.

The progressive/deferred pipeline currently rejects this observer option. Its
background full capture and later cached observation wrappers require a qualified
relationship to the original capture; merely bracketing the later formatter is
insufficient. This is a coverage gap, not native pipeline certification. The
source callback API is otherwise unchanged. Every new runner diagnostic also
requires the [automatic grading contract](automatic-grading.md) or an explicit
ungraded reason. Existing saved acceptance hashes remain historical.
