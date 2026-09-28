# Dataset production protocol

Status: proposed operating protocol, 2026-09-20. Apply to the next explicitly
scoped expansion batch; this does not change historical acceptance, active
certificates, agent configuration or authorize model/browser expenditure.
Goal: reduce total model usage per accepted task without admitting broken tasks
or misleading rewards. Evaluate savings including reviewer work and rework.

## Model selection: choose by uncertainty and consequence

These are initial routing hypotheses using models exposed in this session, not
measured price/quality or subscription-quota guarantees. Record actual model and
effort, and revise after a small pilot. Do not silently fall back to a flagship.

| Work | Initial assignment | Escalate when |
| --- | --- | --- |
| Hashing, schema/ID checks, catalog joins, known grader replay, report aggregation | Existing deterministic scripts; no agent reasoning per row | A check fails or coverage is absent |
| Inventory extraction, parameter instances, selectors, setup from an accepted recipe, grading code from an explicit predicate | Temporary `gpt-5.6-luna`, medium effort | Two unsuccessful repair attempts, missing contract information, or a new state/grading mechanism |
| First adapter for a normal site/family, cross-file implementation, ordinary browser debugging | `gpt-5.6-sol`, medium effort | Unclear goal, inconsistent site/source data, reset uncertainty, new reward semantics |
| Contract interpretation, authorization boundaries, reward loopholes, difficult infrastructure diagnosis, acceptance disputes | Lead `gpt-6-astra`, high effort | User decision is required about scope/intent or resources |

A simple-looking money/subscription check can require the strongest tier if its
meaning is unclear. A long inventory can require no model once parsing exists.
Do not disable the browser policy's reasoning or change inference routing under
this protocol: these tiers concern Codex production agents only.

Writing a grader is not permission to define success. A worker may translate an
approved predicate into code, but must not narrow the goal, normalize an exact
answer, ignore an extra effect, or convert unknown coverage into a pass. A failing
control cannot be fixed by weakening the assertion. Return the counterexample.

## Hierarchy and context

Default topology: lead -> short-lived implementation workers. Use lead -> family
lead -> workers only when the family lead owns several independent implementation
units and can resolve routine issues without forwarding every result upstream.
The middle role must produce a reusable contract or adapter, not merely relay
messages. Tier is a responsibility, not a requirement for another agent thread.

The current tool surface permits child agents to delegate and explicit model/
effort selection. This session has four concurrency slots INCLUDING the root:
root + family lead + two workers fills them; root + two family leads leaves one
worker slot. A flat root + three workers is often the better arrangement.
Nested execution has not been benchmarked here. Use a flat fallback if the actual
runtime cannot create grandchildren; do not launch a second independent session
as a workaround. Do not change global Codex settings for a single batch.

For a bounded worker, select `fork_turns="none"` and supply the work packet below.
This session's full-history fork inherits model/effort and cannot take overrides.
Explicitly name BOTH model and effort. Read back recorded usage/model metadata
when available; absence is unknown, not proof of the requested selection.

One worker owns one coherent batch (initially 10–20 instances of an established
family), or one bounded new-family implementation. Complete it, save the compact
handoff, and retire the worker from further unrelated work. Do not keep restarting
fresh agents to evade escalation limits. Carry forward its attempt count and
unresolved findings. Fresh workers read the packet and referenced files, not the
entire project conversation, all historic reports or every raw trace.

## Work packets and ownership

Use [the batch template](templates/dataset-work-packet.yaml). Each assignment has
one owner, allowed files, pinned contract/runtime/build, environment allocation,
acceptance commands, explicit exclusions, bounded attempts and result path.
A task-family contract defines requirement IDs, observable predicates, unknown
conditions, setup assumptions and evidence needed. Expected answers and privileged
setup/grader data remain outside policy-visible goals and observations.

Keep a single coordinator-owned batch ledger: work ID, family/template/instance
IDs, owner, state, source/build identity, evidence pointers, attempts and blockers.
Claim work before spawning. The lead owns catalog promotion; workers return
candidate records. One publisher owns Git operations. Independent site/context
cases run concurrently; shared mutable site leases serialize or use separate
reset-attested clones. Never solve contention by borrowing manual/shared sites.

No routine agent pings. Send a message only for a blocker, conflicting ownership,
needed decision or release of a dependency. Read the existing evidence index
before requesting another run. Reviewers consume saved artifacts by default.

## Validation that scales

Separate the unit that introduces risk from the number of parameter instances.

| Layer | Required work | Reuse / invalidation |
| --- | --- | --- |
| Site/build | Full-site reachability, account/reset isolation, asset/source identity, supported capabilities | Once per relevant build/config; invalidate on changes to those dependencies |
| Task family/grader | Review meaning; positive + wrong-outcome controls; meaningful overwrite/duplicate/wrong-owner/missing-evidence boundaries for the actual mechanism | Once per semantic predicate/setup branch and revision; every newly introduced branch gets evidence |
| Task instance | ID/goal/parameters, reference grounding, fixture availability, positive native-browser execution, exact policy projection; parameterized negative/checker tests | Run automatically in batches; do not write a unique audit program per row |
| Harness change | Dependency-targeted contract suite plus representative site/family integration controls | Rerun affected coverage; retain old artifacts with old source identity |
| Release | Aggregate machine report, unresolved exceptions, sampled semantic review, requested deployment scope | One release review, not repeated parent/child reviews of every file |

