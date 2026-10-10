# Bounded world requirements: construction investigation

Owner: Claude Code (world construction) since 2026-10-10; started by Product's
`world_requirement_construction` Codex agent the same day. This is an isolated
experiment, not a replacement generator or an episode release.

## Two tracks, two different bars

- **Editing a sampled world** (this experiment). The result is an authored
  scenario. No probability is claimed for it and none is needed. The bar is
  that the edited world still obeys every rule the producer obeys, so it looks
  like a world the producer could have made.
- **Solver-backed sampling** (`experiments/constrained_world_pilot/`, not
  connected to this operator). Here probabilities matter: a constrained sample
  needs the prior weight of what it conditions on.

## What the operator does

`experiments/world_requirement_construction/` implements one requirement:
the declared retailers must be exactly the cheapest available sellers of a
declared product within its concept. One retailer makes a sole cheapest seller;
two or more make a tie.

The producer prices a product **once per retailer**: one recorded draw
(`matched_reference_draw`, `offset_draw`), applied to every listed SKU through
`rounded_price`. The operator therefore edits that draw, never a single SKU's
price. It replaces the draw for a designated retailer/product pair and
recomputes every SKU of the pair with the producer's own rounding. It only uses
draws the producer can emit: the matched reference draw, the clamp endpoints,
and one offset from each interval between neighbouring rounding flips of any
SKU in the pair. The intervals matter when SKUs have their own reference
prices and round in different steps; per-SKU bin centres would miss some of
their joint prices.

Among the prices all designated retailers can reach below the unchanged
competitors, it picks the one that reprices the fewest retailers, then has the
smallest total movement over every repriced SKU price (unavailable siblings
included), then is lowest. This is a deterministic choice, not a random
feasible one. Declining means this operator cannot construct the request; it
does not prove that no world satisfies it. Each decline carries a reason code
(`price_rule`, `unavailable`, `already_holds`, `no_common_price`,
`not_sampled`, `winners`, `operator_limit`).

`price_rule_violations` checks the pricing rule over the whole world: every
price follows from its recorded draw and a positive manufacturer reference, the
draw is one the producer's matched or unmatched branch can record under the
world's own price config, and all SKUs of a product at a retailer share it. The
operator requires this of the parent and of the result. The native commerce
validator does not check it.

### Demonstrated case

Saved seed 73 at accepted source `e3fbfadd84d3b16a26895d62abb66f61df433697`:
25 products, 320 SKUs, 12 retailers, 411 offers. All 411 parent prices satisfy
the pricing rule. One walking shoe costs 480 SEK at `footwear-02` and 500 SEK
at `apparel-06`. Requiring both retailers to be the cheapest sellers reprices
`apparel-06`'s draw for that shoe: its six sizes move from 500 to 480 SEK.
`footwear-02` is untouched. The 12 offers of the two retailers are the only
cheapest available walking shoes; every other offer is unchanged.

### Retired first version

The first operator (`authored-two-offer-price-tie-v1`, commits `e4e26074` to
`394f70aa`) overwrote the price of two individual SKUs. That left one size at
470 SEK beside five sibling sizes at 480 or 500 SEK on the same product page,
which the producer cannot emit for any seed. The pricing-rule check now rejects
that derivative. Its evidence (`native-final-v5/` and earlier) remains as
history under the coordination directory; do not publish it.

## What is rebuilt and what is not

The derivative gets explicit authoring provenance (the parent's draw and every
repriced offer), a new world identity, a new native task/reference, and rebuilt
basket-plan and checkout-domain bindings with the parent's policies and
quantity limits. The changed `price_trace` records hold the authored draw, so
the seed no longer reproduces those prices; provenance says so. A canonical-JSON
comparison confirms that nothing outside the declared offers' price and draw
fields differs from the parent, including value types.

Surrounding comparisons/reviews, public presentation, URL bindings and
execution recipes are **not rebuilt and are unusable for the derivative**. The
receipt says `browser_runtime_ready: false`. No browser, model or new world
draw occurs.

Availability is the native oracle's: stock at any source or an enabled supplier
order. The first version's extra insistence on physical stock is gone; add it as
a separate declared requirement if a scenario needs it.

## Evidence and cost

Evidence is under `.local/coordination/world-requirement-construction-20261010/`:
`native-v7/receipt.json` (with negative controls) and
`native-v7-construct-only/receipt.json`. The requirement is `requirement-v2.json`.
`native-v6*` are the same case on the first draw-level commit, before the Codex
review fixes; the emitted world is the same.

