"""Tests of one-offer price bounds and of several requirements in one world.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_combined.py
The real commerce producer with stand-in products, as in test_stock.py, here
on a world with two concepts so that a who-is-cheapest requirement has
offers outside its own concept to be combined with.
"""
from collections import Counter
from copy import deepcopy
from math import prod
from random import Random
from types import SimpleNamespace
import unittest

from experiments.accepted_catalog_commerce import model as commerce
from experiments.world_requirement_construction import model as edits

from experiments.steered_generation import blocks, combined, price_bounds, prices, stock, streams
from experiments.steered_generation.test_stock import INPUTS, RealProducer

SHOES, SHIRTS = "footwear.walking_shoes", "tops.t_shirts"
SMALL = "travel-03"    # shoes only; three locations, supplier orders
BOTH = "apparel-01"    # shirts and shoes; supplier orders
PLAIN = "apparel-02"   # shirts and shoes; no supplier orders
EMPTY = "footwear-06"  # lists nothing


class TwoConcepts(RealProducer):
    inputs = {**INPUTS, "concept_ids": [SHOES, SHIRTS]}

    def offer(self, rid, concept, index=0):
        concepts = {p["public"]["product_id"]: p["public"]["concept_id"] for p in self.natural["products"]}
        return [o for o in self.retailer(rid)["offers"] if concepts[o["product_id"]] == concept][index]

    def held(self, rid, concept, **stated):
        return {"schema": stock.VERSION, "retailer_id": rid, "sku_id": self.offer(rid, concept)["sku_id"], **stated}

    def priced(self, rid, concept, **limits):
        return {"schema": price_bounds.VERSION, "retailer_id": rid, "sku_id": self.offer(rid, concept)["sku_id"],
                "price_minor": limits}

    def cheapest(self):
        """The natural world's own winners of the shoe concept: a requirement of moderate probability."""
        _, reference = edits._reference(self.natural, {"concept_id": SHOES}, self.api)
        product = reference["winners"][0]["product_id"]
        return {"schema": edits.VERSION, "kind": edits.KIND, "concept_id": SHOES, "product_id": product,
                "retailer_ids": sorted({w["retailer_id"] for w in reference["winners"] if w["product_id"] == product})}

    def together(self, *parts):
        return {"schema": combined.VERSION, "all": list(parts)}

    def alone(self, part):
        """A part's probability from its own module's model."""
        if part["schema"] == edits.VERSION:
            return prices.model(self.natural, part, self.api).probability
        return combined.KINDS[part["schema"]].model(self.natural, part, self.api).probability


