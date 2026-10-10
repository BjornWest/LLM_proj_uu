"""Operator tests on a tiny synthetic world, judged by the real native oracle."""
from copy import deepcopy
from pathlib import Path
from random import Random
import sys
from types import SimpleNamespace
import unittest

if __package__:
    from . import model
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import model

from environments.website_world import basic_offer_task
from experiments.accepted_catalog_commerce import model as commerce
from experiments.footwear_world_pilot import model as native

API = SimpleNamespace(basic=basic_offer_task, commerce=commerce, native=native)
CONCEPT = "footwear.walking_shoes"
PRICE = {"reference_match_probability": 0.4, "offset_standard_deviation": 0.1,
         "offset_min": -0.3, "offset_max": 0.3,
         "rounding_bands_sek": [[100, 1], [500, 5], [2000, 10], [10000, 50], [None, 100]]}
MATCH = (True, 0)


def make_world(assortment, *, products=None, empty=()):
    """assortment: {retailer_id: {product_id: (matched, offset)}}; prices follow the rule."""
    products = products or {"shoe": (510, {})}
    public = {pid: {"product_id": pid, "concept_id": CONCEPT, "name": pid, "reference_price_sek": reference,
                    "skus": [{"sku_id": f"{pid}-{size}", "product_id": pid,
                              **({"reference_price_sek": exact[size]} if size in exact else {})}
                             for size in (39, 40, 41)]}
              for pid, (reference, exact) in products.items()}
    retailers = []
    for rid, carried in assortment.items():
        offers = []
        for pid, draw in carried.items():
            for sku in public[pid]["skus"]:
                reference = int(sku.get("reference_price_sek", public[pid]["reference_price_sek"]) * 100)
                offers.append({
                    "offer_id": rid + "/" + sku["sku_id"], "product_id": pid, "sku_id": sku["sku_id"],
                    "price_minor": native.rounded_price(reference * (1 + draw[1]), reference, PRICE),
                    "currency": "SEK", "stock_by_source": {rid + "-warehouse": 0 if (rid, pid) in empty else 3},
                    "supplier_order": {"enabled": False, "wait_days": None, "disclosure": None},
                    "price_trace": {"reference_minor": reference,
                                    "reference_basis": "exact_sku" if "reference_price_sek" in sku else "product",
                                    "matched_reference_draw": draw[0], "offset_draw": draw[1]}})
        retailers.append({"retailer_id": rid, "name": rid.title(), "product_ids": list(carried),
                          "source_locations": [{"source_id": rid + "-warehouse", "shipping_enabled": True}],
                          "offers": offers,
                          "catalog": [{"product_id": pid, "pages": [{"listings": [
                              {"sku_id": o["sku_id"]} for o in offers if o["product_id"] == pid]}]}
                              for pid in carried]})
    world = {"schema_version": commerce.VERSION, "seed": 1, "status": model.SAMPLED_STATUS,
             "config": {"concept_ids": [CONCEPT], "retailer_price": deepcopy(PRICE)},
             "products": [{"public": p} for p in public.values()], "retailers": retailers,
             "provenance": {}, "limitations": ["Sparse stock is retained; no winner or seed repair."]}
    return seal(world)


def seal(world):
    """Recompute the identity after a test adjusts the synthetic world."""
    world.pop("world_id", None)
    world["world_id"] = native.digest(world)
    return world


def requirement(*retailer_ids, product_id="shoe"):
    return {"schema": model.VERSION, "kind": model.KIND, "concept_id": CONCEPT,
            "product_id": product_id, "retailer_ids": list(retailer_ids)}


def prices(world, rid, pid="shoe"):
    return [o["price_minor"] for r in world["retailers"] if r["retailer_id"] == rid
            for o in r["offers"] if o["product_id"] == pid]


def build(world, need):
    return model.construct(world, need, API, parent_bytes_sha256="test")


