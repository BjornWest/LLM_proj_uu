"""Requirements that steering can force for a native task, with their probabilities.

Given a world and a native task specification (the `task` of a generation
request: its kind, concept, predicates and so on), `of` lists scenarios of
that task as requirement files for the runner: the likeliest outcome, a hard
variant (a better offer that does not count is listed ahead of the winner, a
tie at a shortlist's cutoff, a relaxation that has to be used, a basket that
just misses free shipping), and an unlikely outcome; for a review summary,
each verdict the count can come to. For the memory and
clarification tasks the native module first resolves the remembered or hidden
requirement into the predicates of the feature task that decides the answer. Each comes with the
probability the block model gives it on this world, so that a caller can see
what it is asking for.

Run as a module from the repository root to write them for a generation
input:
    python -m experiments.steered_generation.variants --native-root ROOT --native-commit COMMIT \\
        --generation-input INPUT.json --task TASK.json --output FOLDER
That makes one natural pass through the real producer and no steered one.
"""
import argparse
import importlib
from itertools import combinations
import json
from math import log
from pathlib import Path

from . import (blocks, carriers, cheapest, combined, couriers, listed, prices, reviews, shipments, shortlist, stock, streams,
               threshold)

# Native task kinds read by the cheapest-available block, with the fields of the task that state the reading.
# A comparison site goes with the surrounding-site controls the world is published with (`surrounding`).
SITE = ("comparison_site_id", "surrounding")
WINNERS = {"cheapest_available": SITE,
           "cheapest_matching_available": ("predicates", "availability", *SITE),
           "cheapest_matching_local_branch_stock": ("predicates", "city", "country", *SITE),
           "recommend_matching_by_priorities": ("predicates", "availability", "priorities", *SITE),
           "cheapest_matching_unit_price": ("predicates", "availability", "unit_basis", *SITE),
           "cheapest_matching_with_permitted_relaxations": ("predicates", "availability", "relaxations", *SITE)}
OTHERS = ("shortlist_matching_models", "comparison_cheapest_exact_sku_stock", "audit_free_shipping_claim",
          "summarize_product_reviews", "summarize_carrier_reviews")
# Kinds whose answer is a feature task's, once the native module has resolved what the shopper left unsaid.
RESOLVED = {"cheapest_matching_with_memory": ".memory_offer_task",
            "cheapest_matching_after_clarification": ".hidden_offer_task"}
# Every field of a task that this module reads or knowingly leaves alone, by kind. A task with any other field
# is refused: a native field that changes the answer (a price cap, say) must not be dropped in translation.
DELIVERY = "matching_single_item_delivery"
FIELDS = {**{kind: {"kind", "concept_id", *fields} for kind, fields in WINNERS.items()},
          # One unit delivered home at the lowest total; a cap, a deadline, other delivery methods or a comparison
          # site are not carried. The recipe's delivery settings come beside the task, not in it.
          DELIVERY: {"kind", "concept_id", "predicates", "objective", "destination", "delivery_types", "delivery_options"},
          "cheapest_matching_with_memory": {"kind", "concept_id", "recipient", "predicates", "memory_records",
                                            "availability", *SITE},
          "cheapest_matching_after_clarification": {"kind", "concept_id", "predicates", "hidden_requirement",
                                                    "availability", *SITE},
          "shortlist_matching_models": {"kind", "concept_id", "predicates", "availability", "limit", *SITE},
          "comparison_cheapest_exact_sku_stock": {"kind", "sku_id", *SITE},
          # The delivery methods change which options the native task counts, not the subtotal test steered here.
          "audit_free_shipping_claim": {"kind", "retailer_index", "offer_index", "quantity", "delivery_types"},
          "summarize_product_reviews": {"kind", "concept_id", "operation", "subject_scope", "product_index", "topic",
                                        "min_assessed"},
          "summarize_carrier_reviews": {"kind", "operation", "carrier_index", "shipping_class", "date_from", "date_to",
                                        "aspect", "min_assessed"}}