An instance without successful browser evidence is specified, not browser-validated.
A cached earlier pass is reusable only for identical relevant task/setup/build/
runtime dependencies; report its original execution identity. Dynamic state needs
its own reset/instance evidence. Hashing is integrity evidence, not proof of a
correct grader or a deterministic environment.

For established families, use cheap parameterized adversarial replay across all
instances instead of a second complete browser traversal for every wrong answer.
Retain real negative browser paths for each distinct mutation/evidence mechanism
and for regressions where request history and final state can disagree. Label
synthetic negative/replay evidence separately from executed negative paths.

Initial manual-review rule: independently review every new predicate and branch;
for unchanged instance-only batches, inspect all anomalies plus a reproducible
sample of at least three instances or 10%, whichever is larger (capped at batch
size). Include boundary parameters and each new page layout, not only random easy
cases. A systematic defect holds the affected family and expands review to its
instances. This sampling rule is a pilot heuristic, not statistical certification.

## Checks to consolidate, bound or stop repeating

- Generate provenance/manifests once per immutable artifact set. Verify once at
  ingestion/review boundary; pass the report by reference. Recheck on changed
  dependencies, transfer or suspected mutation, not every time an agent reads it.
- One shared delivered-action-target/evidence audit, schema validator and catalog
  join. Extend their supported evidence formats rather than copying a batch script.
- Run narrow regression checks after a local edit; broader affected-family checks
  at freeze. Do not replay unchanged successful cohorts for reassurance.
- Do not rerun a browser to answer a question already settled by saved evidence.
- Automate report rendering and counts. Keep one current index and immutable raw
  attempts; avoid bespoke prose and independently maintained per-agent counts.
- Infrastructure feasibility is a separate packet. Default initial triage cap:
  30 minutes or two concrete failed approaches, then return a blocker and next
  options. These are soft effort boundaries, not grounds to kill an active write
  or skip cleanup. Prefer established download/resume tools before custom ones.
- Never remove source pages/distractions to simplify validation. Retain unknown
  outcomes, raw failures, isolation, no-answer-leakage and scope-specific negative
  controls. Savings come from reuse and selective execution, not false certainty.

A check earns recurring cost when it catches a demonstrated defect, protects a
clear boundary or cheaply validates an invariant. Track defects caught and runtime;
review expensive, redundant checks after each pilot. Do not delete an established
acceptance requirement silently: document replacement coverage and its limits.

## Escalation and handoff

Start with a concrete hypothesis and bounded diagnostic. After two failed repair
attempts or an unclear predicate, return the smallest counterexample, relevant
step/artifact paths, attempted changes and what decision is needed. Infrastructure
breakage, source changes or invalid isolation stop dependent cases immediately.
No automatic paid retries, downloads or new site provisioning. Existing explicit
resource authorization still governs any work.

A result contains: work ID; actual source/model/effort; changed paths; commands and
machine report; accepted/held IDs with reason; reused evidence IDs; remaining risks;
usage when available. Keep the prose summary to roughly 300 words. Do not paste
full logs, model reasoning, large JSON or duplicate the originating packet.

## Learn before scaling

First trial: one already verified family, about ten new instances, temporary cheap
worker and the lead's acceptance review. Do not deliberately rebuild the same ten
tasks with a second agent just to compare costs. Use the previous comparable batch
as a rough baseline and record its differences. Review the whole first pilot;
apply sampling only after its shared mechanism is accepted.

Measure accepted instances AND distinct templates/sites, output/noncached-input/
cached-input tokens separately, tool/browser time, repair attempts, lead review
usage, missed defects and later regressions. Never translate raw tokens to weekly
quota or prices without valid accounting. Choose tiers by end-to-end cost per
accepted task/family and defect rate, not worker tokens alone. If cheap work creates
more expensive repair than it saves, raise that work class a tier. Savings and
quality for the proposed model assignments are currently unmeasured.

## Sources and boundaries

OpenAI documents per-agent model/effort selection and concurrency controls in
[Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).
Exact tool availability and limits above are from this running session; documented
configuration may differ across versions. No hierarchy configuration was changed
or nested test started to write this protocol. The model routing, effort limits
and sampling policy above are project proposals, not OpenAI guarantees.

The earlier four-hour expansion remains documented in
[dataset expansion](dataset-expansion.md). Maps (OpenStreetMap-derived services)
and Wikipedia belong to WebArena, not ServiceNow WorkArena. Their local provisioning
was paused before runnable acceptance, and neither was published to Vercel.
