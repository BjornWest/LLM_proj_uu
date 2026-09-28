# WebArena-Infinity: lessons for our procedural-commerce MVP

Research and proposed workflow, 2026-09-22. Reviewed the official project writeup and selected repository code/guides at revision `1ca77813bf8d8e4011aa3fb1f740f70d78bd522d`. No upstream pipeline, generated app or model evaluation was run. Small source excerpts were downloaded under `.local/research/webarena-infinity/`; no installation or deployment. This is not a comprehensive audit of their generated environments.

**Recommendation:** borrow the staged generation/evaluation/audit workflow, retaining our Sol integration lead and bounded Luna renderer workers. Add explicit browser validation and an independent semantic review. Do not adopt their entire environment protocol or a new hierarchy merely because the project is multi-agent.

## What their workflow actually does

The pipeline implements five phases: app generation; functional-task generation/evaluation/audit; realistic-task generation/evaluation/audit; new-task hardening based on trajectories; and final regression. It invokes separate Claude CLI processes for coding stages and a browser-evaluation subprocess with parallel workers. Thus the explicit orchestration is primarily a sequence of roles and feedback loops, with independent environments parallelizable—not a specified inexpensive-worker/manager model hierarchy. The coding CLI invocation selects high effort but does not pin a coding model; the pipeline's `--model` selects the evaluated browser agent. [Pipeline source](https://github.com/web-arena-x/webarena-infinity/blob/1ca77813bf8d8e4011aa3fb1f740f70d78bd522d/infra/pipeline.py).

