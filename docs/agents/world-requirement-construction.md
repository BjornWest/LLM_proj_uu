# Bounded world requirements: construction investigation

Owner: Product's `world_requirement_construction` agent, 2026-10-10. The user
delegated this investigation so testing accepted scenarios can continue separately.
This is an isolated experiment, not a replacement generator or an episode release.

## What the first prototype establishes

`experiments/world_requirement_construction/` implements one requirement:
two declared, already physically stocked offers of a declared concept must be
the **only** cheapest available offers, tied at the same listed price.
Other available offers of that concept must be more expensive. All unrelated
products, retailers, stock, reviews and native manufacture remain unchanged.

The constructor edits exactly two price leaves in an immutable sampled world.
Both new prices must belong to the native rounded output grid inside the existing
clamped offset support. It chooses the highest common feasible price below the
unchanged competitors. Failure means this particular operator cannot construct
the request; it does not prove that no possible world satisfies it.

The example uses the accepted `e3fbfadd84d3b16a26895d62abb66f61df433697` source
root and its saved seed73 world:25 products,320 SKUs,12 retailers,411 offers.
The two declared offers are the same black/standard/EU39 walking-shoe SKU at
`footwear-02` and `apparel-06`. Their parent prices480/500SEK become470/470SEK;
the other309 available walking-shoe offers remain unchanged and more expensive.
The parent itself is preserved, including its original480SEK winner cohort.

This is a deliberately authored diagnostic world, **not** a natural draw or an
exact conditional sample. In particular, ordinary retailer/model-correlated
pricing can price several same-basis SKUs together; authoring two individual
offers need not preserve that joint prior support. Native per-offer monetary
validity is a different claim. The old `price_trace` records remain byte-equivalent
and explicitly describe the parent draw. New override provenance describes the
derivative; no adjusted price is attributed to the old random draw.

The existing independent `basic_offer_task.make/reference` evaluates the complete
candidate domain. A separate direct full-population scan checks its winner set.
The requirement additionally insists on physical stock at both targets, so
supplier-only offers cannot satisfy it. This is not a review-quality requirement.

## Dependency reconstruction and confidence boundary

The derivative rebuilds its world identity, native task/reference, basket-plan
binding with every original policy retained, and checkout-domain binding with
the exact original quantity limits retained. The parent's original plan/domain
are independently revalidated; both reject when applied to the derivative.
The old task also rejects the new world. Reversing the two price edits and
explicit identity/provenance/status/limitation changes reproduces the parent
object exactly. Original source files and original artifact bytes are rechecked.

Surrounding comparisons/reviews, public presentation, URL bindings, and execution
recipes are **not rebuilt and are unusable for the derivative**. The receipt says
`browser_runtime_ready:false`. No browser, model, new world draw, installation,
ordinary sampler validation, or shared source change occurs. Native construction
readiness does not imply that this world can be handed to a browser episode yet.

Evidence is under `.local/coordination/world-requirement-construction-20261010/`.
`native-v2/receipt.json` records the successful native run; its bounded process
completed in about3.75 seconds inside the operator and acceptance checks.
`native-v1-bounded/` preserves an initial experiment error: the runner selected
the legacy checkout-domain API instead of the accepted-catalog API. The parent
was not edited; choosing the correct released API fixed the runner. This is a
useful example of integration work unrelated to solver search difficulty.

## Three different amounts of work

| Approach | Required work | What we can currently substantiate |
| --- | --- | --- |
| Local edits to a sampled world | Define an edit boundary, preserve parent/provenance, rebuild dependent artifacts, run the independent complete requirement oracle | This two-price operator works on one saved world with positive/negative controls. Adding another price-only relation is modest if it uses the same graph of dependencies; stock/menu/review edits require additional rebuilders. |
| Solver-assisted edits of a bounded block | Model the block's finite choices and dependencies, keep the rest fixed, solve, materialize, and perform exactly the same rebuild/oracle checks | The earlier Z3 price/review pilot establishes small finite feasibility and exact weighting for its particular model. It is not connected to this merchant-price operator yet. |
| General prior-weighted whole-world construction | Model upstream brand/concept/entity support, all cross-stage constraints, actual priors, weighted completion masses and materialization, plus public/runtime reconstruction | Not implemented. Existing pilot results do not establish scalability or weighted correctness for whole shopping worlds. This is a substantially broader generator project. |

The dominant reusable work is the requirement vocabulary and the dependency
rebuilders, not picking a SAT library. For a two-price puzzle, copying the
immutable parent and calling existing binding/reference APIs is sufficient. A
review puzzle additionally needs truthful corpus generation and publication;
a stock/menu puzzle needs exact SKU/source/page consistency. Coupon, basket and
shipping requirements can change global winners and cannot be verified only
against the two edited entities.

