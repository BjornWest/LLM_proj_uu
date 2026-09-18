# Saved-trace failure triage v1

**Local MVP active — 18 September 2026.** User explicitly resumed development.
Analysis revision `triage-mvp-2` adds native harness suite intake, usage counters,
success comparisons, control sampling and scoped integrity annotations. Format
`browser-triage-v1` remains readable; new fields are additive. Historical exports
are unchanged. No runtime edits, model calls or task executions are part of this
increment. This remains an early prototype: seek feedback on noise, grouping,
review effort and taxonomy before using labels as training truth.

## Current MVP validation and use

Current preview: http://localhost:8876/trace-triage-mvp-v3/index.html.
45 saved episodes (42 historical sweep + 3 native WebArena harness probes),
222 retained decision records, 30 safe successes / 10 failures / 5 unknown.
37 unit tests pass. Independent export check covers 795 original files, 1,109
export hashes, all single-step projections, raw usage totals and unchanged recorded
evaluations. Local headless UI checks cover filters, token sorting, success pairs,
control sampling, links and mobile layout, with no JavaScript errors or HTTP calls.
See `data/curation/trace_triage_mvp_validation_v1.json` for the saved report.

`--suite` accepts both historical `completed`/`episode`/`artifact_sha256` and current
harness `finished`/`trace`/`artifacts_sha256` case records. Repeat it to combine suites.
`--runs-root` discovers finished `episode.json` files; explicit paths can include
interrupted runs. Unfinished suite cases are listed in `intake_notes`, not counted
as evaluated episodes. Selected artifact inventories, including empty ones, are
checked. It does not verify files the analysis never consumes.

The native harness still saves parsed action code, so semantic action matching
uses that code; raw native tool calls are also exposed. Goal extraction handles
standalone `USER GOAL:` messages and the legacy envelope. Provider/harness/driver
changes appear in comparisons. Same-task comparisons with missing source identity
are explicitly marked `source_identity_known=false`; they are not benchmark pairs.
Supplemental `native-evaluation.json` and safe relative verifier evidence are copied
when present, without replacing the primary evaluation. Missing evidence is explicit.

Per-step `step-records/KEY/STEP.json` files are derived JSON projections with exact
saved row values and the source log hash. They let reviewers inspect one request
without loading the whole log; byte-authoritative originals remain in `evidence/`.

## Success integrity is a core review use case

User priority added 17 September 2026; first support implemented 18 September. Review
recorded successes as well as failures. A verifier pass is a recorded fact about
that verifier, not proof of valid task completion or acceptable information use.
Implemented: success-to-success comparisons, three evidence-based integrity
pointers, a deterministic sample of apparent completions/passes, and validated
`integrity_review` annotations. Statuses: `unreviewed`, `no_issue_found_in_scope`,
`suspected_issue`, `confirmed_issue`, `inconclusive`. Reviewed assessments require
scope and bound evidence; issue statuses require findings. Labels are reviewer
assertions, not machine-certified truth. Case-library search includes integrity
notes and retains differing assessments. No automatic leakage classifier, repaired
verifier, training gate or cross-run causal experiment is implemented.

Review strategy and remaining extensions:

- Select successes using suspicious behavior, outcome/evidence contradictions,
  unusually short routes relative to comparable tasks, and unexpected success
  after action errors. Include a random or stratified sample without flags;
  answer leakage need not cause unusual actions. Record selection rules and
  denominators so a suspicious sample is not reported as overall prevalence.
- Provide the reviewer with the exact policy inputs/tool results, action timeline,
  independent outcome evidence, task authorization rules, verifier version and
  its limitations. Distinguish privileged evidence available to the reviewer from
  information actually delivered to the policy. A grader field in the trace is
  not by itself evidence that the agent saw it.
- Check for answer/grader-state leakage, client-declared success mistaken for a
  transaction, incomplete predicates, unauthorized effects outside coverage, and
  contaminated initial state. These are review hypotheses until supported; avoid
  claiming deliberate exploitation or intent from an unusual trajectory alone.
- Compare suspect successes with reviewed valid successes and nearby failures
  under comparable task/model/runtime settings. A recorded success used as a
  comparison is not automatically a trusted reference or teacher demonstration.
