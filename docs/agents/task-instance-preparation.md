# Configurable saved-world task preparation

`environments.website_world.task_instances` prepares task permutations from a
single JSON format. It uses existing native constructors, references, graders
and automatic runners. Changing size, predicates, priority order, shortlist
length, statistics operation/grain or review topic does not require another
runner, grader or setup script. Public wording is an ordinary editable string;
it is not required to equal the native constructor's English.

The initial adapter registry supports `feature_offer`, `catalog_priority`,
`catalog_shortlist`, `catalog_statistics` and `catalog_review`. Other accepted
task families keep their current interfaces. This is a saved-world preparation
API, not a SAT solver, world editor or new inference backend.

## Instance format

```json
{
  "schema": "website-task-instance-v1",
  "family": "catalog_statistics",
  "source": {
    "recipe": "./saved-statistics-recipe",
    "manifest_sha256": "REPLACE_WITH_THE_EXACT_64_CHARACTER_SHA256"
  },
  "parameters": {
    "kind": "comparison_catalog_statistics",
    "concept_id": "footwear.casual_trainers",
    "comparison_site_id": "comparison-00",
    "operation": "median",
    "grain": "listing"
  },
  "user_message": "How many priced casual-trainer retailer listings are there on Prislyktan, and what is their median listed price in SEK? Include the comparison-page link.",
  "start": {"kind": "comparison_catalog", "comparison_site_id": "comparison-00"},
  "requirements": {"status": "summary", "minimum_population": 1}
}
```

The source must be a frozen recipe of the same family, with a verified manifest
and complete data files. Native parameters are the existing family's spec,
not fields from its constructed task. Native constructors reject unsupported
parameters, concepts, units and combinations. Optional `memories` must equal
the native memory list; these initial families have no memory-driven semantics.
Use the existing memory-task family for that behavior.

The request should describe the task naturally and expose the intended scope.
Read it before launching. Do not add defensive checklists, forbidden-action
lists or hints to hidden/address-memory hindrances unless the scenario requires
them. This layer does not try to prove English equivalent to parameters.

Starts:

| Family | Supported start |
|---|---|
| Feature, priority, shortlist | `directory`, `tool_discovery`, or `comparison_home` for the task's named comparison site |
| Statistics | `comparison_catalog` for the task's site; opens its `/search` page |
| Review | `review_product` with a covering `site_id`, optional existing `query`; product identity comes from native parameters |

Feasibility requirements are optional; absent requirements retain natural
no-match and undefined results. `status` must equal the native reference
status. `minimum_population` counts qualifying offer rows for feature/priority,
qualifying distinct models for shortlists, priced observations at the declared
grain for statistics, written comments for topic summaries, and all ratings
for rating summaries. This is a check of a saved world, not sampling
conditioning. Unsuitable fixtures stop before any output is created.

## Common commands and Python API

Inspect native feasibility without creating a recipe:

```bash
python -m environments.website_world.task_instances instance.json
```

Prepare a new immutable recipe through the bounded launcher:

```bash
python3 scripts/run_bounded_job.py --memory-mib 4096 -- \
  timeout 90s .venv/bin/python -m environments.website_world.task_instances \
  instance.json --output .local/prepared/example
```

The CLI resolves relative source paths against the config file. Python callers
pass explicit recipe paths. All outputs must be fresh and separate from the
source. Preparation makes no world draws, browser runs or model calls.

```python
from environments.website_world import task_instances

receipt = task_instances.prepare(instance, output)
result = task_instances.run(
    output, run_directory,
    policy_session=policy_session,
    metadata=metadata,
    runner_options={"max_steps": 20, "max_input_tokens": 100000},
    quota_guard=quota_guard,
    viewer_projection=viewer_projection,
    extraction_backend_factory=formatter_factory,
)
```

Run options and mandatory automatic grading are delegated to existing family
runners. Provider authorization and bounded launch policy still apply. Scripted
browser checks must include `scripted` in metadata tags. No model backend is
chosen by this module.

## Output and preservation

`prepared-instance.json` binds the new recipe, config, native task ID and exact
world bytes. `recipe/` is the ordinary frozen family recipe consumed by its
existing runner. `native-input/` retains the derivative input and parent pin;
`instance-history/` inside the recipe preserves replaced native task/reference,
episode and previous public setup bytes. Unchanged generation records remain
historical records of the original world generation; the current task is
`task-instance.private.json` and the family task/reference pair.

The source recipe stays untouched. World, retailer population, surrounding
sites, complete reviews, cart/checkout policies and other unmodified data are
preserved byte for byte. Current implementation dependencies are frozen once
by the existing publisher. Private baseline data required by that freezer must
be available from an approved immutable dependency release; do not substitute
mutable working-tree files.

Preparation reports `runtime_acceptance: pending`. Native/reference checks do
not establish browser startup, automatic grading, HTTP projection or model
success for the new instance. Evaluation performs those existing acceptance
stages before promotion. No whole-run effect authority is inferred.
