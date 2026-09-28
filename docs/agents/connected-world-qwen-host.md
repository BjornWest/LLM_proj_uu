# Connected-world Qwen manual-review host

Status: additive preparation and scripted host acceptance in progress. No model
requests or graders are run by the preparation/rehearsal commands. The first batch
will be manually reviewed against frozen Product fact packets. The expanded bank is
14 proposed cases, not a paid run authorization or 14 successful agent solves.

## Ownership and input boundary

Product owns world/task data, manual references and the bounded clarification
responder. Curation owns `intent_browser/connected_world_task.py`, preparation and
scripted host acceptance. Backend owns the normal runner's clarification execution
and current observation integration. `with_clarification` and the native ask_user
schema are explicit additions; default profiles/tools remain unchanged.

The public task contains only schema/version, opaque task ID, user message, memories,
environment context and start URL. The goal contains the user message followed by
labeled public memories and environment context. Memories are delivered up front;
this is not a memory retrieval experiment. The normal runner retains the exact
requests, raw model output, reasoning/provider/usage fields and policy delivery.
No answer envelope, reference answer, match rule or private fact pack enters policy.
Nested memories/context are authored public data; the host checks reserved private
keys but cannot establish semantic privacy for arbitrary mislabeled prose.

Private source bytes and hashes are attached under `manual-review-private/` in the
trace. Do not publish that directory, the prepared case root or the whole trace as
policy-accessible website assets. Such attachments are for trusted manual review.
Preparing or copying them does not authorize website publication.

`natural-answer.json` retains the exact executed BrowserGym assistant chat message.
There is no JSON parsing, answer repair, LLM extraction or new grading call. Missing
answers, truncation and technical errors remain distinguishable in the trace. All
completion, authorization, exposure and safe-success labels remain null until review.
A scripted final message proves transport only, not correct shopping behavior.

## Clarification contract

The same `ask_user(question)` tool is proposed on every case, not just the hidden-size
case. Tool presence therefore does not identify the required behavior. It must end a
batch; dependent actions require a later model response. `send_msg_to_user` remains
terminal. Questions are not browser steps and must preserve browser, memory and history.

The trusted callback returns only a natural string. `execute_clarification` saves the
exact question/reply and errors, and rethrows failures without fabricating a response.
`PrivateClarificationAdapter` accepts Product's richer responder dict, saves audit
metadata separately and returns only `reply`. Product's hidden-size responder is
bounded English matching, not a general language model. Unsupported wording supplies
an unavailable response; inspect it as a simulator limitation, not automatic agent
failure. For tasks without additional hidden facts, the same unavailable reply is
used; the original public memories remain in context. Do not grade asking itself.

## Reproducible preparation and offline rehearsals

From the repository root:

```bash
.venv/bin/python -m scripts.prepare_connected_qwen \
  --bank .local/coordination/qwen-depth-readiness/manual-bank-v1 \
  --output .local/connected-shopping/qwen-manual-bank-NEW

LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
.venv/bin/python -m scripts.verify_connected_qwen_host \
  --prepared .local/connected-shopping/qwen-manual-bank-NEW \
  --output .local/connected-shopping/qwen-host-rehearsal-NEW
```

The preparation command validates pinned input bytes and Product's semantic public
hash, then emits a public task and private binding per case. Output directories must
be new; old cohorts remain untouched. `--binding` alternatively adapts the six earlier
structured cases, preserving their original bytes and omitting answer_contract only
in a separately recorded manual projection.

Browser acceptance uses separate nonpersistent contexts and at most two processes.
Published immutable world content is shared; this does not clone/reset server state.
No personal storage/auth is imported. Navigation is restricted to the declared world
origins, excluding private task inspectors; this is a document boundary, not a general
network sandbox. These research pages are not a checkout/purchase benchmark.

The local Chromium installation requires the existing cached shared-library path
shown above. The initial rehearsal without it failed on libasound.so.2; those failed
traces are preserved. No browser packages were downloaded or installed to repair it.

## Proposed first model settings and limits

