"""Stock steering tests against the real producer, with stand-in products.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_stock.py
Product manufacture is replaced by a stand-in, which leaves a pass through the
real commerce producer at about a second: its stock lines, supplier rule and
catalog pages are the ones under test. The full manufactured world is
exercised by the pinned runner.
"""
from collections import Counter
from copy import deepcopy
from itertools import product as combinations
from random import Random
from types import SimpleNamespace
import unittest
from unittest import mock

from environments.website_world import basic_offer_task
from experiments.accepted_catalog_commerce import model as commerce, package_export
from experiments.footwear_world_pilot import model as native
from experiments.world_sampling_defaults import model as population

from experiments.steered_generation import blocks, stock, streams
from experiments.steered_generation.prices import ZeroMass

CONCEPT = "footwear.walking_shoes"
INPUTS = {"seed": 5, "concept_ids": [CONCEPT], "tasks": [CONCEPT], "controls": None,
          "city_id": "uppsala", "review_count": 0}
# Retailers of that world, by what they exercise.
SMALL = "travel-03"          # one shipping warehouse, two branches that do not ship; supplier orders
PLAIN = "apparel-02"         # three locations, no supplier orders
WIDE = "department_store-04"  # eleven locations
EMPTY = "footwear-06"        # lists nothing


def stand_in(seed, concept_id, brand, product_id, *, earlier, review_count):
    return {"public": {"product_id": product_id, "concept_id": concept_id, "family_id": concept_id.split(".")[0],
                       "name": "Product " + product_id, "reference_price_sek": 400 + seed % 600,
                       "skus": [{"sku_id": f"{product_id}-{size}", "product_id": product_id, "size_eu": size}
                                for size in range(38, 42)]},
            "private": {"profiles": {"positioning": brand["positioning"]}},
            "variant_fields": {"size_eu": {"retail_presentation": {"allowed": ["selector"]}}},
            "descriptions": [], "reviews": []}


def need(retailer_id, sku_id, **stated):
    return {"schema": stock.VERSION, "retailer_id": retailer_id, "sku_id": sku_id, **stated}


