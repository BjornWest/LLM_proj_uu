"""Tests of "the cheapest available offer is at a retailer with this shipping policy" against the real producer.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_sellers.py
"""
from collections import Counter
from copy import deepcopy
from math import exp
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from environments.website_world import basic_offer_task
from experiments.accepted_catalog_commerce import model as commerce, package_export
from experiments.footwear_world_pilot import model as native
from experiments.world_sampling_defaults import model as population

from experiments.steered_generation import blocks, cheapest, combined, policies, prices, run, sellers, streams

SHOES, SANDALS = "footwear.walking_shoes", "footwear.walking_sandals"
INPUTS = {"seed": 5, "concept_ids": [SHOES, SANDALS], "tasks": [SHOES], "controls": None,
          "city_id": "uppsala", "review_count": 0}


class Sellers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = SimpleNamespace(basic=basic_offer_task, native=native, population=population,
                                  commerce=commerce, package_export=package_export)
        cls.session = streams.Session(cls.api, INPUTS)
        cls.natural, cls.opened = cls.session.generate()
        cls.frozen = deepcopy(cls.natural)
        cls.carriers = [row["carrier_id"] for row in cls.natural["address_context"]["carriers"]]

    def tearDown(self):
        self.assertEqual(self.natural, self.frozen, "A test changed the natural world")

    def need(self, concept=SANDALS, **policy):
        return {"schema": sellers.VERSION, "cheapest": {"concept_id": concept}, "policy": policy}

    def requirements(self):
        return [self.need(express=False), self.need(express=True, economy=True),
                self.need(carriers={"include": [self.carriers[2]]}, carrier_count={"max": 1}),
                self.need(SHOES, collection_fee_minor={"min": 6900}, dispatch_days={"min": 2}),
                self.need(SHOES, carriers={"exclude": self.carriers[:5]})]