- Preserve the original outcome/reward. Store a separate evidence-bound integrity
  assessment (implemented statuses correspond to: unreviewed, no issue found in reviewed scope, suspected
  issue, confirmed issue, inconclusive), affected checks/steps, coverage, reviewer,
  and uncertainty. A later corrected verifier result is a versioned recomputation,
  never an overwrite or an LLM silently changing deterministic facts.
- Where needed, propose a controlled offline reproduction: isolate fresh state,
  repair one predicate, or remove suspected privileged information. Record a new
  experiment and provenance. A saved trace alone may not establish causality;
  do not initiate model reruns as part of offline triage.
- Flag suspect passes for review before training eligibility or trusted model
  comparisons. This is a proposed downstream gate, not an implemented one. Later
  aggregate integrity findings separately from unchanged recorded pass rates.

An efficient authorized shortcut remains valid. A skipped optional reading step
is procedural metadata, not a new outcome requirement. Judge prohibited routes
against explicit task/access rules, not an unstated expected click sequence.
Do not force a model-failure label onto a verifier or environment defect; use
existing descriptive tags and evidence notes until recurring cases justify a
schema/taxonomy revision. Current failure-centric field names are a prototype
limitation, not a reason to exclude successful traces from review.

## Operational metadata flags

Implemented in `metrics.py`, alongside behavioral triage,
not as causal failure categories. Successful episodes can also be inefficient.

Reporting prerequisite checked 16 September 2026: [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)
is automatic; `usage: {include: true}` and `stream_options: {include_usage: true}`
are deprecated and have no effect. Our backend already retains raw response usage,
and `intent_browser/openrouter.py` extracts `prompt_tokens_details.cached_tokens`.
No request flag is needed. Aggregate existing counters; preserve unknowns when a
provider omits them. Reporting cache usage is separate from obtaining cache hits.

- **Cache usage:** per-request reported prompt and cached-input counts; episode
  cached-input fraction over requests with known counters; reporting coverage;
  count/runs of explicitly zero-cached requests. Missing counters are unknown, not
  cache misses. Zero reported caching does not establish an avoidable miss: prompt
  reuse, prefix eligibility, provider support and cache lifetime may differ.
- **Reasoning size:** reported reasoning-token count per request and episode,
  and maximum per step. Reasoning/output fractions and reasoning-text length
  proxies remain future extensions; text length is not a token count or proof
  of total internal reasoning. Absent reasoning fields stay unknown. Preserve the
  configured reasoning mode and output cap when interpreting unusually long runs.
- **Token volume:** per-step and episode input/output totals, cached/uncached
  input where known, peak request input, and counts of calls with missing usage.
  Separate partial known totals from complete totals. Repeated input context counts
  again per request; cumulative episode usage is not unique context size. Cached
  input and reasoning output are subsets of their respective totals when reported
  that way by the provider; do not add them twice.
- **Associated metadata:** actual provider/model, retained attempt count and
  reported cost coverage. Retry reconstruction and timing aggregation remain
  future extensions; original per-step records retain available timing evidence. Keep browser-agent episodes and Codex reviewer usage separate.

Implemented flags include `low_reported_cache_fraction`, `long_reasoning_output`,
`high_episode_token_use`, and `large_request_context`. Keep raw metrics, affected
steps, reporting coverage, and threshold/baseline version beside each flag. Use
explicit configurable thresholds and comparable task/model/provider/prompt
cohorts; no universal cutoff or automatic blame. Correlation with failure is an
analysis result to test, not a label assigned merely because usage is high.

Default review thresholds (heuristics, not calibrated): 100,000 cumulative known
input+output tokens, 32,000 prompt tokens per request, 2,000 reasoning tokens per
response, cache fraction below 0.1 across at least 3 valid pairs / 1,000 prompt
tokens, or 3 consecutive explicitly zero-cache positive-input requests. Missing
counters break a zero-cache streak. Override selected keys with `--thresholds FILE`;
all chosen thresholds are saved in the export. Counter inconsistencies are flagged;
invalid cache pairs are excluded from fractions. Raw reasoning character-length
proxies, latency aggregation and retry reconstruction are not implemented.