class RealProducer(unittest.TestCase):
    inputs = INPUTS
    product = staticmethod(stand_in)

    @classmethod
    def setUpClass(cls):
        patch = mock.patch.object(package_export, "sample", cls.product)
        patch.start()
        cls.addClassCleanup(patch.stop)
        cls.api = SimpleNamespace(basic=basic_offer_task, native=native, population=population,
                                  commerce=commerce, package_export=package_export)
        cls.session = streams.Session(cls.api, cls.inputs)
        cls.natural, cls.opened = cls.session.generate()
        cls.frozen = deepcopy(cls.natural)

    def retailer(self, rid):
        return next(r for r in self.natural["retailers"] if r["retailer_id"] == rid)

    def sku(self, rid, index=0):
        return self.retailer(rid)["offers"][index]["sku_id"]

    def sources(self, rid):
        return [s["source_id"] for s in self.retailer(rid)["source_locations"]]

    def enumerate(self, requirement):
        """Every outcome of the offer's stock draws with its probability, straight from the configuration."""
        retailer = self.retailer(requirement["retailer_id"])
        offer = next(o for o in retailer["offers"] if o["sku_id"] == requirement["sku_id"])
        config = self.natural["config"]
        rows = {row["source_id"]: row["probabilities"] for row in retailer["conditions"]
                if row["product_id"] == offer["product_id"]}
        per_source = []
        for source in retailer["source_locations"]:
            options = []
            for condition, weight in rows[source["source_id"]].items():
                zero = config["stock"]["zero_probability"][condition]
                low, high = config["stock"]["quantity_ranges"][retailer["scale"]][condition]
                options.append((weight * zero, condition, 0))
                options += [(weight * (1 - zero) / (high - low + 1), condition, held) for held in range(low, high + 1)]
            per_source.append(options)
        eligible = config["supplier"]["sku_eligible_probability"] if retailer["supplier_enabled"] else 0
        outcomes = Counter()
        for combo in combinations(*per_source):
            mass = 1
            for part in combo:
                mass *= part[0]
            held = [part[2] for part in combo]
            dispatch = any(q and s["shipping_enabled"] for q, s in zip(held, retailer["source_locations"]))
            for supplier, share in ((True, 0 if dispatch else eligible), (False, 1 if dispatch else 1 - eligible)):
                supply = ("in_stock" if dispatch else "backorder" if supplier else
                          "in_stock" if any(held) else "unavailable")
                bounds = requirement.get("stock", {})
                fits = all(bounds.get(s["source_id"], {}).get("min", 0) <= q <=
                           bounds.get(s["source_id"], {}).get("max", q)
                           for q, s in zip(held, retailer["source_locations"]))
                if mass * share and fits and requirement.get("availability", supply) == supply:
                    outcomes[(tuple(part[1] for part in combo), tuple(held), supplier)] += mass * share
        return outcomes

    def cases(self):
        warehouse, first, second = self.sources(SMALL)
        sku = self.sku(SMALL)
        return [need(SMALL, sku, availability="in_stock"),
                need(SMALL, sku, availability="backorder"),
                need(SMALL, sku, availability="unavailable"),
                need(SMALL, sku, stock={warehouse: {"min": 5}}),
                need(SMALL, sku, stock={warehouse: {"max": 0}, second: {"min": 1, "max": 2}}),
                need(SMALL, sku, availability="in_stock", stock={warehouse: {"max": 0}}),
                need(SMALL, sku, availability="backorder", stock={first: {"min": 2}}),
                need(PLAIN, self.sku(PLAIN, 3), availability="unavailable"),
                need(PLAIN, self.sku(PLAIN, 3), availability="in_stock",
                     stock={self.sources(PLAIN)[0]: {"max": 0}, self.sources(PLAIN)[1]: {"max": 0}})]


