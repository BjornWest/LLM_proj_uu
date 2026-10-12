"""Tests of the shipping-policy block against the real producer, on a small world of pilot products.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_policies.py
"""
from collections import Counter
from copy import deepcopy
from itertools import combinations, product
from math import comb, prod
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from environments.website_world import basic_offer_task
from experiments.accepted_catalog_commerce import model as commerce, package_export
from experiments.footwear_world_pilot import model as native
from experiments.world_sampling_defaults import model as population

from experiments.steered_generation import blocks, combined, policies, prices, run, stock, streams, threshold

SHOES, SANDALS = "footwear.walking_shoes", "footwear.walking_sandals"
INPUTS = {"seed": 5, "concept_ids": [SHOES, SANDALS], "tasks": [SHOES], "controls": None,
          "city_id": "uppsala", "review_count": 0}


class Policies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = SimpleNamespace(basic=basic_offer_task, native=native, population=population,
                                  commerce=commerce, package_export=package_export)
        cls.session = streams.Session(cls.api, INPUTS)
        cls.natural, cls.opened = cls.session.generate()
        cls.frozen = deepcopy(cls.natural)
        cls.carriers = [row["carrier_id"] for row in cls.natural["address_context"]["carriers"]]
        # One retailer of each scale, with its natural contracts.
        cls.retailers = {scale: next(r for r in cls.natural["retailers"] if r["scale"] == scale)
                         for scale in ("small", "medium", "large")}

    def tearDown(self):
        self.assertEqual(self.natural, self.frozen, "A test changed the natural world")

    def need(self, scale="medium", **stated):
        return {"schema": policies.VERSION, "retailer_id": self.retailers[scale]["retailer_id"], **stated}

    def requirements(self):
        first, second, third = self.carriers[0], self.carriers[3], self.carriers[6]
        return [self.need(express=False), self.need(express=True, economy=False),
                self.need(carriers={"include": [first]}), self.need(carriers={"include": [first, second], "exclude": [third]}),
                self.need("small", carriers={"include": [third]}, carrier_count={"max": 1}),
                self.need(collection_fee_minor={"min": 6900}), self.need(home_fee_minor={"max": 2900}),
                self.need("large", carrier_count={"min": 5}, express=False, economy=False),
                self.need("large", dispatch_days={"min": 2}),
                self.need("small", dispatch_days={"max": 0}, carriers={"exclude": [first, second]},
                          collection_fee_minor={"min": 5900, "max": 6900}, home_fee_minor={"min": 6900})]


