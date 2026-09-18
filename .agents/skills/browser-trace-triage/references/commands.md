# Commands for a bounded investigation

Run from the repository root. `Q` below is only a convenience shell variable.
All commands analyze saved files; none starts browser-agent inference.

```bash
Q=.agents/skills/browser-trace-triage/scripts/query_traces.py

# Reuse existing exports where possible. Otherwise choose a NEW output directory.
python3 -m data.curation.trace_triage.run \
  --suite .local/preflight/harness-suite-v3 \
  --viewer-url http://localhost:8878 \
  --output .local/review/NEW-triage

# Alternatively: --runs-root path/to/traces, or positional episode directories.
# Repeat --suite to include several cohorts; compare context differences explicitly.
python3 "$Q" summary --triage .local/review/NEW-triage/triage.json
python3 "$Q" list --triage .local/review/NEW-triage/triage.json \
  --outcome failure --flag repeated_action --limit 10
python3 "$Q" list --triage .local/review/NEW-triage/triage.json \
  --task P10 --sort tokens --limit 5
python3 "$Q" list --triage .local/review/NEW-triage/triage.json \
  --queue sampled --limit 5
```

`list` supports task/condition/driver/provider/requested-model filters, ANDed flags,
outcome and review-queue selection, plus sorting by priority/tokens/reasoning/cache.
Task matching is substring-based; other fields are exact. Missing numeric values
sort last and never pass a numeric minimum. Provider filtering means that provider
appeared somewhere in the trace, not that every request used it. No filter silently
changes an original outcome. Cards link the packet, template and step-record directory.

## Group, choose representatives, compare

```bash
python3 "$Q" groups --triage PATH/triage.json --kind flag --limit 10
python3 "$Q" groups --triage PATH/triage.json --kind trajectory --task P07 --limit 10
python3 "$Q" groups --triage PATH/triage.json --kind trajectory_neighborhood --limit 10
python3 "$Q" list --triage PATH/triage.json \
  --group-kind trajectory --group-key GROUP_KEY --limit 10 --offset 0
python3 "$Q" neighbors --triage PATH/triage.json --episode EPISODE_ID --limit 5
python3 "$Q" neighbors --triage PATH/triage.json --episode EPISODE_ID \
  --outcome success --limit 3
python3 "$Q" compare --triage PATH/triage.json --left FAILED_ID --right OTHER_ID
```

Exact trajectory groups match semantic action signatures, not raw element IDs.
The group representative is a stable member, not a certified medoid. Inspect a
second differing member before deciding whether a shared explanation is plausible.
Neighborhoods were formed at similarity >=0.75 against their center; they overlap
and their endpoints need not resemble each other. Do not add their counts together.
Singletons/outliers may reveal new mechanisms that large groups hide.

`neighbors` ranks all eligible same-source/task candidates, including failures and
unknowns unless filtered. Different/unknown goals remain explicit; identical goals
rank first. `compare` requires the same recorded source/task and displays context
differences, first action divergence, preceding state differences, and focused
step links. It does not run an evaluator or infer a causal explanation.

## Manage context and scope

Query output is compact JSON, defaults to ten rows and caps each page at 100.
Use `--offset` to paginate; matched/returned counts disclose truncation. The helper
loads the saved index locally, not into the agent context, and performs comparisons
only as requested. The main analysis still uses pairwise same-task comparisons:
for much larger collections, build bounded task/cohort exports rather than assuming
this early prototype is a distributed or streaming analysis system.

Existing triage exports contain raw policy inputs and may be private. Opening a
local HTML report does not publish it to Vercel. Avoid selecting a root that also
contains earlier exported evidence, to prevent discovering copies as new episodes.

For format limitations and metric thresholds, read `docs/agents/failure-triage.md`
in the project. For a human walkthrough, read `docs/trace-triage.md`.
