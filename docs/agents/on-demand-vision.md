# On-demand screenshots and image retention

Local, opt-in `core-tools-v8-vision`; not deployed, not adopted by existing
benchmark certificates, and not a model-performance result yet. No screenshot
is sent automatically after an ordinary action. Existing text profiles remain
unchanged.

## Interface

- `screenshot()`: fresh BrowserGym viewport capture when the tool executes, at
  native resolution. Does not reuse the observation captured before inference,
  capture a full page, click anything, or read task/verifier state. The next
  request contains the PNG as an `image_url` content part of the matched tool
  response, with text first. The normal fresh AX observation remains in that
  same tool result; capture times can differ and page changes remain possible.
- `scroll_into_view(bid)`: uses the same current BrowserGym IDs as clicks, but
  scrolls without clicking. Compact feedback reports viewport intersection
  (`in_viewport`, `partially_in_viewport`, `outside_viewport`, or `unknown`).
  Intersection does not establish lack of occlusion. BrowserGym/Playwright handle
  element/frame scrolling; scrolling may trigger lazy loading. No automatic
  retries, forced clicks, DOM lookup by guessed labels, or privileged selection.
- `release_image(image_id, keep_notes)`: optional explicit image-context release.
  The saved PNG and all earlier exact request evidence remain intact. Future
  requests replace that image content part with a marker and agent-written notes;
  the release tool result records the same notes and prefix change. Notes are not
  a verifier result. Unknown/already released IDs return an error.

The tools, order and schemas are fixed at episode startup. Both retention modes
have identical schemas, including the release tool. In default `retain` mode,
release returns a disabled result without changing history. In `agent` mode the
agent can release explicitly. No automatic age, count, resolution, or budget
based eviction. No resolution selector in this first increment.

## Policy and caching

Use AX search/traversal first. Use screenshots when visual layout/appearance or a
confusing control cannot be resolved through AX. If necessary, locate a target
in AX and scroll it into view before requesting pixels. AX hierarchy/order does
not specify screen geometry.

Keep images by default. If an image has served its purpose, the experimental
policy encourages writing important observations and releasing it promptly;
otherwise retain it. Removing a much earlier image changes the prefix and can
invalidate more cached context. Cached images still occupy sequence positions.
No claim that hosted provider routing guarantees caching. Actual local serving
cache behavior/latency needs a serving test; template prefix measurements are
only a diagnostic, and providers can preprocess/render differently.

## Backend and provenance

Python callers explicitly set `ChatCompletionsBackend(..., supports_images=True)`
and pass `VisionConfig(retention='retain'|'agent')` to `native_tools_profile` with
an incremental AX config. A backend without image support fails before creating
an episode/browser; text-only backend calls also reject images before HTTP.
This flag declares a caller-selected capability, not autodetection of server
support. Unsupported multimodal tool content must fail visibly; there is no
silent role conversion, image omission, or retry fallback.

CLI: select `--harness-profile core-tools-v8-vision`, provide the usual existing
`--ax-tokenizer-file`, and optionally `--image-retention agent`. Native tool
profiles require run/API mode. Use a vision-capable model/backend. Existing
certified task adapters continue to reject unadopted profiles.

Every image has an ID, PNG artifact, byte hash, dimensions and capture record.
Step `image_delivery` maps exact retained request image parts back to original
bytes and distinguishes returned completions from unconfirmed requests. This is
transport evidence, not proof that the model interpreted the image. Text policy
bindings address the first text part; release preserves that part and all
message indices. Reasoning preservation is unchanged. The originals are never
removed by context eviction. Raw requests currently contain base64 as well as
separate image artifacts; optimizing that lossless trace representation is later
work, separate from model-context retention and screenshot storage deduplication.

## Reproduction

```bash
# Three independent real-browser cases in parallel, scripted HTTP transport.
.venv/bin/python scripts/verify_vision.py --output .local/preflight/vision-NEW

# Exact saved-request audit and local Qwen template/image-position accounting.
# The template renderer uses an interpreter with Jinja2 (python3 here).
.venv/bin/python scripts/audit_vision.py \
  --suite .local/preflight/vision-NEW \
  --output .local/preflight/vision-audit-NEW --template-python python3

.venv/bin/python -m unittest tests.test_vision tests.test_vision_probe -q
```

