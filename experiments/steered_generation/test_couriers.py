"""Tests of "the cheapest delivered offer comes with this carrier" against the native delivery task and the oracle.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_couriers.py
"""
from copy import deepcopy
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from environments.website_world import basic_offer_task
from experiments.accepted_catalog_commerce import model as commerce, package_export
from experiments.footwear_world_pilot import model as native
from experiments.world_sampling_defaults import model as population

from experiments.steered_generation import (blocks, cheapest, combined, couriers, menus, policies, prices, ratings, run, streams,
                                            threshold)
from experiments.steered_generation.test_delivered import INPUTS, SHOES, SIZE, totals


class Couriers(unittest.TestCase):
    inputs = INPUTS

    @classmethod
    def setUpClass(cls):
        cls.api = SimpleNamespace(basic=basic_offer_task, native=native, population=population,
                                  commerce=commerce, package_export=package_export)
        cls.session = streams.Session(cls.api, cls.inputs)
        cls.natural, cls.opened = cls.session.generate()
        cls.frozen = deepcopy(cls.natural)
        cls.carriers = [row["carrier_id"] for row in cls.natural["address_context"]["carriers"]]
        cls.base = {"concept_id": SHOES, "predicates": SIZE, "delivered": {}}
        frame = cheapest.frame(cls.natural, {"schema": cheapest.VERSION, **cls.base}, cls.api)
        cls.skus, chances = frame.scope.skus, {}
        for pair in sorted(frame.places):
            try:
                chances[pair] = cheapest.model(cls.natural, {"schema": cheapest.VERSION, **cls.base, "retailer_ids": [pair[0]],
                                                             "product_id": pair[1]}, cls.api, frame).probability
            except prices.ZeroMass:
                pass
        cls.likely = sorted(chances, key=chances.get, reverse=True)

    def tearDown(self):
        self.assertEqual(self.natural, self.frozen, "A test changed the natural world")

    def need(self, pair, carrier=2):
        return {"schema": couriers.VERSION, "carrier_id": self.carriers[carrier],
                "cheapest": {**self.base, "retailer_ids": [pair[0]], "product_id": pair[1]}}

    def confirmed(self, world, need):
        """A steered world by the oracle's own quotes: the winner alone is cheapest delivered, with the carrier."""
        pair = (need["cheapest"]["retailer_ids"][0], need["cheapest"]["product_id"])
        quoted, by_pair = totals(world, self.skus), {}
        for (rid, _), (total, product, _) in quoted.items():
            by_pair[(rid, product)] = min(by_pair.get((rid, product), total), total)
        self.assertEqual([found for found in by_pair if by_pair[found] == min(by_pair.values())], [pair])
        place = menus.oracle(world, pair[0], {}, self.api)
        self.assertEqual(menus.cheapest(menus.official(world, place)), need["carrier_id"])
        return by_pair[pair]

    def probabilities(self, pairs, trials=2500):
        for pair in pairs:
            with self.subTest(pair=pair):
                need = self.need(pair)
                block = couriers.model(self.natural, need, self.api)
                self.assertTrue(block.estimated and 0 < block.accepted <= couriers.PROPOSALS)
                hits, chance = couriers.empirical(self.natural, need, self.api, trials, 10 ** 6), block.probability
                self.assertLess(abs(hits / trials - chance), 4.5 * (chance * (1 - chance) / trials + block.error ** 2) ** .5 + 1e-9)
                self.assertEqual(couriers.model(self.natural, need, self.api).probability, chance)
                # The conditions the draws are made under are implied by the requirement, so each is likelier.
                self.assertLessEqual(chance, block.contracts.probability * block.block.probability * (1 + 1e-12))

    def steered(self, pairs):
        for index, pair in enumerate(pairs):
            with self.subTest(pair=pair):
                need = self.need(pair)
                world, found, record = couriers.steer(self.session, self.natural, self.opened, need, self.api, Random(index))
                total = self.confirmed(world, need)
                self.assertEqual((found["total_minor"], record["winning_total_minor"]), (total, total))
                self.assertTrue(all(row["delivery"]["carrier_id"] == need["carrier_id"] for row in found["reference"]["winners"]))
                self.assertTrue(record["probability_is_estimated"])
                for before, after in zip(self.natural["retailers"], world["retailers"]):
                    if after["retailer_id"] != pair[0]:
                        self.assertEqual(after["contracts"], before["contracts"])
                    self.assertEqual((after["free_shipping_threshold_minor"], after["source_locations"]),
                                     (before["free_shipping_threshold_minor"], before["source_locations"]))
                self.assertEqual(world["carrier_evidence"], self.natural["carrier_evidence"])
        reading = couriers.trial(self.natural, self.need(pairs[0]), self.api)
        for seed in range(900, 904):
            found = blocks.redraw(self.session, self.natural, [reading], seed)
            self.assertEqual((found.identical, found.agreed), ([True], [True]))
            self.assertEqual(found.satisfied, reading.holds(seed))


