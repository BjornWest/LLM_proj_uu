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

    def test_the_bounds_hold_for_any_contracts(self):
        """The block is drawn with the winner charged nothing and its other products the ceiling; whatever contracts
        are drawn, what they charge lies between, at every price and for every location, waived or not."""
        need = self.need(self.likely[0])
        whole = couriers.model(self.natural, need, self.api)
        found, retailer = whole.site, self.likely[0][0]
        bounds = found.shared.scope.delivered[retailer]
        self.assertEqual((bounds.lowest(1), bounds.lowest(10 ** 7), bounds.highest(1), bounds.highest(10 ** 7), bounds.uniform),
                         (0, 0, found.ceiling, found.ceiling, False))
        self.assertTrue(whole.block.bounded)
        designated = whole.block.places[self.likely[0]]
        self.assertEqual(designated.best("sku", 50000), 50000)
        self.assertEqual(designated.rank("sku", 50000), 50000 + found.ceiling)
        rng, seen = Random(9), set()
        free = policies.model(self.natural, {"schema": policies.VERSION, "retailer_id": retailer, "carrier_count": {"min": 0}}, self.api)
        for block in (whole.contracts, free):
            for _ in range(400):
                charge = menus.delivery(found.place.menu, policies.draw(block, rng)[1])
                if charge is not None:
                    seen.add(charge.highest(1))
                    self.assertTrue(0 <= charge.lowest(1) <= charge.highest(1) <= found.ceiling)
                    self.assertLessEqual(charge.highest(10 ** 7), found.ceiling)
        # The ceiling is reached within a few thousand of what contracts do charge, not far above it.
        self.assertGreater(len(seen), 5)
        self.assertGreater(max(seen), found.ceiling - 5000)

    def test_the_paying_carrier_is_the_oracles_also_under_a_waiver(self):
        """Per offer, the carrier of the strictly cheapest home option the oracle quotes, with and without a waiver."""
        from environments.website_world import delivery_options
        from experiments.accepted_catalog_commerce import basket_quote, delivery_admission
        seen = {"waived_tie": 0, "waived_one": 0, "paid": 0}
        for retailer in self.natural["retailers"]:
            for limit in (None, 1):
                world = deepcopy(self.natural)
                patched = next(r for r in world["retailers"] if r["retailer_id"] == retailer["retailer_id"])
                patched["free_shipping_threshold_minor"] = limit
                place = menus.oracle(world, retailer["retailer_id"], {}, self.api)
                charge = menus.delivery(place)
                if charge is None:
                    continue
                settings = delivery_options.options({"enabled": True, "admission_plan": menus.VERSION})
                plan = basket_quote.make_plan(world)
                sidecar = delivery_admission.make_plan(world, plan, seed=world["seed"], plan_version=menus.VERSION,
                                                       count_weights=delivery_options.producer_weights(settings))
                oracle = delivery_admission.Oracle(world, plan, sidecar)
                ships = {s["source_id"] for s in patched["source_locations"] if s["shipping_enabled"]}
                for offer in [o for o in patched["offers"] if o["sku_id"] in self.skus][:6]:
                    quote = oracle.quote(world, retailer["retailer_id"], [{"line_id": "a", "offer_id": offer["offer_id"], "quantity": 1}],
                                         plan=plan)
                    choices = {row["choice_id"]: row for row in quote["delivery_choices"]}
                    best = {}
                    for option in quote["options"]:
                        choice = choices[option["selection"]["a"]]
                        if choice["destination_type"] == "home":
                            best[choice["carrier_id"]] = min(best.get(choice["carrier_id"], option["shipping_minor"]), option["shipping_minor"])
                    if not best:
                        continue
                    lowest = sorted(best.values())
                    expected = None if len(lowest) > 1 and lowest[0] == lowest[1] else min(best, key=best.get)
                    holding = [name for name, quantity in offer["stock_by_source"].items() if quantity and name in ships]
                    found = charge.carrier(offer["price_minor"], holding or [charge.warehouse])
                    self.assertEqual(found, expected, (retailer["retailer_id"], limit, offer["offer_id"]))
                    self.assertEqual(charge.at(offer["price_minor"], holding or [charge.warehouse]), lowest[0])
                    seen["paid" if limit is None else "waived_tie" if expected is None else "waived_one"] += 1
        self.assertTrue(all(count > 3 for count in seen.values()), seen)

    def test_a_waived_winner_with_two_carriers_shown_does_not_hold(self):
        need = self.need(self.likely[0])
        world = deepcopy(self.natural)
        next(r for r in world["retailers"] if r["retailer_id"] == self.likely[0][0])["free_shipping_threshold_minor"] = 1
        # The edited copy keeps the world's id, which the estimates of this process are kept by.
        saved = dict(couriers.ESTIMATES)
        couriers.ESTIMATES.clear()
        try:
            whole, reading = couriers.model(world, need, self.api), couriers.trial(world, need, self.api)
        finally:
            couriers.ESTIMATES.clear()
            couriers.ESTIMATES.update(saved)
        held = [reading.reading(seed) for seed in range(10 ** 6, 10 ** 6 + 2500) if reading.holds(seed)]
        chance, trials = whole.probability, 2500
        self.assertGreater(len(held), 30)
        self.assertLess(abs(len(held) / trials - chance), 4.5 * (chance * (1 - chance) / trials + whole.error ** 2) ** .5)
        # Under a waiver the carrier's option must still be strictly the cheapest of those shown, where every route
        # that is not express costs nothing. Without a waiver other carriers' ordinary routes are shown beside it.
        place, warehouse = whole.site.place.menu, whole.site.shared.scope.delivered[self.likely[0][0]].warehouse
        ordinary = lambda contracts: {row["carrier_id"] for row in menus.shown(place, contracts) if row["tier"] != "express"}
        for contracts, _ in held:
            self.assertLessEqual(ordinary(contracts), {need["carrier_id"]})
            self.assertEqual(menus.delivery(place, contracts).carrier(10 ** 6, [warehouse]), need["carrier_id"])
        natural = couriers.trial(self.natural, need, self.api)
        beside = [natural.reading(seed)[0] for seed in range(10 ** 6, 10 ** 6 + 2500) if natural.holds(seed)]
        self.assertTrue(any(len(ordinary(contracts)) > 1 for contracts in beside))

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

    def test_a_threshold_the_winning_price_reaches_naturally(self):
        """Astra v30: a retailer whose threshold a winning price reaches, with two carriers shown. Every plan must
        pass the native check, whose winning rows are the carrier's alone; and the record's totals are the world's."""
        base = {"concept_id": SHOES, "delivered": {},
                "predicates": [{"field": "product.facts.reference_mass_g", "operator": "eq", "value": 317, "unit": "g"}]}
        need = {"schema": couriers.VERSION, "carrier_id": self.carriers[2],
                "cheapest": {**base, "retailer_ids": ["travel-02"], "product_id": "footwear-brand-06/footwear.walking_shoes/11"}}
        retailer = next(r for r in self.natural["retailers"] if r["retailer_id"] == "travel-02")
        self.assertEqual(retailer["free_shipping_threshold_minor"], 75000)
        whole = couriers.model(self.natural, need, self.api)
        found, waived, tied = whole.site, 0, 0
        for seed in range(32):
            step = couriers.prepare(self.natural, need, self.api, Random(seed))
            if seed < 6:
                world, seen, record = blocks.steer(self.session, self.natural, self.opened, step, self.api)
                rows = seen["reference"]["winners"]
                self.assertEqual({row["delivery"]["carrier_id"] for row in rows}, {need["carrier_id"]})
                self.assertEqual(record["winning_total_minor"], seen["total_minor"])
                totals = {}
                for row in seen["reference"]["candidates"]:
                    pair = (row["retailer_id"], row["product_id"])
                    totals[pair] = min(totals.get(pair, row["option"]["total_minor"]), row["option"]["total_minor"])
                for row in record["restocked"]:
                    self.assertEqual(row["cheapest_available_minor"], totals.get((row["retailer_id"], row["product_id"])))
                waived += seen["total_minor"] == rows[0]["price_minor"]
        # The broader event, without the paying carrier, does happen here: redraws where the pair wins with a tie of carriers.
        reading = couriers.trial(self.natural, need, self.api)
        trials, hits = 3000, 0
        for seed in range(10 ** 6, 10 ** 6 + trials):
            contracts, leaves = reading.reading(seed)
            scope = couriers.charged(found, contracts)
            wins = scope is not None and policies.displayed(found.place, contracts) and cheapest.judged(leaves, found.need, scope) is not None
            holds = reading.holds(seed)
            self.assertLessEqual(holds, wins)
            hits, tied = hits + holds, tied + (wins and not holds)
        self.assertGreater(tied, 5)
        chance = whole.probability
        self.assertLess(abs(hits / trials - chance), 4.5 * (chance * (1 - chance) / trials + whole.error ** 2) ** .5)

    def test_a_winner_that_charges_by_location_and_one_that_does_not(self):
        split = self.split()
        self.assertGreaterEqual(len(split), 2)
        pairs = [next(pair for pair in self.likely if pair[0] in split), next(pair for pair in self.likely if pair[0] not in split)]
        self.probabilities(pairs, trials=2000)
        self.steered(pairs)


if __name__ == "__main__":
    unittest.main()