The authors describe Opus 4.6 for coding and Gemini-3-Flash with Browser Use for browser execution. Their documentation ablation favors richer source material; audit iterations improve functional results; trajectory-based hardening reduces success from 54.2% to 41.9% on the compared hard-task sets. These are their reported results, not our reproduction. Final functional regressions include two substantial drops, so the workflow is not a guarantee of correctness. Their under-$100 / within-ten-hours generation claim is not directly comparable to our frozen coding-token accounting. [Official writeup](https://webarena.dev/webarena-infinity/), [underlying article](https://webarena.dev/webarena-infinity/content.md).

## Comparison with our actual aggregator trial

Our [development review](agents/aggregator-development-review.md) records Astra owning specification/review, Sol owning the shared engine, integration and verification, and Luna owning two retailer interfaces and later homepage work. Luna delivered useful distinct interfaces but needed help with browser validation. Bugs also occurred in shared code and grading; they were not all worker-quality issues.

| Dimension | WebArena-Infinity | Proposed procedural-commerce adaptation |
| --- | --- | --- |
| Input | Selected real-app documentation and a generated implementation description | Stable semantic contract, representative world records and a distinct DOM/interaction brief |
| Output unit | Specific app, seed data, tasks and verifiers | Reusable renderer plus capability declaration, working across worlds and supported product traits |
| Work split | Coding/generation, browser execution, audit, task hardening | Sol integrates; Luna implements bounded renderer work; independent reviewer checks outcome semantics |
| Acceptance | Functional tasks, model trajectories and verifier checks | Cheap state/oracle tests and native browser conformance first; bounded model calibration afterwards |
| Improvement | Diagnose failures and add harder tasks | Repair defects separately; improve declared mechanism distributions without discarding infeasible worlds |
| Scale | More independent apps and task suites | More reusable designs, trait support, seeds and task compositions |

The table is our proposed adaptation, not a claim that their project evaluated model-tier delegation or procedural renderer generalization.

## Practices worth adopting

**A generated capability handoff.** Their app-generation prompt asks for an implementation description covering features, entities, navigation, controls and seed data for downstream task generation. We should produce a compact capability manifest and compare it with the original requirements; describing an implementation must not excuse missing requirements. [Generation prompt](https://github.com/web-arena-x/webarena-infinity/blob/1ca77813bf8d8e4011aa3fb1f740f70d78bd522d/infra/prompts/generate-app.md).

**Explicit interface contracts before delegation.** Their repository guidance identifies cross-module handler/data mismatches as a major bug source and recommends contract definition before parallel implementation plus browser checks after integration. That closely matches our trial's DOM-handler, visibility and displayed-price defects. It supports strengthening the existing work split, rather than replacing it. [Repository engineering notes](https://github.com/web-arena-x/webarena-infinity/blob/1ca77813bf8d8e4011aa3fb1f740f70d78bd522d/CLAUDE.md).

**Separate functional tests from user tasks.** A “change quantity, reload, inspect cart” check can validate the app without becoming a training prompt. Real tasks express user outcomes. Privileged test setup and browser-only policy execution must remain distinct. [Functional-task guide](https://github.com/web-arena-x/webarena-infinity/blob/1ca77813bf8d8e4011aa3fb1f740f70d78bd522d/docs/function-task-design-guide.md).

**Use trajectories to propose new difficulty.** Their hardening guide adds tasks without changing existing task identities, and focuses on discovery, disambiguation and dependent operations. For us, this could motivate new combinations of variant, delivery, promotion and authorization conditions. Preserve benchmark distributions/holdouts; do not tune every seed to a particular model failure. [Hardening guide](https://github.com/web-arena-x/webarena-infinity/blob/1ca77813bf8d8e4011aa3fb1f740f70d78bd522d/docs/task-hardening-guide.md).

## Practices we should change or decline

**Passing-state checks are insufficient.** Their sanity guide derives state mutations from verifier predicates and checks acceptance. This catches shape/consistency problems but can reproduce the verifier's omissions. Our independent checks must also reject wrong quantity, unauthorized extras, prior unsafe orders and duplicate purchases, and cover unknown evidence. An always-true verifier must fail validation. [Sanity-check guide](https://github.com/web-arena-x/webarena-infinity/blob/1ca77813bf8d8e4011aa3fb1f740f70d78bd522d/docs/verifier-sanity-check.md).

**Human feasibility does not prove verifier correctness.** Their audit guide uses human completion and sanity checks to attribute remaining failures to the agent. We should retain harness/observation errors and uncertainty as possibilities, and inspect suspicious successes as well as failures. Our valid no-match worlds also differ from their emphasis on feasible action tasks. [Audit guide](https://github.com/web-arena-x/webarena-infinity/blob/1ca77813bf8d8e4011aa3fb1f740f70d78bd522d/docs/real-task-audit-guide.md).

**Keep authoritative state in our engine.** Their protocol has the browser push full application state to a server, which verifiers read. That is a different trust boundary from our server-computed quotes and committed-effect ledger. Reuse workflow ideas, not this state protocol, especially when studying reward loopholes. [Environment protocol](https://github.com/web-arena-x/webarena-infinity/blob/1ca77813bf8d8e4011aa3fb1f740f70d78bd522d/docs/environment-protocol.md).

**Keep supported native controls.** Their design guide prohibits several native controls, including select elements, in favor of custom widgets. Our renderer diversity should include both where the harness supports them; deleting useful control families would narrow the experience we want to train. [Design guide](https://github.com/web-arena-x/webarena-infinity/blob/1ca77813bf8d8e4011aa3fb1f740f70d78bd522d/docs/web-app-design-guide.md).

## Proposed next MVP workflow

1. **Lead and user settle one worked contract:** world/quote rules, three request modes, authorized effects, representative correct/wrong/unknown outcomes. Lead reviews semantics once, rather than supervising routine coding.
2. **Sol builds the shared foundation and reference integration:** generator/materialized world, public projections, state transitions, private ledger and parameterized outcome checks. Independent expected results for small worlds guard against engine/oracle shared mistakes.
3. **Short-lived Luna workers adapt individual renderer designs:** explicit input/action schemas, owned files and a runnable browser-check command. No new pricing rules, seed-specific answers or grader changes inside a renderer.
4. **Automation exercises a small cross-product of worlds and designs:** changing prices/stock, different catalog sizes, long names, authorized versus forbidden extras, reloads and quote invalidation. Metamorphic checks include identity renaming, offer-order changes and equivalent rendering. Layout changes preserve semantic results; changed commercial facts should alter results where appropriate.
5. **Independent audit reviews failures and suspicious passes:** concise reproduction, evidence, ownership and verdict; ambiguous bugs get escalated. Cheap shared checks handle routine regressions. Root returns for semantic blockers and final contract review, not every worker report.
6. **A separately agreed model cohort calibrates difficulty:** use our existing harness and trace triage. Avoid repeated expensive model runs to diagnose deterministic UI bugs. Fixing a defect creates a new revision; historical evidence remains frozen.

Measure effort by phase (contract, engine, renderer, validation, repair, coordination), model tokens and defect recurrence. Compare this trial with our historical work using the existing usage tooling; do not assume more agents or fewer browser failures automatically means lower cost.

The unproven part is reusable generation: one renderer must work on unfamiliar materialized worlds without new code. WebArena-Infinity supplies useful construction and audit practices, but does not by itself establish that capability for our product/retailer sampling design.