class PriceBoundTests(TwoConcepts):
    def bounds(self):
        reference = self.offer(BOTH, SHIRTS)["price_trace"]["reference_minor"]
        return [self.priced(BOTH, SHIRTS, max=reference - 1), self.priced(BOTH, SHIRTS, min=reference, max=reference),
                self.priced(BOTH, SHIRTS, min=int(reference * 1.1)),
                self.priced(SMALL, SHOES, min=int(reference * .9), max=int(reference * 1.2))]

    def test_every_price_is_within_some_bound(self):
        whole = price_bounds.model(self.natural, self.priced(BOTH, SHIRTS, min=0), self.api)
        self.assertAlmostEqual(whole.probability, 1, places=6)
        low, high = min(whole.by_price), max(whole.by_price)
        split = [self.priced(BOTH, SHIRTS, max=(low + high) // 2), self.priced(BOTH, SHIRTS, min=(low + high) // 2 + 1)]
        self.assertAlmostEqual(sum(self.alone(part) for part in split), whole.probability, places=12)

    def test_probability_and_prices_match_the_real_pricing_function(self):
        trials = 20000
        for requirement in self.bounds():
            with self.subTest(requirement=requirement):
                block = price_bounds.model(self.natural, requirement, self.api)
                seen = price_bounds.empirical(self.natural, requirement, self.api, trials, 10 ** 6)
                hits, probability = sum(seen.values()), block.probability
                self.assertGreater(hits, 500)
                self.assertLess(abs(hits / trials - probability), 4 * (probability * (1 - probability) / trials) ** .5)
                # 3,000 plans against the real function's prices when the bounds hold.
                planned = Counter()
                for index in range(3000):
                    draw, _ = price_bounds.plan(self.natural, requirement, self.api, Random(index))
                    planned[edits._price(block.site.reference, draw, block.site.config, block.site.native_round)] += 1
                self.assertLessEqual(set(planned), set(block.by_price))
                self.assertLess(sum(abs(planned[p] / 3000 - seen[p] / hits) for p in set(planned) | set(seen)) / 2, 0.08)

    def test_steered_price_comes_from_the_producer(self):
        for index, requirement in enumerate(self.bounds()):
            with self.subTest(requirement=requirement):
                world, found, record = price_bounds.steer(self.session, self.natural, self.opened, requirement,
                                                          self.api, Random(index))
                self.assertTrue(blocks.within(requirement["price_minor"], found["price_minor"]))
                self.assertEqual(found, price_bounds.check(world, requirement, self.api))
                self.assertEqual(world["status"], streams.STATUS)
                self.assertTrue(commerce.validate({**world, "world_id": world["world_id"]})["valid"])
                self.assertEqual(edits.price_rule_violations(world, self.api.native.rounded_price), [])
                self.assertEqual(record["probability_given_upstream"], self.alone(requirement))
                self.assertEqual(record["streams_steered"], 1)
                # The producer repriced the product's other SKUs here from the same draw.
                retailer = next(r for r in world["retailers"] if r["retailer_id"] == requirement["retailer_id"])
                product = next(o["product_id"] for o in retailer["offers"] if o["offer_id"] == found["offer_id"])
                group = [o for o in retailer["offers"] if o["product_id"] == product]
                self.assertGreater(len(group), 1)
                self.assertEqual(len({edits._draw(o) for o in group}), 1)
                self.assertEqual(len(record["repriced"][0]["offers"]), len(group))
        self.assertEqual(self.natural, self.frozen)

    def test_zero_probability_and_bad_requirements(self):
        sku = self.offer(BOTH, SHIRTS)["sku_id"]
        need = lambda rid, **limits: {"schema": price_bounds.VERSION, "retailer_id": rid, "sku_id": sku,
                                      "price_minor": limits}
        for requirement, reason in ((need(EMPTY, max=10 ** 9), "not_listed"), (need(BOTH, max=1), "no_price"),
                                    (need(BOTH, min=10 ** 9), "no_price")):
            with self.assertRaises(prices.ZeroMass) as caught:
                price_bounds.plan(self.natural, requirement, self.api, Random(0))
            self.assertEqual(caught.exception.reason, reason)
        good = need(BOTH, max=10 ** 9)
        for bad in ({**good, "price_minor": {}}, {**good, "price_minor": {"min": 5, "max": 4}},
                    {**good, "price_minor": {"max": 5.0}}, {**good, "price_minor": {"max": -1}},
                    {**good, "price_minor": {"under": 5}}, {**good, "availability": "in_stock"},
                    {k: v for k, v in good.items() if k != "price_minor"}, {**good, "schema": stock.VERSION},
                    {**good, "retailer_id": "no-such-shop"}, {**good, "sku_id": "no-such-sku"}):
            with self.assertRaises(ValueError, msg=bad) as caught:
                price_bounds.model(self.natural, bad, self.api)
            self.assertNotIsInstance(caught.exception, prices.ZeroMass)


class CombinedTests(TwoConcepts):
    def combinations(self):
        warehouse = self.sources(SMALL)[0]
        reference = self.offer(BOTH, SHIRTS)["price_trace"]["reference_minor"]
        return [
            # One offer: its stock and its price.
            self.together(self.held(SMALL, SHOES, stock={warehouse: {"min": 3}}),
                          self.priced(SMALL, SHOES, max=self.offer(SMALL, SHOES)["price_trace"]["reference_minor"])),
            # Three offers at three retailers.
            self.together(self.held(SMALL, SHOES, availability="backorder"),
                          self.held(PLAIN, SHOES, availability="unavailable"),
                          self.priced(BOTH, SHIRTS, max=reference - 1)),
            # Who is cheapest for shoes, with requirements on shirts.
            self.together(self.cheapest(), self.held(BOTH, SHIRTS, availability="backorder"),
                          self.priced(PLAIN, SHIRTS, min=reference))]

    def test_probability_is_the_product_of_the_parts(self):
        for requirement in self.combinations():
            steps = combined.prepare(self.natural, requirement, self.api, Random(0))
            self.assertEqual([step.probability for step in steps], [self.alone(part) for part in requirement["all"]])

    def test_joint_frequency_under_other_seeds_matches_the_product(self):
        likely = self.together(self.held(SMALL, SHOES, availability="in_stock"),
                               self.priced(SMALL, SHOES, max=self.offer(SMALL, SHOES)["price_trace"]["reference_minor"]),
                               self.held(PLAIN, SHIRTS, stock={self.sources(PLAIN)[0]: {"max": 4}}))
        for requirement, trials in ((likely, 20000), (self.combinations()[0], 20000), (self.combinations()[2], 4000)):
            with self.subTest(requirement=requirement):
                parts = [self.alone(part) for part in requirement["all"]]
                alone, both = combined.empirical(self.natural, requirement, self.api, trials, 10 ** 6)
                for probability, hits in zip(parts + [prod(parts)], alone + [both]):
                    self.assertLess(abs(hits / trials - probability),
                                    4 * (probability * (1 - probability) / trials) ** .5)
                self.assertGreater(min(alone), 20)

    def test_steered_worlds_satisfy_every_part_through_the_producer(self):
        for index, requirement in enumerate(self.combinations()):
            with self.subTest(requirement=requirement):
                world, found, record = combined.steer(self.session, self.natural, self.opened, requirement,
                                                      self.api, Random(index))
                for part, read in zip(requirement["all"], found):
                    self.assertTrue(combined.KINDS[part["schema"]].satisfied(world, part, self.api))
                    self.assertIsInstance(read, dict)
                self.assertEqual(world["status"], streams.STATUS)
                self.assertTrue(commerce.validate({**world, "world_id": world["world_id"]})["valid"])
                self.assertEqual(world["provenance"]["steered_generation"], record)
                self.assertEqual(record["method"], "independent_blocks")
                self.assertEqual(record["probability_given_upstream"],
                                 prod(self.alone(part) for part in requirement["all"]))
                self.assertEqual([block["requirement"] for block in record["blocks"]], requirement["all"])
                self.assertEqual(record["streams_steered"], sum(
                    len(step.script) for step in combined.prepare(self.natural, requirement, self.api, Random(index))))
        self.assertEqual(self.natural, self.frozen)

    def test_repeated_samples_differ_and_keep_the_other_draws(self):
        requirement = self.combinations()[1]
        worlds = [combined.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))[0]
                  for index in range(3)]
        self.assertEqual(len({world["world_id"] for world in worlds}), 3)
        writes = set().union(*(found.writes for found in combined.trial(self.natural, requirement, self.api)))
        self.assertEqual(len(writes), 3)
        for world in worlds:
            self.assertEqual(blocks.background(world, writes), blocks.background(self.natural, writes))
            self.assertNotEqual(blocks.background(world, set()), blocks.background(self.natural, set()))

    def test_coupled_parts_are_refused(self):
        first, second = (self.offer(BOTH, SHOES, index)["sku_id"] for index in (0, 1))
        same_product = [{"schema": stock.VERSION, "retailer_id": BOTH, "sku_id": sku, "availability": "in_stock"}
                        for sku in (first, second)]
        winner = self.cheapest()
        for parts in (same_product,
                      [winner, self.held(BOTH, SHOES, availability="in_stock")],
                      [self.held(PLAIN, SHOES, availability="in_stock"), winner],
                      [winner, self.priced(winner["retailer_ids"][0], SHOES, min=0)],
                      [self.priced(BOTH, SHIRTS, min=0), self.priced(BOTH, SHIRTS, max=10 ** 9)]):
            with self.subTest(parts=parts):
                for attempt in (lambda: combined.prepare(self.natural, self.together(*parts), self.api, Random(0)),
                                lambda: combined.trial(self.natural, self.together(*parts), self.api),
                                lambda: combined.steer(self.session, self.natural, self.opened,
                                                       self.together(*parts), self.api, Random(0))):
                    with self.assertRaises(blocks.Coupled) as caught:
                        attempt()
                    self.assertEqual(caught.exception.reason, "coupled_requirements")

    def test_a_part_with_probability_zero_is_named(self):
        requirement = self.together(self.held(SMALL, SHOES, availability="in_stock"),
                                    self.held(PLAIN, SHOES, availability="backorder"))
        with self.assertRaises(prices.ZeroMass) as caught:
            combined.prepare(self.natural, requirement, self.api, Random(0))
        self.assertEqual((caught.exception.reason, caught.exception.part), ("supplier_disabled", 1))

    def test_requirement_shape_is_validated(self):
        part = self.held(SMALL, SHOES, availability="in_stock")
        for bad in (self.together(part), self.together(), {"schema": combined.VERSION, "all": [part, part], "any": []},
                    {"schema": "other", "all": [part, part]}, self.together(part, self.together(part, part)),
                    self.together(part, {"schema": "unknown"}), self.together(part, "text"),
                    {"schema": combined.VERSION, "all": {"a": part, "b": part}}):
            with self.assertRaises(ValueError, msg=bad) as caught:
                combined.prepare(self.natural, bad, self.api, Random(0))
            self.assertNotIsInstance(caught.exception, (prices.ZeroMass, blocks.Coupled))

    def test_readings_equal_the_producer_under_other_seeds(self):
        held = 0
        likely = self.together(self.held(SMALL, SHOES, availability="in_stock"), self.priced(BOTH, SHIRTS, min=0))
        for requirement in (self.combinations()[2], likely):
            for seed in range(900, 904):
                found = combined.redraw(self.session, self.natural, requirement, self.api, seed)
                self.assertEqual((found.identical, found.agreed), ([True] * len(requirement["all"]),) * 2)
                held += found.satisfied
        self.assertTrue(0 < held < 8)
        self.assertEqual(self.session.generate()[0], self.frozen)


