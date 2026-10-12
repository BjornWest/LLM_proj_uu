"""Tests of the requirement candidates for native task specifications.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_variants.py
Every candidate of every supported task kind is steered once through the real
producer (stand-in products) and read back with its own check.
"""
from math import exp
from random import Random

from experiments.steered_generation import cheapest, combined, variants
from experiments.steered_generation.test_cheapest import SIZE_40, Cheapest
from experiments.steered_generation.test_combined import BOTH, SHOES
from experiments.steered_generation.test_rankings import FOOD, LIGHT, LIGHTEST, RELAXED, Ranked


class Steered:
    def candidates(self, task, names):
        found = variants.of(self.natural, task, self.api)
        self.assertEqual([row["name"] for row in found], names, task["kind"])
        logs = [row["log_probability"] for row in found]
        self.assertTrue(all(value <= 1e-12 for value in logs))
        for index, row in enumerate(found):
            requirement = row["requirement"]
            module = combined if requirement["schema"] == combined.VERSION else combined.KINDS[requirement["schema"]]
            with self.subTest(kind=task["kind"], name=row["name"]):
                world, _, record = module.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))
                parts = requirement.get("all", [requirement])
                self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in parts))
                self.assertAlmostEqual(record.get("log_probability_given_upstream", row["log_probability"]),
                                       row["log_probability"], places=9)
                if record.get("probability_given_upstream"):
                    self.assertAlmostEqual(record["probability_given_upstream"], exp(row["log_probability"]), places=12)
        return found


