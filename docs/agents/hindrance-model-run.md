# Hindrance model runner

`scripts/hindrance_model_run.py` runs a finite manifest through the ordinary
native-tool harness. It uses OpenRouter `qwen/qwen3.8-27b`, temperature 0.6,
top_p 0.95, top_k 20, reasoning enabled and a 16,384-token output limit.
Routing uses the existing OpenRouter provider defaults (Akash first, with the
configured capacity fallbacks). There are no automatic retries or formatter
calls. The default concurrency is eight separate worker processes, each owning
its browser and HTTP client. Use lower concurrency for large worlds.

## Inputs and grading

The BUILD manifest has a `tasks` array; an `entries` array or a bare array is
also accepted. Each entry has `task_id` (or `id`), `tier`, `mechanism`, `clean`,
`twin_id`, `world_dir`, `instance_path`, `recipe_path` and `request_text`.
Paths can be absolute or relative to the manifest directory. BUILD's `variant`
object describes the product and is retained as `product_variant`; output
`variant` is `trapped` or `clean`.

Recipes use BUILD's `scripts.hindrance_suite.prepare_task`, `CleanGrading`,
`browser_policy` and `finish_order` APIs. Integrate the BUILD worker's reviewed
helper alongside this runner before launching the new suite. The helper owns
the native order capture and reference binding. The runner requires the
manifest request to agree with the prepared request.

For a trapped recipe, the result conjoins the native mechanism verdict and
the simulated-order component (SKU, quantity, address and cheapest home
delivery). For a clean twin it uses the native order component. Whole-run
effect authority remains unknown. In particular, the native raw order grade
can be inconclusive about effects while its scoped order component passes.

Frozen development instances can omit `recipe_path`. They run through
`commerce_scenarios.publication.prepare_episode` and `CommerceGrading`. An
optional `offer_id` selects a consent/extras shopping target. These retain the
native mechanism scope: consent/extras do **not** assess order contents.
Historical steering instances may fail native reference/source validation;
this runner does not rewrite or bypass their binding.

## Launch

Use the shared virtual environment, a compatible `agent_trace` checkout, and
local tokenizer assets. On this workstation:

```bash
export PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016"
export LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu
export TASK_SOURCE_BINDING=current
```

The runner defaults `HARNESS_AX_TOKENIZER` to
`.local/model-tokenizers/qwen3.8-27b-1d4bf0f2/tokenizer.json`. The full tokenizer
bundle (including template/config files) must be available locally. No assets
are downloaded by the runner. The old `common_agent_util` checkout lacks the
`is_scripted_run` viewer API required by this harness.

Offline controls use the actual browser with an HTTP mock and carry the
`scripted` metadata tag:

```bash
DISPLAY=:99 python3 scripts/run_bounded_job.py --memory-mib 8192 --tasks 0 -- \
  /home/bjorn/code/LLM_proj_uu/.venv/bin/python scripts/hindrance_model_run.py \
  --manifest PATH/manifest.json --output PATH/offline --offline --concurrency 2
```

After finite episode authorization, a real run uses the existing dotenv file
without copying or printing its key:

```bash
DISPLAY=:99 python3 scripts/run_bounded_job.py --memory-mib 4096 --tasks 0 -- \
  /home/bjorn/code/LLM_proj_uu/.venv/bin/python scripts/hindrance_model_run.py \
  --manifest PATH/manifest.json --output PATH/one-model-episode \
  --providers chutes,akashml \
  --env-file /home/bjorn/code/LLM_proj_uu/.env \
  --episode EXACT_TASK_ID --limit 1 --concurrency 1
```

Outputs must be new directories. `--episode` is repeatable; `--limit` applies
after filtering. Defaults are no decision cap and a 150,000-token request input
budget. Set explicit `--max-steps`, `--max-total-input-tokens` and
`--max-total-output-tokens` for a finite authorized run. A failed real
attempt is consumed; it is not automatically relaunched.

Qwen runs default to `--providers chutes,akashml`; an explicit provider list
overrides that hindrance-runner default. `--bridge gpt-6.1-sol` selects the Codex
subscription transport instead and makes no OpenRouter calls.

`--context-keep-turns 4` opts into a four-decision window for browser evidence,
including large historical `ax_read` results. Zero (the default) keeps full
history. Actions, assistant notes/reasoning, user goals, human messages and
tool-call IDs remain. Omitted spans are marked and removed from subsequent
delivery bindings; original requests remain in the trace. Cross-page AX
description reuse is disabled for windowed runs, and AX page updates/search/read
repeat fields by default (including text ranges), so observations do not depend
on omitted descriptions. The agent can read current page content again.
An explicit `repeat:false` asks AX to suppress previously acknowledged fields;
use `repeat:true` to retrieve any such fields after history eviction.

Input-budget preflight avoids tokenizing text history when a conservative
UTF-8 byte bound plus usage-backed opaque reasoning fits the limit. Images and
requests near the limit use the existing Qwen template estimator. Trace
`input_budget` explicitly identifies this bound; it is not a prompt-token
measurement. Use response `usage.prompt_tokens` to compare actual model inputs.

## Outputs

The output root contains `launch.json`, append-only terminal `results.jsonl`
and an updated `summary.json`. Each `episode-NNNN` directory retains the input,
runner log, normal `runs/TIMESTAMP-ID/` trace, native automatic grading/viewer
artifacts, `grade.json`, `result.json`, and real-provider `usage.jsonl`.
BUILD recipe traces also have `suite-order-grade.json`.

Usage retains every response's original `usage` object plus provider/model,
response ID and HTTP status. Totals include prompt, completion, cached prompt
tokens and reported USD cost. Missing metrics remain null and have missing
response counters. The cache percentage is the token-weighted fraction of
cached prompt tokens on responses reporting both cached and prompt counts;
it is not a claim about cache continuity after a provider fallback.
`side_effect_rate` uses only episodes with a native committed-effect verdict,
with the assessed count reported separately. Infrastructure failures and
inconclusive grades remain in pass-rate denominators.

Private fact recording is requested by default using the existing native DOM
probe wrapper. The source pins are retained in trace metadata. Per-episode
`fact-recording.json` reports actual enablement, captures and pairing failures;
unsupported setup records the reason and proceeds once without recording.
`--no-fact-provenance` is an explicit off switch. These captures do not change
task grades or establish complete source coverage.

A complete native grade can coexist with a policy transport or cleanup error.
Such episodes retain `status: graded`, their native (usually inconclusive)
verdict and `policy_error`; `infrastructure_completed` and `safe_success` remain
false/null as appropriate. A real finalization failure is reported separately
as `status: grading_error`, an inconclusive grade and the precise error.

Recover previously completed grades misclassified by the old caller into a
new directory, without browsers, inference or historical trace edits:

```bash
/home/bjorn/code/LLM_proj_uu/.venv/bin/python scripts/recover_hindrance_grades.py \
  --cohort PATH/old-run --output PATH/recovered
```

`--cohort` is repeatable. This verifies the saved native grade and binding
digests, then recovers that grade. It does not rerun native grading, upgrade
interrupted policies or invent a missing order projection.

Focused tests:

```bash
/home/bjorn/code/LLM_proj_uu/.venv/bin/python -m pytest \
  tests/test_hindrance_model_run.py tests/test_hindrance_context.py \
  experiments/commerce_dark_patterns/test_automatic.py tests/test_automatic_grading.py -q
```
