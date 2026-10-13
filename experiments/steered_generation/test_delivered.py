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

from experiments.steered_generation import (blocks, cheapest, combined, menus, policies, prices, ratings, sellers, streams,
                                            threshold, variants)

SHOES, SANDALS = "footwear.walking_shoes", "footwear.walking_sandals"
INPUTS = {"seed": 5, "concept_ids": [SHOES, SANDALS], "tasks": [SHOES], "controls": None,
          "city_id": "uppsala", "review_count": 0}
SIZE = [{"field": "sku.size_eu", "operator": "eq", "value": 42}]


def totals(world, skus, options=None, kinds=("home",)):
    """Per offer of the given SKUs, the lowest total the admitted oracle quotes for one unit delivered home, or to the
    kinds of destination given.

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
                     if choices[option["selection"]["a"]]["destination_type"] in kinds]
            if homes:
                found[(retailer["retailer_id"], offer["sku_id"])] = (min(homes), offer["product_id"], offer["price_minor"])
    return found


class Delivered(unittest.TestCase):
    inputs, delivered = INPUTS, {}

    @classmethod
    def setUpClass(cls):
        cls.api = SimpleNamespace(basic=basic_offer_task, native=native, population=population,
                                  commerce=commerce, package_export=package_export)
        cls.session = streams.Session(cls.api, cls.inputs)
        cls.natural, cls.opened = cls.session.generate()
        cls.frozen = deepcopy(cls.natural)
        cls.base = {"schema": cheapest.VERSION, "concept_id": SHOES, "predicates": SIZE, "delivered": cls.delivered}
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
        quoted = totals(world, scope.skus, kinds=self.delivered.get("delivery_types", ("home",)))
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
                self.assertTrue(scope.delivered[rid].uniform)
                self.assertEqual(scope.delivered[rid].lowest(1), scope.delivered[rid].highest(1))
                self.assertEqual(scope.delivered[rid].lowest(1), rows[0]["charge_minor"])
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
            charge, before = (found.scope.delivered[retailer["retailer_id"]].lowest for found in (frame, self.frame))
            self.assertLessEqual(charge(20000), before(20000))
            self.assertEqual(charge(19999), before(19999))
            for (rid, sku), (total, _, price) in totals(world, frame.scope.skus).items():
                if rid == retailer["retailer_id"]:
                    seen += charge(price) < before(price)
                    self.assertEqual(total, price + charge(price))
        self.assertGreater(seen, 10)
        # At the threshold itself the charge is waived, as the oracle waives it.
        at = 0
        for retailer in self.natural["retailers"]:
            offers = [o for o in retailer["offers"] if o["sku_id"] in self.frame.scope.skus]
            if retailer["retailer_id"] not in self.frame.scope.delivered or not offers:
                continue
            world = deepcopy(self.natural)
            patched = next(r for r in world["retailers"] if r["retailer_id"] == retailer["retailer_id"])
            patched["free_shipping_threshold_minor"] = offers[0]["price_minor"]
            charge = cheapest.frame(world, self.base, self.api).scope.delivered[retailer["retailer_id"]].lowest
            quoted = totals(world, {offers[0]["sku_id"]})
            if (retailer["retailer_id"], offers[0]["sku_id"]) in quoted:
                at += 1
                self.assertEqual(quoted[(retailer["retailer_id"], offers[0]["sku_id"])][0],
                                 offers[0]["price_minor"] + charge(offers[0]["price_minor"]))
                self.assertLessEqual(charge(offers[0]["price_minor"]), charge(offers[0]["price_minor"] - 1))
        self.assertGreater(at, 3)

    def test_a_retailer_that_delivers_nowhere_does_not_compete(self):
        listing = sorted({pair[0] for pair in self.frame.places})
        world = deepcopy(self.natural)
        patched = next(r for r in world["retailers"] if r["retailer_id"] == listing[0])
        patched["geography"]["fulfilment_policy"]["delivery_countries"] = []
        frame = cheapest.frame(world, self.base, self.api)
        self.assertNotIn(listing[0], frame.scope.delivered)
        self.assertEqual({pair[0] for pair in frame.places}, set(listing[1:]))
        quoted = totals(world, frame.scope.skus)
        self.assertFalse(any(rid == listing[0] for rid, _ in quoted))
        best, compared = cheapest.lowest(cheapest.recorded(world, SHOES, set(frame.places)), frame.scope)
        self.assertEqual({key: total for key, (total, _, _) in quoted.items()}, {key: compared[key] for key in quoted})
        self.assertFalse(any(rid == listing[0] for rid, _ in compared))
        with self.assertRaises(prices.ZeroMass):
            cheapest.model(world, self.need(next(pair for pair in sorted(self.frame.places) if pair[0] == listing[0])), self.api)

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
        charge = self.frame.scope.delivered[below["retailer_id"]].lowest
        self.assertLess(offer["price_minor"] + charge(offer["price_minor"]), min(total for total, _, _ in quoted.values()))

    def test_a_cap_on_the_total(self):
        """A delivery task with a cap counts no offer above it: the winner's total is under the cap."""
        pair = max(self.chances, key=self.chances.get)
        open_block = cheapest.model(self.natural, self.need(pair), self.api, self.frame)
        totals_possible = sorted(open_block.log_terms)
        cap = totals_possible[len(totals_possible) // 2]
        capped = {**self.need(pair), "delivered": {"max_total_minor": cap}}
        block = cheapest.model(self.natural, capped, self.api)
        self.assertEqual(sorted(block.log_terms), [total for total in totals_possible if total <= cap])
        self.assertLess(block.probability, open_block.probability)
        self.assertAlmostEqual(block.probability, sum(share for total, share in open_block.shares.items() if total <= cap) *
                               open_block.probability, places=12)
        found, trials = cheapest.trial(self.natural, capped, self.api), 800
        hits, chance = sum(found.holds(seed) for seed in range(10 ** 6, 10 ** 6 + trials)), block.probability
        self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5 + 1e-9)
        for seed in range(4):
            world, seen, record = cheapest.steer(self.session, self.natural, self.opened, capped, self.api, Random(seed))
            self.assertEqual(seen["task"]["max_total_minor"], cap)
            self.assertLessEqual(seen["reference"]["optimal_score"][0], cap)
            self.assertEqual({(row["retailer_id"], row["product_id"]) for row in seen["reference"]["winners"]}, {pair})
            self.assertTrue(all(row["option"]["total_minor"] <= cap for row in seen["reference"]["candidates"]))
        # A cap under every total the pair can have leaves nothing; and the candidates tool carries a task's cap.
        with self.assertRaises(prices.ZeroMass):
            cheapest.model(self.natural, {**capped, "delivered": {"max_total_minor": totals_possible[0] - 1}}, self.api)
        task = {"kind": "matching_single_item_delivery", "concept_id": SHOES, "predicates": SIZE, "max_total_minor": cap}
        listed = variants.of(self.natural, task, self.api)
        self.assertTrue(listed and all(row["requirement"].get("delivered", row["requirement"].get("cheapest", {}).get("delivered"))[
            "max_total_minor"] == cap for row in listed))
        for bad in ("900", 900.0, -1, True):
            with self.assertRaises(ValueError) as caught:
                cheapest.model(self.natural, {**capped, "delivered": {"max_total_minor": bad}}, self.api)
            self.assertNotIsInstance(caught.exception, prices.ZeroMass)

    def test_a_cap_through_the_seller_requirement(self):
        """Astra v35: the seller requirement's own reading of who wins must honour the cap, as its model and check do."""
        natural = self.frame.scope.reference(self.natural)[1]["optimal_score"][0]
        ranking = {key: value for key, value in self.base.items() if key != "schema"}
        seller = lambda cap: {"schema": sellers.VERSION, "policy": {"dispatch_days": {"min": 1}},
                              "cheapest": {**ranking, "delivered": {"max_total_minor": cap}}}
        need, trials = seller(natural - 1), 500
        block = sellers.model(self.natural, need, self.api)
        open_block = sellers.model(self.natural, {**need, "cheapest": ranking}, self.api)
        self.assertLess(block.probability, open_block.probability)
        hits, chance = sum(sellers.empirical(self.natural, need, self.api, trials, 10 ** 6).values()), block.probability
        self.assertLess(abs(hits / trials - chance), 4.5 * (chance * (1 - chance) / trials + block.error ** 2) ** .5 + 1e-9)
        reading = sellers.trial(self.natural, need, self.api)
        scope = cheapest.frame(self.natural, sellers.ranking(need), self.api).scope
        above = 0
        for seed in range(10 ** 6, 10 ** 6 + 60):
            best, _ = cheapest.lowest(reading.reading(seed)[0], scope)
            if best and min(best.values()) > natural - 1:
                above += 1
                self.assertIsNone(reading.winner(seed))
                self.assertFalse(reading.holds(seed))
        self.assertGreater(above, 3)
        for seed in (10 ** 6, 10 ** 6 + 9, 904):
            found = blocks.redraw(self.session, self.natural, [reading], seed)
            self.assertEqual((found.identical, found.agreed), ([True], [True]))
        world, found, record = sellers.steer(self.session, self.natural, self.opened, need, self.api, Random(1))
        self.assertLessEqual(found["cheapest"]["reference"]["optimal_score"][0], natural - 1)
        # No total is at or under zero: no mass, and no redraw holds.
        with self.assertRaises(prices.ZeroMass):
            sellers.model(self.natural, seller(0), self.api)
        nothing = sellers.trial(self.natural, seller(0), self.api)
        self.assertFalse(any(nothing.holds(seed) for seed in range(10 ** 6, 10 ** 6 + 100)))

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
        # The same through the seller requirement, which reads what its ranking reads (Astra v27).
        ranking = {key: value for key, value in self.base.items() if key != "schema"}
        seller = {"schema": sellers.VERSION, "cheapest": ranking, "policy": {"dispatch_days": {"min": 1}}}
        declared = sellers.footprint(self.natural, seller, self.api)
        self.assertEqual(declared.reads, self.frame.scope.reads)
        threshold_elsewhere = {"schema": threshold.VERSION, "retailer_id": ranked[1], "quantity": 1, "subtotal_test": threshold.TESTS[0],
                               "sku_id": next(r for r in self.natural["retailers"] if r["retailer_id"] == ranked[1])["offers"][0]["sku_id"]}
        for other in (threshold_elsewhere, {"schema": policies.VERSION, "retailer_id": ranked[1], "express": True}):
            with self.subTest(seller_with=other), self.assertRaises(blocks.Coupled):
                combined.prepare(self.natural, {"schema": combined.VERSION, "all": [seller, other]}, self.api, Random(0))
        self.assertLessEqual(self.frame.scope.reads, sellers.prepare(self.natural, seller, self.api, Random(0)).reads)
        world, found, record = sellers.steer(self.session, self.natural, self.opened, seller, self.api, Random(2))
        self.assertGreaterEqual(found["policy"]["warehouse_dispatch_days"], 1)
        self.assertEqual(found["cheapest"]["reference"]["objective"], "cheapest_total")
        # A recipe that strands a retailer: the combination reports the part, and its runner does not fall over.
        from experiments.steered_generation import run
        stranding = {**self.need(pair), "delivered": {"delivery_options": {"count_weights": {"10000": 1}}}}
        dispatch = {"schema": policies.VERSION, "retailer_id": ranked[0], "dispatch_days": {"min": 1}}
        with self.assertRaises(prices.ZeroMass) as caught:
            combined.prepare(self.natural, {"schema": combined.VERSION, "all": [dispatch, stranding]}, self.api, Random(0))
        self.assertEqual((caught.exception.reason, caught.exception.part), ("no_outcome", 1))
        case = {"samples": [], "requirement_sha256": "x"}
        run.combined_case(SimpleNamespace(samples=1, producer_redraws=0, validate_trials=0), self.session, self.natural,
                          self.opened, self.api, {"schema": combined.VERSION, "all": [dispatch, stranding]}, case, None)
        self.assertEqual((case["status"], case["part"]), ("zero_probability_given_upstream", 1))
        self.assertFalse(cheapest.satisfied(self.natural, stranding, self.api))
        # Dispatch days and a carrier's stars are read by no total.
        together = {"schema": combined.VERSION, "all": [
            need, {"schema": policies.VERSION, "retailer_id": ranked[0], "dispatch_days": {"min": 1}},
            {"schema": ratings.VERSION, "carrier_id": carrier, "average_stars": {"max": 4.0}}]}
        world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(1))
        self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in together["all"]))

    def test_the_candidates_of_the_delivery_task(self):
        task = {"kind": "matching_single_item_delivery", "concept_id": SHOES, "predicates": SIZE}
        found = variants.of(self.natural, task, self.api)
        self.assertEqual([row["name"] for row in found], ["likeliest_winner", "better_offer_unavailable", "unlikely_winner",
                                                          "cheapest_delivered_with_lowest_rated_carrier"])
        listed = variants.of(self.natural, {"kind": "cheapest_matching_available", "concept_id": SHOES, "predicates": SIZE}, self.api)
        self.assertNotEqual([row["log_probability"] for row in found[:3]], [row["log_probability"] for row in listed])
        for index, row in enumerate(found[:3]):
            with self.subTest(name=row["name"]):
                self.assertEqual(row["requirement"]["delivered"], {})
                world, seen, record = cheapest.steer(self.session, self.natural, self.opened, row["requirement"], self.api,
                                                     Random(index))
                self.assertAlmostEqual(record["log_probability_given_upstream"], row["log_probability"], places=9)
                winner = seen["reference"]["winners"][0]
                self.assertEqual((winner["retailer_id"], winner["product_id"]),
                                 (row["requirement"]["retailer_ids"][0], row["requirement"]["product_id"]))
        # The fourth: the likeliest winner again, delivered by the carrier the world rates lowest; an estimate.
        from experiments.steered_generation import couriers
        last, top = found[3], found[0]["requirement"]
        stars = {row["carrier_id"]: row["summary"]["average_stars"] for row in self.natural["carrier_evidence"]["public"]["carriers"]}
        self.assertEqual(last["requirement"]["schema"], couriers.VERSION)
        self.assertEqual(stars[last["requirement"]["carrier_id"]], min(stars.values()))
        self.assertEqual(last["requirement"]["cheapest"], {key: value for key, value in top.items() if key != "schema"})
        self.assertTrue(last["probability_is_estimated"])
        self.assertLess(last["log_probability"], found[0]["log_probability"])
        world, seen, record = couriers.steer(self.session, self.natural, self.opened, last["requirement"], self.api, Random(9))
        self.assertTrue(all(row["delivery"]["carrier_id"] == last["requirement"]["carrier_id"] for row in seen["reference"]["winners"]))
        self.assertAlmostEqual(record["log_probability_given_upstream"], last["log_probability"], places=9)
        same = variants.of(self.natural, {**task, "objective": "cheapest_total", "delivery_types": ["home"],
                                          "destination": "user_home"}, self.api)
        self.assertEqual(same, found)
        counted = variants.of(self.natural, {**task, "delivery_options": {"count_weights": {"1": 1}}}, self.api)
        self.assertEqual(counted[0]["requirement"]["delivered"], {"delivery_options": {"count_weights": {"1": 1}}})
        for other in ({"objective": "fastest_then_cheapest"}, {"delivery_types": ["home", "retailer_branch"]},
                      {"delivery_types": []}, {"delivery_types": {"parcel_locker": False}}, {"delivery_types": None},
                      {"delivery_types": ["home", 1]}, {"delivery_types": ["home", "home"]}, {"max_total_minor": 900.5},
                      {"max_total_minor": -1}, {"arrival_deadline": "2026-10-20"}, {"comparison_site_id": "comparison-00"},
                      {"availability": "positive_stock"},
                      {"delivery_options": {"admission_plan": "retailer-delivery-admission-plan-v1"}}):
            with self.subTest(other=other), self.assertRaises(ValueError):
                variants.of(self.natural, {**task, **other}, self.api)
        with self.assertRaises(ValueError):
            variants.of(self.natural, {key: value for key, value in task.items() if key != "predicates"}, self.api)


