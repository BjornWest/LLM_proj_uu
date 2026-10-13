"""Tests of the ranking by delivered totals against the native single-item delivery task and the admitted oracle.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_delivered.py
"""
from copy import deepcopy
from random import Random
from types import SimpleNamespace
import unittest

from environments.website_world import basic_offer_task, delivery_options
from experiments.accepted_catalog_commerce import basket_quote, delivery_admission, model as commerce, package_export
from experiments.footwear_world_pilot import model as native
from experiments.world_sampling_defaults import model as population

from experiments.steered_generation import blocks, cheapest, combined, menus, policies, prices, ratings, sellers, streams, threshold

SHOES, SANDALS = "footwear.walking_shoes", "footwear.walking_sandals"
INPUTS = {"seed": 5, "concept_ids": [SHOES, SANDALS], "tasks": [SHOES], "controls": None,
          "city_id": "uppsala", "review_count": 0}
SIZE = [{"field": "sku.size_eu", "operator": "eq", "value": 42}]


def totals(world, skus, options=None):
    """Per offer of the given SKUs, the lowest total the admitted oracle quotes for one unit delivered home.

    Written apart from the block: the public plans under admission plan
    version 2 and the oracle's options. Offers without a home option are left out.
    """
    settings = delivery_options.options({"enabled": True, "admission_plan": menus.VERSION, **(options or {})})
    plan = basket_quote.make_plan(world)
    sidecar = delivery_admission.make_plan(world, plan, seed=world["seed"], plan_version=menus.VERSION,
                                           count_weights=delivery_options.producer_weights(settings))
    oracle = delivery_admission.Oracle(world, plan, sidecar)
    found = {}
    for retailer in world["retailers"]:
        for offer in retailer["offers"]:
            if offer["sku_id"] not in skus:
                continue
            result = oracle.quote(world, retailer["retailer_id"], [{"line_id": "a", "offer_id": offer["offer_id"], "quantity": 1}],
                                  plan=plan)
            choices = {row["choice_id"]: row for row in result["delivery_choices"]}
            homes = [option["total_minor"] for option in result["options"]
                     if choices[option["selection"]["a"]]["destination_type"] == "home"]
            if homes:
                found[(retailer["retailer_id"], offer["sku_id"])] = (min(homes), offer["product_id"], offer["price_minor"])
    return found


class Delivered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = SimpleNamespace(basic=basic_offer_task, native=native, population=population,
                                  commerce=commerce, package_export=package_export)
        cls.session = streams.Session(cls.api, INPUTS)
        cls.natural, cls.opened = cls.session.generate()
        cls.frozen = deepcopy(cls.natural)
        cls.base = {"schema": cheapest.VERSION, "concept_id": SHOES, "predicates": SIZE, "delivered": {}}
        cls.frame = cheapest.frame(cls.natural, cls.base, cls.api)
        cls.chances = {}
        for pair in sorted(cls.frame.places):
            try:
                cls.chances[pair] = cheapest.model(cls.natural, cls.need(pair), cls.api, cls.frame).probability
            except prices.ZeroMass:
                pass

    def tearDown(self):
        self.assertEqual(self.natural, self.frozen, "A test changed the natural world")

    @classmethod
    def need(cls, pair, **more):
        return {**cls.base, "retailer_ids": [pair[0]], "product_id": pair[1], **more}

    def agree(self, world):
        """The scope's reading of a world's leaves against the oracle's quotes: who can be delivered, and each total."""
        scope = self.frame.scope
        best, compared = cheapest.lowest(cheapest.recorded(world, SHOES, set(self.frame.places)), scope)
        quoted = totals(world, scope.skus)
        by_pair = {}
        for (rid, sku), (total, product, price) in quoted.items():
            self.assertEqual(compared[(rid, sku)], total, (rid, sku, price))
            by_pair[(rid, product)] = min(by_pair.get((rid, product), total), total)
        self.assertEqual(best, by_pair)
        return by_pair


