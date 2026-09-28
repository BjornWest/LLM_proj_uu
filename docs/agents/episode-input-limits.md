# Episode limits: next input, not accumulated usage

User decision, September 21, 2026: allow up to 200 model decisions and stop
**before another request** if its complete input would exceed 100,000 tokens.
Equality is allowed. Output tokens, cumulative usage and previously cached
tokens are not added to this count. Money budgets remain independent.

The runner counts after assembling the next messages and tool definitions,
before dispatch or inference reservation. Completion (`send_msg_to_user` or
environment termination) ends the loop without preparing/checking another
request. A context stop is recorded as `max_input_tokens`, with no technical
error; the privileged verifier still evaluates the existing state and may
report success. It is not automatically a failed task. Final evaluation still
precedes browser close except where an adapter explicitly finalizes afterward.

## Counting and evidence

`intent_browser/input_budget.py` uses the local Qwen tokenizer and adjacent
`chat_template.jinja`. It includes tool definitions, retained reasoning/history,
and image positions estimated from the Qwen image-sizing rules. It never
changes the request. The per-decision `input_budget` record contains the count,
limit, comparison, tokenizer/template hashes and estimation scope. A blocked
decision has `model_dispatch_skipped=true`, no model request and no action;
it remains an attempt record, not a billed inference.

This is a **local estimate** for hosted OpenRouter models: provider templates
or image processors may differ. A backend with a different model/processor
should pass its own `input_counter(messages, tools)` returning `input_tokens`
and provenance. Unsupported modalities or opaque reasoning fail explicitly
instead of being silently ignored. No tokenizer downloads occur automatically.

## Entry points and compatibility

- Current CLI runs use `--max-steps 200 --max-input-tokens 100000` by default
  with an AX-enabled profile. Both values are configurable.
- Current team-worker live policy, remote Ask, local BrowserGym demo and newly
  frozen capability suites select these limits. Parent/helper inference shares
  the 200-call family guard; each conversation has its own input-size check.
  Existing helper-specific step/time guards remain separate.
- The low-level `run_episode` API defaults to 200 decisions but keeps
  `max_input_tokens=None` for explicit legacy/non-Qwen callers. Frozen historical
  profiles and results are not rewritten. The older standalone JS demo is a
  separate runtime, not the current BrowserGym policy.
- Worker/runtime packagers include the template beside the tokenizer; Jinja2
  is a declared dependency. Existing installed workers need a rebuilt,
  validated package before these defaults become deployed behavior.
- Byte transport limits, daily financial/request caps, timeouts and session
  lifetimes remain separate guards. In particular, configure
  `DEMO_DAILY_CALL_LIMIT` to accommodate longer team runs; this change does not
  silently raise the shared daily quota or any money cap.

Validation is offline: deterministic request-count tests cover exact equality,
no cumulative/output cutoff, final answer/termination with no second check,
and successful verification when a subsequent input is blocked. Broker tests
cover 200 decisions, large batched summaries and four-digit observation names.
No model calls, worker restart or production rollout is part of this change.

Saved-request check: local counts matched provider-reported prompt tokens on
34 of 36 final requests from the capability suite; the largest difference was
253 tokens. This supports the estimator for those recorded requests, not exact
agreement across providers or image-processing configurations. Evidence:
`.local/review/input-limit-v1/saved-request-counts.json`.

## Curation launcher correction — September 27, 2026

User reaffirmed 200 model decisions for future runs, with token usage the primary
constraint. The completed `synthetic-glm-merchandising-v1` launcher carried an older
80-decision override; retain its historical settings and evidence. New curation
launchers should import `DEFAULT_MAX_STEPS` rather than copying that override, and
retain the agreed input limit unless separately changed. Decisions can contain several
tool calls; this is not a cap of 200 individual browser actions.