class ByLocation(Delivered):
    """A world where two retailers charge more from a far location: totals depend on where the stock is."""
    inputs = {**INPUTS, "seed": 7}

    def split(self):
        return sorted(rid for rid, found in self.frame.scope.delivered.items() if not found.uniform)

    def test_charges_by_location_are_the_oracles_and_lie_between_the_bounds(self):
        scope, split = self.frame.scope, self.split()
        self.assertGreaterEqual(len(split), 2)
        classes = set()
        reading, _ = cheapest.reader(self.natural, self.frame.places, self.api)
        keys = cheapest.trial(self.natural, self.need(max(self.chances, key=self.chances.get)), self.api).keys
        worlds = [self.natural] + [self.session.generate({key: streams.Reseeded(seed) for key in keys})[0]
                                   for seed in range(950, 954)]
        for world in worlds:
            self.agree(world)
        for seed in range(2000, 2200):
            best, compared = cheapest.lowest(reading(seed), scope)
            leaves = reading(seed)["offers"]
            for (rid, sku), rank in compared.items():
                price = next(row["price_minor"] for row in leaves.values() if (row["retailer_id"], row["sku_id"]) == (rid, sku))
                low, high = (cheapest.ranks(scope, rid, best=flag)(sku, price) for flag in (True, False))
                self.assertTrue(low <= rank <= high)
                if rid in split:
                    classes.add((rid, rank == low, rank == high))
        # Both classes occur at both retailers.
        self.assertLessEqual({(rid, near, not near) for rid in split for near in (True, False)}, classes)

    def test_probabilities_are_estimates_that_match_other_seeds(self):
        trials, split = 1500, self.split()
        winners = [max((pair for pair in self.chances if pair[0] == rid), key=self.chances.get) for rid in split]
        winners.append(max((pair for pair in self.chances if pair[0] not in split), key=self.chances.get))
        for pair in winners:
            with self.subTest(pair=pair):
                block = cheapest.model(self.natural, self.need(pair), self.api, self.frame)
                self.assertTrue(block.bounded and 0 < block.accepted <= cheapest.PROPOSALS)
                self.assertGreater(block.error, 0) if block.accepted < cheapest.PROPOSALS else self.assertEqual(block.error, 0)
                found = cheapest.trial(self.natural, self.need(pair), self.api)
                hits, chance = sum(found.holds(seed) for seed in range(10 ** 6, 10 ** 6 + trials)), block.probability
                self.assertLess(abs(hits / trials - chance), 4.5 * (chance * (1 - chance) / trials + block.error ** 2) ** .5 + 1e-9)
                self.assertEqual(cheapest.model(self.natural, self.need(pair), self.api).probability, chance)

    def test_samples_hold_on_the_charges_as_they_are_and_match_rejection_sampling(self):
        pair = max((found for found in self.chances if found[0] in self.split()), key=self.chances.get)
        need, scope = self.need(pair), self.frame.scope
        found = cheapest.trial(self.natural, need, self.api)
        accepted = [leaves for leaves in (found.reading(seed) for seed in range(10 ** 6, 10 ** 6 + 5000))
                    if cheapest.judged(leaves, need, scope) is not None]
        self.assertGreater(len(accepted), 250)
        block, rng, planned = cheapest.model(self.natural, need, self.api), Random(8), []
        while len(planned) < 300:
            draws = cheapest.sample(block, rng)[1]
            if cheapest.true(block, draws):
                planned.append(cheapest.planned(block, draws))
        low = lambda row: cheapest.ranks(scope, row["retailer_id"], best=True)(row["sku_id"], row["price_minor"])

        def features(leaves):
            best, compared = cheapest.lowest(leaves, scope)
            mine = [row for row in leaves["offers"].values() if (row["retailer_id"], row["product_id"]) == pair
                    and (row["retailer_id"], row["sku_id"]) in compared and compared[(row["retailer_id"], row["sku_id"])] == best[pair]]
            return {"total": best[pair], "runner_up": sorted(best.values())[1] - best[pair] if len(best) > 1 else 0,
                    "pairs_available": len(best), "winner_from_near": any(low(row) == best[pair] for row in mine),
                    "winner_by_supplier": any(row["supplier_order"] for row in mine)}

        mine, theirs = [features(leaves) for leaves in planned], [features(leaves) for leaves in accepted]
        self.assertTrue(0 < sum(row["winner_from_near"] for row in theirs) < len(theirs))
        for name in mine[0]:
            with self.subTest(feature=name):
                a, b = [float(row[name]) for row in mine], [float(row[name]) for row in theirs]
                error = lambda values: (sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values) ** 2) ** .5
                self.assertLess(abs(sum(a) / len(a) - sum(b) / len(b)), 4.5 * (error(a) ** 2 + error(b) ** 2) ** .5 + 1e-9)

    def test_steered_worlds_are_confirmed_by_the_native_task(self):
        split = self.split()
        for index, pair in enumerate([max((found for found in self.chances if found[0] == rid), key=self.chances.get)
                                      for rid in split] + [min(self.chances, key=lambda found: (found[0] in split, -self.chances[found]))]):
            with self.subTest(pair=pair):
                world, found, record = cheapest.steer(self.session, self.natural, self.opened, self.need(pair), self.api,
                                                      Random(index))
                self.assertEqual({(row["retailer_id"], row["product_id"]) for row in found["reference"]["winners"]}, {pair})
                by_pair = self.agree(world)
                self.assertEqual([other for other in by_pair if by_pair[other] == min(by_pair.values())], [pair])
                self.assertTrue(record["probability_is_estimated"])
                self.assertGreaterEqual(record["block_samples_for_this_sample"], 1)
                self.assertEqual(record["proposals"], cheapest.PROPOSALS)
                # What is recorded is what the accepted world's offers cost, not the ranks the block was sampled on.
                self.assertEqual([record["winning_price_minor"]], found["reference"]["optimal_score"])
                for row in record["restocked"]:
                    self.assertEqual(row["cheapest_available_minor"], by_pair.get((row["retailer_id"], row["product_id"])))
        reading = cheapest.trial(self.natural, self.need(pair), self.api)
        for seed in range(900, 903):
            found = blocks.redraw(self.session, self.natural, [reading], seed)
            self.assertEqual((found.identical, found.agreed), ([True], [True]))
            self.assertEqual(found.satisfied, reading.holds(seed))

    def test_the_runner_the_seller_requirement_and_the_candidates_carry_the_estimate(self):
        """Astra v28: a winner shipped from a far location through the runner; estimates through the wrappers."""
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from experiments.steered_generation import run
        split = self.split()
        pair = max((found for found in self.chances if found[0] in split), key=self.chances.get)
        args = SimpleNamespace(samples=6, producer_redraws=1, validate_trials=1500)
        case = {"samples": [], "requirement_sha256": "v28-charge-bound-record"}
        with TemporaryDirectory() as folder:
            run.cheapest_case(args, self.session, self.natural, self.opened, self.api, self.need(pair), case,
                              lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], len(case["samples"]), case["probability_is_estimated"]), ("sampled", 6, True))
        self.assertIsNone(case["winning_prices_modelled"])
        self.assertIsNone(case["validation"]["winning_price_total_variation"])
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertGreater(len({row["winning_price_minor"] for row in case["samples"]}), 1)
        # The seller requirement over this ranking: its alternatives' weights are estimates, and it says so.
        ranking = {key: value for key, value in self.base.items() if key != "schema"}
        seller = {"schema": sellers.VERSION, "cheapest": ranking, "policy": {"dispatch_days": {"min": 1}}}
        block = sellers.model(self.natural, seller, self.api)
        self.assertTrue(block.estimated and block.ranking_estimates and not block.estimates)
        self.assertGreater(block.error, 0)
        self.assertLess(block.error, block.probability)
        step = sellers.prepare(self.natural, seller, self.api, Random(3))
        self.assertTrue(step.estimated)
        self.assertEqual(step.error, block.error)
        world, found, record = sellers.steer(self.session, self.natural, self.opened, seller, self.api, Random(3))
        self.assertTrue(record["probability_is_estimated"])
        self.assertEqual(record["ranking_samples_accepted_by_pair"], block.ranking_estimates)
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.seller_case(SimpleNamespace(samples=1, producer_redraws=0, validate_trials=600), self.session, self.natural,
                            self.opened, self.api, seller, case, lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], case["probability_is_estimated"]), ("sampled", True))
        self.assertEqual(case["probability_standard_error"], block.error)
        # The candidates of the delivery task: the two this world's ranking can carry, marked as estimates.
        found = variants.of(self.natural, {"kind": "matching_single_item_delivery", "concept_id": SHOES, "predicates": SIZE}, self.api)
        self.assertEqual([row["name"] for row in found][:2], ["likeliest_winner", "unlikely_winner"])
        self.assertLessEqual({row["name"] for row in found[2:]}, {"cheapest_delivered_with_lowest_rated_carrier"})
        self.assertTrue(all(row["probability_is_estimated"] and row["probability_standard_error"] >= 0 for row in found))
        self.assertNotIn("probability_is_estimated", variants.of(
            self.natural, {"kind": "cheapest_matching_available", "concept_id": SHOES, "predicates": SIZE}, self.api)[0])

    def test_what_the_bounds_cannot_carry_is_refused(self):
        pairs = sorted(self.chances, key=self.chances.get, reverse=True)
        two = next((a, b) for a in pairs for b in pairs if a[0] != b[0] and a[1] == b[1])
        with self.assertRaises(ValueError) as caught:
            cheapest.model(self.natural, {**self.need(two[0]), "retailer_ids": [two[0][0], two[1][0]]}, self.api)
        self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        other = next(place for found, place in sorted(self.frame.places.items()) if found[0] != pairs[0][0] and place.competing)
        with self.assertRaises(ValueError) as caught:
            cheapest.model(self.natural, self.need(pairs[0], listed_below=[
                {"retailer_id": other.pair[0], "sku_id": other.competing[0]["sku_id"]}]), self.api)
        self.assertNotIsInstance(caught.exception, prices.ZeroMass)