class ReadingTests(Delivered):
    def test_totals_and_deliverability_are_the_oracles(self):
        by_pair = self.agree(self.natural)
        self.assertGreater(len(by_pair), 4)
        # Retailers that show no home route do not compete; the others' charges are those of their shown routes.
        scope = self.frame.scope
        listing = {r["retailer_id"] for r in self.natural["retailers"] for o in r["offers"] if o["sku_id"] in scope.skus}
        self.assertEqual({pair[0] for pair in scope.pairs}, set(scope.delivered))
        self.assertLessEqual(set(scope.delivered), listing)
        for rid in listing:
            place = menus.oracle(self.natural, rid, {}, self.api)
            rows = menus.shown(place, place.retailer["contracts"])
            self.assertEqual(bool(rows), rid in scope.delivered)
            if rows:
                self.assertEqual(scope.delivered[rid](1), rows[0]["charge_minor"])
        self.assertEqual(self.frame.scope.reads, {(kind, rid, "") for rid in listing for kind in ("contracts", "threshold")})

    def test_a_reached_threshold_waives_as_the_oracle_does(self):
        seen = 0
        for retailer in self.natural["retailers"]:
            world = deepcopy(self.natural)
            patched = next(r for r in world["retailers"] if r["retailer_id"] == retailer["retailer_id"])
            patched["free_shipping_threshold_minor"] = 20000
            frame = cheapest.frame(world, self.base, self.api)
            if retailer["retailer_id"] not in frame.scope.delivered:
                continue
            charge, before = frame.scope.delivered[retailer["retailer_id"]], self.frame.scope.delivered[retailer["retailer_id"]]
            self.assertLessEqual(charge(20000), before(20000))
            self.assertEqual(charge(19999), before(19999))
            for (rid, sku), (total, _, price) in totals(world, frame.scope.skus).items():
                if rid == retailer["retailer_id"]:
                    seen += charge(price) < before(price)
                    self.assertEqual(total, price + charge(price))
        self.assertGreater(seen, 10)

    def test_refusals(self):
        pair = max(self.chances, key=self.chances.get)
        good = self.need(pair)
        for bad in ({**good, "delivered": []}, {**good, "delivered": {"count": 1}},
                    {**good, "delivered": {"delivery_options": {"admission_plan": delivery_admission.PLAN_VERSION}}},
                    {**good, "delivered": {"delivery_options": {"enabled": False}}},
                    {**good, "availability": "positive_stock"}, {k: v for k, v in good.items() if k != "predicates"},
                    {**good, "comparison_site_id": "site"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                cheapest.model(self.natural, bad, self.api)
            self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        # A retailer that shows no home route cannot win.
        outside = sorted({(r["retailer_id"], o["product_id"]) for r in self.natural["retailers"] for o in r["offers"]
                          if o["sku_id"] in self.frame.scope.skus} - set(self.frame.places))
        if outside:
            with self.assertRaises((prices.ZeroMass, ValueError)):
                cheapest.model(self.natural, self.need(outside[0]), self.api)
        ranking = {key: value for key, value in self.base.items() if key != "schema"}
        for policy in ({"express": True}, {"shown": {"cheapest_carrier": self.natural["address_context"]["carriers"][0]["carrier_id"]}}):
            with self.assertRaises(ValueError):
                sellers.model(self.natural, {"schema": sellers.VERSION, "cheapest": ranking, "policy": policy}, self.api)
        with self.assertRaises(ValueError):
            sellers.model(self.natural, {"schema": sellers.VERSION, "cheapest": ranking, "policy": {"dispatch_days": {"min": 1}},
                                         "free_shipping": False}, self.api)


class SteeringTests(Delivered):
    def test_probabilities_match_other_seeds(self):
        trials = 500
        likely = sorted(self.chances, key=self.chances.get, reverse=True)[:3]
        for pair in likely:
            with self.subTest(pair=pair):
                chance = self.chances[pair]
                found = cheapest.trial(self.natural, self.need(pair), self.api)
                hits = sum(found.holds(seed) for seed in range(10 ** 6, 10 ** 6 + trials))
                self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5 + 1e-9)
        # The order by delivered total is not the order by listed price: some pair's chance differs between the two.
        plain = {key: value for key, value in self.base.items() if key != "delivered"}
        shared = cheapest.frame(self.natural, plain, self.api)
        listed = cheapest.model(self.natural, {**plain, "retailer_ids": [likely[0][0]], "product_id": likely[0][1]}, self.api,
                                shared).probability
        self.assertGreater(abs(listed - self.chances[likely[0]]), .01)

    def test_steered_worlds_are_confirmed_by_the_native_task_and_the_oracle(self):
        rare = sorted((pair for pair in self.chances if self.chances[pair] < .02), key=self.chances.get, reverse=True)[:3]
        self.assertTrue(rare)
        for index, pair in enumerate([max(self.chances, key=self.chances.get), *rare]):
            with self.subTest(pair=pair):
                world, found, record = cheapest.steer(self.session, self.natural, self.opened, self.need(pair), self.api,
                                                      Random(index))
                reference = found["reference"]
                self.assertEqual(reference["objective"], "cheapest_total")
                self.assertEqual({(row["retailer_id"], row["product_id"]) for row in reference["winners"]}, {pair})
                self.assertTrue(all(row["delivery"]["destination_type"] == "home" for row in reference["winners"]))
                by_pair = self.agree(world)
                self.assertEqual([found for found in by_pair if by_pair[found] == min(by_pair.values())], [pair])
                self.assertEqual(reference["optimal_score"], [by_pair[pair]])
                # Contracts, thresholds and everything outside the walking shoes are the seed's own.
                for before, after in zip(self.natural["retailers"], world["retailers"]):
                    self.assertEqual((after["contracts"], after["free_shipping_threshold_minor"], after["source_locations"]),
                                     (before["contracts"], before["free_shipping_threshold_minor"], before["source_locations"]))
                self.assertEqual(world["carrier_evidence"], self.natural["carrier_evidence"])
        reading = cheapest.trial(self.natural, self.need(max(self.chances, key=self.chances.get)), self.api)
        for seed in range(900, 904):
            found = blocks.redraw(self.session, self.natural, [reading], seed)
            self.assertEqual((found.identical, found.agreed), ([True], [True]))
            self.assertEqual(found.satisfied, reading.holds(seed))

    def test_an_offer_can_be_listed_below_the_winner_and_not_deliverable(self):
        pair = max(self.chances, key=self.chances.get)
        block = None
        for found, place in sorted(self.frame.places.items()):
            if found[0] == pair[0] or not place.competing:
                continue
            below = {"retailer_id": found[0], "sku_id": place.competing[0]["sku_id"]}
            need = self.need(pair, listed_below=[below])
            try:
                block = cheapest.model(self.natural, need, self.api)
                break
            except prices.ZeroMass:
                continue
        self.assertIsNotNone(block)
        self.assertLess(block.probability, self.chances[pair])
        world, found, record = cheapest.steer(self.session, self.natural, self.opened, need, self.api, Random(5))
        quoted = totals(world, self.frame.scope.skus)
        self.assertNotIn((below["retailer_id"], below["sku_id"]), quoted)
        offer = next(o for r in world["retailers"] if r["retailer_id"] == below["retailer_id"] for o in r["offers"]
                     if o["sku_id"] == below["sku_id"])
        charge = self.frame.scope.delivered[below["retailer_id"]]
        self.assertLess(offer["price_minor"] + charge(offer["price_minor"]), min(total for total, _, _ in quoted.values()))

    def test_what_it_reads_cannot_be_redrawn_beside_it(self):
        pair = max(self.chances, key=self.chances.get)
        need, carrier = self.need(pair), self.natural["address_context"]["carriers"][0]["carrier_id"]
        ranked = sorted({found[0] for found in self.frame.places})
        offer = next(r for r in self.natural["retailers"] if r["retailer_id"] == ranked[0])["offers"][0]
        for other in ({"schema": policies.VERSION, "retailer_id": ranked[0], "express": True},
                      {"schema": threshold.VERSION, "retailer_id": ranked[0], "sku_id": offer["sku_id"], "quantity": 1,
                       "subtotal_test": threshold.TESTS[0]}):
            with self.subTest(other=other), self.assertRaises(blocks.Coupled):
                combined.prepare(self.natural, {"schema": combined.VERSION, "all": [need, other]}, self.api, Random(0))
        # Dispatch days and a carrier's stars are read by no total.
        together = {"schema": combined.VERSION, "all": [
            need, {"schema": policies.VERSION, "retailer_id": ranked[0], "dispatch_days": {"min": 1}},
            {"schema": ratings.VERSION, "carrier_id": carrier, "average_stars": {"max": 4.0}}]}
        world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(1))
        self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in together["all"]))


if __name__ == "__main__":
    unittest.main()
