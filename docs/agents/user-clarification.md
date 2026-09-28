# Opt-in user clarification

`with_clarification(profile)` adds the native `ask_user(question)` tool. Pass the
resulting profile and a trusted `clarification_callback(question: str) -> str` to
`run_episode`. An optional `clarification_audit_id` identifies the caller's private
reply contract. It is recorded in metadata and artifacts, never supplied to policy.
The task adapter must explicitly accept the resulting profile name as usual.

```python
profile = with_clarification(profile)
run_episode(
    env_factory, backend, metadata,
    harness_profile=profile,
    clarification_callback=respond_to_question,
    clarification_audit_id="my-reviewed-reply-contract",
)
```

A callback is required before inference starts. Supplying a callback without the
opt-in tool profile is an error. Ordinary profiles, prompts and tools are unchanged.
This is a local runner capability; no deployment/UI responder was added.

## Execution and evidence

- `ask_user` does not call `env.step`, validate the task, award a reward, terminate
  the episode or reset its browser. The reply becomes a native tool result in the
  existing conversation. `send_msg_to_user` remains the final-answer tool.
- A question must be the final call in a batch. Invalid ordering is rejected
  before any member executes. A valid question ends the batch with
  `clarification_boundary`; dependent actions require another model turn.
- The callback receives the exact question and returns a nonempty string. Its
  verbatim answer bypasses page-feedback compaction. It is not interpreted as a
  preference, permission or grading signal by the runner.
- `clarification-NNN.json` retains the question, exact reply, audit ID, start/end
  timestamps and any callback error. The step points to that artifact, including
  when the callback fails. Callback failures are technical failures; there is no
  implicit retry, fallback answer or replay of preceding browser actions.
- `clarification_result` policy evidence binds the exact feedback span to the
  subsequent retained model request and completion acknowledgment. Producing a
  reply is not proof that the next request consumed it. For example, a reply at
  the episode's last permitted step remains saved but has no confirmed delivery.
- When helpers are enabled, they inherit the explicitly supplied callback and
  write evidence in their own episode. The host owns responder behavior and
  availability. Callbacks run synchronously on the runner's owning thread; no
  human-response transport, timeout or asynchronous UI is introduced here.

## Validation

Offline runner tests cover exact reply/delivery, unchanged request prefix/tool
registry, batch ordering, disabled/misconfigured tools, callback failures without
retry, unconsumed last-step replies and evaluation-before-close. Regression tests
include native tools, batching, policy delivery, decision retry and delegation.

```bash
.venv/bin/python -m unittest tests.test_runner_clarification tests.test_clarification \
  tests.test_native_batch tests.test_policy_delivery tests.test_native_tools \
  tests.test_decision_retry tests.test_delegation
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python scripts/verify_runner_clarification.py --output .local/clarification-new
```

The browser script uses real BrowserGym/Chromium, native batches, incremental AX,
compact feedback and a scripted HTTP transport. It exercises a successful callback
and a failed callback; no external inference occurs. Its output path must be new,
and source hashes are checked before/after execution. Current acceptance:
`.local/clarification-runner-v2/report.json`. Historical v1 precedes the added
policy-source artifact link and is not current-source execution evidence.