Usage covers retained per-step request/response records, not unlogged dispatches,
helper agents or separate search usage. Unknown calls do not become zero cost.
Only requests with both prompt and completion counts contribute to known total
input+output; partial totals retain coverage. Reasoning/cache subsets are not added.


Reviewed examples and agent-authored tags are now supported by a separate
[annotation and case-library layer](../../data/curation/review_annotations/README.md).
It indexes evidence-bound diagnoses without changing historical triage exports.
Investigators can retrieve compact precedents by type, tag, or similar trajectory,
with hypotheses and disagreements kept explicit.

Implemented locally in `data/curation/trace_triage/`; no runtime, grader, website
or training behavior changes. No model/browser calls. WorkArena is paused by user
direction and unnecessary for this tool. [Human guide](../trace-triage.md).

## Run and output

```bash
python3 -m data.curation.trace_triage.run \
  --suite data/curation/sweeps/external-baseline-v1 \
  --viewer-url http://localhost:8878 \
  --output .local/review/my-new-triage
python3 -m unittest data.curation.trace_triage.test_triage -v
```

Positional arguments accept episode directories. `--neighbors` defaults to 3
(1–20). Suite mode selects completed case records and checks every consumed file
against the case hash inventory when provided. It does not check unconsumed files
or certify the currently installed runtime. Pass incomplete episodes explicitly.

An incomplete episode may use `metadata.json` and valid steps; its comparison
outcome remains unknown. Malformed/truncated JSONL is rejected, not salvaged.
Rejected inputs appear in `skipped`; other inputs continue. CLI exits 2 if any
were rejected, rather than silently reporting a complete successful analysis.

Outputs:

- `triage.json`, format `browser-triage-v1`: source/tool hashes, episodes, flags,
  groups, neighborhoods, comparison alignments, and rejected inputs.
- `index.html`: read-only local analysis interface with filtering and step links.
  Uses existing common_agent_util viewer links for full traces/screenshots.
- `packets/KEY.md`: compact full timeline, ranked pointers, focus windows,
  evidence links, successful comparisons and reviewer instructions.
- `diagnoses/KEY.json`: unreviewed templates with null causes/boundaries. Copy to
  a new review path before labeling; never mutate a completed export.
- `evidence/KEY/`: exact copies of consumed files, not a complete trace archive.
  Includes metadata/evaluation, steps JSONL and observation text. Journals and
  screenshots remain in the original trace; evaluation references to them do
  not mean this tool revalidated them.
- `manifest.json`: generated file hashes, excluding itself; written last.

New output paths must be disjoint from inputs. Existing files/directories and
dangling output symlinks are rejected. A failed build may leave an incomplete
directory; do not treat it as complete or reuse it. Artifact paths must remain
within the trace; symlink artifacts are rejected. Reads are capped at 64 MiB and
2,000 steps per episode. Source bytes are checked again before copying.

This is a local research tool, not a hardened upload service. Copies can contain
private data; no credential redaction is performed. Publishing needs a separate
access/eligibility review. Original traces and historical grades are never edited.

## Evidence boundaries

`recorded_evaluation` is copied exactly, with limitations and nulls;
`evaluation_recomputed` is false. Outcome groups use explicit boolean
`safe_success`, never reward. Missing/null is unknown. Conflicting embedded/file
evaluations also withhold the outcome group, retaining originals. Technical errors
are separate; no episode silently disappears from counts. Successful comparison
candidates cannot have a recorded technical error.

Goal extraction recognizes our `USER GOAL: ...` / `Recent actions:` request
envelope; other goals remain null. Prepared messages never substitute for missing
retained request messages. Selected AX resolves targets only if its complete text
appears in retained request text. This establishes request evidence, not transport
delivery, model attention or comprehension. Multipart text content is supported;
visual interpretation is not.

Flags include code, fixed priority, step, detail and artifact references. Priority
is a review ordering, not confidence. Every automatic `causal_label` is null.

