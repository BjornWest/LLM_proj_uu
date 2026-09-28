# Completion and final-message limits

2026-09-27. Future ordinary OpenRouter requests now default to 16384 output tokens,
including reasoning. Curation owns the Python helper/default/CLI change. Backend
aligns the Daylight JS default; explicit settings and frozen profiles remain
unchanged. This code is locally tested, not a deployment/restart announcement.
Python demo/team consumers already call the shared helper.

## Native terminal answer

`send_msg_to_user.text` has its own schema-visible 65536-character limit. This is
not a token estimate. Native encoded JSON admits up to 12 times that bound plus
1024 characters for JSON escaping/envelope; the decoded field still has to pass
its exact schema. This avoids rejecting non-ASCII text simply because a provider
uses escaped Unicode. A validated native terminal message bypasses the historical
4096-character Python-action-string parser; its function name and exact argument
shape have already been checked. Other tools retain their existing limits, and
the legacy textual-action parser is unchanged.

## Truncation evidence and recovery

The runner records `completion_diagnostic` on steps and a `completion_classified`
event when usage reaches the requested cap or the provider reports a length stop.

- `reported_incomplete_output`: provider says length.
- `probable_output_truncation`: usage reaches the cap AND tool arguments fail JSON
  parsing, even if the provider reports tool_calls/stop. This is not causal proof.
- `output_limit_reached`: cap reached without that evidence. A valid call still
  executes normally; finishing at the cap is not itself task failure.

Reasoning tokens, total completion tokens, requested cap, raw finish fields and
JSON error position are retained. Exact raw output remains unchanged. No closing
quotes/braces or answer content are invented. The existing opt-in retry policy
will not retry reported/probable truncation with the unchanged budget. Other
ordinary argument mistakes retain their existing one-recovery behavior. This does
not add automatic retries, provider fallback changes or output-limit escalation.

Saved v4 classification is `.local/completion-limit-review/v4-classification.json`:
4096 total, 3438 reasoning, both finish fields tool_calls, unterminated JSON string.
Historical request/response files and labels were not modified.

## Local acceptance / rollout boundary

36 focused Python tests, 40 focused Node tests, and 15 real-browser background
capture regressions pass; inference is HTTPX/mock only. Long terminal text and
worst-case escaped Unicode pass, oversized decoded strings fail, other tool
bounds remain, a long complete answer finishes once, and a truncated answer
preserves evidence without replay/retry. Reports under `.local/completion-limit-review/`.

Existing Vercel/control processes, workers, containers, explicit 4096 environment
settings and frozen cohorts have NOT been restarted or rewritten. A deployment
must update broker and worker together: the broker rejects requests above its own
configured output ceiling. Preserve explicit overrides unless deliberately
changing that deployment's config. No inference/release is implied by these tests.
