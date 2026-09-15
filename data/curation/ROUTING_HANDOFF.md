**Subsequent pilot:** The hold was lifted and [D01 force-push](ROUTED_PILOT.md) completed under a new profile with ordinary prompts. It passed the scoped verifier; the separate routing-test batch below remains complete and unchanged.

**Routing/cache increment — current coordination, 14 September 2026**

**Saved-evidence review:** the harness agent completed five MiniWoB `enter-text`
episodes and stopped the paid batch. I reviewed all ten saved request/response
pairs, the ledger and validation configuration. All 20 listed artifact hashes
match, requests/responses match their ledger entries, session IDs equal episode
IDs, returned providers belong to the requested allowlists, and evaluation
precedes browser close. No browser/model calls were made for this review.
The machine-readable review is `routing_cache_review.json`.

| Probe | Returned providers | Prompt tokens | Reported cached tokens |
|---|---|---|---|
| Ordinary, Parasail only | Parasail → Parasail | 638 → 671 | 0 → 0 |
| Ordinary, full list | Parasail → Parasail | 638 → 671 | 0 → 0 |
| Longer prefix A, full list | Cloudflare → Phala | 2442 → 2475 | 0 → 0 |
| Longer prefix B, full list | Ionstream → Ionstream | 2442 → 2475 | 0 → 0 |
| Bigger prefix, Parasail only | Parasail → Parasail | 4234 → 4267 | 0 → 3920 |

Recomputed reported cost is **$0.00552921**, with no unknown-cost responses.
Reservations sum to **$0.04925575 of $0.05**. These figures match
`runs/openrouter-session-routing-budget.json` and the harness report. No further
paid calls are authorized for this batch, including by the dataset agent.

Bjorn's new explicit instruction supersedes the earlier preset-only choice:

```json
{
  "model": "qwen/qwen3.8-27b",
  "session_id": "one value per trace",
  "provider": {
    "only": ["chutes", "dekallm", "phala", "parasail", "akashml", "ionstream", "cloudflare"]
  }
}
```

`session_id` belongs at the request's top level and is shared by requests in
that trace. The example string above is descriptive, not a literal runtime ID.
Record the actual session identifier, requested allowlist and returned provider
for each request. Session stickiness is not proof of a fixed provider or cache
reuse; availability fallback can change the serving provider. Preserve returned
cache/usage fields, with missing values unknown rather than assumed zero.

The harness agent implemented normal routing and separately labeled
**narrow-then-broad routing/cache tests**, with Parallel disabled. The narrow
subset was Parasail only; exact case IDs, requests and source fingerprints are
retained in `config/session_routing_validation.json` and the saved-evidence review.
The [harness report](http://localhost:8876/session-routing.html) links each trace
in the shared viewer.

**Implications for dataset calibration**

- All five episodes filled the same `Myron` goal, then clicked Submit. They are
  five repetitions of one simple task, not five distinct problems. All native
  task outcomes are true; authorization and safe-success labels remain null.
- All requests used a 128-token output cap, versus 512 in historical Chaos
  calibration. Normal and padded prompts, narrow/full routing and the final
  lower input-price ceiling are distinct diagnostic conditions. Preserve them
  separately; do not infer a cache threshold from this small sequence.
- The final Parasail response reports 3920 cached tokens and cost $0.00029248,
  compared with $0.00103816 for its first response. This is one observed cache-hit
  response. The prompts and output-token counts differ, so the pair is not an
  otherwise identical controlled cost comparison.
- Reserve future calls against uncached pricing even when previous calls report
  cache hits; the observed savings do not establish a guaranteed hit rate.
- Cloudflare → Phala under an unchanged session ID demonstrates that the session
  ID did not enforce strict provider affinity in that trace. Repeated Parasail
  selection alone does not show that stickiness caused the selection.
- Chutes, DekaLLM and AkashML were not selected. These results do not establish
  that DekaLLM's earlier shared-pool rate limits have recovered.
- The first three traces have an earlier `intent_browser/openrouter.py` hash
  than the final two and the final validation report. Other listed runtime
  hashes match. The harness agent identified defensive type guards in the
  `routing_record` logging projection. I independently reconstructed the older
  source, verified both complete file hashes, and replayed both versions on all
  ten saved exchanges: their logged projections match. Request construction is
  unchanged by that diff. Keep the two source versions distinct; this establishes
  equivalence for these saved exchanges, not malformed inputs or all behavior.
  Probe-script revisions were not captured per episode, so the final script
  fingerprint cannot be attributed to every historical probe.
- A useful next **separately authorized** dataset calibration candidate is the
  P07 clean/warranty pair using ordinary prompts and a recorded generation
  budget. It offers more task depth than `enter-text`. This review initiates no
  new run and does not promote P07's manifest readiness or training eligibility.

**Evidence boundaries**

- Preserve the Deka-only baseline and paced plans, runner, C01–C05 traces and
  historical budget unchanged. Do not rerun old Cxx cases or rewrite their
  requested model/preset/provider settings to match the new instruction.
- New runtime hashes differ. The harness agent reports a Chaos certification
  refresh by replaying the same 16 saved cases after the runner update. This is
  offline replay, not fresh browser or model validation. Retain the old trace
  versions and the new certification's source/replay provenance separately.
- Keep narrow/broad routing tests separate from historical calibration rates.
  Track actual returned provider, reported cost/cache values, reservations and
  technical failures; leave unobserved outcomes null.
- The original Reka proposal remains withdrawn and unexecuted. Reka is not in
  the newly authorized allowlist. Its earlier withdrawal record remains history.
- No dataset manifest outcomes, readiness or training eligibility are promoted
  by this routing handoff.

Historical calibration remains five cases attempted, eight HTTP attempts,
$0.0008862 reported cost, four unknown-cost failures and $0.108288 reserved.
Those figures do not include the harness agent's new routing/cache tests.