class SellerTests(Sellers):
    def test_the_alternatives_are_the_winners_times_their_policies(self):
        requirement = self.need(express=False)
        block = sellers.model(self.natural, requirement, self.api)
        shared = cheapest.frame(self.natural, sellers.ranking(requirement), self.api)
        self.assertEqual({pair for pair, _ in block.alternatives} <= set(shared.places), True)
        self.assertGreater(len(block.alternatives), 3)
        for pair, value in block.alternatives:
            win = cheapest.model(self.natural, sellers.ranking(requirement, pair), self.api).probability
            suited = policies.model(self.natural, sellers.policy(requirement, pair[0]), self.api).probability
            self.assertAlmostEqual(exp(value), win * suited, places=12)
        self.assertAlmostEqual(block.probability, sum(exp(value) for _, value in block.alternatives), places=12)
        # With a policy every retailer has, the requirement is that some pair alone is cheapest.
        anyone = sellers.model(self.natural, self.need(carrier_count={"min": 0}), self.api)
        alone = sum(cheapest.model(self.natural, sellers.ranking(requirement, pair), self.api).probability
                    for pair, _ in anyone.alternatives)
        self.assertAlmostEqual(anyone.probability, alone, places=12)
        self.assertLess(block.probability, anyone.probability)

    def test_probabilities_match_other_seeds(self):
        trials = 1200
        for requirement in self.requirements():
            with self.subTest(requirement=requirement):
                block = sellers.model(self.natural, requirement, self.api)
                seen = sellers.empirical(self.natural, requirement, self.api, trials, 10 ** 6)
                hits, chance = sum(seen.values()), block.probability
                self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5 + 1e-9)
                # Which retailer wins, where winners are common enough to count.
                for pair, times in Counter(seen).most_common(2):
                    part = exp(block.log_terms[pair])
                    self.assertLess(abs(times / trials - part), 4.5 * (part * (1 - part) / trials) ** .5 + 1e-9, pair)

    def test_steered_worlds_hold_through_the_producer_and_the_native_oracle(self):
        winners = Counter()
        for index, requirement in enumerate(self.requirements() * 2):
            with self.subTest(requirement=requirement, index=index):
                world, found, record = sellers.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))
                pair = (found["retailer_id"], found["product_id"])
                winners[pair] += 1
                retailer = next(r for r in world["retailers"] if r["retailer_id"] == pair[0])
                self.assertTrue(policies.holds(policies.resolve(sellers.policy(requirement, pair[0])), retailer["contracts"],
                                               retailer["source_locations"][0]["dispatch_days"]))
                # The native oracle's own winner, read here.
                reference = found["cheapest"]["reference"]
                self.assertEqual(record["chosen"]["retailer_id"], pair[0])
                self.assertTrue(cheapest.satisfied(world, sellers.ranking(requirement, pair), self.api))
                self.assertIsNotNone(reference)
                # Every other retailer's policy is the seed's own.
                for before, after in zip(self.natural["retailers"], world["retailers"]):
                    if after["retailer_id"] != pair[0]:
                        self.assertEqual((after["contracts"], after["source_locations"]),
                                         (before["contracts"], before["source_locations"]))
                self.assertEqual((world["products"], world["carrier_evidence"]),
                                 (self.natural["products"], self.natural["carrier_evidence"]))
                self.assertEqual(world["status"], streams.STATUS)
        self.assertGreater(len(winners), 3)
        self.assertEqual(self.session.generate()[0]["world_id"], self.natural["world_id"])

    def test_winners_are_picked_in_proportion(self):
        requirement = self.need(express=False)
        block = sellers.model(self.natural, requirement, self.api)
        rng, seen, trials = Random(7), Counter(), 160
        retailers = sorted({pair[0] for pair, _ in block.alternatives})
        for _ in range(trials):
            # The winner a plan samples is the retailer whose contracts it scripts.
            step = sellers.prepare(self.natural, requirement, self.api, rng)
            chosen = [retailer for retailer in retailers if retailer + "/carrier_count" in step.script]
            self.assertEqual(len(chosen), 1)
            seen[chosen[0]] += 1
        for retailer in retailers:
            chance = sum(exp(value - block.log_probability) for pair, value in block.alternatives if pair[0] == retailer)
            self.assertLess(abs(seen[retailer] / trials - chance), 4.5 * (chance * (1 - chance) / trials) ** .5 + 1 / trials,
                            retailer)
        self.assertGreater(len(seen), 3)

    def test_redraws_combinations_and_refusals(self):
        requirement = self.need(express=False)
        reading = sellers.trial(self.natural, requirement, self.api)
        for seed in range(900, 904):
            found = blocks.redraw(self.session, self.natural, [reading], seed)
            self.assertEqual((found.identical, found.agreed), ([True], [True]))
            self.assertEqual(found.satisfied, reading.holds(seed))
        # Another concept's ranking is a separate thing; the same concept's ranking, or a ranked retailer's policy, is not.
        winner = sellers.model(self.natural, self.need(SHOES, express=False), self.api).alternatives[0][0]
        other = {"schema": cheapest.VERSION, "concept_id": SHOES, "retailer_ids": [winner[0]], "product_id": winner[1]}
        together = {"schema": combined.VERSION, "all": [requirement, other]}
        ranked = {pair[0] for pair in cheapest.frame(self.natural, sellers.ranking(requirement), self.api).places}
        world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(3))
        self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in together["all"]))
        policy = {"schema": policies.VERSION, "retailer_id": sorted(ranked)[0], "express": True}
        with self.assertRaises(blocks.Coupled):
            combined.prepare(self.natural, {"schema": combined.VERSION, "all": [requirement, policy]}, self.api, Random(0))
        with self.assertRaises(blocks.Coupled):
            combined.prepare(self.natural, {"schema": combined.VERSION, "all": [requirement, self.need(economy=True)]},
                             self.api, Random(0))
        with self.assertRaises(prices.ZeroMass):
            sellers.model(self.natural, self.need(carrier_count={"min": 9}), self.api)
        good = self.need(express=False)
        for bad in ({**good, "policy": {}}, {**good, "policy": {"express": 1}}, {**good, "policy": {"retailer_id": "x", "express": True}},
                    {**good, "cheapest": {}}, {**good, "cheapest": {"concept_id": SANDALS, "retailer_ids": ["x"]}},
                    {**good, "cheapest": {"concept_id": "no.such"}}, {k: v for k, v in good.items() if k != "policy"},
                    {**good, "cheapest": {"concept_id": SANDALS, "unknown_field": True}},
                    # A malformed ranking is an error whatever the policy, an impossible one included.
                    {**good, "cheapest": {"concept_id": SANDALS, "unknown_field": True}, "policy": {"carrier_count": {"min": 9}}},
                    {**good, "cheapest": {"concept_id": SANDALS, "availability": "somewhere"}, "policy": {"carrier_count": {"min": 9}}},
                    None):
            for call in (sellers.model, sellers.trial, sellers.footprint, lambda *a: sellers.prepare(*a, Random(0))):
                with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)

    def test_the_runner_samples_and_checks(self):
        args = SimpleNamespace(samples=2, producer_redraws=2, validate_trials=1500)
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.seller_case(args, self.session, self.natural, self.opened, self.api, self.need(express=False), case,
                            lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], len(case["samples"])), ("sampled", 2))
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertEqual(case["producer_redraws"]["identical_to_reading"], 2)


if __name__ == "__main__":
    unittest.main()
