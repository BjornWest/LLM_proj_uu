# OpenRouter session routing: observed results

The runtime now sends the model slug and an episode-scoped `session_id`, with the seven requested providers in `provider.only`. The old preset is unset in `.env`. No manual provider order is sent.

**Verified:** all ten requests used their trace ID, all serving providers were allowed, and all five MiniWoB form-filling episodes succeeded. A long-prefix Parasail diagnostic reported 3,920 cached tokens on its second request.

**Limitation:** one full-allowlist episode changed from Cloudflare to Phala despite the same session ID. The saved responses do not establish why. Session routing is best effort; it is not a strict provider lock. A same-provider pair alone does not prove stickiness caused that selection.

| Probe | Returned providers | Cached tokens (first → second) | Trace |
|---|---|---|---|
| 1: narrow | Parasail → Parasail | 0 → 0 | [20260914T205804Z-f1a76355](http://localhost:8878/#457253f376bb313152b7) |
| 2: full | Parasail → Parasail | 0 → 0 | [20260914T205819Z-fea56730](http://localhost:8878/#1a5f4f1501c23f0f731b) |
| 3: cache | Cloudflare → Phala | 0 → 0 | [20260914T205932Z-9784088d](http://localhost:8878/#85083bd5595a991b6f69) |
| 4: cache | Ionstream → Ionstream | 0 → 0 | [20260914T210103Z-c62b59d8](http://localhost:8878/#6ee51fb77133fadc790c) |
| 5: cache-parasail | Parasail → Parasail | 0 → 3920 | [20260914T210214Z-a29dfb9e](http://localhost:8878/#d6df60bd56232f3b64d3) |

Reported cost: **$0.00552921**. Reserved: **$0.04925575 of $0.05**. All ten calls returned cost data. No more paid tests in this batch.

The first two probes use the ordinary harness prompt (638–671 input tokens). The next two use a longer stable synthetic reference prefix (about 2,440–2,475 tokens) with the full allowlist. The last uses a doubled prefix on Parasail only (4,234–4,267 tokens) and a $0.25/M input-price ceiling. These are separate diagnostics, not a controlled estimate of a cache threshold. Synthetic padding is not enabled for normal runs.

The last pair cost $0.00103816 and $0.00029248 respectively; both completed the task. This proves a reported cache hit in that diagnostic, not universal caching across all seven providers. Chutes, DekaLLM and AkashML were allowed but were not selected in these probes.

Configuration and reproduction: `README.md`, `scripts/smoke_session_routing.py`. Machine-readable evidence: `config/session_routing_validation.json`; raw payloads, screenshots and videos stay under the linked `runs/` directories. The shared viewer reads them without conversion. All tests are training-ineligible, and MiniWoB reward does not verify broader authorization preservation.

All ten requests used `max_tokens=128`; the historical Chaos calibration used
512. Native task success is true for all five probes, while authorization and
safe-success labels remain null.

Runtime provenance is not identical across all five probes. The first three
record `openrouter.py` SHA256 `723001d1e21e7098e02d12a1beafb28a4364732f3d167bbfe4932534b2b322e1`;
the final two record `810d4b6434ff824dc09af0d481d96e32d02fa86d74e0f925d3b7b9be095c25c4`.
The change adds type checks to `routing_record`, the logging projection, so a
malformed response or nested field produces null metadata instead of masking
the original error with an exception. It changes neither `provider_options`
nor request construction. The reconstructed earlier file matches its recorded
SHA256 exactly. An offline replay of both versions on all ten saved exchanges
produced identical routing records. That establishes equivalence of the logged
fields for these exchanges, not identical runtime versions or broader behavior.
The JSON report includes the diff and per-case recorded runtime fingerprints.
Its top-level source hashes describe the final checkout; probe-script versions
were not recorded per episode and must not be treated as a uniform historical
script fingerprint.

The current Chaos certification was refreshed by replaying the same 16 saved verifier cases after the runner change. This was an offline replay, not another browser/model evaluation. Historical calibration plans, requests and outcomes remain unchanged.

References: [OpenRouter prompt caching and session IDs](https://openrouter.ai/docs/guides/best-practices/prompt-caching), [provider allowlists](https://openrouter.ai/docs/guides/routing/provider-selection).