class ModelTests(RealProducer):
    def test_world_under_test_is_the_expected_one(self):
        self.assertEqual([s["shipping_enabled"] for s in self.retailer(SMALL)["source_locations"]], [True, False, False])
        self.assertTrue(self.retailer(SMALL)["supplier_enabled"])
        self.assertFalse(self.retailer(PLAIN)["supplier_enabled"])
        self.assertEqual(len(self.sources(WIDE)), 11)
        self.assertEqual(self.retailer(EMPTY)["offers"], [])

    def test_location_outcomes_sum_to_one(self):
        config = self.natural["config"]["stock"]
        for scale, ranges in config["quantity_ranges"].items():
            found = stock.atoms(config["condition_weights"], config["zero_probability"], ranges)
            self.assertAlmostEqual(sum(a[0] for a in found), 1, places=12)
            self.assertEqual(len(found), sum(1 + high - low + 1 for low, high in ranges.values()), scale)

    def test_probability_equals_enumeration(self):
        for requirement in self.cases():
            with self.subTest(requirement=requirement):
                expected = sum(self.enumerate(requirement).values())
                self.assertGreater(expected, 0)
                self.assertAlmostEqual(stock.model(self.natural, requirement, self.api).probability, expected, places=12)

    def test_availabilities_partition_the_outcomes(self):
        for rid in (SMALL, PLAIN, WIDE):
            total = 0
            for wanted in stock.AVAILABILITY:
                try:
                    total += stock.model(self.natural, need(rid, self.sku(rid), availability=wanted), self.api).probability
                except ZeroMass as error:
                    self.assertEqual((rid == SMALL, error.reason), (False, "supplier_disabled"))
            self.assertAlmostEqual(total, 1, places=12)

    def test_repeated_plans_follow_the_conditional_distribution(self):
        # One frozen natural world, many plans: the whole block must follow its
        # distribution given the requirement, not stay near the world's own draws.
        trials = 4000
        for requirement in self.cases()[:7:2]:
            with self.subTest(requirement=requirement):
                outcomes = self.enumerate(requirement)
                total = sum(outcomes.values())
                names = self.sources(requirement["retailer_id"])
                seen = Counter()
                for index in range(trials):
                    draws, _ = stock.plan(self.natural, requirement, self.api, Random(index))
                    seen[(tuple(draws.conditions[n] for n in names),
                          tuple(draws.quantities[n] or 0 for n in names), draws.supplier)] += 1
                self.assertLessEqual(set(seen), set(outcomes))
                # The condition and the quantity at each location, then jointly
                # which locations hold stock and whether a supplier order is offered.
                views = [lambda o, i=i: o[0][i] for i in range(len(names))]
                views += [lambda o, i=i: o[1][i] for i in range(len(names))]
                views += [lambda o: (tuple(map(bool, o[1])), o[2])]
                for view in views:
                    expected, found = Counter(), Counter()
                    for outcome, weight in outcomes.items():
                        expected[view(outcome)] += weight / total
                    for outcome, count in seen.items():
                        found[view(outcome)] += count / trials
                    self.assertLess(sum(abs(expected[k] - found[k]) for k in expected) / 2, 0.05)

    def test_zero_probability_is_a_coded_refusal(self):
        sku, warehouse = self.sku(PLAIN), self.sources(PLAIN)[0]
        for requirement, reason in (
                (need(EMPTY, sku, availability="in_stock"), "not_listed"),
                (need(PLAIN, sku, availability="backorder"), "supplier_disabled"),
                (need(PLAIN, sku, stock={"no-such-branch": {"min": 1}}), "no_such_source"),
                (need(PLAIN, sku, stock={warehouse: {"min": 21}}), "no_outcome"),
                (need(PLAIN, sku, availability="unavailable", stock={warehouse: {"min": 1}}), "no_outcome")):
            with self.assertRaises(ZeroMass) as caught:
                stock.plan(self.natural, requirement, self.api, Random(0))
            self.assertEqual(caught.exception.reason, reason)

    def test_requirement_shape_is_validated(self):
        sku = self.sku(PLAIN)
        for bad in (need(PLAIN, sku), need(PLAIN, sku, availability="sold_out"), need(PLAIN, sku, stock={}),
                    need(PLAIN, sku, stock={"w": {}}), need(PLAIN, sku, stock={"w": {"min": 3, "max": 2}}),
                    need(PLAIN, sku, stock={"w": {"min": -1}}), need(PLAIN, sku, stock={"w": {"min": True}}),
                    need(PLAIN, sku, stock={"w": {"exactly": 1}}), need(PLAIN, sku, availability="in_stock", price=1),
                    {**need(PLAIN, sku, availability="in_stock"), "schema": "other"},
                    need("no-such-shop", sku, availability="in_stock"),
                    need(PLAIN, "no-such-sku", availability="in_stock")):
            with self.assertRaises(ValueError, msg=bad) as caught:
                stock.model(self.natural, bad, self.api)
            self.assertNotIsInstance(caught.exception, ZeroMass)