class UniformCharges(Couriers):
    def test_probabilities_match_other_seeds(self):
        self.probabilities(self.likely[:2])

    def test_steered_worlds_are_confirmed_by_the_native_task_and_the_oracle(self):
        self.steered(self.likely[:3])

    def test_samples_match_rejection_sampling(self):
        need = self.need(self.likely[0])
        pair, carrier = self.likely[0], need["carrier_id"]
        reading = couriers.trial(self.natural, need, self.api)
        accepted = [reading.reading(seed) for seed in range(10 ** 6, 10 ** 6 + 7000) if reading.holds(seed)]
        self.assertGreater(len(accepted), 200)
        whole = couriers.model(self.natural, need, self.api)
        found, rng, planned = whole.site, Random(4), []
        while len(planned) < 300:
            contracts = couriers.contracted(found, whole.contracts, rng)[1]
            leaves = cheapest.planned(whole.block, cheapest.sample(whole.block, rng)[1])
            if couriers.met(found, contracts, leaves):
                planned.append((contracts, leaves))

        def features(row):
            contracts, leaves = row
            best, _ = cheapest.lowest(leaves, couriers.charged(found, contracts))
            mine = next(entry for entry in contracts if entry["carrier_id"] == carrier)
            return {"total": best[pair], "margin": sorted(best.values())[1] - best[pair] if len(best) > 1 else 0,
                    "contracts": len(contracts), "pairs_available": len(best),
                    "charge": couriers.charged(found, contracts).delivered[pair[0]].lowest(1),
                    "carrier_fee": mine["collection_fee_minor"] + mine["home_delta_minor"],
                    "carrier_has_economy": "economy" in mine["tiers"]}

        mine, theirs = [features(row) for row in planned], [features(row) for row in accepted]
        for name in mine[0]:
            with self.subTest(feature=name):
                a, b = [float(row[name]) for row in mine], [float(row[name]) for row in theirs]
                error = lambda values: (sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values) ** 2) ** .5
                self.assertLess(abs(sum(a) / len(a) - sum(b) / len(b)), 4.5 * (error(a) ** 2 + error(b) ** 2) ** .5 + 1e-9)
        # A lower charge helps the winner: accepted contracts are cheaper than contracts that only show the carrier.
        rng, shown = Random(5), []
        for _ in range(300):
            contracts = couriers.contracted(found, whole.contracts, rng)[1]
            shown.append(couriers.charged(found, contracts).delivered[pair[0]].lowest(1))
        self.assertLess(sum(row["charge"] for row in mine) / len(mine), sum(shown) / len(shown))

    def test_what_it_reads_and_combines_with(self):
        need = self.need(self.likely[0])
        winner = self.likely[0][0]
        declared = couriers.footprint(self.natural, need, self.api)
        self.assertIn(("contracts", winner, ""), declared.writes)
        self.assertIn(("threshold", winner, ""), declared.reads)
        others = sorted({pair[0] for pair in self.likely} - {winner})
        self.assertLessEqual({(kind, rid, "") for rid in others for kind in ("contracts", "threshold")}, declared.reads)
        self.assertFalse(declared.reads & declared.writes)
        step = couriers.prepare(self.natural, need, self.api, Random(0))
        self.assertEqual((step.writes, step.reads, step.estimated), (declared.writes, declared.reads, True))
        offer = next(r for r in self.natural["retailers"] if r["retailer_id"] == winner)["offers"][0]
        for other in ({"schema": policies.VERSION, "retailer_id": others[0], "express": True},
                      {"schema": policies.VERSION, "retailer_id": winner, "economy": True},
                      {"schema": threshold.VERSION, "retailer_id": winner, "sku_id": offer["sku_id"], "quantity": 1,
                       "subtotal_test": threshold.TESTS[0]},
                      {"schema": cheapest.VERSION, "concept_id": SHOES, "retailer_ids": [winner], "product_id": self.likely[0][1]}):
            with self.subTest(other=other), self.assertRaises(blocks.Coupled):
                combined.prepare(self.natural, {"schema": combined.VERSION, "all": [need, other]}, self.api, Random(0))
        # The carrier's stars and a retailer's dispatch days are read by nothing here.
        together = {"schema": combined.VERSION, "all": [
            need, {"schema": ratings.VERSION, "carrier_id": need["carrier_id"], "average_stars": {"max": 3.9}},
            {"schema": policies.VERSION, "retailer_id": others[0], "dispatch_days": {"min": 1}}]}
        world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(2))
        self.confirmed(world, need)
        self.assertLessEqual(found[1]["average_stars"], 3.9)
        self.assertTrue(record["probability_is_estimated"])

    def test_refusals_and_the_runner(self):
        good = self.need(self.likely[0])
        ranked = good["cheapest"]
        for bad in ({**good, "carrier_id": "carrier-99"}, {**good, "carrier_id": ""}, {k: v for k, v in good.items() if k != "carrier_id"},
                    {**good, "cheapest": {k: v for k, v in ranked.items() if k != "delivered"}},
                    {**good, "cheapest": {**ranked, "retailer_ids": [self.likely[0][0], self.likely[1][0]]}},
                    {**good, "cheapest": {**ranked, "listed_below": [{"retailer_id": self.likely[1][0], "sku_id": "x"}]}},
                    {**good, "cheapest": {**ranked, "schema": cheapest.VERSION}}, {**good, "extra": 1}, None):
            for call in (couriers.model, couriers.trial, couriers.footprint):
                with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        args = SimpleNamespace(samples=2, producer_redraws=1, validate_trials=1500)
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.courier_case(args, self.session, self.natural, self.opened, self.api, good, case, lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], len(case["samples"]), case["probability_is_estimated"]), ("sampled", 2, True))
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertEqual(case["producer_redraws"]["identical_to_reading"], 1)


class ChargesByLocation(Couriers):
    """A world where two retailers charge more from a far location."""
    inputs = {**INPUTS, "seed": 7}

    def split(self):
        frame = cheapest.frame(self.natural, {"schema": cheapest.VERSION, **self.base}, self.api)
        return [rid for rid, found in sorted(frame.scope.delivered.items()) if not found.uniform]

    def test_a_winner_that_charges_by_location_and_one_that_does_not(self):
        split = self.split()
        self.assertGreaterEqual(len(split), 2)
        pairs = [next(pair for pair in self.likely if pair[0] in split), next(pair for pair in self.likely if pair[0] not in split)]
        self.probabilities(pairs, trials=2000)
        self.steered(pairs)


if __name__ == "__main__":
    unittest.main()
