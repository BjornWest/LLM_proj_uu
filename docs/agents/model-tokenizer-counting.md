# Model-matched input limits

OpenRouter episodes must size their complete next request with the policy
model's official tokenizer and chat template. The AX tokenizer controls the
size of browser observations; it does not select the policy tokenizer.

`intent_browser.model_input_budget.model_matched_input_counter(backend,
ax_tokenizer_path=..., assets_root=...)` returns the normal callable counter,
including the existing usage-backed opaque-reasoning wrapper. Explicit
`run_episode(input_counter=...)` remains authoritative. Unsupported OpenRouter
models and missing or mismatched assets fail locally before provider dispatch.
There is no automatic download or cross-model fallback.

The registry is `intent_browser/model_tokenizers.json`. It currently pins
official Qwen3.8-27B and GLM-5.3-Flash revisions, tokenizer/template hashes, and
GLM's image-processor configuration. Install tokenizer assets only (no weights):

```bash
python3 scripts/fetch_model_tokenizer.py z-ai/glm-5.3-flash
python3 scripts/fetch_model_tokenizer.py qwen/qwen3.8-27b
```

The default location is `.local/model-tokenizers/`. Frozen evaluation releases
must explicitly supply/pin this external asset root along with the registry and
counter sources; never substitute mutable development imports into a running
suite. New model adoption adds an official repository/revision and exact assets
to the registry, verifies its template against retained provider-reported usage,
and records any discrepancy before dispatch. Model aliases require explicit
bindings rather than guessed tokenizer families.

The Qwen counter renders the actual enabled/disabled reasoning setting and
the model's supported effort (`xhigh`, `medium`, `low`); unsupported effort
settings fail rather than silently sizing the default mode.

Counts cover the full next input, tools, retained reasoning and supported image
content. They are not cumulative episode usage and do not reserve output tokens.
Hosted providers can alter templates or image processing, so local counts remain
qualified estimates; completed-request provider usage stays authoritative.
GLM image sizing follows the official Glm5Next processor's aligned patch budget;
video/audio and remote image retrieval are unsupported by the current counter.

GLM's official JSON is loaded through semantic JSON reserialization for the
installed tokenizers0.23.2 compatibility; raw downloaded bytes remain pinned and
unchanged. No vendor code or model weights execute during loading.

For the retained grip-review GLM run, the official tokenizer/template matches
all20 completed provider prompt counts exactly. Its blocked next request is
29,132 GLM tokens; the historical Qwen proxy estimated32,749. Historical trace,
grade and guard decisions remain unchanged. Counter qualification does not
authorize another model episode.

MiMo V2.6 Pro uses the official XiaomiMiMo/MiMo-V2.6-Pro-RL tokenizer, chat
template and Qwen2VL processor configuration. Its explicit registry entry supports
text, function tools, retained reasoning, and local PNG/JPEG images. Remote images,
audio/video and mixed content-part shapes reject locally. Install with
`python3 scripts/fetch_model_tokenizer.py xiaomi/mimo-v2.6-pro`.
Hosted prompt counts remain authoritative; local MiMo counts are qualified estimates
until compared with the selected provider. The evaluation case retains the original
18-comment world and tools, with a 32,000-token official-MiMo input guard.