`profile.proposed.json` captures selected nonsecret .env settings. At preparation:
Qwen `qwen/qwen3.8-27b`, Akash-first routing with the current six-provider fallback list,
reasoning enabled, temperature zero, 4096 total output tokens per request (reasoning
and answer share the cap), 200 model turns, and 100000 locally estimated input tokens
per request using the Qwen tokenizer/template. Hosted token accounting can differ.
Session ID is the trace episode ID; provider affinity is not guaranteed.

Current standard incremental AX, image tools and data tools are retained; helpers
are explicitly disabled for this proposed baseline. No Parallel search, client retry
or decision retry. Two independent episodes may run concurrently; video is proposed.
Freeze actual runtime/tool schemas and source hashes after the backend increment
settles, before paid execution. Capture actual provider costs including unknown usage.
There is no live API dispatch command in this preparation/rehearsal tool.

Six-case original smoke: `.local/connected-shopping/qwen-host-rehearsal-v2/report.json`
passes all six with zero action errors and unchanged sources during execution. This
checks initial task/memory delivery, native AX query and exact natural answer capture,
not full task solving. Expanded bank and clarification acceptance follow separately.

## Calling the ordinary runner

The host adapter accepts an already configured backend; it does not select a second
answer model or change the backend settings. A future authorized caller can use:

```python
from intent_browser.connected_world_task import load_prepared, TERMINAL_INSTRUCTION
from intent_browser.runner import run_episode

task, profile, responder = load_prepared(case_directory, clarification=True)
trace, summary = run_episode(
    task.make_env, backend,
    {"source": "connected-world-manual-v1", "training_eligible": False},
    output=output_directory, episode_task=task, harness_profile=profile,
    terminal_response_instruction=TERMINAL_INSTRUCTION,
    clarification_callback=responder,
    max_steps=200, max_input_tokens=100_000, record_video=True,
)
```

The backend must support native tools and image input, use reasoning-enabled Qwen
settings, and retain actual request/response/usage data. Freeze settings and case list
before invoking this. The example is an API usage pattern, not an executed paid run.

## Accepted host evidence and remaining limits

- Prepared expanded bank: `.local/connected-shopping/qwen-manual-bank-host-v2/`.
  Its `public_sha256` is file-byte SHA256. Upstream private packet public_sha256 is
  canonical JSON digest; both encodings are checked separately. The initial adapter
  incorrectly compared these; the incomplete v1 host output is retained, bank unchanged.
- Isolated host source: `.local/connected-shopping/qwen-host-source-v1/`, with exact
  source-map.json. This avoids inheriting ongoing backend observation edits.
- Final 14-case scripted intake: `.local/connected-shopping/qwen-bank-rehearsal-v2/report.json`.
  Every case has correct policy/memory delivery, native tools, an unchanged source set,
  exact natural terminal text, fresh browser storage and unknown outcome labels. D08
  asks for size and receives only the permitted natural reply before continuing.
- Additional exchange/error boundaries and final configuration are recorded in
  `.local/connected-shopping/qwen-readiness-v1/`.

Failure rehearsal exposed BrowserGym's built-in assistant greeting. The adapter now
records initial chat at reset and excludes that prefix from model-answer capture;
only later executed messages count. The old reply-failure-v1 trace retains the bug,
not a claimed model answer. Regression checks preserve missing answers on failures.

This is host readiness for the finite manually reviewed bank, not evidence of model
competence, a complete automatic grader, arbitrary-seed world correctness or server
clone isolation. The proposed source snapshot does not silently adopt later opt-in
observation changes. New settings need their own explicitly identified run profile.

Current final offline summary: `.local/connected-shopping/qwen-readiness-v1/acceptance.json`
(16 scripted cases, 611 retained artifact hashes, one common tool schema); separate
video evidence is `qwen-video-smoke-v1/report.json`. Fourteen focused curation unit
checks pass. Earlier 14-case source set was checked out of an actively changing
workspace; final acceptance uses the immutable source snapshot named above.

**Dispatch deferred:** the subsequent FOOTWEAR-DEPTH-20260926 request requires a
richer footwear preview before model testing. Do not relabel these v7 host rehearsals
as acceptance of that upcoming world, and do not silently replace the prepared cases.