class ProducerTests(RealProducer):
    def test_steered_worlds_come_from_the_producer_and_satisfy_the_oracle(self):
        cases = self.cases()
        wide = need(WIDE, self.sku(WIDE), availability="unavailable")
        for index, requirement in enumerate([cases[1], cases[2], cases[4], cases[5], cases[8], wide]):
            with self.subTest(requirement=requirement):
                world, found, record = stock.steer(self.session, self.natural, self.opened, requirement,
                                                   self.api, Random(index))
                self.assertEqual(found, {**stock.check(world, requirement, self.api), "offer_id": record["offer_id"]})
                self.assertEqual(found["availability"], requirement.get("availability", found["availability"]))
                for source, bound in requirement.get("stock", {}).items():
                    self.assertTrue(stock.within(bound, found["stock_by_source"][source]))
                self.assertEqual(world["status"], streams.STATUS)
                self.assertNotEqual(world["world_id"], self.natural["world_id"])
                self.assertTrue(commerce.validate({**world, "world_id": world["world_id"]})["valid"])
                self.assertEqual(record["probability_given_upstream"],
                                 stock.model(self.natural, requirement, self.api).probability)
                # The producer, not this module, wrote what depends on stock.
                retailer = next(r for r in world["retailers"] if r["retailer_id"] == requirement["retailer_id"])
                warehouse = retailer["source_locations"][0]["source_id"]
                held = {o["sku_id"]: o["stock_by_source"][warehouse] for o in retailer["offers"]}
                for entry in retailer["catalog"]:
                    for page in entry["pages"]:
                        self.assertEqual([row["stock"] for row in page["listings"]],
                                         [held[row["sku_id"]] for row in page["listings"]])
                        self.assertEqual(page["warehouse_sold_out"], not any(row["stock"] for row in page["listings"]))
                for offer in retailer["offers"]:
                    dispatch = any(q and s["shipping_enabled"] for q, s in
                                   zip(offer["stock_by_source"].values(), retailer["source_locations"]))
                    self.assertFalse(offer["supplier_order"]["enabled"] and dispatch)
        self.assertLess(stock.model(self.natural, wide, self.api).probability, 1e-3)
        self.assertEqual(self.natural, self.frozen)

    def test_a_steered_condition_reaches_the_sibling_skus_through_the_producer(self):
        # Requiring a full warehouse makes it well stocked for the whole product.
        warehouse = self.sources(WIDE)[0]
        requirement = need(WIDE, self.sku(WIDE), stock={warehouse: {"min": 40}})
        changed = 0
        for index in range(3):
            world, found, record = stock.steer(self.session, self.natural, self.opened, requirement,
                                               self.api, Random(index))
            self.assertEqual(found["conditions"][warehouse], "well_stocked")
            changed += record["rebuilt_by_the_producer"]["sibling_offers_with_other_stock"]
        self.assertGreater(changed, 0)

    def test_reading_of_the_stock_lines_equals_the_producer(self):
        hits = 0
        for rid, wanted in ((SMALL, "backorder"), (PLAIN, "unavailable"), (WIDE, "in_stock")):
            requirement = need(rid, self.sku(rid, 1), availability=wanted)
            for seed in range(900, 905):
                found = blocks.redraw(self.session, self.natural,
                                      [stock.trial(self.natural, requirement, self.api)], seed)
                self.assertEqual((found.identical, found.agreed), ([True], [True]))
                hits += found.satisfied
        self.assertTrue(0 < hits < 15)
        self.assertEqual(self.session.generate()[0], self.frozen)

    def test_computed_probability_matches_other_seeds(self):
        trials = 20000
        for requirement in self.cases()[:6]:
            with self.subTest(requirement=requirement):
                block = stock.model(self.natural, requirement, self.api)
                ends = stock.empirical(self.natural, requirement, self.api, trials, 10 ** 6)
                hits, probability = sum(ends.values()), block.probability
                self.assertLess(abs(hits / trials - probability), 4 * (probability * (1 - probability) / trials) ** .5)
                self.assertLess(sum(abs(block.outcomes.get(e, 0) / probability - ends.get(e, 0) / hits)
                                    for e in set(block.outcomes) | set(ends)) / 2, 0.05)


class SeamTests(unittest.TestCase):
    def test_reseeded_streams_are_natural_draws_of_another_seed(self):
        opened = []
        with streams.steered(population, {"a": streams.Reseeded(9), "never-opened": streams.Reseeded(9)}, opened):
            first, other = population.stream(1, "a").random(), population.stream(1, "b").random()
        self.assertEqual(first, population.stream(9, "a").random())
        self.assertNotEqual(first, population.stream(1, "a").random())
        self.assertEqual(other, population.stream(1, "b").random())
        self.assertEqual(opened, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
