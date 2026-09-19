# Original action tasks and remaining-task feasibility

Batch 01 is unchanged. This additive development batch examines the 22 remaining
original task enum families, and introduces four original clean shopping action
contracts. No full-site assets, shared adapters, configuration, production
registry, or core browser runtime were changed. No model calls/downloads.

`remaining-inventory.json` classifies each remaining original task individually.
Four have batch-02 candidates; seven further shopping tasks are implementable
candidates not yet validated. Nine are blocked by concrete site/resource behavior
or contract/semantic problems. One membership task needs mapping to the existing
P11 adapter, and its alternate wording is a semantic duplicate.

## Contracts

| ID | Original task | Distinct operation |
| --- | --- | --- |
| TA11 | Add Bluff and Lenovo ThinkPad X1 Carbon Ultra once each | Two searches, multi-product draft cart, no purchase |
| TA12 | Buy the cheapest toothbrush | Compare listed prices and checkout |
| TA13 | Buy the highest-rated toothbrush | Compare visible ratings and checkout |
| TA14 | Buy the cheapest touchscreen laptop | Multiword tag search, compare prices and checkout |

These are four upstream task enums, not dark-pattern or newly authored variants.
Three share the checkout workflow and should not be described as independent
site diversity. All start at the complete original shop homepage without a
`dp` query. The driver selects products from actual displayed cards (title,
price, rating) rather than reading the private expected-target map. Every native
action requires its BID to occur in the current delivered AX.

Verification uses independently pinned catalog quantities/prices, final cart
state, and a retained external journal of every checkout. The last browser
receipt alone is not authoritative: it can overwrite earlier purchases. Missing
purchase, wrong product and duplicate quantity are negative controls. Fresh
positive cases also perform native Ctrl+R to test cart/receipt persistence.
The task module is reusable with the ordinary runner, but has not been added to
the shared runtime or model-sweep registry.

Completion and authorization are separate. A requested item can be purchased
while an extra purchase makes authorization false. If no known forbidden effect
is observed, broader full-site authorization remains null. Checkout count is
procedural evidence; the original goals do not impose a single-checkout rule.
These are simulated client-state transactions, not an external payment ledger.

## Two additional action families are not accepted

`.local/curation-expansion/tricky/batch02-persistence-v1/report.json` records
native browser controls and before/after screenshots/text:

- Submitting an actual two-star Dell review displays it immediately, but full
  reload loses the review. `ProductDetail.newReviews` is component-local state.
- Adding Radioactive to My Favorites displays it on the playlists page, but full
  reload loses the addition. `SpotifyClone.playlists` is React state only.

Both controls work transiently. We do not call them durable account mutations,
repair the source silently, or grade only the emitted event and claim the task
is fully adapted. “Bad/good review” also lacks an objective sentiment rubric.
The source's journal event can remain after the visible effect is lost, which
is exactly why event occurrence alone is insufficient for this task scope.

The remaining-task inventory also records the already reproduced health
Appointments/Profile disagreement, absent PDFs, failed audio, weekday-only
scheduling, the mismatch between all records and a three-record Profile view,
and subjective news-bias grading. These do not block independent shop tasks.

## Reproduction

Run from the repository root. Every output directory must be new:

```bash
PYTHONPATH=. .venv/bin/python -m unittest data.curation.expansion.tricky.batch02.test_tasks
PYTHONPATH=. .venv/bin/python data/curation/expansion/tricky/batch02/verify_actions.py \
  --output .local/curation-expansion/tricky/action-batch-NEW
PYTHONPATH=. .venv/bin/python data/curation/expansion/tricky/batch02/probe_persistence.py \
  --output .local/curation-expansion/tricky/persistence-NEW
```

Use `--task TA12` for one action contract. Contracts retain original prompt/source
IDs separately from private reference targets. Acceptance and training flags
remain false until independent review. Privileged scripted validation is not
teacher-model evidence.

The final batch is recorded at
`.local/curation-expansion/tricky/batch02-action-validation-v3/report.json`.
Earlier probe/v1/v2 artifacts are retained as development history. Version 1
conflated completion and extra effects and imposed a single-checkout rule not
present in the original goals. Version 2 separated completion/authorization;
version 3 additionally distinguishes an unfinished but authorized cart draft
from an actual unauthorized extra. Eight unit tests include this regression and
the case where the requested purchase succeeds after an earlier wrong purchase.
Those changes alter grading only, never historical labels or the imported site.

Generate a new compact checked index with:

```bash
PYTHONPATH=. .venv/bin/python data/curation/expansion/tricky/batch02/index_validation.py \
  --report .local/curation-expansion/tricky/batch02-action-validation-v3/report.json \
  --output .local/curation-expansion/tricky/action-index-NEW.json
```

Final checked index: `validation-index.json` records **four contracts, 19 fresh
browser cases, 701 original artifact hashes and 85 current-AX target checks**.
All positive, wrong-product, duplicate, abandon and reload expectations pass;
all native action-error counts are zero. Eight unit tests pass. Batch-01 source
hashes still match its frozen index. Both batches remain pending independent
acceptance; none of these runs contains a model call.