class BlockTests(TwoConcepts):
    def test_single_requirement_records_keep_their_fields(self):
        _, _, record = stock.steer(self.session, self.natural, self.opened,
                                   self.held(SMALL, SHOES, availability="in_stock"), self.api, Random(0))
        self.assertEqual(set(record), {
            "method", "requirement", "natural_world_id", "probability_given_upstream", "offer_id", "natural",
            "steered", "streams_opened", "streams_steered", "streams_opened_only_when_steered",
            "streams_opened_only_naturally", "rebuilt_by_the_producer", "distribution_claim"})
        _, _, _, record = prices.steer(self.session, self.natural, self.cheapest(), self.api, Random(0))
        self.assertEqual(set(record), {
            "method", "requirement", "natural_world_id", "probability_given_upstream", "winning_price_minor",
            "streams_opened", "streams_steered", "repriced", "distribution_claim"})

    def test_background_hides_exactly_the_declared_leaves(self):
        offer = self.offer(BOTH, SHOES)
        pair = (BOTH, offer["product_id"])
        source = self.sources(BOTH)[0]

        def edited(change):
            world = deepcopy(self.natural)
            retailer = next(r for r in world["retailers"] if r["retailer_id"] == BOTH)
            change(retailer, next(o for o in retailer["offers"] if o["offer_id"] == offer["offer_id"]))
            return world

        def held(retailer, row):
            row["stock_by_source"][source] += 1

        def condition(retailer, row):
            next(c for c in retailer["conditions"] if c["product_id"] == pair[1])["condition"] = "another"

        def page(retailer, row):
            entry = next(e for e in retailer["catalog"] if e["product_id"] == pair[1])
            entry["pages"][0]["listings"][0]["stock"] += 1

        def price(retailer, row):
            row["price_minor"] += 100

        def draw(retailer, row):
            row["price_trace"]["offset_draw"] = 0.123

        def reference(retailer, row):
            row["price_trace"]["reference_minor"] += 100

        def name(retailer, row):
            retailer["name"] += "!"

        same = lambda world, writes: blocks.background(world, writes) == blocks.background(self.natural, writes)
        for change, hidden_by in ((held, "stock"), (condition, "stock"), (page, "stock"), (price, "price"),
                                  (draw, "price"), (reference, None), (name, None)):
            world = edited(change)
            for kind in ("stock", "price"):
                self.assertEqual(same(world, {(kind, *pair)}), kind == hidden_by, (change.__name__, kind))
            self.assertFalse(same(world, {("stock", PLAIN, pair[1]), ("price", BOTH, "another-product")}))
            self.assertFalse(same(world, set()))
        self.assertTrue(same(deepcopy(self.natural), set()))

    def test_independence_is_read_from_what_blocks_declare(self):
        block = lambda writes, reads=(): SimpleNamespace(writes=set(writes), reads=set(reads))
        a, b, c = ("stock", "r", "p"), ("price", "r", "p"), ("stock", "r", "q")
        blocks.independent([block([a]), block([b]), block([c])])
        blocks.independent([block([b], [c]), block([a])])
        blocks.independent([block([], [a]), block([], [a])])
        for coupled in ([block([a]), block([a])], [block([a]), block([b], [a])], [block([b], [a]), block([a])],
                        [block([c]), block([a]), block([b], [c])]):
            with self.assertRaises(blocks.Coupled):
                blocks.independent(coupled)


if __name__ == "__main__":
    unittest.main()