class ConstructTests(unittest.TestCase):
    def setUp(self):
        # 480, 500 and 510 SEK for the same shoe at three retailers.
        self.parent = make_world({"north": {"shoe": (False, -0.0535)},
                                  "south": {"shoe": (False, -0.024)},
                                  "west": {"shoe": MATCH}})

    def reason(self, call):
        with self.assertRaises(model.CannotConstruct) as caught:
            call()
        return caught.exception.reason

    def test_tie_reprices_one_retailer_and_every_sku_of_the_product(self):
        before = deepcopy(self.parent)
        world, task, reference, provenance = build(self.parent, requirement("north", "south"))
        self.assertEqual(self.parent, before)
        self.assertEqual(prices(world, "north"), [48000] * 3)
        self.assertEqual(prices(world, "south"), [48000] * 3)
        self.assertEqual(prices(world, "west"), [51000] * 3)
        self.assertEqual([c["retailer_id"] for c in provenance["changes"]], ["south"])
        self.assertEqual(provenance["changes"][0]["before"],
                         {"matched_reference_draw": False, "offset_draw": -0.024})
        self.assertEqual(len(reference["winners"]), 6)
        self.assertEqual(model.price_rule_violations(world, native.rounded_price), [])
        self.assertEqual(world["status"], model.AUTHORED_STATUS)
        self.assertNotEqual(world["world_id"], self.parent["world_id"])
        self.assertEqual(task["world_id"], world["world_id"])

    def test_one_designated_retailer_becomes_sole_cheapest(self):
        world, _, reference, provenance = build(self.parent, requirement("west"))
        self.assertEqual(prices(world, "west"), [47000] * 3)
        self.assertEqual({row["retailer_id"] for row in reference["winners"]}, {"west"})
        self.assertEqual(provenance["changes"][0]["after"]["matched_reference_draw"], False)

    def test_matched_reference_draw_is_used_for_the_reference_price(self):
        parent = make_world({"north": {"shoe": (False, 0.05)}, "south": {"shoe": MATCH},
                             "west": {"shoe": (False, 0.1)}})
        world, _, _, provenance = build(parent, requirement("north", "south"))
        self.assertEqual(prices(world, "north"), [51000] * 3)
        self.assertEqual(provenance["changes"][0]["after"],
                         {"matched_reference_draw": True, "offset_draw": 0})

    def test_single_variant_price_edit_breaks_the_price_rule(self):
        self.parent["retailers"][1]["offers"][0]["price_minor"] = 47000
        self.assertEqual(self.reason(lambda: build(self.parent, requirement("north", "south"))), "price_rule")
        world, *_ = build(make_world({"north": {"shoe": (False, -0.0535)}, "south": {"shoe": MATCH}}),
                          requirement("north", "south"))
        world["retailers"][0]["offers"][0]["price_minor"] -= 1000
        self.assertEqual(self.reason(lambda: model.check(world, requirement("north", "south"), API)), "price_rule")

    def test_sku_with_its_own_reference_shares_the_retailer_draw(self):
        # West also sells at 500 SEK, so the tie has to form below it.
        parent = make_world({"north": {"shoe": (False, -0.0535)}, "south": {"shoe": (False, -0.024)},
                             "west": {"shoe": (False, -0.024)}},
                            products={"shoe": (510, {41: 560})})
        world, _, reference, _ = build(parent, requirement("north", "south"))
        self.assertEqual(prices(world, "south")[:2], [48000] * 2)
        self.assertGreater(prices(world, "south")[2], 48000)
        self.assertEqual(model.price_rule_violations(world, native.rounded_price), [])
        self.assertEqual(len(reference["winners"]), 4)

    def test_mixed_references_reach_a_joint_minimum_with_one_reprice(self):
        # 499 SEK rounds in 5 SEK steps and 500 SEK in 10 SEK steps: 504/500/500
        # needs an offset between the two SKUs' own bin centres.
        for offset_min in (-0.3, 0):
            parent = make_world({"north": {"shoe": MATCH}, "south": {"shoe": MATCH}},
                                products={"shoe": (499, {40: 500, 41: 500})})
            parent["retailers"][1]["offers"][0]["stock_by_source"]["south-warehouse"] = 0
            parent["config"]["retailer_price"]["offset_min"] = offset_min
            with self.subTest(offset_min=offset_min):
                world, _, reference, provenance = build(seal(parent), requirement("north", "south"))
                self.assertEqual([c["retailer_id"] for c in provenance["changes"]], ["north"])
                self.assertEqual(prices(world, "north"), [50400, 50000, 50000])
                self.assertEqual(reference["minimum_price_minor"], 50000)

    def test_movement_counts_every_repriced_sku(self):
        # 400/500/600 SEK; only north lists three sizes. Meeting at 500 moves
        # four prices by 100 SEK, meeting at 400 moves two by 300 SEK in total.
        parent = make_world({"north": {"shoe": (False, -110 / 510)}, "south": {"shoe": (False, -10 / 510)},
                             "west": {"shoe": (False, 90 / 510)}})
        for retailer in parent["retailers"][1:]:
            retailer["offers"] = retailer["offers"][:1]
            retailer["catalog"][0]["pages"][0]["listings"] = retailer["catalog"][0]["pages"][0]["listings"][:1]
        world, _, reference, provenance = build(seal(parent), requirement("north", "south", "west"))
        self.assertEqual(reference["minimum_price_minor"], 40000)
        self.assertEqual([c["retailer_id"] for c in provenance["changes"]], ["south", "west"])

    def test_declines_when_a_competitor_is_below_every_producer_price(self):
        parent = make_world({"north": {"shoe": (False, -0.0535)}, "south": {"shoe": MATCH},
                             "west": {"budget": MATCH}},
                            products={"shoe": (510, {}), "budget": (200, {})})
        self.assertEqual(self.reason(lambda: build(parent, requirement("north", "south"))), "no_common_price")

    def test_declines_without_stock_or_retailer(self):
        parent = make_world({"north": {"shoe": (False, -0.0535)}, "south": {"shoe": MATCH}},
                            empty={("south", "shoe")})
        self.assertEqual(self.reason(lambda: build(parent, requirement("north", "south"))), "unavailable")
        self.assertEqual(self.reason(lambda: build(self.parent, requirement("north", "absent"))), "unavailable")

    def test_declines_satisfied_and_authored_parents(self):
        self.assertEqual(self.reason(lambda: build(self.parent, requirement("north"))), "already_holds")
        world, *_ = build(self.parent, requirement("north", "south"))
        self.assertEqual(self.reason(lambda: build(world, requirement("north", "south"))), "not_sampled")

    def test_check_requires_exactly_the_designated_retailers(self):
        world, *_ = build(self.parent, requirement("north", "south"))
        for ids in (("north",), ("north", "south", "west")):
            self.assertEqual(self.reason(lambda: model.check(world, requirement(*ids), API)), "winners")

    def test_background_change_is_detected(self):
        world, *_ = build(self.parent, requirement("north", "south"))
        changed = {o["offer_id"] for o in world["retailers"][1]["offers"]}
        self.assertTrue(model._only_declared_changes(self.parent, world, changed))
        world["retailers"][2]["offers"][0]["stock_by_source"]["west-warehouse"] = 0
        self.assertFalse(model._only_declared_changes(self.parent, world, changed))
        world, *_ = build(self.parent, requirement("north", "south"))
        self.assertFalse(model._only_declared_changes(self.parent, world, set()))
        retyped = deepcopy(self.parent)
        retyped["retailers"][0]["source_locations"][0]["shipping_enabled"] = 1
        self.assertFalse(model._only_declared_changes(self.parent, retyped, set()))