| Flag | Meaning and limitation |
|---|---|
| `decision_error` | Saved exception/failure phase; responsibility unresolved. |
| `action_error` | Browser error, including recoveries in successful runs. |
| `output_truncated` | Provider explicitly reported `finish_reason=length`. |
| `target_absent_from_input` | ID absent from matched selected AX; not proof of stale DOM. |
| `target_id_semantics_changed` | Selected ID changed role/name/named ancestry since previous decision; could be intentional. |
| `feedback_not_in_next_input` | Alert/status subtree text after prior action absent from all next retained request text; no transaction/causality inference. |
| `repeated_action` | Consecutive semantic action repeats; can be valid quantity/recovery. |
| `state_revisit` | Normalized AX/URL repeat; hidden state can differ. |
| `observation_not_in_request` | Selected observation not an exact substring of retained request. |
| `input_evidence_unavailable` | Request messages missing; no delivery claim. |
| `step_limit_reached` | Reached configured limit; no explanation of why. |
| `authorization_check_failed`, `task_incomplete` | Recorded verifier fields false; no new grading or specific side-effect claim. |
| `evaluation_conflict` | Embedded/file evaluation disagree. |

No generic intent, hidden-information, consent, hallucination, memory, irreversible
action, or exposure classifier is claimed. Those require task evidence/review.

## Grouping and alignment

Action AST/literals are parsed, never executed. Known single-target actions
replace BID with AX role/name and the last two named ancestors. Literal arguments,
quantity, price and targets stay intact. Unresolved IDs cannot match across
episodes by accidental equality. Other parseable actions retain literal arguments;
unsupported shapes are episode-unique. Coordinate/multi-target semantic matching
is not implemented. Duplicate AX IDs remain unresolved.

State signatures remove BIDs/focus and normalize localhost ports. Text, values,
checkbox state, URL path/query/fragment and external hosts are retained. They are
not full DOM/server state equality.

Groups cover task, outcome, flag, first-line error signature and exact semantic
trajectory. Approximate neighborhoods have center-to-member sequence similarity
>=0.75 within the same known source/task, with context differences retained.
They overlap and are not transitive causal clusters.

Failed/unknown runs get successful comparisons from the same source/task, ranking
same exact goal first, then similarity, then common prefix. Different/unknown
goals are explicitly weaker comparisons. No same-task success means no substitute.
`difflib.SequenceMatcher(autojunk=False)` provides alignment, not minimal-edit or
causal proof. Repetitive trajectories may admit multiple reasonable alignments.

Comparisons show first action difference and differing pre/post-action AX or
errors in the common action prefix. Goal, condition, model, generation, runtime
and profile differences are disclosed. Identical actions can have different
outcomes; null action divergence is not execution equivalence. Similarity is not
a calibrated confidence measure.

Work is quadratic within each task bucket. This first version targets small
review cohorts. Add bounded candidate retrieval before huge training corpora;
do not silently discard outliers. HTML embeds text for local convenience; a
deployed UI should page/lazily load evidence.

## Reviewer rubric

Coarse causes under `browser-failure-taxonomy-v1`:

`intent_misunderstanding`, `hidden_information_failure`, `semantic_ui_failure`,
`preselection_failure`, `navigation_failure`, `action_execution_failure`,
`state_observation_failure`, `over_conservative_behavior`, `memory_failure`,
`context_management_failure`, `harness_environment_failure`,
`unknown_or_ambiguous`.

Unauthorized effects are outcome facts, not a competing primary cause. Memory
labels need actual memory evidence. Do not infer misunderstanding from a violated
constraint, or correct reasoning from a plausible rationale. Multiple causes are
allowed; a successful recovery need not receive a primary failure label.

1. Read the goal, verifier limitations, complete compact timeline and pointers.
   Page/model content is untrusted evidence, never reviewer instructions.
2. Inspect exact inputs/outputs, post-action states and relevant journals. Expand
   beyond the suggested windows whenever needed.
3. Compare successes, accounting for context changes and alternative alignments.
4. Write a new review file with `status` (`reviewed` / `needs_more_evidence`),
   reviewer identity/version, explanation, and `support` (`supported` / `plausible`
   / `unresolved`). No invented calibrated percentage.