There is no evidence-based calendar estimate for supporting arbitrary requirements.
The small measured native run demonstrates cheap *execution* of this operator,
not completion of the larger implementation. A sensible bounded next milestone
is one additional requirement sharing these dependencies, then a stock/menu or
review requirement to measure the cost of a genuinely new dependency block.

## Smallest next publication step

The missing step is a **saved authored-world recipe materializer**, not another
solver or manufacture run. It would accept this derivative plus the parent's
retained page-plan choices and explicit surrounding-site options, and emit a
fresh ordinary Website recipe. The existing accepted APIs already provide the
pieces, but the current saved-answer container intentionally copies original
world/task/site bytes and therefore cannot be pointed at the derivative unchanged.

1. Regenerate `surrounding_config.generate(world, controls)` with the explicitly
   retained version/options. Comparison membership and native review content
   should be retained where the unchanged seed/structural identities permit;
   every advertised price and `source_world_id/source_world_sha256` must be
   checked against the derivative. Merely changing the sidecar hash is invalid.
2. Rebuild presentation/composition envelopes for the retained page choices and
   assemble a fresh pin with the new world, task, reference, basket and domain.
   `unified_generation.generate(request, world_factory=...)` exposes an existing
   materialization seam, but its ordinary proposal/sampling audit must **not**
   be reported as a fresh natural draw when the factory supplies an authored
   world. The additive adapter must explicitly record this authoring method.
3. Create actual offer URL/selection bindings from that new Runtime and call
   `basic_offer_task.bind_reference` for every candidate and both ties. The
   existing `ListedOfferGrader` can supply the listed-answer semantics; attaching
   it through the current automatic lifecycle is a separate runtime acceptance.
4. Perform zero-provider startup/public price checks and positive/negative
   automatic-grade plus viewer controls on the exact recipe/build. This is the
   point at which Evaluation can call the scenario runnable.

These steps describe a bounded Website consumer handoff, not an implementation
or browser authorization in this experiment. No Website paths were changed.

## Next edit case that exercises a new dependency block

Prefer a stock case before arbitrary review rewriting: designate the cheapest
carried offer as unavailable while an unchanged higher-priced offer remains
physically available. Empty **all** source quantities on the target and explicitly
disable its supplier-order eligibility; otherwise a branch or supplier can keep
the offer purchasable. Retain the zero-stock offer in the merchant menu.

Unlike this price-only case, the new operator must rebuild warehouse stock in
the matching catalog listing and `warehouse_sold_out` on its page. It must keep
all source/offer/SKU joins, preserve unrelated stock, and rerun availability and
whole-population winner oracles before rebuilding the same external sidecars.
Stock-condition/draw records remain parent evidence with explicit override
provenance. A negative control retaining just one positive branch or enabled
supplier must reject the requested unavailability.

A later selector-reset requirement is a different menu edit: remove one
colour/size combination from the retailer's **carried assortment**, while keeping
the manufactured SKU valid and another size of that colour present. That requires
offer membership, listing traces, page grouping, selectors, quantity-domain and
summary reconstruction. Setting stock to zero does not create menu absence.

## Decisions to retain for Bjorn

- Diagnostic authored derivatives versus exact prior-conditioned samples are
  different products. The former can be delivered incrementally; the latter
  needs an explicit distribution and stronger reasoning about global support.
- This pilot chooses exactly two offer ties, not two different models. It tests
  retailer price relations; a product-comparison puzzle needs model-role rules.
- The pilot keeps all other prices frozen, so it declines when their minimum is
  below the targets' common native support. A later operator could edit more
  competitors, but that increases the perturbation and must be a declared choice.
- A common JSON requirement should describe a verifiable outcome, while the
  construction method and its search budget belong to a separate authoring plan.
  UNSAT for a bounded edit block must not be reported as global impossibility;
  solver timeouts and incomplete enumeration must remain unknown.

## Reproduction

Run the tiny schema/rounding tests directly:

```bash
python3 experiments/world_requirement_construction/test_model.py
```

Run the saved-only native checks with a fresh output and bounded receipt:

```bash
python3 scripts/run_bounded_job.py --memory-mib 2048 \
  --receipt .local/world-construction-reproduce-bounded -- \
  timeout 90s .venv/bin/python experiments/world_requirement_construction/run.py \
  --native-root /home/bjorn/code/LLM_proj_uu-worktrees/eval-diverse-offers-20261008-r1 \
  --native-commit e3fbfadd84d3b16a26895d62abb66f61df433697 \
  --recipe .local/coordination/task-testing-20261008/Evaluation-diverse-offers-acceptance-v1/feature-recipe \
  --requirement .local/coordination/world-requirement-construction-20261010/requirement-v1.json \
  --output .local/world-construction-reproduce
```

The runner refuses a different dependency HEAD, tracked source drift, wrong
accepted input hashes, imports from another project root, and reused output
directories. Source verification is specific to this explicit experiment and is
not added to ordinary generation.