class PriceRuleTests(unittest.TestCase):
    def violations(self, draw, *, reference=510, **config):
        world = make_world({"north": {"shoe": draw}}, products={"shoe": (reference, {})})
        world["config"]["retailer_price"].update(config)
        return model.price_rule_violations(world, native.rounded_price)

    def test_draws_the_producer_cannot_record_are_violations(self):
        self.assertEqual(self.violations(MATCH), [])
        self.assertEqual(self.violations((False, -0.1)), [])
        self.assertEqual(len(self.violations(MATCH, reference_match_probability=0)), 3)
        self.assertEqual(len(self.violations((False, -0.1), reference_match_probability=1)), 3)
        self.assertEqual(len(self.violations((False, -0.1), offset_standard_deviation=0)), 3)
        self.assertEqual(self.violations((False, 0.0), offset_standard_deviation=0), [])
        self.assertEqual(len(self.violations((False, 0.31))), 3)
        self.assertEqual(len(self.violations((True, 0.05))), 3)

    def test_recorded_draw_types_follow_the_producer(self):
        # Matched is the integer 0; unmatched is a float unless clamped to an
        # integer-typed bound.
        self.assertEqual(len(self.violations((True, 0.0))), 3)
        self.assertEqual(len(self.violations((False, 0))), 3)
        self.assertEqual(self.violations((False, 0.0)), [])
        self.assertEqual(self.violations((False, 0), offset_min=0), [])
        self.assertEqual(len(self.violations((False, 0), offset_standard_deviation=0)), 3)

    def test_recorded_type_at_a_clamp_bound_is_the_bound_object(self):
        # max(lo, min(hi, g)) returns lo itself when the value equals lo, else
        # hi itself when it equals hi.
        self.assertEqual(len(self.violations((False, 0.0), offset_min=0)), 3)
        self.assertEqual(self.violations((False, 1), offset_max=1), [])
        self.assertEqual(len(self.violations((False, 1.0), offset_max=1)), 3)
        self.assertEqual(self.violations((False, 0.0), offset_min=0.0, offset_max=0), [])
        self.assertEqual(len(self.violations((False, 0), offset_min=0.0, offset_max=0)), 3)
        self.assertEqual(self.violations((False, 0), offset_min=0, offset_max=0), [])
        self.assertEqual(len(self.violations((False, 0.0), offset_min=0, offset_max=0)), 3)
        self.assertEqual(self.violations((False, 0.3)), [])
        self.assertEqual(self.violations((False, -0.3)), [])

    def test_recorded_zero_keeps_the_sign_the_producer_writes(self):
        self.assertEqual(len(self.violations((False, -0.0), offset_min=0.0)), 3)
        self.assertEqual(self.violations((False, 0.0), offset_min=0.0), [])
        self.assertEqual(len(self.violations((False, -0.0), offset_standard_deviation=0)), 3)
        self.assertEqual(len(self.violations((False, 0.0), offset_min=-0.0, offset_max=0.0)), 3)
        self.assertEqual(self.violations((False, -0.0), offset_min=-0.0, offset_max=0.0), [])
        self.assertEqual(len(self.violations((False, -0.0))), 3)

    def test_matched_draw_is_valid_outside_the_unmatched_clamp(self):
        self.assertEqual(self.violations(MATCH, offset_min=0.1), [])
        self.assertEqual(len(self.violations((False, 0.0), offset_min=0.1)), 3)

    def test_nonpositive_manufacturer_reference_is_a_violation(self):
        self.assertEqual(len(self.violations(MATCH, reference=0)), 3)


