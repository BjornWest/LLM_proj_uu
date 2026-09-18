# Find useful moments in saved browser runs

**Local MVP available — 18 September 2026.** Development resumed at the user's
request. It is ready for trial use on saved evaluation runs; detector usefulness,
taxonomy and review effort still need feedback on more varied traces.

[Open the current 45-episode MVP](http://localhost:8876/trace-triage-mvp-v3/index.html).
It includes the earlier sweep and three saved native-tool harness probes. This is
local tooling, not a deployed Vercel feature. No new model calls were used.

Token, cache and reasoning summaries now retain missing-data coverage, resolved
model/provider information, and configurable flags. Token totals are reported by
the provider using the resolved model's native tokenizer; they are not character
estimates. Sort by total or reasoning tokens, or filter the suggested review queue.

The local trace-triage tool groups saved runs, flags moments worth reviewing,
and compares failures, unknown outcomes, and successes with other recorded
successes of the same task. Those references are not automatically trusted.
It does not execute the agent, call a model, or change a task's grade.

## Audit apparent successes too

Success auditing is a core use case, not just finding successful comparisons for
failures. A recorded pass can hide leaked answers, a verifier loophole, an
unauthorized effect the verifier missed, or state left over from another run.
Keep the recorded grade and the review conclusion separate.

The MVP includes successful runs in flags, groups, comparisons and reviewed
cases. It flags recorded contradictions, completion despite errors, and completion
without a parsed state-changing action. A deterministic control sample also
selects apparent successes regardless of flags. Reviewers can record a separate
scoped integrity assessment with cited evidence. Unusually short solutions are another useful manual review candidate; automatic
short-route outlier detection and automatic leakage detection are not implemented. These are pointers, not proof of exploitation.
Also sample ordinary-looking successes: leakage may produce a normal trajectory.

Reviewers should check the actual outcome evidence, what information reached the
policy, and whether the behavior violated an explicit task or access constraint.
A valid shortcut is not a loophole just because it differs from the expected
route. Skipping an optional information page remains a procedure observation,
not an outcome failure. Suspected invalid successes need review before being
promoted to teacher examples or used as evidence that training improved behavior;
the tool does not currently enforce that gate.

[Open the first 42-run analysis](http://localhost:8876/trace-triage-v2/index.html).
This is a local preview, not a deployed Vercel feature.

There is also a [reviewed-case library](http://localhost:8876/reviewed-cases-v3/index.html)
for finding prior diagnoses by tags or causal type. It currently contains P07,
with its unresolved cause clearly marked. [Annotation/search guide](../data/curation/review_annotations/README.md).
Agents can add descriptive tags while keeping assigned causes and alternative
hypotheses separate. Similar cases are examples to investigate, not labels to copy.

## A useful review workflow

1. Filter by task, outcome, error, detector flag, or trajectory neighborhood.
2. Select a run. Its recorded result stays separate from the review flags.
3. Use **Review step** to jump to a suspicious decision. Inspect decision text
   and the state after the action. **Full trace / screenshots** opens the existing
   detailed trace viewer.
4. Examine a recorded-success comparison, including when the selected run passed. The page aligns actions using target labels
   and surrounding named elements, instead of changing element IDs. It marks
   the first different action and differences in observations/results before it.
5. Open the exact saved request/response for a suspicious step, without reading
   the entire steps log. Give the **Codex review packet** to a reviewer. It points to exact evidence
   while retaining the complete compact timeline. Save diagnoses separately.

For example, our shopping failures repeatedly add the same laptop. A successful
run starts with the same actions but moves to the cart. That divergence is a
useful place to investigate. It does not establish that the deceptive warranty
caused the failure: these failures occurred before actual warranty exposure.

If a task has no successful run in the collection, the tool says so. It never
substitutes an unrelated task. Comparisons disclose differences in goal,
clean/deceptive condition, model and runtime.

## Pointers, not diagnoses

Repeated clicks might be a loop, a valid quantity request, or recovery. A page
notification is observed feedback, not transaction proof. Text in an input does
not prove the model understood it. Successful runs can have flags too.

The initial detectors cover action/decision errors, truncated output, repeated
actions and AX states, reused/missing target IDs, and alert/status feedback
missing from the next request. Failed recorded checks and step limits are also
surfaced. Outcome, behavior, and suspected cause remain separate.

## Analyze another collection

You can now ask a Codex agent to use the repository skill:

> Use $browser-trace-triage on .local/preflight/harness-suite-v3. Group the runs,
> identify suspicious successes and expensive traces, and review a few useful
> representatives. Save evidence-backed annotations; do not rerun the model.

The skill lives in [.agents/skills/browser-trace-triage](../.agents/skills/browser-trace-triage/SKILL.md).
Its query helper returns small filtered lists, group summaries, nearest same-task
trajectories and focused comparisons. It keeps full requests out of the agent's
context until needed. Grouping is descriptive: the agent still checks individual
evidence before assigning causes or calling a success invalid. Neighborhoods
overlap, so their counts must not be added as separate failure populations.

The [new 15-condition harness cohort](http://localhost:8876/trace-triage-harness-baseline-v1/index.html)
is available as a skill-use example. It preserves 14 scoped safe successes and
one unknown. The P10 clean run is easy to locate by token usage/state-revisit flags;
those flags identify a useful inspection target, not the explanation for its path.
There are no exact-task comparison pairs inside this one-repeat cohort. Add a
later iteration of the same task IDs to compare harness changes; old reduced
fixtures and restored full sites should not be treated as a controlled baseline.

Run from the repository root, choosing a new output path:

```bash
python3 -m data.curation.trace_triage.run \
  --suite data/curation/sweeps/external-baseline-v1 \
  --viewer-url http://localhost:8878 \
  --output .local/review/my-triage
```

For the new harness development suites, the same command accepts their case format:

```bash
python3 -m data.curation.trace_triage.run \
  --suite .local/harness-suites/YOUR-SUITE \
  --viewer-url http://localhost:8878 \
  --output .local/review/YOUR-SUITE-triage
```

Repeat `--suite` to compare iterations. Use `--runs-root DIRECTORY` to discover
finished episode records recursively, or give individual episode directories.
Suite intake skips unfinished case records and records that decision; direct
paths can inspect interrupted traces. Each export needs a new directory and never
modifies the original runs. Hash inventories are checked when a suite provides them.

Or replace `--suite ...` with one or more `runs/EPISODE_ID` directories. Open the
generated `index.html` directly or through the local review server. Start the
existing screenshot viewer with `.venv/bin/python scripts/view_traces.py`.

Outputs include the index, structured analysis, Codex packets, blank diagnosis
templates, exact copies of consumed evidence, and hashes. They may contain private
task text/model inputs; they are not automatically sanitized or published.

Review outcomes and tags: copy a generated `diagnoses/KEY.json` to a new review
path, fill its reviewer/evidence fields, and run:

```bash
python3 -m data.curation.trace_triage.annotations \
  --triage .local/review/YOUR-SUITE-triage/triage.json \
  --diagnosis PATH-TO-YOUR-REVIEW.json
```

The `integrity_review` block is separate from causal failure labels. Use
`no_issue_found_in_scope`, `suspected_issue`, `confirmed_issue`, or `inconclusive`,
with a scope and artifact/hash references. A recorded pass is never overwritten.
The [annotation guide](../data/curation/review_annotations/README.md) explains tags
and building/searching the reusable reviewed-case library.

This version supports our local BrowserGym traces, including native-tool runs. It does not yet consume
browser-side website traces, run Codex automatically, or attach labels to training
data. [Technical guide and review rubric](agents/failure-triage.md).
