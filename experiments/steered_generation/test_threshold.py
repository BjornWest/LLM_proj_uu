"""Tests of the free-shipping threshold block against the real producer, with stand-in products.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_threshold.py
"""
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from environments.website_world import catalog_checkout_domain, catalog_shipping_claim_task
from experiments.accepted_catalog_commerce import basket_quote
from experiments.accepted_catalog_commerce.prepared_quote import prepare

from experiments.steered_generation import blocks, combined, price_bounds, prices, run, stock, streams, threshold
from experiments.steered_generation.test_combined import BOTH, PLAIN, SHIRTS, SHOES, SMALL, TwoConcepts
from experiments.steered_generation.test_stock import stand_in


def shippable(seed, concept_id, brand, product_id, *, earlier, review_count):
    """The stand-in product with what the native basket quote reads of a product."""
    product = stand_in(seed, concept_id, brand, product_id, earlier=earlier, review_count=review_count)
    product["commerce"] = {"shipping_class": "regular", "classification_basis": "closed_ordinary_parcel_concept_slice_v1"}
    product["public"].update(facts={}, brand_id=brand["brand_id"])
    return product


class ThresholdTests(TwoConcepts):
    product = staticmethod(shippable)

    def need(self, rid, test, concept=SHOES, quantity=1, **stated):
        return {"schema": threshold.VERSION, "retailer_id": rid, "sku_id": self.offer(rid, concept)["sku_id"],
                "quantity": quantity, "subtotal_test": test, **stated}

    def requirements(self):
        price = self.offer(BOTH, SHOES)["price_trace"]["reference_minor"]
        return [self.need(SMALL, "no_threshold"), self.need(BOTH, "meets_threshold"), self.need(BOTH, "below_threshold"),
                # Two pairs just reach a threshold, and three just miss the next one.
                self.need(BOTH, "meets_threshold", quantity=2, gap_minor={"max": price}),
                self.need(PLAIN, "below_threshold", SHIRTS, quantity=3, gap_minor={"max": 15000})]

    def test_probability_matches_the_producers_draws_under_other_seeds(self):
        trials, total = 20000, {}
        for requirement in self.requirements():
            with self.subTest(requirement=requirement):
                block = threshold.model(self.natural, requirement, self.api)
                hits, chance = sum(threshold.empirical(self.natural, requirement, self.api, trials, 10 ** 6).values()), block.probability
                self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5)
                self.assertGreater(hits, 100 if chance > .01 else 0)
        # The three tests without a gap are the whole of what can happen to one basket.
        for test in threshold.TESTS:
            total[test] = threshold.model(self.natural, self.need(BOTH, test), self.api).probability
        self.assertAlmostEqual(sum(total.values()), 1, places=8)
        policy = self.natural["shipping_policy"]["free_shipping_threshold"]
        self.assertAlmostEqual(total["no_threshold"], 1 - policy["enabled_probability_by_profile"][
            threshold.PROFILES[self.retailer(BOTH)["scale"]]], places=12)

    def test_steered_worlds_hold_through_the_producer_and_the_native_oracle(self):
        for index, requirement in enumerate(self.requirements()):
            with self.subTest(requirement=requirement):
                world, found, record = threshold.steer(self.session, self.natural, self.opened, requirement,
                                                       self.api, Random(index))
                rid = requirement["retailer_id"]
                retailer = next(r for r in world["retailers"] if r["retailer_id"] == rid)
                offer = next(o for o in retailer["offers"] if o["sku_id"] == requirement["sku_id"])
                self.assertEqual((found["advertised_threshold_minor"], found["unit_price_minor"]),
                                 (retailer["free_shipping_threshold_minor"], offer["price_minor"]))
                self.assertEqual(found["subtotal_test"], requirement["subtotal_test"])
                if "gap_minor" in requirement:
                    self.assertLessEqual(abs(found["subtotal_minor"] - found["advertised_threshold_minor"]),
                                         requirement["gap_minor"]["max"])
                self.assertEqual(record["probability_given_upstream"],
                                 threshold.model(self.natural, requirement, self.api).probability)
                self.assertEqual(world["status"], streams.STATUS)
                writes = threshold.footprint(self.natural, requirement, self.api).writes
                self.assertEqual(len(writes), 1 if requirement["subtotal_test"] == "no_threshold" else 2)
                self.assertEqual(blocks.background(world, writes), blocks.background(self.natural, writes))
                self.assertTrue(threshold.satisfied(world, requirement, self.api))
                # The native shipping-claim oracle on the steered world, for the same offer and quantity.
                retailers = sorted(world["retailers"], key=lambda r: r["retailer_id"])
                spec = {"kind": catalog_shipping_claim_task.KIND, "quantity": requirement["quantity"],
                        "retailer_index": [r["retailer_id"] for r in retailers].index(rid),
                        "offer_index": sorted(o["offer_id"] for o in retailer["offers"]).index(offer["offer_id"])}
                quote = prepare(world, plan=basket_quote.make_plan(world))
                domain = catalog_checkout_domain.make(world)
                task = catalog_shipping_claim_task.make(world, spec, quote_context=quote, checkout_domain=domain)
                reference = catalog_shipping_claim_task.reference(world, task, quote_context=quote, checkout_domain=domain)
                self.assertEqual(reference["subject"]["offer_id"], offer["offer_id"])
                self.assertEqual((reference["subtotal_test"], reference["subtotal_minor"], reference["advertised_threshold_minor"]),
                                 (requirement["subtotal_test"], found["subtotal_minor"], found["advertised_threshold_minor"]))
        self.assertEqual(self.natural, self.frozen)

    def test_a_subtotal_equal_to_the_threshold_meets_it(self):
        stated = self.need(BOTH, "meets_threshold")
        self.assertTrue(threshold.holds(stated, 20000, 20000))
        self.assertFalse(threshold.holds(stated, 20000, 19999))
        self.assertFalse(threshold.holds(self.need(BOTH, "below_threshold"), 20000, 20000))
        self.assertTrue(threshold.holds(self.need(BOTH, "below_threshold"), 20000, 19999))
        self.assertTrue(threshold.holds(self.need(BOTH, "meets_threshold", quantity=2), 40000, 20000))
        # Through the producer and the native oracle: some basket in this world can land exactly on a threshold.
        exact = None
        for retailer in self.natural["retailers"]:
            for offer in retailer["offers"][:4]:
                for quantity in (1, 2, 3, 4, 5):
                    candidate = {"schema": threshold.VERSION, "retailer_id": retailer["retailer_id"], "sku_id": offer["sku_id"],
                                 "quantity": quantity, "subtotal_test": "meets_threshold", "gap_minor": {"max": 0}}
                    try:
                        exact = exact or (threshold.model(self.natural, candidate, self.api) and candidate)
                    except prices.ZeroMass:
                        pass
        self.assertIsNotNone(exact)
        world, found, _ = threshold.steer(self.session, self.natural, self.opened, exact, self.api, Random(0))
        self.assertEqual(found["subtotal_minor"], found["advertised_threshold_minor"])
        retailer = next(r for r in world["retailers"] if r["retailer_id"] == exact["retailer_id"])
        spec = {"kind": catalog_shipping_claim_task.KIND, "quantity": exact["quantity"],
                "retailer_index": sorted(r["retailer_id"] for r in world["retailers"]).index(exact["retailer_id"]),
                "offer_index": sorted(o["offer_id"] for o in retailer["offers"]).index(found["offer_id"])}
        quote, domain = prepare(world, plan=basket_quote.make_plan(world)), catalog_checkout_domain.make(world)
        task = catalog_shipping_claim_task.make(world, spec, quote_context=quote, checkout_domain=domain)
        reference = catalog_shipping_claim_task.reference(world, task, quote_context=quote, checkout_domain=domain)
        self.assertEqual((reference["subtotal_test"], reference["subtotal_minor"]),
                         ("meets_threshold", reference["advertised_threshold_minor"]))
        below = self.need(BOTH, "below_threshold", gap_minor={"max": 0})
        with self.assertRaises(prices.ZeroMass):
            threshold.model(self.natural, below, self.api)

    def test_readings_equal_the_producer_under_other_seeds(self):
        for requirement in self.requirements()[:3]:
            reading = threshold.trial(self.natural, requirement, self.api)
            for seed in range(900, 904):
                found = blocks.redraw(self.session, self.natural, [reading], seed)
                self.assertEqual((found.identical, found.agreed), ([True], [True]))

    def test_it_combines_with_what_it_does_not_decide(self):
        just_misses = self.need(BOTH, "below_threshold")
        held = {"schema": stock.VERSION, "retailer_id": BOTH, "sku_id": just_misses["sku_id"], "availability": "in_stock"}
        other = {"schema": price_bounds.VERSION, "retailer_id": PLAIN, "sku_id": self.offer(PLAIN, SHOES)["sku_id"],
                 "price_minor": {"min": 0}}
        requirement = self.together(just_misses, held, other)
        world, found, record = combined.steer(self.session, self.natural, self.opened, requirement, self.api, Random(2))
        self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in requirement["all"]))
        same_price = {"schema": price_bounds.VERSION, "retailer_id": BOTH, "sku_id": just_misses["sku_id"],
                      "price_minor": {"min": 0}}
        for parts in ((just_misses, same_price), (just_misses, self.need(BOTH, "no_threshold", SHIRTS)),
                      (self.need(BOTH, "meets_threshold", SHIRTS), just_misses)):
            with self.subTest(parts=parts), self.assertRaises(blocks.Coupled) as caught:
                combined.prepare(self.natural, self.together(*parts), self.api, Random(0))
            self.assertIn(BOTH, str(caught.exception))
        # Without a threshold the price is not part of the block.
        combined.prepare(self.natural, self.together(self.need(BOTH, "no_threshold"), same_price), self.api, Random(0))

    def test_the_runner_samples_and_checks_a_threshold_requirement(self):
        args = SimpleNamespace(samples=2, producer_redraws=2, validate_trials=2000)
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.threshold_case(args, self.session, self.natural, self.opened, self.api, self.need(BOTH, "below_threshold"),
                               case, lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], len(case["samples"])), ("sampled", 2))
        self.assertTrue(all(sample["subtotal_test"] == "below_threshold" for sample in case["samples"]))
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertEqual(case["producer_redraws"]["identical_to_reading"], 2)

    def test_zero_probability_and_bad_requirements(self):
        good = self.need(BOTH, "below_threshold")
        with self.assertRaises(prices.ZeroMass) as caught:
            threshold.model(self.natural, self.need(BOTH, "meets_threshold", gap_minor={"max": 0}, quantity=7), self.api)
        self.assertEqual(caught.exception.reason, "no_outcome")
        with self.assertRaises(prices.ZeroMass):
            threshold.model(self.natural, {**good, "sku_id": self.offer(PLAIN, SHIRTS)["sku_id"], "retailer_id": SMALL}, self.api)
        for bad in ({**good, "quantity": 0}, {**good, "quantity": "2"}, {**good, "subtotal_test": "free"},
                    {**good, "retailer_id": "nobody"}, {**good, "sku_id": "nothing"}, {**good, "gap_minor": {}},
                    {**self.need(BOTH, "no_threshold"), "gap_minor": {"max": 5}}, {**good, "concept_id": SHOES}):
            for call in (threshold.model, threshold.footprint, threshold.trial):
                with self.subTest(bad=bad, call=call), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