class PriceAndStockTasks(Steered, Cheapest):
    def test_tasks_read_on_the_listed_price(self):
        winner = ["likeliest_winner", "better_offer_unavailable", "unlikely_winner"]
        found = self.candidates({"kind": "cheapest_available", "concept_id": SHOES}, winner)
        self.assertGreater(found[0]["log_probability"], found[1]["log_probability"])
        self.assertNotIn("predicates", found[0]["requirement"])
        self.candidates({"kind": "cheapest_available", "concept_id": SHOES, "comparison_site_id": "comparison-00"}, winner)
        found = self.candidates({"kind": "cheapest_matching_available", "concept_id": SHOES, "predicates": SIZE_40,
                                 "availability": cheapest.PHYSICAL}, winner)
        self.assertTrue(found[1]["requirement"]["listed_below"][0]["sku_id"].endswith("-40"))
        found = self.candidates({"kind": "cheapest_matching_local_branch_stock", "concept_id": SHOES, "predicates": SIZE_40,
                                 "city": "Uppsala", "country": "SE"}, winner)
        self.assertEqual(found[0]["requirement"]["availability"], cheapest.BRANCH)

    def test_memory_and_clarification_tasks_resolve_to_a_feature_task(self):
        winner = ["likeliest_winner", "better_offer_unavailable", "unlikely_winner"]
        size = {"field": "sku.size_eu", "operator": "eq", "value": 40}
        hidden = {"kind": "cheapest_matching_after_clarification", "concept_id": SHOES, "availability": cheapest.PHYSICAL,
                  "predicates": [], "hidden_requirement": {
                      "id": "personal-shoe-size", "subject": "self", "predicate": size,
                      "match_rule": "personal_shoe_size_en_v1", "ordering": "before_search", "contrast_values": [41]}}
        found = self.candidates(hidden, winner)
        self.assertEqual(found[0]["requirement"]["predicates"], [size])
        stated = variants.of(self.natural, {"kind": "cheapest_matching_available", "concept_id": SHOES,
                                            "predicates": SIZE_40, "availability": cheapest.PHYSICAL}, self.api)
        self.assertEqual([row["log_probability"] for row in found], [row["log_probability"] for row in stated])
        remembered = {"kind": "cheapest_matching_with_memory", "concept_id": SHOES, "recipient": "self",
                      "availability": cheapest.PHYSICAL, "predicates": [], "memory_records": [
                          {"id": "shoe-size", "subject": "self", "scope": {"concept_ids": [SHOES]}, "channel": "episodic",
                           "predicates": [size]}]}
        found = variants.of(self.natural, remembered, self.api)
        self.assertEqual([row["log_probability"] for row in found], [row["log_probability"] for row in stated])

    def test_shortlist_comparison_stock_and_free_shipping_tasks(self):
        found = self.candidates({"kind": "shortlist_matching_models", "concept_id": SHOES, "predicates": SIZE_40,
                                 "availability": cheapest.PHYSICAL, "limit": 3},
                                ["natural_shortlist", "tie_at_cutoff", "another_shortlist"])
        self.assertEqual([len(row["requirement"]["product_ids"]) for row in found], [3, 4, 3])
        pairs = cheapest.scope(self.natural, {"concept_id": SHOES, "comparison_site_id": "comparison-00"}, self.api).pairs
        rid, product = next(pair for pair in sorted(pairs) if self.retailer(pair[0])["supplier_enabled"] and
                            sum(other[1] == pair[1] for other in pairs) > 2)
        found = self.candidates({"kind": "comparison_cheapest_exact_sku_stock", "comparison_site_id": "comparison-00",
                                 "sku_id": self.size(rid, 0, product)},
                                ["advertised_cheapest_in_stock", "advertised_cheapest_on_supplier_order",
                                 "advertised_cheapest_unavailable"])
        self.assertTrue(all(len(row["requirement"]["all"]) == 2 for row in found))
        retailers = sorted(r["retailer_id"] for r in self.natural["retailers"])
        found = self.candidates({"kind": "audit_free_shipping_claim", "retailer_index": retailers.index(BOTH),
                                 "offer_index": 0, "quantity": 2},
                                ["no_threshold", "meets_threshold", "below_threshold", "just_below_threshold",
                                 "just_meets_threshold"])
        self.assertAlmostEqual(sum(exp(row["log_probability"]) for row in found[:3]), 1, places=8)
        with self.assertRaises(ValueError):
            variants.of(self.natural, {"kind": "summarize_carrier_reviews"}, self.api)

    def test_a_task_field_that_is_not_carried_is_refused_not_dropped(self):
        size = {"field": "sku.size_eu", "operator": "eq", "value": 40}
        tasks = [{"kind": "cheapest_available", "concept_id": SHOES},
                 {"kind": "cheapest_matching_available", "concept_id": SHOES, "predicates": SIZE_40},
                 {"kind": "cheapest_matching_local_branch_stock", "concept_id": SHOES, "predicates": SIZE_40, "city": "Uppsala"},
                 {"kind": "shortlist_matching_models", "concept_id": SHOES, "predicates": SIZE_40, "limit": 3},
                 {"kind": "cheapest_matching_after_clarification", "concept_id": SHOES, "predicates": [],
                  "hidden_requirement": {"id": "personal-shoe-size", "subject": "self", "predicate": size,
                                         "match_rule": "personal_shoe_size_en_v1", "ordering": "before_search",
                                         "contrast_values": [41]}},
                 {"kind": "audit_free_shipping_claim", "quantity": 1}]
        for task in tasks:
            self.assertTrue(variants.of(self.natural, task, self.api), task["kind"])
            # A price cap changes the native answer (a cap of zero leaves no candidate at all).
            for extra in ({"max_price_minor": 0}, {"max_price_minor": 10 ** 9}, {"no_such_field": 1}):
                with self.subTest(kind=task["kind"], extra=extra), self.assertRaises(ValueError) as caught:
                    variants.of(self.natural, {**task, **extra}, self.api)
                self.assertIn(next(iter(extra)), str(caught.exception))

    def test_tasks_with_nothing_to_steer_give_no_candidates_or_a_clear_error(self):
        none = [{"field": "sku.size_eu", "operator": "eq", "value": 99}]
        for task in ({"kind": "cheapest_matching_available", "concept_id": SHOES, "predicates": none},
                     {"kind": "cheapest_matching_local_branch_stock", "concept_id": SHOES, "predicates": SIZE_40, "city": "Kiruna"},
                     {"kind": "cheapest_matching_with_permitted_relaxations", "concept_id": SHOES, "predicates": none,
                      "relaxations": [{"label": "Other size", "drop_fields": [], "replacements": [
                          {"field": "sku.size_eu", "operator": "in", "value": [99, 98]}]}]}):
            with self.subTest(kind=task["kind"]):
                self.assertEqual(variants.of(self.natural, task, self.api), [])
        retailers = len(self.natural["retailers"])
        for task in ({"kind": "cheapest_available"}, {"kind": "cheapest_available", "concept_id": 3},
                     {"kind": "shortlist_matching_models", "predicates": SIZE_40, "limit": 3},
                     {"kind": "comparison_cheapest_exact_sku_stock", "sku_id": "nothing", "comparison_site_id": "comparison-00"},
                     {"kind": "comparison_cheapest_exact_sku_stock", "sku_id": self.size(self.first, 0)},
                     {"kind": "audit_free_shipping_claim", "retailer_index": retailers},
                     {"kind": "audit_free_shipping_claim", "offer_index": 10 ** 4},
                     {"kind": "audit_free_shipping_claim", "retailer_index": -1},
                     {"kind": "audit_free_shipping_claim", "quantity": 0}, None, []):
            with self.subTest(task=task), self.assertRaises(ValueError):
                variants.of(self.natural, task, self.api)

    def test_shortlist_tasks_at_the_edges(self):
        base = {"kind": "shortlist_matching_models", "concept_id": SHOES, "availability": cheapest.PHYSICAL}
        # No shoe comes in this size: nothing to name, and no error.
        self.assertEqual(variants.of(self.natural, {**base, "limit": 3, "predicates": [
            {"field": "sku.size_eu", "operator": "eq", "value": 99}]}, self.api), [])
        for limit in ({}, {"limit": None}, {"limit": "3"}):
            with self.subTest(limit=limit), self.assertRaises(ValueError) as caught:
                variants.of(self.natural, {**base, "predicates": SIZE_40, **limit}, self.api)
            self.assertIn("limit", str(caught.exception))
        # A limit above the number of models: the natural list is every model, and no larger list exists.
        found = variants.of(self.natural, {**base, "limit": 10, "predicates": SIZE_40}, self.api)
        self.assertEqual([row["name"] for row in found], ["natural_shortlist"])


class RankedTasks(Steered, Ranked):
    def test_tasks_with_another_ranking(self):
        winner = ["likeliest_winner", "better_offer_unavailable", "unlikely_winner"]
        self.candidates({"kind": "recommend_matching_by_priorities", "concept_id": SHOES, "predicates": SIZE_40,
                         "availability": cheapest.PHYSICAL, "priorities": LIGHTEST}, winner)
        found = self.candidates({"kind": "cheapest_matching_with_permitted_relaxations", "concept_id": SHOES,
                                 "predicates": SIZE_40 + [LIGHT], "availability": cheapest.PHYSICAL,
                                 "relaxations": RELAXED}, ["criteria_set_0", "criteria_set_1"])
        self.assertEqual([row["requirement"]["selected"] for row in found], ["Original requirements", RELAXED[0]["label"]])
        found = variants.of(self.natural, {"kind": "cheapest_matching_unit_price", "concept_id": FOOD, "predicates": [],
                                           "availability": cheapest.PHYSICAL, "unit_basis": "net_food_mass_kg"}, self.api)
        self.assertEqual(found[0]["name"], "likeliest_winner")
        self.assertNotIn("predicates", found[0]["requirement"])