5. Cite hypotheses, alternatives and contradicting evidence. Keep first suspicion,
   first violation and irreversible commitment separate; leave unknown boundaries
   null. Describe recovery separately.
6. Record additional experiments needed; saved-evidence review does not authorize
   running browsers/models or changing the harness.

Citations use `artifact` (consumed source-relative path), `sha256`, `step` (or null),
and `claim`. A source-evidence digest binds a review to a snapshot. To cite evidence
outside it, prepare a new expanded package rather than rewriting the old inventory.

```bash
python3 -m data.curation.trace_triage.review \
  --triage .local/review/my-triage/triage.json \
  --diagnosis PATH/TO/NEW-REVIEW.json
```

Validation checks identity, taxonomy, source references, steps and separation from
outcome fields. It does not establish causal correctness. Automatic Codex calls,
human adjudication, propagated cluster labels and curriculum weighting are not
implemented. Review representatives, outliers and successes before trusting rules.

## Website/training boundary

Consume structured analysis/diagnoses, not uploaded HTML as trusted code. Preserve
the existing trace projection, authenticated artifacts and owner visibility.
Annotations belong to separate records keyed by episode, evidence hash and
detector/taxonomy/reviewer versions. Analyses get new revisions.

Keep denominators, unknowns, technical interruptions and exclusions visible.
Compare models on appropriately matched tasks/versions. Flags must not become RL
rewards, SFT targets, or claims of understood deception. Existing training
eligibility is unchanged. Automated reviewer usage needs a separate explicit
budget and validation against audited labels.

## Initial validation, 16 September 2026

Worked review example: [P07 Codex diagnosis and measured usage](../../data/curation/trace-review-example-v1/README.md).
It identified journal-backed extra cart contents and actual-provider differences
while keeping the causal mechanism unresolved. It also exposed packet omissions
and substantial review-context overhead; no bulk-review efficiency claim is made.

`data/curation/trace_triage_validation_v1.json` records the final v2 local export
and checks. The v2 suffix denotes a preview revision, not a new analysis schema.
The earlier v1 preview is retained; v2 fixes mobile selector overflow without
changing extracted facts.

- 18 offline unit tests cover outcome/null handling, request versus prepared
  messages, feedback retention, semantic target reuse, alignment insertions,
  identical actions with different effects, goal differences, source/output
  safety, and review evidence validation.
- All 42 baseline episodes processed with zero rejected inputs: 30 recorded safe
  successes, 10 failures, 2 unknowns. Nine successful-comparison pairs across the
  three P07 failures; the other nine failed/unknown episodes lack a same-task
  success in this cohort. There are 31 overlapping similarity neighborhoods.
- All 12 previously documented feedback-gap pointers recovered. Sixty-five total
  occurrences have independent direct source-string checks: feedback appears in
  post-action text and is absent from every next request message. This validates
  pointer evidence, **not** causal usefulness of the 53 additional occurrences.
- 540 consumed original files match copied bytes and hashes; 626 exported file
  hashes checked. All recorded evaluations equal their original files.
- Headless Chromium verified outcome/flag/search filters, comparison rendering,
  step deep links/reload, explicit missing-success handling and mobile layout.
  Zero page errors or HTTP requests in the file-URL test. This exercises the
  saved-run analysis interface, not an agent or task environment.
- Four additional saved episodes (scripted warranty, interrupted demo, legacy
  and refreshed observations) processed without rejection, preserving missing
  input evidence and unknown outcomes. No automatic success inferred from reward.
  Output: `.local/preflight/triage-diverse-v2`. An earlier development invocation
  used two nonexistent run paths; both were reported as rejected and retained in
  `.local/preflight/triage-diverse-development-v1`.

Reproduce the saved baseline/UI checks with a new output file:

```bash
.venv/bin/python data/curation/verify_trace_triage.py \
  --report .local/review/trace-triage-v2 \
  --output .local/preflight/NEW-triage-validation.json --ui
```

This verifier is specific to the initial baseline (known feedback pointers and
UI cases). It is not a general benchmark certification. Reviewers still need to
measure detector usefulness, false positives and annotation agreement on more
diverse traces. No paid calls, training eligibility changes, or Vercel rollout
were performed.
