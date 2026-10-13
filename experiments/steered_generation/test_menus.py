"""Tests of what a retailer shows of its delivery options, against the commerce oracle's plans and quotes.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_menus.py
"""
from collections import Counter
from copy import deepcopy
from math import exp
from random import Random
from types import SimpleNamespace
import unittest

from environments.website_world import basic_offer_task, delivery_options
from experiments.accepted_catalog_commerce import basket_quote, delivery_admission, model as commerce, package_export
from experiments.footwear_world_pilot import model as native
from experiments.world_sampling_defaults import model as population

from experiments.steered_generation import blocks, combined, menus, policies, prices, ratings, sellers, streams

SHOES, SANDALS = "footwear.walking_shoes", "footwear.walking_sandals"
INPUTS = {"seed": 5, "concept_ids": [SHOES, SANDALS], "tasks": [SHOES], "controls": None,
          "city_id": "uppsala", "review_count": 0}
V2 = delivery_admission.STRUCTURAL_PLAN_VERSION


def quoted(world, retailer_id, settings=None):
    """What the oracle quotes for home delivery of one unit of each of a retailer's offers, under the site's plans.

    Written apart from `menus`: the public plans, the admitted oracle and its
    options. Returns, per offer that can be delivered and is not waived, the
    carrier of the strictly cheapest home option (None for a tie) and the
    carriers of all home options.
    """
    settings = delivery_options.options({"enabled": True, "admission_plan": V2, **(settings or {})})
    plan = basket_quote.make_plan(world)
    sidecar = delivery_admission.make_plan(world, plan, seed=world["seed"], count_weights=delivery_options.producer_weights(settings),
                                           plan_version=delivery_options.producer_plan_version(settings))
    oracle = delivery_admission.Oracle(world, plan, sidecar)
    retailer = next(row for row in world["retailers"] if row["retailer_id"] == retailer_id)
    found = []
    for offer in retailer["offers"][:40]:
        result = oracle.quote(world, retailer_id, [{"line_id": "a", "offer_id": offer["offer_id"], "quantity": 1}], plan=plan)
        choices = {row["choice_id"]: row for row in result["delivery_choices"]}
        homes = [(option["shipping_minor"], choices[option["selection"]["a"]]["carrier_id"], option) for option in result["options"]
                 if choices[option["selection"]["a"]]["destination_type"] == "home"]
        if not homes or any(shipment["qualification"]["qualified"] for _, _, option in homes for shipment in option["shipments"]):
            continue
        best = {}
        for charge, carrier, _ in homes:
            best[carrier] = min(best.get(carrier, charge), charge)
        lowest = sorted(best.values())
        found.append((None if len(lowest) > 1 and lowest[0] == lowest[1] else min(best, key=best.get), set(best)))
    return found


class Menus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = SimpleNamespace(basic=basic_offer_task, native=native, population=population,
                                  commerce=commerce, package_export=package_export)
        cls.session = streams.Session(cls.api, INPUTS)
        cls.natural, cls.opened = cls.session.generate()
        cls.frozen = deepcopy(cls.natural)
        cls.carriers = [row["carrier_id"] for row in cls.natural["address_context"]["carriers"]]
        cls.retailers = {scale: next(r for r in cls.natural["retailers"] if r["scale"] == scale)
                         for scale in ("small", "medium", "large")}

    def tearDown(self):
        self.assertEqual(self.natural, self.frozen, "A test changed the natural world")

    def need(self, scale="medium", **stated):
        return {"schema": policies.VERSION, "retailer_id": self.retailers[scale]["retailer_id"], **stated}

    def requirements(self):
        a, b, c = self.carriers[2], self.carriers[5], self.carriers[0]
        return [self.need(shown={"cheapest_carrier": a}), self.need(shown={"cheapest_carrier": b, "destination_type": "any"}),
                self.need("large", shown={"carriers": {"include": [a], "exclude": [c]}}),
                self.need("small", shown={"carriers": {"exclude": [c, a]}, "destination_type": "any"}, express=True),
                self.need("large", shown={"cheapest_carrier": a, "carriers": {"include": [b]}}, carrier_count={"max": 4},
                          dispatch_days={"min": 1}),
                self.need(shown={"cheapest_carrier": c, "delivery_options": {"count_weights": {"1": 1}}})]


