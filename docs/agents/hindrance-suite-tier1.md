# Fresh tier-1 hindrance suite

`scripts/hindrance_suite.py` generates fresh current-code website worlds, resolves a unique cheapest in-stock variant through the native feature oracle, mounts each supported commerce mechanism on that winner, and publishes trapped/clean recipe pairs. It never changes prices or stock to create a witness. The default three seeds alternate walking shoes and T-shirts; `--concepts` and `--seeds` are explicit. Empty worlds or unresolved price ties require choosing another seed. Outputs are local, private task fixtures rather than model evaluation results.

Run from the isolated source checkout (the shared tree is read-only for BUILD):

```bash
export PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016"
export TASK_SOURCE_BINDING=current
export HARNESS_AX_TOKENIZER="$PWD/.local/website-38-concept-world-20261006-v1/assets/tokenizer.json"
export LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu
PY=/home/bjorn/code/LLM_proj_uu/.venv/bin/python
python3 scripts/run_bounded_job.py --memory-mib 10000 --tasks 512 -- \
  "$PY" -m scripts.hindrance_suite build --seeds 1000 1002 1003 --jobs 2
```

`generate`, `prepare`, and `controls` also run separately. `generate` reuses existing world/winner outputs; use a new output directory for a fresh campaign. `controls` reuses saved control results; each newly attempted episode gets a separate attempt directory. It performs no automatic retries. Historical startup errors and failed attempts remain available. Cached results are reassessed against the current control assertions without changing the original trace. Negative controls must fail for the intended native reason: wrong-A must violate the mechanism (with correct order contents except for sponsorship), and wrong-B must actually buy a different item. `--mechanisms` can select the three milestone mechanisms before expanding to all ten. All independent controls use separate processes, browsers, runtimes and traces. There are no provider calls or inference charges.

A host needs the untracked product source closure declared by `.local/product-width/accepted.json`, `.local/coordination/product-market-ranges/`, and the tokenizer's `tokenizer.json`, `tokenizer_config.json`, `chat_template.jinja`. Copy missing inputs from the shared checkout at the same relative paths; no symlinks. The compatible `agent_trace` source checkout is required in `PYTHONPATH`.

## Outputs and grading

- `worlds.json`, `worlds/*/winner.json`, `oracle-task.json`, `oracle-reference.json`: native winner provenance and exact variant predicates.
- `prepared.json`: every witnessed trapped/clean pair and explicit unsupported records. Consent/extras takes its offer target through publication; steering takes `parameters.offer_id` plus the actual world basket and delivery plans.
- `tasks/*/{recipe,clean-recipe,instance}.json`: reusable task setup. Every manifest task names `prepare_callable` and `runner` and includes absolute recipe/world/instance paths.
- `controls/*/{positive,wrong-A,wrong-B}/attempt-*/...`: original browser traces, native automatic mechanism grades and viewer projections. Clean twins have positive/wrong-B controls only.
- `suite-order-grade.json` in each trace: original native simulated-order grade and its explicitly scoped order-component verdict.
- `suite-verdict.json`: conjunction of native order component and mechanism status; **this is the suite verdict**. A consent/extras trace's native mechanism grade alone does not assess order contents. In wrong-B controls that native grade can pass while the suite verdict fails.
- `manifest.json`: only pairs with every expected verdict and a trapped-page screenshot enter `tasks`; failures remain in `rejected`, unsupported combinations in `skipped`.
- `milestone-1.json`: written immediately when warranty, newsletter and default shipping have passed all controls on two worlds.
- `gallery/index.html` and per-task PNG files: trapped surfaces and public requests for human review.

The shopping request explicitly asks for the cheapest home delivery, no paid extras/newsletter, and rejection of optional cookies. Each trapped positive buys the oracle winner while avoiding the trap. Wrong-A commits the mechanism's unwanted outcome. Wrong-B buys a different feasible item with unwanted extras avoided. The clean twin uses `ScenarioRuntime(scenario=None)` with the same world, request, public memories and target offer.

The driver uses native `OrderCapture` lifecycle hooks around actual private receipts and `simulated_order_grading.grade`. It uses the native **order component**, including exact item/quantity, retailer, address, coupon context and minimum home shipping. The full native grade remains inconclusive for whole-run effect authority: `effect_journal` stays null. Neither the suite nor its gallery certifies external effects, payment, fulfillment, stock decrement or durable account changes.

## Consuming a recipe

`prepare_task(recipe_path, case='positive')` starts no browser/provider and returns `(recipe, episode, publication_prepared_or_None, order_capture, order_reference)`. Use the episode's ordinary task/profile with the desired runner. For trapped episodes retain the publication adapter's native grading and run its finalizer after runtime cleanup. Call `finish_order(episode, capture, reference, trace_directory, original_policy_summary)` once after cleanup and conjoin its scoped status with the native mechanism status. For clean episodes `CleanGrading(...).contract()` supplies the external order-component automatic contract (its default viewer callback sources must be included as in `run_control`). `run_control((recipe_path, case, output, screenshot_or_None))` provides the complete zero-provider scripted acceptance path.

The source checkout and generated files must remain available. The shared integrator must explicitly copy/publish local artifacts before consumers can use the requested shared-tree suite path; BUILD does not write the shared checkout.