class ModelTests(Policies):
    def test_the_reading_is_what_the_producer_recorded(self):
        for retailer in self.natural["retailers"]:
            need = {"schema": policies.VERSION, "retailer_id": retailer["retailer_id"], "express": True,
                    "dispatch_days": {"min": 0}}
            found = policies.trial(self.natural, need, self.api)
            self.assertEqual(found.reading(INPUTS["seed"]), found.recorded(self.natural))
            self.assertEqual(found.recorded(self.natural), (retailer["contracts"], retailer["source_locations"][0]["dispatch_days"]))
            self.assertLessEqual({key for key in found.keys if key in self.opened} , set(self.opened))
            # Every stream the natural pass opened for this retailer's policy is one of the block's.
            place = policies.site(self.natural, need, self.api)
            used = {place.keys.count, place.keys.carriers, place.keys.dispatch} | {
                key for row in retailer["contracts"] for key in (
                    place.keys.tier(row["carrier_id"], "economy"), place.keys.tier(row["carrier_id"], "express"),
                    place.keys.fee(row["carrier_id"]), place.keys.home(row["carrier_id"]))}
            self.assertLessEqual(used, found.keys)
            self.assertLessEqual(used, set(self.opened))

    def test_probabilities_match_enumeration(self):
        """Every carrier set and every combination of contracts for a small retailer, read by `holds`."""
        place = policies.site(self.natural, self.need("small", express=True), self.api)
        kinds = policies.kinds(place)
        self.assertAlmostEqual(sum(kinds.values()), 1, places=12)
        self.assertEqual(len(kinds), 100)
        first, second = self.carriers[0], self.carriers[1]
        needs = [self.need("small", carrier_count={"max": 2}, **stated) for stated in (
            {"express": True}, {"express": False, "economy": True}, {"carriers": {"include": [first]}},
            {"carriers": {"exclude": [first, second]}, "collection_fee_minor": {"max": 4900}},
            {"home_fee_minor": {"min": 4900, "max": 5900}, "economy": False},
            {"carriers": {"include": [first, second]}, "collection_fee_minor": {"min": 5900}, "home_fee_minor": {"max": 6900}})]
        for need in needs:
            with self.subTest(need=need):
                direct = 0
                for count in place.counts:
                    if count > 2:
                        continue
                    for chosen in combinations(self.carriers, count):
                        for drawn in product(kinds.items(), repeat=count):
                            contracts = [{"carrier_id": carrier, "tiers": ["standard", *(["economy"] if kind[0] else []),
                                                                           *(["express"] if kind[1] else [])],
                                          "collection_fee_minor": int(kind[2]), "home_delta_minor": int(kind[3])}
                                         for carrier, (kind, _) in zip(chosen, drawn)]
                            if policies.holds(policies.resolve(need), contracts, 0):
                                direct += prod(share for _, share in drawn) / comb(len(self.carriers), count) / len(place.counts)
                self.assertAlmostEqual(policies.model(self.natural, need, self.api).probability, direct, places=12)

    def test_probabilities_match_other_seeds(self):
        trials = 4000
        for requirement in self.requirements():
            with self.subTest(requirement=requirement):
                chance = policies.model(self.natural, requirement, self.api).probability
                hits = policies.empirical(self.natural, requirement, self.api, trials, 10 ** 6)
                self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5 + 1e-9)
        # Complementary statements add up.
        both = [policies.model(self.natural, self.need(express=side), self.api).probability for side in (True, False)]
        self.assertAlmostEqual(sum(both), 1, places=12)
        self.assertAlmostEqual(policies.model(self.natural, self.need(carrier_count={"min": 0}), self.api).probability, 1, places=12)
        self.assertAlmostEqual(policies.model(self.natural, self.need(dispatch_days={"min": 0}), self.api).probability, 1, places=12)

    def test_samples_match_rejection_sampling(self):
        requirement = self.need(express=True, collection_fee_minor={"min": 5900}, carriers={"exclude": [self.carriers[2]]})
        reading = policies.trial(self.natural, requirement, self.api)
        accepted = [reading.reading(seed)[0] for seed in range(10 ** 6, 10 ** 6 + 30000) if reading.holds(seed)]
        rng, sampled = Random(11), []
        for _ in range(600):
            step = policies.prepare(self.natural, requirement, self.api, rng)
            names = step.script[self.retailers["medium"]["retailer_id"] + "/carriers"][0][1]
            self.assertEqual(len(names), len(set(names)))
            sampled.append(step)
        self.assertGreater(len(accepted), 1500)
        planned = []
        for step in sampled:
            place = policies.site(self.natural, requirement, self.api)
            order = [self.carriers[int(name.split("-")[1])] for name in step.script[place.keys.carriers][0][1]]
            planned.append([{"carrier_id": carrier,
                             "economy": step.script[place.keys.tier(carrier, "economy")][0][1] == 0.0,
                             "express": step.script[place.keys.tier(carrier, "express")][0][1] == 0.0,
                             "collection_fee_minor": int(step.script[place.keys.fee(carrier)][0][1]),
                             "home_delta_minor": int(step.script[place.keys.home(carrier)][0][1])} for carrier in order])
            self.assertEqual(step.script[place.keys.count], [("randint", len(order))])
        natural = [[{"carrier_id": row["carrier_id"], "economy": "economy" in row["tiers"], "express": "express" in row["tiers"],
                     "collection_fee_minor": row["collection_fee_minor"], "home_delta_minor": row["home_delta_minor"]}
                    for row in contracts] for contracts in accepted]
        features = {
            "count": len, "express": lambda rows: sum(row["express"] for row in rows),
            "economy": lambda rows: sum(row["economy"] for row in rows),
            "first_express": lambda rows: rows[0]["express"], "last_fee": lambda rows: rows[-1]["collection_fee_minor"],
            "fees": lambda rows: sum(row["collection_fee_minor"] for row in rows),
            "lowest_fee": lambda rows: min(row["collection_fee_minor"] for row in rows),
            "home": lambda rows: sum(row["home_delta_minor"] for row in rows),
            "has_first_carrier": lambda rows: any(row["carrier_id"] == self.carriers[0] for row in rows),
            "first_is_last_carrier": lambda rows: rows[0]["carrier_id"] == self.carriers[-1]}
        for name, feature in features.items():
            with self.subTest(feature=name):
                mine, theirs = [feature(rows) for rows in planned], [feature(rows) for rows in natural]
                spread = lambda values: (sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values) ** 2) ** .5
                self.assertLess(abs(sum(mine) / len(mine) - sum(theirs) / len(theirs)),
                                4.5 * (spread(mine) ** 2 + spread(theirs) ** 2) ** .5 + 1e-9)
        self.assertFalse(any(row["carrier_id"] == self.carriers[2] for rows in planned for row in rows))

    def test_zero_probability_and_bad_requirements(self):
        many = self.carriers[:5]
        for impossible in (self.need("small", carriers={"include": many[:4]}), self.need(carrier_count={"min": 9}),
                           self.need(carriers={"exclude": self.carriers}), self.need(collection_fee_minor={"max": 3800}),
                           self.need(home_fee_minor={"min": 9901}), self.need(dispatch_days={"min": 99}),
                           self.need("small", carrier_count={"min": 3}, carriers={"exclude": self.carriers[:6]})):
            with self.subTest(impossible=impossible), self.assertRaises(prices.ZeroMass):
                policies.model(self.natural, impossible, self.api)
        good = self.need(express=True)
        for bad in ({**good, "retailer_id": "nothing"}, {k: v for k, v in good.items() if k != "express"},
                    {**good, "express": 1}, {**good, "carriers": {}}, {**good, "carriers": {"include": ["carrier-99"]}},
                    {**good, "carriers": {"include": [self.carriers[0]], "exclude": [self.carriers[0]]}},
                    {**good, "carriers": {"only": [self.carriers[0]]}}, {**good, "carrier_count": {"min": 3, "max": 2}},
                    {**good, "collection_fee_minor": {"min": 49.5}}, {**good, "home_fee_minor": {}},
                    {**good, "dispatch_days": {"min": -1}}, {**good, "sku_id": "x"}, None):
            for call in (policies.model, policies.trial, lambda *a: policies.prepare(*a, Random(0))):
                with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        other = deepcopy(self.natural)
        other["provenance"]["plan_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            policies.model(other, good, self.api)
        # A planned sample must be an ordered sample the producer's draw could have returned.
        place = policies.site(self.natural, good, self.api)
        for planned in (["carrier-0", "carrier-0"], ["carrier-0"], ["carrier-9", "carrier-1"], ("carrier-0", "carrier-1")):
            with self.subTest(planned=planned), self.assertRaises((streams.OutOfSupport, streams.PlanMismatch)):
                self.session.generate({place.keys.count: [("randint", 2)], place.keys.carriers: [("sample", planned)]})


class ProducerTests(Policies):
    def test_steered_worlds_hold_through_the_producer(self):
        for index, requirement in enumerate(self.requirements()):
            with self.subTest(requirement=requirement):
                world, found, record = policies.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))
                retailer = next(r for r in world["retailers"] if r["retailer_id"] == requirement["retailer_id"])
                before = next(r for r in self.natural["retailers"] if r["retailer_id"] == requirement["retailer_id"])
                self.assertTrue(policies.holds(policies.resolve(requirement), retailer["contracts"],
                                               retailer["source_locations"][0]["dispatch_days"]))
                self.assertEqual((found["contracts"], found["warehouse_dispatch_days"]),
                                 (retailer["contracts"], retailer["source_locations"][0]["dispatch_days"]))
                self.assertEqual(world["status"], streams.STATUS)
                about = policies.CONTRACTS & set(requirement)
                # Only what the requirement is about moved: the contracts, the warehouse's dispatch days, or both.
                if not about:
                    self.assertEqual(retailer["contracts"], before["contracts"])
                if "dispatch_days" not in requirement:
                    self.assertEqual(retailer["source_locations"], before["source_locations"])
                skip = ("contracts", "source_locations")
                self.assertEqual({k: v for k, v in retailer.items() if k not in skip}, {k: v for k, v in before.items() if k not in skip})
                self.assertEqual([row for row in retailer["source_locations"][1:]], before["source_locations"][1:])
                self.assertEqual([r for r in world["retailers"] if r is not retailer],
                                 [r for r in self.natural["retailers"] if r is not before])
                self.assertEqual((world["products"], world["carrier_evidence"]),
                                 (self.natural["products"], self.natural["carrier_evidence"]))
                # The contracts are ones the producer's validators take: known carriers, standard first, tabled fees.
                for row in retailer["contracts"]:
                    self.assertIn(row["carrier_id"], self.carriers)
                    self.assertEqual(row["tiers"][0], "standard")
                    self.assertIn(str(row["collection_fee_minor"]), world["shipping_policy"][
                        "retailer_carrier_standard_collection_base_fee_minor_probabilities"])
                self.assertEqual(len({row["carrier_id"] for row in retailer["contracts"]}), len(retailer["contracts"]))
        self.assertEqual(self.session.generate()[0]["world_id"], self.natural["world_id"])

    def test_repeated_samples_differ_and_redraws_equal_the_reading(self):
        requirement = self.need(express=True)
        worlds = [policies.steer(self.session, self.natural, self.opened, requirement, self.api, Random(seed))[0]
                  for seed in range(6)]
        self.assertGreater(len({world["world_id"] for world in worlds}), 3)
        for requirement in (self.requirements()[1], self.requirements()[-1]):
            reading = policies.trial(self.natural, requirement, self.api)
            for seed in range(900, 906):
                found = blocks.redraw(self.session, self.natural, [reading], seed)
                self.assertEqual((found.identical, found.agreed), ([True], [True]))
                self.assertEqual(found.satisfied, reading.holds(seed))

    def test_it_combines_with_other_requirements(self):
        retailer = self.retailers["medium"]
        policy = self.need(express=False, carriers={"include": [self.carriers[4]]})
        other = self.need("large", dispatch_days={"min": 2})
        offer = retailer["offers"][0]
        held = {"schema": stock.VERSION, "retailer_id": retailer["retailer_id"], "sku_id": offer["sku_id"],
                "availability": "in_stock"}
        free = {"schema": threshold.VERSION, "retailer_id": retailer["retailer_id"], "sku_id": offer["sku_id"],
                "quantity": 1, "subtotal_test": "no_threshold"}
        together = {"schema": combined.VERSION, "all": [policy, other, held, free]}
        world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(4))
        self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in together["all"]))
        self.assertAlmostEqual(record["probability_given_upstream"], prod(
            combined.KINDS[part["schema"]].model(self.natural, part, self.api).probability for part in together["all"]), places=12)
        # A retailer's contracts and its dispatch days are separate; two statements about its contracts are not.
        combined.prepare(self.natural, {"schema": combined.VERSION, "all": [policy, self.need(dispatch_days={"min": 1})]},
                         self.api, Random(0))
        with self.assertRaises(blocks.Coupled):
            combined.prepare(self.natural, {"schema": combined.VERSION, "all": [policy, self.need(economy=True)]},
                             self.api, Random(0))

    def test_the_runner_samples_and_checks_a_policy(self):
        args = SimpleNamespace(samples=2, producer_redraws=2, validate_trials=2000)
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.policy_case(args, self.session, self.natural, self.opened, self.api,
                            self.need(express=False, dispatch_days={"min": 2}), case, lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], len(case["samples"])), ("sampled", 2))
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertEqual(case["producer_redraws"]["identical_to_reading"], 2)
        impossible = {"samples": [], "requirement_sha256": "x"}
        run.policy_case(args, self.session, self.natural, self.opened, self.api, self.need(carrier_count={"min": 9}), impossible, None)
        self.assertEqual(impossible["status"], "zero_probability_given_upstream")


if __name__ == "__main__":
    unittest.main()
