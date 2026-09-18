# Browser trace triage skill

Entrypoint: [.agents/skills/browser-trace-triage/SKILL.md](../../.agents/skills/browser-trace-triage/SKILL.md).
Invoke as `$browser-trace-triage` while working in this repository. Automatic
selection remains enabled. The local shared Codex server's read-only `skills/list`
discovered exactly one enabled entry at this path with scope `repo`; no agent
session was started or restarted. Repository `.agents/skills` discovery follows
the [official skill documentation](https://learn.chatgpt.com/docs/build-skills).

The skill supplies selection/review guidance and a compact read-only query helper;
it reuses the existing triage engine and annotation validators. It does not copy
the parser, replace graders, launch Codex subagents, schedule background work,
or run browser/model calls. It depends on this project's Python modules and is
not a standalone package for arbitrary trace formats.

## Practical workflow

1. Bound the requested cohort and reuse/build a saved triage export.
2. Query summary/filter pages; select failures, apparent-success controls, or
   operational outliers without loading whole trace logs into context.
3. Inspect groups and their representatives. Exact sequences and overlapping
   neighborhoods are candidate organization, not inferred shared causes.
4. Find same-task neighbors, inspect divergence and preceding state differences,
   and read only relevant step/request/evaluation artifacts before expanding.
5. Search reviewed precedents, write evidence-bound annotations, validate and
   index them. Record which members remain unreviewed and any competing accounts.

Commands and review details are progressively loaded from the skill's two
references. The helper has `summary`, `list`, `groups`, `neighbors`, `compare`;
pagination defaults to 10 and caps at 100. Filters include task, condition, driver,
model, provider, outcome, ANDed flags, queue sample, group membership and minimum
known tokens. Missing usage is not zero. Comparisons reject self/cross-task pairs
and retain source/goal/context uncertainty. This supports bounded cohorts; the
underlying analyzer still performs pairwise work within task buckets.

## Validation scope

- Skill-creator structural validator passes; entrypoint/references contain no
  scaffold placeholders, and UI invocation names the skill.
- Four offline helper tests exercise filtering, unknown usage, pagination, group
  isolation, cross-task/self rejection, divergence and unchanged export bytes.
- Real queries exercised the 45-episode MVP and the newly imported 15-condition
  native harness baseline. The latter retains 14 true/1 unknown safe outcomes;
  its single repeat supplies no same-task pairs. No unrelated substitute was used.
- Existing source/triage exports remain untouched. No new inference, task browser
  execution or agent delegation was used to create or test the skill. Query tests
  establish mechanics; they do not establish future Codex diagnosis accuracy.

The latest baseline trace review is an example of selecting likely useful work,
not a new causal finding. Raw requests remain ignored/local. See
`data/curation/trace_triage_skill_validation_v1.json` for hashes and query checks.