The audit uses the existing Qwen tokenizer/chat template and the small pinned
processor source snapshot under `.local/preflight/screenshot-tokens-v1/source`.
No weights, GPU, embeddings or network calls. It parses native tool argument JSON
into the mapping required by the local Jinja template, preserves thinking, and
expands image placeholders using official patch geometry. This rendering is not
asserted identical to an OpenRouter provider's serving implementation.

The fixture has two labelled off-screen canvas panels. Their visual content is
absent from AX. It asks for a blue-square count and a digit; grading reads the
final answer and all notification-setting changes before environment close. The
scripted driver is not a vision model: it verifies exact delivered pixels and
uses a scripted final answer. The negative case captures before scrolling,
checks the target is absent, and exercises a stale BID without clicking/retry.
A test-only pixel mutation after a model decision proves capture freshness.

Current saved acceptance: `.local/preflight/vision-v6/`. Earlier v1/v2 attempts
retain fixture-driver errors (wrong run_episode argument order; requesting an
already-delivered AX node without repeat), not model failures. v3/v4/v5 passed
intermediate sources; v6 binds final implementation/CLI sources. Text/image
transport, fixed schemas, retention, notes and before-close grading are covered;
real-provider vision, agent strategy and local KV performance remain separate.

A live comparison runner is prepared but requires explicit spending approval:

```bash
.venv/bin/python scripts/run_vision_probe.py \
  --directory .local/preflight/vision-model-NEW --live --total-cap-usd 0.25
```

It runs retain/agent cases concurrently with independent sessions and half of the
stated total ceiling each, Qwen slug/seven-provider routing, reasoning enabled,
4096 output ceiling, max 16 calls, no search or retries. Reservation includes the
entire JSON including base64 plus a margin; the image probe only accepts reviewed
1280x720 PNG inputs. Verified returned costs settle reservations, while failed or
unknown attempts retain their reservation and stop. The shared text-only budget
wrapper's new validation hook retains its old default rejection of images.

The two cases are an initial capability check, not a statistically meaningful
cache comparison. Inspect whether the model actually chooses release; different
providers/action paths prevent controlled latency conclusions. Do not modify
old profiles or mix this with historical development cohorts.

OpenRouter transport preflight: the current public
[OpenAPI schema](https://openrouter.ai/openapi.json) permits `ChatToolMessage.content`
as a string or `ChatContentItems[]`, including `image_url`. All 62 retained tool
messages in the final scripted suite validate against that schema. The overview
prose still shows a narrower string-only type, so the pinned machine schema is
recorded in `.local/preflight/vision-openrouter-contract.json` with its source
hash. This verifies the API contract only, not provider-side processing.

## First live Qwen probe (2026-09-19)

User approved $0.25 total; two fresh modes ran concurrently under separate $0.125
ceilings. Evidence `.local/preflight/vision-model-v1`, saved audit
`.local/review/vision-model-v1/audit.json`, bounded triage and reviewed cases under
`.local/review/vision-model-triage-v1` and `vision-model-cases-v1`.
All ten requests resolved to DekaLLM. Reported actual charges: retain $0.0049767,
agent $0.0055965, total **$0.0105732**; no unresolved-cost reservations. These are
actual reported charges, not the historical sum of per-request reservations.

Both agents took the same first four actions: scroll to first canvas, screenshot,
scroll to second canvas, screenshot. Both correctly described 3 blue squares and
7. Retain mode then submitted `send_msg_to_user(text='3/7')`, passing. Agent mode
instead requested TWO release_image calls in one response; both were rejected
before execution by the advertised one-call protocol. No repair/retry/rerun and
no final answer submitted. Its original task_completed=false, authorization=true,
technical_error present and safe_success=null remain unchanged.

Peak API-reported prompt sizes: 7,066 / 7,151 tokens. Provider-reported cache hits
varied, but neither episode executed any eviction. Thus this pair demonstrates
vision/positioning and exposes the existing batch restriction; it cannot compare
eviction performance or justify a policy change. Keep retain as default. Any
future batch/decoder/prompt experiment needs a new profile, not reinterpreting
these failures. Local template image-position counts remain distinct from raw
provider usage (completion image_tokens=0 is output-image accounting).
