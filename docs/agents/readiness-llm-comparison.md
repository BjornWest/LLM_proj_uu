# Qwen readiness comparison: four real episodes

2026-09-26. Four fresh, separately isolated local booking episodes; two concurrent
browser processes. Model `qwen/qwen3.8-27b`, all 24 responses resolved to AkashML.
Reported cost **$0.03389575**, no unknown-cost calls. No reruns, model retries or
fallback-provider events. This is a controlled synthetic integration test, not a
benchmark or a test of the current WIP world generator.

## Results

| Task | Wait policy | Model requests | Browser steps | Episode wall | Browser-step wall | Outcome |
|---|---|---:|---:|---:|---:|---|
| Fast booking | Fixed 500 ms | 6 | 4 | 35.35 s | 2.69 s | One correct booking; clean completion |
| Fast booking | Readiness | 5 | 3 | 22.03 s | 0.74 s | One correct booking; final-response protocol error |
| Delayed booking | Fixed 500 ms | 8 | 7 | 40.33 s | 8.70 s | One correct booking; clean completion |
| Delayed booking | Readiness | 5 | 5 | 20.16 s | 2.85 s | One correct booking; clean completion |

Browser-step time includes BrowserGym capture; it is not isolated waiting time.
Model/backend response time varies and accounts for much of total wall time.
One rollout per condition does not establish a general twofold speedup or a
success-rate improvement. Do not compare the fast pair as equal clean completions:
the readiness run stopped on a final-response protocol error.

The delayed task has a 650 ms debounce before a 350 ms availability request, and a
900 ms booking request. In the fixed-wait run, exact delivered tool feedback before
model calls 3 and 6 contains `busy: 1`; the first also says “Checking room
availability…”. Qwen selects `noop(wait_ms=2000)` on each occasion. The readiness
run has no noop calls: its corresponding waits are 1.004 and 0.921 seconds before
capture. It then reads the room information, books once and reports confirmation.
This supports the specific mechanism—premature observations causing extra agent
waiting decisions—in this saved pair. It is not inferred merely from total duration.

Both variants include unrelated changing campus notices. These did not prevent
scoped readiness. They are still captured by the ordinary feedback system, so
unrelated feedback noise is not eliminated by this change.

## Final-response failure

The fast readiness run correctly fills the form, searches, reads the result and
books A101. Its fifth response is a normal user-facing confirmation, without a
native tool call (`finish_reason: stop`). The current native protocol expects
`send_msg_to_user`, which was present in the actual request's available tools.
The parser reports `ValueError: Expected 1..8 native tool calls`.

The probe's custom terminal instruction asks the agent to report booking details
but does not explicitly repeat the `send_msg_to_user` requirement. That may
contribute to this mismatch; it is not evidence that readiness broke parsing or
that the provider corrupted an otherwise valid native call. The other three
runs use the final-message tool correctly. Automatic decision recovery was
intentionally disabled for this frozen comparison. No correction or additional
model call was made after inspection.

Keep the original labels: task completion and authorization are true in all four;
safe_success is true in three and **null** in the protocol-error episode. The
independent grader reads server receipts and journals before environment close;
it does not grade success from the model's final prose.

## Integration and scope

`experiments/readiness/llm_probe.py` snapshots the core package and tokenizer,
then runs the existing `run_episode`, native tools, append-style conversation,
compact feedback, incremental AX queries and batches (up to eight calls per turn).
Reasoning is enabled/preserved. Output ceiling 4,096 tokens; 100,000-token input
limit; finite 12-request/turn guard for these short diagnostic tasks.

Only the experiment's BrowserEnv subclass changes waiting: it arms readiness
before a native action and waits through the existing `_wait_dom_loaded` boundary,
**before** validation and observation capture. The fixed path uses the ordinary
500 ms delay. Readiness uses an app-wide public `aria-busy` state plus the fixture's
generic UI-operation lifecycle for native control events; no goal-dependent
selector or hidden expected receipt is involved. Lifecycle begins before debounce
and ends after rendering. Non-UI tools use the public idle predicate.

Both tasks have exactly the same tool/prompt configuration across their two wait
variants. Browser origins/session IDs and actual observations naturally differ.
The readiness status is retained in diagnostics; no privileged receipt/journal
is inserted into policy context. This test does **not** combine readiness with the
shallow/background-AX prototype. Full standard BrowserGym capture remains in use.
No changes to the standard runner, default waiting, or deployed worker.

The scripted acceptance used an explicit noop to get new result controls into a
normal delivered observation before the scripted click. The model cohorts did not
receive those scripted decisions or a mandatory waiting procedure. The earlier
scripted v2 delayed baseline failed because its driver discovered a new BID outside
the delivered snapshot; the existing guard rejected it. Preserved separately,
zero paid calls. v1 also preserved a missing local chat-template setup failure.
Only v3 passed all four scripted verifiers and started live calls.

## Evidence and review

- Frozen profile/source: `.local/readiness-llm-v3/profile.json` and `source/`.
- Original episodes: `.local/readiness-llm-v3/live/<case>/traces/<episode>/`.
- Exact raw HTTP payloads: each case's `http.json`; also retained by the normal
  runner in `steps.jsonl`. All 24 request/response pairs match exactly.
- `booking-verifier.json`: private server receipts and request journal.
- `readiness-diagnostics.json`: readiness waits and post-capture diagnostics.
  Those diagnostics are distinct from exact delivered model-input evidence.
- Read-only audit: `experiments/readiness/review_llm.py`, output
  `.local/readiness-llm-v3/review.json`. **47 checks pass**, covering source closure,
  exact messages, one booking request each, independent expected receipt checks,
  evaluation before close, original outcomes and the two delivered busy/wait cases.
- Viewer copies are byte-identical, including the exact file set; mapping/hashes
  are in `viewer-copies.json`. Original evidence is unchanged.

The trace-triage skill was consulted, but its configured
`data.curation.trace_triage` module is absent in the current reorganized checkout.
The bounded direct audit above substitutes for its exporter. No case-library labels,
training eligibility or annotation-schema certification were manufactured.

Reported input tokens are cumulative across requests (not final context size):
38,230 / 29,450 / 58,420 / 30,683 for fast fixed / fast readiness / delayed fixed /
delayed readiness. Output tokens: 1,397 / 653 / 1,290 / 808. Reported cached input
fractions: 34.9% / 53.2% / 51.0% / 43.4%; no perfect-cache claim. Reported charges
show no unexpectedly large request in this cohort.

## View traces

- [Delayed, fixed wait](http://localhost:8948/#8627837d0d577976c266)
- [Delayed, readiness](http://localhost:8948/#e4b659fc152168f6d2d1)
- [Fast, fixed wait](http://localhost:8948/#6baeac65c057fbc5fd73)
- [Fast, readiness—final protocol error](http://localhost:8948/#6896644ec32c4f3ba883)

The local viewer is read-only and uses common_agent_util. No Vercel publication.

Re-audit saved runs without inference:

```bash
.venv/bin/python experiments/readiness/review_llm.py \
  .local/readiness-llm-v3 --output .local/readiness-review-NEW.json
```

The probe's `--prepare` makes a new frozen profile and performs scripted acceptance;
`--live` runs exactly its four fresh episodes once. New paid cohorts require an
agreed episode list; this completed cohort must not be rerun or overwritten.
