# Reasoning enabled for new OpenRouter runs

Bjorn requested reasoning on globally by default after inspecting the earlier
warranty requests. That run explicitly disabled reasoning; its original requests,
profiles, traces, grades and spending reservations remain historical evidence.

## Python request contract

- `provider_options()` now sends `reasoning: {enabled: true}`.
- Direct OpenRouter `ChatCompletionsBackend` clients also get that default,
  including legacy preset clients. Explicit caller-supplied reasoning settings
  remain explicit overrides. Other API endpoints receive no OpenRouter-specific
  reasoning field automatically.
- The default OpenRouter completion ceiling is **4096**. The CLI resolves an
  explicit `--max-tokens` first, then `OPENROUTER_MAX_TOKENS` (including an explicit
  `--env-file`), then 4096. `completion_token_limit(value)` provides the shared
  positive-integer validation/default for other consumers. Non-OpenRouter CLI
  and generic backend defaults remain 128.
- The default does not force a particular reasoning effort or reserve a fixed
  thinking-token allocation. A provider must support the requested settings.
- The final response `content` alone becomes the browser action. Raw reasoning,
  reasoning details, usage and finish reason remain in the retained response.
  Empty final content, including reasoning-only truncation, is not converted
  into an action and does not trigger an automatic retry.

OpenRouter states that reasoning usually counts against the same `max_tokens`
ceiling as the visible answer; a small limit can be exhausted before any answer
is produced. This is why simply retaining the old 128/512 ceiling is inadequate
as the new general default. 4096 is a project default, not a guarantee that every
task/provider finishes within it. See the [official reasoning-token guide](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#reasoning-tokens-and-max_tokens).

## Budgets and experiments

Total authorized caps are unchanged. Every budgeted entry point must reserve
against the completion ceiling it actually sends; changing output defaults must
not leave a broker reserving for 512 while a worker requests 4096. A larger
completion ceiling can reduce the number of requests that fit a capped ledger.
Do not reset or refund historical reservations to compensate.

Historical calibration wrappers and original smoke protocols are frozen. Some
explicitly disable reasoning and retain their old output settings; they are not
the recommended entry points for new work. Existing source fingerprints will
reject changed shared code. Freeze a new profile with explicit reasoning and
output settings before a new cohort; do not relabel earlier results.

## Verification and rollout boundary

`tests/test_reasoning_defaults.py` exercises actual HTTP request construction with
MockTransport: direct/routed/preset defaults, explicit overrides, local endpoint
isolation, final-content-only action parsing, retained reasoning-only failures,
and CLI environment/argument precedence. These checks make no provider calls.

The deployment owner coordinates the separate Daylight JavaScript default,
demo/team consumers, broker reservations, Vercel publication and PC worker
replacement. A host source edit alone does not update an already-running worker
image. Current ownership and rollout evidence are recorded under
`.local/coordination/reasoning-default.md`; offline checks do not establish live
provider compliance or deployment state.