class ReadingTests(Menus):
    def test_the_reading_from_contracts_is_what_the_plans_give(self):
        for retailer in self.natural["retailers"]:
            for scope in menus.SCOPES:
                place = menus.site(self.natural, retailer["retailer_id"], {"cheapest_carrier": self.carriers[0],
                                                                           "destination_type": scope}, self.api)
                rows = menus.shown(place, retailer["contracts"])
                self.assertEqual(rows, menus.official(self.natural, place))
                self.assertEqual([row["charge_minor"] for row in rows], sorted(row["charge_minor"] for row in rows))
                self.assertLessEqual({row["carrier_id"] for row in rows}, {row["carrier_id"] for row in retailer["contracts"]})
                if scope == "home":
                    self.assertTrue(all(row["destination_type"] == "home" for row in rows))
                    # The oracle's own quotes of real offers, wherever nothing is waived.
                    for cheapest, shown in quoted(self.natural, retailer["retailer_id"]):
                        self.assertEqual((cheapest, shown), (menus.cheapest(rows), {row["carrier_id"] for row in rows}))

    def test_cheapest_is_strict_and_the_clause_reads_carriers(self):
        row = lambda carrier, charge: {"carrier_id": carrier, "charge_minor": charge}
        self.assertEqual(menus.cheapest([row("a", 5), row("a", 3), row("b", 4)]), "a")
        self.assertIsNone(menus.cheapest([row("a", 3), row("b", 3), row("c", 9)]))
        self.assertEqual(menus.cheapest([row("a", 3), row("a", 3)]), "a")
        self.assertIsNone(menus.cheapest([]))
        rows = [row("a", 3), row("b", 4)]
        self.assertTrue(menus.holds({"carriers": {"include": ["a"], "exclude": ["c"]}, "cheapest_carrier": "a"}, rows))
        for clause in ({"carriers": {"include": ["c"]}}, {"carriers": {"exclude": ["b"]}}, {"cheapest_carrier": "b"}):
            self.assertFalse(menus.holds(clause, rows))
        self.assertFalse(menus.holds({"carriers": {"exclude": ["c"]}}, None))

    def test_a_recipes_counts_decide_how_many_are_shown(self):
        retailer = self.retailers["large"]
        sizes = {}
        for weights in ({"1": 1}, {"2": 1}, {"10000": 1}, None):
            clause = {"cheapest_carrier": self.carriers[0], "destination_type": "any",
                      **({} if weights is None else {"delivery_options": {"count_weights": weights}})}
            place = menus.site(self.natural, retailer["retailer_id"], clause, self.api)
            rows = menus.shown(place, retailer["contracts"])
            self.assertEqual(rows, menus.official(self.natural, place))
            sizes[str(weights)] = None if rows is None else len(rows)
        # One shown route is the home anchor; a count beyond the routes has no support and generation rejects the world.
        self.assertEqual((sizes["{'1': 1}"], sizes["{'10000': 1}"]), (1, None))
        self.assertLessEqual(sizes["{'2': 1}"], 2)

    def test_bad_clauses_and_settings(self):
        good = self.need(shown={"cheapest_carrier": self.carriers[0]})
        for bad in ({}, {"destination_type": "home"}, {"cheapest_carrier": ""}, {"cheapest_carrier": "carrier-99"},
                    {"cheapest_carrier": self.carriers[0], "destination_type": "branch"},
                    {"carriers": {}}, {"carriers": {"include": []}}, {"carriers": {"include": ["carrier-99"]}},
                    {"carriers": {"include": [self.carriers[0]], "exclude": [self.carriers[0]]}},
                    {"cheapest_carrier": self.carriers[0], "carriers": {"exclude": [self.carriers[0]]}},
                    {"cheapest_carrier": self.carriers[0], "count": 1},
                    {"cheapest_carrier": self.carriers[0], "delivery_options": {"enabled": False}},
                    {"cheapest_carrier": self.carriers[0], "delivery_options": {"admission_plan": delivery_admission.PLAN_VERSION}},
                    {"cheapest_carrier": self.carriers[0], "delivery_options": {"count_weights": {"0": 1}}},
                    {"cheapest_carrier": self.carriers[0], "delivery_options": []}, None):
            for call in (policies.model, policies.trial, lambda *a: policies.prepare(*a, Random(0))):
                with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                    call(self.natural, {**good, "shown": bad}, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        # A carrier that must be shown and must not be contracted; and a menu no contracts give.
        for impossible in (self.need(shown={"cheapest_carrier": self.carriers[0]}, carriers={"exclude": [self.carriers[0]]}),
                           self.need("small", shown={"carriers": {"include": self.carriers[:4]}}),
                           self.need(shown={"cheapest_carrier": self.carriers[0], "delivery_options": {"count_weights": {"10000": 1}}})):
            with self.subTest(impossible=impossible), self.assertRaises(prices.ZeroMass):
                policies.model(self.natural, impossible, self.api)
        other = deepcopy(self.natural)
        del other["seed"]
        with self.assertRaises(ValueError):
            policies.model(other, good, self.api)


class SteeringTests(Menus):
    def test_probabilities_match_other_seeds(self):
        trials = 2500
        for requirement in self.requirements():
            with self.subTest(requirement=requirement):
                block = policies.model(self.natural, requirement, self.api)
                chance, share = block.probability, block.accepted / policies.PROPOSALS
                hits = policies.empirical(self.natural, requirement, self.api, trials, 10 ** 6)
                # The estimate's own error (a share of a fixed number of draws) and the count's.
                error = (chance * (1 - chance) / trials + chance ** 2 * (1 - share) / (share * policies.PROPOSALS)) ** .5
                self.assertLess(abs(hits / trials - chance), 4.5 * error + 1e-9)
                self.assertEqual(policies.model(self.natural, requirement, self.api).probability, chance)
                saved = dict(policies.ESTIMATES)
                policies.ESTIMATES.clear()
                self.assertEqual(policies.model(self.natural, requirement, self.api).probability, chance)
                self.assertEqual(policies.ESTIMATES.keys() <= saved.keys(), True)
        # What the contracts must have for the menu is in the exact part: a shown carrier is a contracted one.
        with_shown = policies.site(self.natural, self.requirements()[0], self.api)
        self.assertEqual(with_shown.contract["carriers"], {"include": [self.carriers[2]]})

    def test_samples_match_rejection_sampling(self):
        requirement = self.need(shown={"cheapest_carrier": self.carriers[2]}, express=True)
        carrier = self.carriers[2]
        reading = policies.trial(self.natural, requirement, self.api)
        accepted = [reading.reading(seed)[0] for seed in range(10 ** 6, 10 ** 6 + 25000) if reading.holds(seed)]
        self.assertGreater(len(accepted), 500)
        place = policies.site(self.natural, requirement, self.api)
        rng, planned = Random(13), []
        for _ in range(500):
            step = policies.prepare(self.natural, requirement, self.api, rng)
            order = [self.carriers[int(name.split("-")[1])] for name in step.script[place.keys.carriers][0][1]]
            planned.append([{"carrier_id": name, "tiers": ["standard"] + [tier for tier in policies.TIERS
                                                                          if step.script[place.keys.tier(name, tier)][0][1] == 0.0],
                             "collection_fee_minor": int(step.script[place.keys.fee(name)][0][1]),
                             "home_delta_minor": int(step.script[place.keys.home(name)][0][1])} for name in order])
            self.assertTrue(policies.met(place, planned[-1], 0))
        own = lambda rows: next(row for row in rows if row["carrier_id"] == carrier)
        features = {"count": len, "own_fee": lambda rows: own(rows)["collection_fee_minor"],
                    "own_home": lambda rows: own(rows)["home_delta_minor"],
                    "own_economy": lambda rows: "economy" in own(rows)["tiers"],
                    "own_place": lambda rows: [row["carrier_id"] for row in rows].index(carrier),
                    "others_fee": lambda rows: sum(row["collection_fee_minor"] for row in rows if row is not own(rows)),
                    "express_count": lambda rows: sum("express" in row["tiers"] for row in rows),
                    "shown_count": lambda rows: len(menus.shown(place.menu, rows)),
                    "has_first_carrier": lambda rows: any(row["carrier_id"] == self.carriers[0] for row in rows)}
        for name, feature in features.items():
            with self.subTest(feature=name):
                mine, theirs = [feature(rows) for rows in planned], [feature(rows) for rows in accepted]
                error = lambda values: (sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values) ** 2) ** .5
                self.assertLess(abs(sum(mine) / len(mine) - sum(theirs) / len(theirs)),
                                4.5 * (error(mine) ** 2 + error(theirs) ** 2) ** .5 + 1e-9)

    def test_steered_worlds_show_it_through_the_producer_and_the_oracle(self):
        quotes = 0
        for index, requirement in enumerate(self.requirements()):
            with self.subTest(requirement=requirement):
                world, found, record = policies.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))
                rid, clause = requirement["retailer_id"], requirement["shown"]
                shown = {row["carrier_id"] for row in found["shown"]}
                self.assertLessEqual(set(clause.get("carriers", {}).get("include", [])), shown)
                self.assertFalse(set(clause.get("carriers", {}).get("exclude", [])) & shown)
                self.assertTrue(record["probability_is_estimated"])
                self.assertEqual(record["proposals"], policies.PROPOSALS)
                # The oracle's own quotes of the retailer's real offers on the steered world.
                if clause.get("destination_type", "home") == "home":
                    for cheapest, carriers in quoted(world, rid, clause.get("delivery_options")):
                        quotes += 1
                        self.assertEqual(carriers, shown)
                        if "cheapest_carrier" in clause:
                            self.assertEqual(cheapest, clause["cheapest_carrier"])
                # Nothing but this retailer's contracts (and dispatch days, where stated) moved.
                before = next(r for r in self.natural["retailers"] if r["retailer_id"] == rid)
                after = next(r for r in world["retailers"] if r["retailer_id"] == rid)
                skip = ("contracts", "source_locations")
                self.assertEqual({k: v for k, v in after.items() if k not in skip}, {k: v for k, v in before.items() if k not in skip})
                self.assertEqual([r for r in world["retailers"] if r is not after],
                                 [r for r in self.natural["retailers"] if r is not before])
                self.assertEqual((world["products"], world["carrier_evidence"], world["seed"]),
                                 (self.natural["products"], self.natural["carrier_evidence"], self.natural["seed"]))
        self.assertGreater(quotes, 20)
        reading = policies.trial(self.natural, self.requirements()[0], self.api)
        for seed in range(900, 904):
            found = blocks.redraw(self.session, self.natural, [reading], seed)
            self.assertEqual((found.identical, found.agreed), ([True], [True]))
            self.assertEqual(found.satisfied, reading.holds(seed))

    def test_the_cheapest_seller_shows_a_badly_rated_carrier_cheapest(self):
        carrier = self.carriers[3]
        seller = {"schema": sellers.VERSION, "cheapest": {"concept_id": SANDALS},
                  "policy": {"shown": {"cheapest_carrier": carrier}}}
        rated = {"schema": ratings.VERSION, "carrier_id": carrier, "average_stars": {"max": 3.8}}
        block = sellers.model(self.natural, seller, self.api)
        self.assertGreater(len(block.alternatives), 3)
        for pair, value in block.alternatives[:3]:
            suited = policies.model(self.natural, sellers.policy(seller, pair[0]), self.api)
            self.assertLess(suited.accepted, policies.PROPOSALS)
            self.assertLess(exp(value), suited.probability)
        winners = Counter()
        for seed in range(4):
            together = {"schema": combined.VERSION, "all": [seller, rated]}
            world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(seed))
            winner = found[0]["retailer_id"]
            winners[winner] += 1
            self.assertEqual(menus.cheapest(found[0]["policy"]["shown"]), carrier)
            self.assertLessEqual(found[1]["average_stars"], 3.8)
            self.assertTrue(all(cheapest == carrier for cheapest, _ in quoted(world, winner)))
            self.assertTrue(sellers.satisfied(world, seller, self.api) and ratings.satisfied(world, rated, self.api))
        self.assertGreater(len(winners), 1)
        self.unwaived(seller, rated, block)
        policy = {"schema": policies.VERSION, "retailer_id": sorted({pair[0] for pair, _ in block.alternatives})[0],
                  "shown": {"cheapest_carrier": carrier}}
        with self.assertRaises(blocks.Coupled):
            combined.prepare(self.natural, {"schema": combined.VERSION, "all": [seller, policy]}, self.api, Random(0))

    def unwaived(self, seller, rated, plain):
        """The same with no free shipping at the winner: what the menu costs is what every one of its offers is quoted."""
        seller = {**seller, "free_shipping": False}
        block = sellers.model(self.natural, seller, self.api)
        self.assertLess(block.probability, plain.probability)
        offered = lambda world, rid: next(r for r in world["retailers"] if r["retailer_id"] == rid)["free_shipping_threshold_minor"]
        natural = {pair[0]: offered(self.natural, pair[0]) for pair, _ in block.alternatives}
        self.assertTrue(any(value is not None for value in natural.values()))
        trials = 1500
        seen = sum(sellers.empirical(self.natural, seller, self.api, trials, 10 ** 6).values())
        share = block.probability
        self.assertLess(abs(seen / trials - share), 4.5 * (share * (1 - share) / trials) ** .5 + .25 * share)
        for seed in range(4):
            world, found, record = combined.steer(self.session, self.natural, self.opened,
                                                  {"schema": combined.VERSION, "all": [seller, rated]}, self.api, Random(seed))
            winner = found[0]["retailer_id"]
            self.assertIsNone(offered(world, winner))
            self.assertIsNone(found[0]["free_shipping"]["advertised_threshold_minor"])
            quotes = quoted(world, winner)
            # Nothing is waived, so every deliverable offer of the winner is among the quotes read.
            self.assertTrue(quotes and all(cheapest == seller["policy"]["shown"]["cheapest_carrier"] for cheapest, _ in quotes))
            for retailer in world["retailers"]:
                if retailer["retailer_id"] != winner:
                    self.assertEqual(retailer["free_shipping_threshold_minor"], offered(self.natural, retailer["retailer_id"]))
        reading = sellers.trial(self.natural, seller, self.api)
        for seed in range(900, 903):
            found = blocks.redraw(self.session, self.natural, [reading], seed)
            self.assertEqual((found.identical, found.agreed), ([True], [True]))
            self.assertEqual(found.satisfied, reading.holds(seed))
        for bad in (True, None, "none", 0):
            with self.assertRaises(ValueError):
                sellers.model(self.natural, {**seller, "free_shipping": bad}, self.api)


if __name__ == "__main__":
    unittest.main()