class ToAnyDestination(Delivered):
    """Home delivery and collection points both count, as a delivery task can state."""
    delivered = {"delivery_types": ["home", "parcel_locker", "staffed_counter"]}

    def test_totals_are_the_oracles_and_points_matter(self):
        by_pair = self.agree(self.natural)
        home = cheapest.frame(self.natural, {**self.base, "delivered": {}}, self.api)
        # A collection point is cheaper than the door at some retailer, and some retailer delivers only to points.
        cheaper = [rid for rid, charge in self.frame.scope.delivered.items()
                   if rid in home.scope.delivered and charge.lowest(1) < home.scope.delivered[rid].lowest(1)]
        self.assertTrue(cheaper)
        self.assertGreaterEqual(set(self.frame.scope.delivered), set(home.scope.delivered))
        for rid, charge in self.frame.scope.delivered.items():
            if rid in home.scope.delivered:
                self.assertLessEqual(charge.lowest(1), home.scope.delivered[rid].lowest(1))
        task, reference = self.frame.scope.reference(self.natural)
        self.assertEqual(task["delivery_types"], sorted(self.delivered["delivery_types"]))
        self.assertEqual(reference["optimal_score"], [min(by_pair.values())])

    def test_retailers_that_deliver_to_points_only_compete(self):
        """Astra v34: with no carrier delivering to the door, retailers compete through collection points alone."""
        world = deepcopy(self.natural)
        for carrier in world["address_context"]["carriers"]:
            carrier["home_delivery"] = False
        points = cheapest.frame(world, self.base, self.api)
        home = cheapest.frame(world, {**self.base, "delivered": {}}, self.api)
        self.assertFalse(home.scope.delivered)
        only = set(points.scope.delivered) - set(home.scope.delivered)
        self.assertGreater(len(only), 3)
        best, compared = cheapest.lowest(cheapest.recorded(world, SHOES, set(points.places)), points.scope)
        quoted = totals(world, points.scope.skus, kinds=self.delivered["delivery_types"])
        self.assertGreater(len(quoted), 10)
        self.assertEqual({key: total for key, (total, _, _) in quoted.items()}, {key: compared[key] for key in quoted})
        self.assertEqual({pair[0] for pair in best}, {rid for rid, _ in quoted})

    def test_probabilities_and_steered_worlds(self):
        likely = sorted(self.chances, key=self.chances.get, reverse=True)[:2]
        home = cheapest.frame(self.natural, {**self.base, "delivered": {}}, self.api)
        different = 0
        for index, pair in enumerate(likely):
            with self.subTest(pair=pair):
                need, chance, trials = self.need(pair), self.chances[pair], 600
                found = cheapest.trial(self.natural, need, self.api)
                hits = sum(found.holds(seed) for seed in range(10 ** 6, 10 ** 6 + trials))
                block = cheapest.model(self.natural, need, self.api, self.frame)
                self.assertLess(abs(hits / trials - chance), 4.5 * (chance * (1 - chance) / trials + block.error ** 2) ** .5 + 1e-9)
                world, seen, record = cheapest.steer(self.session, self.natural, self.opened, need, self.api, Random(index))
                by_pair = self.agree(world)
                self.assertEqual([other for other in by_pair if by_pair[other] == min(by_pair.values())], [pair])
                self.assertTrue(all(row["delivery"]["destination_type"] in self.delivered["delivery_types"]
                                    for row in seen["reference"]["winners"]))
        # Counting collection points changes who is likely to be cheapest for some pair of the world.
        for pair, chance in self.chances.items():
            try:
                at_home = cheapest.model(self.natural, {**self.need(pair), "delivered": {}}, self.api, home).probability
            except (prices.ZeroMass, ValueError):
                at_home = 0.0
            different += abs(at_home - chance) > 1e-9
        self.assertTrue(different)

    def test_kinds_are_checked_and_the_carrier_requirement_is_for_the_door(self):
        from experiments.steered_generation import couriers
        pair = max(self.chances, key=self.chances.get)
        for bad in ([], ["home", "home"], ["branch"], "home", ["home", 1]):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                cheapest.model(self.natural, {**self.need(pair), "delivered": {"delivery_types": bad}}, self.api)
            self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        carrier = self.natural["address_context"]["carriers"][0]["carrier_id"]
        with self.assertRaises(ValueError) as caught:
            couriers.model(self.natural, {"schema": couriers.VERSION, "carrier_id": carrier, "cheapest": {
                key: value for key, value in self.need(pair).items() if key != "schema"}}, self.api)
        self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        task = {"kind": "matching_single_item_delivery", "concept_id": SHOES, "predicates": SIZE,
                "delivery_types": ["parcel_locker", "home", "staffed_counter"]}
        found = variants.of(self.natural, task, self.api)
        self.assertEqual(found[0]["requirement"]["delivered"], self.delivered)
        self.assertNotIn("cheapest_delivered_with_lowest_rated_carrier", [row["name"] for row in found])
        self.assertEqual(found[0]["requirement"]["retailer_ids"][0], pair[0])


if __name__ == "__main__":
    unittest.main()