def ranked(world, needs, api, module=cheapest, shared=None):
    """The possible ones of some requirements, likeliest first, as (log probability, requirement).

    `shared` is a `cheapest.frame` for requirements of one reading, which are
    then modelled without rebuilding what they have in common.
    """
    found = []
    for need in needs:
        try:
            block = module.model(world, need, api, shared) if shared else module.model(world, need, api)
        except prices.ZeroMass:
            continue
        found.append((getattr(block, "log_probability", None) or log(block.probability), need,
                      {"probability_is_estimated": True, "probability_standard_error": block.error}
                      if getattr(block, "estimated", False) else {}))
    return sorted(found, key=lambda row: (-row[0], json.dumps(row[1], sort_keys=True)))


def entry(name, summary, row):
    return {"name": name, "summary": summary, "log_probability": row[0], "requirement": row[1], **(row[2] if len(row) > 2 else {})}


def winners(world, task, api, extra=None):
    """Scenarios of a task whose answer is the best available offer under the task's reading."""
    stated = {key: task[key] for key in WINNERS[task["kind"]] if task.get(key)}
    if task["kind"] == "cheapest_matching_local_branch_stock":
        stated["availability"] = cheapest.BRANCH
    base = {"schema": cheapest.VERSION, "concept_id": task["concept_id"], **stated, **(extra or {})}
    shared = cheapest.frame(world, base, api)
    scope = shared.scope
    offers = [(r["retailer_id"], o) for r in world["retailers"] for o in r["offers"] if o["sku_id"] in scope.skus and
              (scope.pairs is None or (r["retailer_id"], o["product_id"]) in scope.pairs)]
    pairs = sorted({(rid, o["product_id"]) for rid, o in offers})
    alone = ranked(world, ({**base, "product_id": product, "retailer_ids": [rid]} for rid, product in pairs), api,
                   shared=shared)
    if not alone:
        return []
    found = [entry("likeliest_winner", "the retailer and product most likely to be the only best available offer", alone[0])]
    top = alone[0][1]
    # A ranking by delivered totals with a charge that depends on the location takes no offers listed below the winner.
    bounded = scope.delivered is not None and not all(charge.uniform for charge in scope.delivered.values())
    behind = [] if bounded else ranked(
        world, ({**top, "listed_below": [{"retailer_id": rid, "sku_id": o["sku_id"]}]} for rid, o in offers
                if (rid, o["product_id"]) != (top["retailer_ids"][0], top["product_id"])), api, shared=shared)
    if behind:
        found.append(entry("better_offer_unavailable", "the same winner, with the likeliest single offer of another "
                           "retailer or product that would rank ahead of it listed and unavailable", behind[0]))
    if len(alone) > 2:
        found.append(entry("unlikely_winner", "the retailer and product at the middle of the ranking by probability",
                           alone[len(alone) // 2]))
    if scope.delivered is not None and "delivery_types" not in base["delivered"]:
        # The likeliest winner again, delivered home by the carrier this world rates lowest.
        rated = min(world["carrier_evidence"]["public"]["carriers"],
                    key=lambda row: (row["summary"]["average_stars"], row["carrier_id"]))
        with_carrier = ranked(world, [{"schema": couriers.VERSION, "carrier_id": rated["carrier_id"],
                                       "cheapest": {key: value for key, value in top.items() if key != "schema"}}], api, couriers)
        if with_carrier:
            found.append(entry("cheapest_delivered_with_lowest_rated_carrier", "the same winner, whose cheapest delivery "
                               "option, the one its total is made with, is the carrier this world rates lowest",
                               with_carrier[0]))
    return found


def relaxations(world, task, api):
    """One scenario per criteria set of a relaxation task: that set is the first with an available match."""
    relaxation = importlib.import_module(api.basic.__package__ + ".catalog_relaxation_task")
    labels = [relaxation.ORIGINAL] + [row["label"] for row in task["relaxations"]]
    found = []
    for index, label in enumerate(labels):
        rows = winners(world, task, api, {"selected": label})
        if rows:
            found.append({**rows[0], "name": f"criteria_set_{index}",
                          "summary": f"'{label}' is the first criteria set with an available match"})
    return found


def shortlists(world, task, api):
    """The natural shortlist, a tie at the cutoff, and another shortlist of the limit's size.

    The tie and the other shortlist are the likeliest among the first limit +
    3 models of the natural ranking, not among all models. A task without a
    limit lists every model and is not something a shortlist requirement can
    state.
    """
    if type(task.get("limit")) is not int:
        raise ValueError("Steering states a shortlist for an integer limit; a task that lists every model has none")
    base = {"schema": shortlist.VERSION, "concept_id": task["concept_id"], "limit": task["limit"],
            **{key: task[key] for key in ("predicates", "availability", *SITE) if task.get(key)}}
    reference = shortlist.reference(world, {**base, "limit": 10}, api)[1]
    models, limit = [row["product_id"] for row in reference["all_models"]], task["limit"]
    natural = [row["product_id"] for row in shortlist.reference(world, base, api)[1]["selected_models"]]
    listing = lambda group: {**base, "product_ids": list(group)}
    # A world in which no model has an available matching offer has no shortlist to name.
    found = [entry("natural_shortlist", "the shortlist as this world has it", row)
             for row in ranked(world, [listing(natural)] if natural else [], api, shortlist)]
    nearby = models[:limit + 3]
    ties = ranked(world, (listing(group) for group in combinations(nearby, limit + 1)), api, shortlist)
    if ties:
        found.append(entry("tie_at_cutoff", "one model more than the limit: two or more models share the cutoff price",
                           ties[0]))
    others = ranked(world, (listing(group) for group in combinations(nearby, limit) if set(group) != set(natural)),
                    api, shortlist)
    if others:
        found.append(entry("another_shortlist", "the likeliest shortlist of the limit's size other than the natural one",
                           others[0]))
    return found


def comparison_stock(world, task, api):
    """The comparison-stock task: who the site shows cheapest for the model, and the variant's stock there."""
    sku_id, site = task["sku_id"], {key: task[key] for key in SITE if task.get(key)}
    product = next((p["public"]["product_id"] for p in world["products"] for s in p["public"]["skus"]
                    if s["sku_id"] == sku_id), None)
    if product is None:
        raise ValueError("The task's SKU is not a product of this world")
    sellers = sorted(r["retailer_id"] for r in world["retailers"] if any(o["sku_id"] == sku_id for o in r["offers"]))
    advertised = ranked(world, ({"schema": listed.VERSION, "product_id": product, "retailer_ids": [rid], **site}
                                for rid in sellers), api, listed)
    found = []
    for log_chance, need, _ in advertised[:1]:
        retailer = next(r for r in world["retailers"] if r["retailer_id"] == need["retailer_ids"][0])
        nothing = {source["source_id"]: {"max": 0} for source in retailer["source_locations"]}
        for name, summary, stated in (
                ("advertised_cheapest_in_stock", "the retailer shown cheapest holds the variant", {"availability": "in_stock"}),
                ("advertised_cheapest_on_supplier_order", "the retailer shown cheapest has the variant only on supplier "
                 "order", {"availability": "backorder", "stock": nothing}),
                ("advertised_cheapest_unavailable", "the retailer shown cheapest has the variant listed and unavailable",
                 {"availability": "unavailable"})):
            part = {"schema": stock.VERSION, "retailer_id": retailer["retailer_id"], "sku_id": sku_id, **stated}
            try:
                chance = log_chance + log(stock.model(world, part, api).probability)
            except prices.ZeroMass:
                continue
            found.append(entry(name, summary, (chance, {"schema": combined.VERSION, "all": [need, part]})))
    return found


def free_shipping(world, task, api):
    """The shipping-claim task's offer and quantity against the retailer's threshold."""
    retailers = sorted(world["retailers"], key=lambda r: r["retailer_id"])
    indexes = [task.get("retailer_index", 0), task.get("offer_index", 0), task.get("quantity", 1)]
    if any(type(value) is not int or value < 0 for value in indexes) or indexes[2] < 1 or indexes[0] >= len(retailers):
        raise ValueError("The task selects a retailer, an offer and a quantity by non-negative integers within the world")
    retailer = retailers[indexes[0]]
    offers = sorted(retailer["offers"], key=lambda o: o["offer_id"])
    if indexes[1] >= len(offers):
        raise ValueError("The selected retailer has no offer at this index")
    offer = offers[indexes[1]]
    base = {"schema": threshold.VERSION, "retailer_id": retailer["retailer_id"], "sku_id": offer["sku_id"],
            "quantity": task.get("quantity", 1)}
    close = {"max": offer["price_trace"]["reference_minor"] * base["quantity"] // 5}
    rows = (("no_threshold", "the retailer advertises no free-shipping threshold", {"subtotal_test": "no_threshold"}),
            ("meets_threshold", "the subtotal reaches the threshold", {"subtotal_test": "meets_threshold"}),
            ("below_threshold", "the subtotal is below the threshold", {"subtotal_test": "below_threshold"}),
            ("just_below_threshold", "the subtotal misses the threshold by at most a fifth of the basket's reference value",
             {"subtotal_test": "below_threshold", "gap_minor": close}),
            ("just_meets_threshold", "the subtotal reaches the threshold with at most a fifth of the basket's reference "
             "value to spare", {"subtotal_test": "meets_threshold", "gap_minor": close}))
    return [entry(name, summary, row) for name, summary, stated in rows
            for row in ranked(world, [{**base, **stated}], api, threshold)]


def review_verdicts(world, task, api):
    """The review-summary task's verdict on one product and topic: one candidate per verdict that can occur."""
    if task.get("operation") != "topic_counts" or task.get("subject_scope", "product") != "product":
        raise ValueError("Steering states topic counts over all of a product's reviews, not ratings or one option's")
    products = sorted(p["public"]["product_id"] for p in world["products"]
                      if p["public"]["concept_id"] == task["concept_id"])
    index = task.get("product_index", 0)
    if type(index) is not int or not 0 <= index < len(products):
        raise ValueError("The task selects a product of its concept by an index within the world")
    base = {"schema": reviews.VERSION, "product_id": products[index], "topic": task.get("topic"),
            "min_assessed": task.get("min_assessed", 1)}
    found = verdicts(world, base, api, reviews)
    # The verdict against the stars, where that can occur: the product's rating summary points the other way.
    for name, verdict, limits, words in (
            ("high_stars_verdict_more_negative", "more_negative", {"min": 4},
             "more comments report the topic unfavourably than favourably, yet the product's mean rating is four stars or more"),
            ("low_stars_verdict_more_positive", "more_positive", {"max": 2},
             "more comments report the topic favourably than unfavourably, yet the product's mean rating is two stars or less")):
        try:
            found += [entry(name, words, row) for row in ranked(
                world, [{**base, "verdict": verdict, "mean_rating": limits}], api, reviews)]
        except blocks.NumericalLimit:
            pass
    # The first page against the whole, as a review site lists comments four to a page with the highest ratings
    # first (the suite's instance of it); only where the block reads the concept's reviews for pages.
    for shown, verdict in (("more_positive", "more_negative"), ("more_negative", "more_positive")):
        need = {**base, "verdict": verdict, "first_page": {"size": 4, "order": "highest", "verdict": shown}}
        try:
            found += [entry(f"first_page_{shown}_verdict_{verdict}",
                            f"the first four comments, highest ratings first, are {shown.replace('_', ' ')} about the topic "
                            f"and all the comments together are {verdict.replace('_', ' ')}", row)
                      for row in ranked(world, [need], api, reviews)]
        except (blocks.NumericalLimit, ValueError):
            pass
    return found


def verdicts(world, base, api, module, prefix="", note=""):
    words = {"more_positive": "more comments report the topic favourably than unfavourably",
             "more_negative": "more comments report the topic unfavourably than favourably",
             "tie": "as many comments report the topic favourably as unfavourably",
             "insufficient_evidence": "fewer comments assess the topic than the task asks for"}
    return [entry(prefix + "verdict_" + row[1]["verdict"], words[row[1]["verdict"]] + note, row)
            for row in ranked(world, [{**base, "verdict": verdict} for verdict in reviews.VERDICTS], api, module)]


def carrier_verdicts(world, task, api):
    """The carrier-review task's verdict on one carrier and aspect: one candidate per verdict that can occur.

    Twice over where the aspect allows it: with what happened to the
    carrier's shipments kept, so that a verdict their histories rule out is
    not among the candidates, and (`redrawn_shipments_...`) with the shipments
    redrawn as well.
    """
    if task.get("operation") != "topic_counts":
        raise ValueError("Steering states topic counts over a carrier's reviews, not ratings")
    names = sorted(c["carrier_id"] for c in world["carrier_evidence"]["public"]["carriers"])
    index = task.get("carrier_index", 0)
    if type(index) is not int or not 0 <= index < len(names):
        raise ValueError("The task selects a carrier by an index within the world")
    base = {"schema": carriers.VERSION, "carrier_id": names[index], "aspect": task.get("aspect"),
            "min_assessed": task.get("min_assessed", 1),
            **{key: task[key] for key in ("shipping_class", "date_from", "date_to") if key in task}}
    found = verdicts(world, base, api, carriers, note="; what happened to the shipments is kept")
    if base["aspect"] in shipments.MODELLED:
        found += verdicts(world, {**base, "schema": shipments.VERSION}, api, shipments, "redrawn_shipments_",
                          "; the carrier's shipments are redrawn")
    return found


def of(world, task, api):
    """Scenarios of a native task on a world, as requirement candidates.

    An unsupported kind is a ValueError, and so is a task with a field this
    module does not carry into the requirement.
    """
    kind = task.get("kind") if type(task) is dict else None
    if kind in FIELDS and set(task) - FIELDS[kind]:
        raise ValueError("Steering cannot state this field of the task: " + ", ".join(sorted(set(task) - FIELDS[kind])))
    needed = {OTHERS[1]: ("sku_id", "comparison_site_id"), OTHERS[2]: (), OTHERS[4]: ("aspect",)}.get(kind, ("concept_id",))
    if kind in FIELDS and any(type(task.get(key)) is not str or not task[key] for key in needed):
        raise ValueError("The task must name its " + " and ".join(needed))
    if kind == "cheapest_matching_with_permitted_relaxations":
        return relaxations(world, task, api)
    if kind in RESOLVED:
        native = importlib.import_module(api.basic.__package__ + RESOLVED[kind])
        selection = native.resolve({key: value for key, value in task.items() if key != "surrounding"},
                                   inventory=cheapest.inventory(api.basic.__package__, task["concept_id"]),
                                   concept_ids=world["config"]["concept_ids"])[1]
        # The remembered or hidden requirement joins the stated predicates; the answer is that feature task's.
        return winners(world, {**selection, "kind": "cheapest_matching_available",
                               **{key: task[key] for key in ("surrounding",) if key in task}}, api)
    if kind == DELIVERY:
        if task.get("objective", "cheapest_total") != "cheapest_total" or task.get("destination", "user_home") != "user_home":
            raise ValueError("Steering reads this task for the cheapest total delivered for the customer's home address")
        # Home delivery alone is the task's default and is left unstated, as the native task leaves it.
        kinds = {} if sorted(task.get("delivery_types", ["home"])) == ["home"] else {"delivery_types": sorted(task["delivery_types"])}
        return winners(world, {"kind": "cheapest_matching_available", "concept_id": task["concept_id"],
                               "predicates": task.get("predicates")}, api,
                       extra={"delivered": {**{key: task[key] for key in ("delivery_options",) if key in task}, **kinds}})
    if kind in WINNERS:
        return winners(world, task, api)
    if kind not in OTHERS:
        raise ValueError("Steering has no requirement for this kind of task: " + str(kind))
    return {OTHERS[0]: shortlists, OTHERS[1]: comparison_stock, OTHERS[2]: free_shipping,
            OTHERS[3]: review_verdicts, OTHERS[4]: carrier_verdicts}[kind](world, task, api)


def main():
    from experiments.world_requirement_construction import run as pinned
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--native-commit", required=True)
    parser.add_argument("--generation-input", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True, help="a native task specification as JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    api = pinned.load_native(args.native_root.resolve(), args.native_commit)
    api.package_export = importlib.import_module("experiments.accepted_catalog_commerce.package_export")
    api.population = importlib.import_module("experiments.world_sampling_defaults.model")
    natural, _ = streams.Session(api, json.loads(args.generation_input.read_text())).generate()
    found = of(natural, json.loads(args.task.read_text()), api)
    args.output.mkdir(parents=True, exist_ok=True)
    for row in found:
        (args.output / (row["name"] + ".json")).write_text(
            json.dumps(row["requirement"], indent=2, ensure_ascii=False) + "\n")
    summary = {"natural_world_id": natural["world_id"], "summary": natural["summary"],
               "candidates": [{key: row[key] for key in ("name", "summary", "log_probability")} for row in found]}
    (args.output / "candidates.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