class DrawTests(unittest.TestCase):
    def reachable(self, reference, config):
        return {native.rounded_price(reference * (1 + draw[1]), reference, config)
                for draw in model.candidate_draws([reference], config)}

    def test_candidates_reach_every_price_the_producer_draws(self):
        rng = Random(7)
        for reference in (9900, 19000, 51000, 129900, 550000, 1250000):
            reachable = self.reachable(reference, PRICE)
            for _ in range(3000):
                # The producer's own expression in `_offer_price`.
                match = rng.random() < PRICE["reference_match_probability"]
                offset = 0 if match else max(PRICE["offset_min"], min(PRICE["offset_max"], rng.gauss(0, PRICE["offset_standard_deviation"])))
                self.assertIn(native.rounded_price(reference * (1 + offset), reference, PRICE), reachable)

    def test_candidates_reach_every_joint_price_of_differently_rounded_skus(self):
        rng = Random(11)
        for references in ((49900, 50000), (9900, 19000, 51000), (129900, 199000, 201000)):
            joint = {tuple(native.rounded_price(r * (1 + draw[1]), r, PRICE) for r in references)
                     for draw in model.candidate_draws(references, PRICE)}
            if references == (49900, 50000):
                self.assertIn((50400, 50000), joint)
            for _ in range(3000):
                match = rng.random() < PRICE["reference_match_probability"]
                offset = 0 if match else max(PRICE["offset_min"], min(PRICE["offset_max"], rng.gauss(0, PRICE["offset_standard_deviation"])))
                self.assertIn(tuple(native.rounded_price(r * (1 + offset), r, PRICE) for r in references), joint)

    def test_rounding_knife_edges_are_not_candidates(self):
        # At offset 1/102 both SKUs sit on a flip and ties-to-even gives
        # 510/1550 SEK, which neither neighbouring interval produces. The float
        # plateau around it is about 1e-16 wide; the operator does not use it.
        references = (51000, 153000)
        edge = tuple(native.rounded_price(r * (1 + 1 / 102), r, PRICE) for r in references)
        self.assertEqual(edge, (51000, 155000))
        self.assertTrue(model.knife_edge(references, 1 / 102, PRICE))
        self.assertFalse(model.knife_edge(references, 1 / 102 + 1e-6, PRICE))
        joint = {tuple(native.rounded_price(r * (1 + draw[1]), r, PRICE) for r in references)
                 for draw in model.candidate_draws(references, PRICE)}
        self.assertNotIn(edge, joint)
        self.assertTrue({(51000, 154000), (52000, 155000)} <= joint)

    def test_midpoint_inside_a_tie_plateau_is_skipped_but_endpoints_stay(self):
        # A clamp this narrow puts the only interior midpoint on the plateau.
        narrow = {**PRICE, "reference_match_probability": 0,
                  "offset_min": 0.00980392156862719, "offset_max": 0.009803921568627711}
        draws = model.candidate_draws((51000, 153000), narrow)
        self.assertEqual(draws, [(False, narrow["offset_min"]), (False, narrow["offset_max"])])
        for config in (PRICE, {**PRICE, "offset_min": 0.05}):
            for draw in model.candidate_draws((49900, 50000, 51000, 153000), config):
                if draw[0] or draw[1] in (config["offset_min"], config["offset_max"]):
                    continue
                self.assertFalse(model.knife_edge((49900, 50000, 51000, 153000), draw[1], config))

    def test_coincident_clamp_bounds_give_one_endpoint_candidate(self):
        pinned = {**PRICE, "reference_match_probability": 0, "offset_min": 0.0, "offset_max": 0}
        self.assertEqual(model.candidate_draws((51000,), pinned), [(False, 0.0)])
        self.assertTrue(model._producible((False, 0.0), pinned))

    def test_search_limit_is_a_coded_decline(self):
        with self.assertRaises(model.CannotConstruct) as caught:
            model.candidate_draws([200000000], PRICE)
        self.assertEqual(caught.exception.reason, "operator_limit")

    def test_candidates_stay_inside_the_producer_range(self):
        for config in (PRICE, {**PRICE, "offset_min": 0.1}, {**PRICE, "reference_match_probability": 0}):
            for draw in model.candidate_draws([19000, 51000], config):
                self.assertTrue(model._producible(draw, config))
        self.assertEqual(model.candidate_draws([51000], PRICE).count((True, 0)), 1)
        self.assertNotIn((False, 0.0), model.candidate_draws([51000], PRICE))

    def test_degenerate_configs_do_not_invent_prices(self):
        self.assertEqual(self.reachable(99000, {**PRICE, "reference_match_probability": 1}), {99000})
        self.assertEqual(self.reachable(99000, {**PRICE, "offset_standard_deviation": 0}), {99000})
        shifted = {**PRICE, "offset_standard_deviation": 0, "offset_min": 0.1,
                   "reference_match_probability": 0}
        self.assertEqual(self.reachable(100000, shifted), {110000})
        never_matched = model.candidate_draws([51000], {**PRICE, "reference_match_probability": 0})
        self.assertIn((False, 0.0), never_matched)
        self.assertNotIn((True, 0), never_matched)


class RequirementTests(unittest.TestCase):
    def test_resolve_copies_and_rejects_malformed_requirements(self):
        need = requirement("north", "south")
        model.resolve(need)["retailer_ids"].append("west")
        self.assertEqual(need["retailer_ids"], ["north", "south"])
        for ids in (["a", "a"], [], ["a", 2], [True, "b"], "ab"):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                model.resolve({**need, "retailer_ids": ids})
        for extra in ({"allow_price_overflow": True}, {"kind": "other"}, {"product_id": ""}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                model.resolve({**need, **extra})


if __name__ == "__main__":
    unittest.main()