The edit itself is cheap: about 0.2 s for `construct` on this world, most of it
the native oracle hashing the 6.4 MB world. A whole runner invocation is
dominated by loading, source pinning and rebuilding the bindings. Negative
controls are opt-in (`--controls`) and are not needed to construct.

Unit tests build a tiny synthetic world and judge it with the real native
oracle, so they run from a fresh checkout without saved worlds.

## Smallest next publication step

The missing step is a **saved authored-world recipe materializer**, not another
solver or manufacture run. It would accept a derivative plus the parent's
retained page-plan choices and explicit surrounding-site options, and emit a
fresh ordinary Website recipe. The existing saved-answer container copies the
original world/task/site bytes and cannot be pointed at a derivative unchanged.

1. Regenerate `surrounding_config.generate(world, controls)` with the retained
   version/options. Comparison listings take the minimum price per
   product/retailer pair, so they follow the new prices; every advertised price
   and `source_world_id/source_world_sha256` must be checked against the
   derivative. Changing only the sidecar hash is invalid.
2. Rebuild presentation/composition envelopes for the retained page choices and
   assemble a fresh pin with the new world, task, reference, basket and domain.
   `unified_generation.generate(request, world_factory=...)` exposes a
   materialization seam, but its sampling audit must not be reported as a fresh
   natural draw when the factory supplies an authored world.
3. Create actual offer URL/selection bindings from the new Runtime and call
   `basic_offer_task.bind_reference` for every candidate and every tied winner.
   `ListedOfferGrader` can supply the listed-answer semantics; attaching it
   through the automatic lifecycle is a separate runtime acceptance.
4. Zero-provider startup, public price checks, and positive/negative
   automatic-grade plus viewer controls on the exact recipe/build. Only then can
   Evaluation call the scenario runnable.

## Next edit that exercises a new dependency block

Prefer a stock case: make the cheapest carried offer unavailable while an
unchanged higher-priced offer remains available. Stock has its own producer
rules (a condition per product and source, then a zero draw and a quantity per
SKU and source, then supplier eligibility only without dispatchable stock), so
the operator should again edit recorded draws where they exist and add a stock
rule check beside the price one. It must also rebuild the catalog page's stock
summaries, which the price edit never touched.

A selector-reset requirement is a different, menu-level edit: remove one
colour/size combination from a retailer's carried assortment. Zero stock is not
menu absence.

## Decisions to retain for Bjorn

- Edits need rule-consistency, not probabilities (Bjorn, 2026-10-10).
  Probabilities belong to the solver-backed sampling track.
- A requirement describes a verifiable outcome; the construction method and its
  search budget are separate. A bounded decline is not global impossibility.
- "Two offers tie" at SKU level is not a price requirement in this producer: a
  retailer's SKUs of one product share a price. It arises naturally only when
  stock leaves one SKU available at each retailer, which is a stock requirement.
- The sampled-parent marker check is a scope guard, not proof against stripped
  provenance. The runner binds the parent recipe to an externally declared
  manifest digest. Authored chains are outside this operator's scope.

## Reproduction

Unit tests:

```bash
.venv/bin/python -m pytest -q experiments/world_requirement_construction/test_model.py
```

Saved-only native construction with a fresh output and bounded receipt:

```bash
python3 scripts/run_bounded_job.py --memory-mib 2048 \
  --receipt .local/world-construction-reproduce-bounded -- \
  timeout 90s .venv/bin/python experiments/world_requirement_construction/run.py \
  --native-root /home/bjorn/code/LLM_proj_uu-worktrees/eval-diverse-offers-20261008-r1 \
  --native-commit e3fbfadd84d3b16a26895d62abb66f61df433697 \
  --constructor-commit EXACT_REVIEWED_CONSTRUCTOR_COMMIT \
  --recipe .local/coordination/task-testing-20261008/Evaluation-diverse-offers-acceptance-v1/feature-recipe \
  --expected-parent-manifest-sha256 4381a4e6047e4370833f8b2f2d95135f2511b5a0bfb59f31a341cd2d42128ba5 \
  --requirement .local/coordination/world-requirement-construction-20261010/requirement-v2.json \
  --controls --output .local/world-construction-reproduce
```

The runner refuses a different dependency HEAD, tracked source drift, wrong
accepted input hashes, imports from another project root, a constructor that
differs from its declared commit, and reused output directories.
