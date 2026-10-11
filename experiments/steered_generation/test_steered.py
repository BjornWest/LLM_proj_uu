"""Steering tests: real pricing function, real oracle, a toy world loop.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_steered.py
The full producer takes about half a minute per world; that path is exercised
by the pinned runner, not here.
"""
from collections import Counter
from copy import deepcopy
from itertools import product as combinations
from random import Random
from types import SimpleNamespace
import unittest

from environments.website_world import basic_offer_task
from experiments.accepted_catalog_commerce import model as commerce
from experiments.footwear_world_pilot import model as native
from experiments.world_requirement_construction import model as edits
from experiments.world_sampling_defaults import model as population

from experiments.steered_generation import prices, streams

CONCEPT = "footwear.walking_shoes"
PRICE = {"reference_match_probability": 0.4, "offset_standard_deviation": 0.1,
         "offset_min": -0.3, "offset_max": 0.3,
         "rounding_bands_sek": [[100, 1], [500, 5], [2000, 10], [10000, 50], [None, 100]]}
ASSORTMENT = {"north": ["shoe", "boot"], "south": ["shoe"], "west": ["shoe", "boot"]}
REFERENCES = {"shoe": (510, {}), "boot": (499, {40: 500, 41: 500})}
# A narrow clamp keeps the toy's price supports small enough to enumerate.
NARROW = {**PRICE, "offset_min": -0.05, "offset_max": 0.05}
INPUTS = {"seed": 5, "concept_ids": [CONCEPT], "tasks": [CONCEPT], "controls": {},
          "city_id": "uppsala", "review_count": 0}


def toy_api(config=PRICE, empty=()):
    """The real pricing function, oracle and stream seam around a tiny world loop."""
    api = SimpleNamespace(basic=basic_offer_task, native=native, population=population, manufactured=[])

    def manufacture(seed, concept_id, brand, product_id, *, earlier, review_count):
        api.manufactured.append(product_id)
        reference, exact = REFERENCES[product_id]
        return {"public": {"product_id": product_id, "concept_id": concept_id, "name": product_id,
                           "reference_price_sek": reference,
                           "skus": [{"sku_id": f"{product_id}-{size}", "product_id": product_id,
                                     **({"reference_price_sek": exact[size]} if size in exact else {})}
                                    for size in (39, 40, 41)]}}

    def generate(seed, *, concept_ids, tasks, controls, city_id, review_count):
        made = []
        for product_id in REFERENCES:
            made.append(api.package_export.sample(seed, CONCEPT, {"brand_id": "b"}, product_id,
                                                  earlier=made, review_count=review_count))
        public = {p["public"]["product_id"]: p["public"] for p in made}
        retailers = []
        for rid, carried in ASSORTMENT.items():
            offers = []
            for pid in carried:
                for sku in public[pid]["skus"]:
                    price, trace = commerce._offer_price(seed, rid, public[pid], sku, config)
                    offers.append({"offer_id": rid + "/" + sku["sku_id"], "product_id": pid, "sku_id": sku["sku_id"],
                                   "price_minor": price, "currency": "SEK", "price_trace": trace,
                                   "stock_by_source": {rid + "-warehouse": 0 if (rid, sku["sku_id"]) in empty else 3},
                                   "supplier_order": {"enabled": False, "wait_days": None, "disclosure": None}})
            retailers.append({"retailer_id": rid, "name": rid.title(), "product_ids": list(carried),
                              "source_locations": [{"source_id": rid + "-warehouse", "shipping_enabled": True}],
                              "offers": offers,
                              "catalog": [{"product_id": pid, "pages": [{"listings": [
                                  {"sku_id": o["sku_id"]} for o in offers if o["product_id"] == pid]}]}
                                  for pid in carried]})
        world = {"schema_version": commerce.VERSION, "seed": seed, "status": edits.SAMPLED_STATUS,
                 "config": {"concept_ids": [CONCEPT], "retailer_price": deepcopy(config)},
                 "products": made, "retailers": retailers, "provenance": {},
                 "limitations": ["Sparse stock is retained; no winner or seed repair."]}
        world["world_id"] = native.digest(world)
        return world

    api.commerce = SimpleNamespace(VERSION=commerce.VERSION, generate=generate, validate=commerce.validate,
                                   _offer_price=commerce._offer_price)
    api.package_export = SimpleNamespace(sample=manufacture)
    return api


def requirement(*retailer_ids, product_id="shoe"):
    return {"schema": edits.VERSION, "kind": edits.KIND, "concept_id": CONCEPT,
            "product_id": product_id, "retailer_ids": list(retailer_ids)}


def price_key(rid, pid):
    return commerce.VERSION + "/" + rid + "/" + pid + "/price"


class StreamTests(unittest.TestCase):
    public = {"product_id": "shoe", "reference_price_sek": 510}

    def price(self, plan):
        with streams.steered(population, plan):
            return [commerce._offer_price(1, "north", self.public, {"sku_id": s}, PRICE) for s in ("a", "b")]

    def test_planned_results_reach_the_real_pricing_function(self):
        natural = self.price({})
        self.assertEqual(self.price({price_key("north", "shoe"): prices.script((False, -3 / 51), PRICE)}),
                         [(48000, {"reference_minor": 51000, "reference_basis": "product",
                                   "matched_reference_draw": False, "offset_draw": -3 / 51})] * 2)
        matched = self.price({price_key("north", "shoe"): prices.script((True, 0), PRICE)})
        self.assertEqual(matched[0][1]["offset_draw"], 0)
        self.assertIs(type(matched[0][1]["offset_draw"]), int)
        self.assertEqual(natural, self.price({}))

    def test_clamped_plan_is_recorded_as_the_bound(self):
        (price, trace), _ = self.price({price_key("north", "shoe"): prices.script((False, 0.3), PRICE)})
        self.assertEqual((price, trace["offset_draw"]), (66000, 0.3))

    def test_plan_that_does_not_match_the_producer_fails(self):
        key = price_key("north", "shoe")
        for plan, error in (({key: [("gauss", 0.1)]}, streams.PlanMismatch),
                            ({key: [("random", 0.999), ("gauss", 0.1), ("gauss", 0.1)]}, streams.PlanMismatch),
                            ({key: [("random", 1.5)]}, streams.OutOfSupport),
                            ({price_key("absent", "shoe"): [("random", 0.0)]}, streams.PlanMismatch)):
            with self.subTest(plan=plan), self.assertRaises(error):
                self.price(plan)
        self.assertEqual(population.stream.__module__, population.__name__)

    def test_supports_of_other_draw_kinds_are_checked(self):
        scripted = streams.Scripted("k", [("randint", 4), ("choices", "full"), ("choice", "x"), ("randint", 9)])
        self.assertEqual(scripted.randint(1, 5), 4)
        self.assertEqual(scripted.choices(["empty", "full"], weights=[0.2, 0.8]), ["full"])
        self.assertEqual(scripted.choice(["x", "y"]), "x")
        with self.assertRaises(streams.OutOfSupport):
            scripted.randint(1, 5)
        with self.assertRaises(streams.OutOfSupport):
            streams.Scripted("k", [("choices", "empty")]).choices(["empty", "full"], weights=[0, 1])
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value), self.assertRaises(streams.OutOfSupport):
                streams.Scripted("k", [("gauss", value)]).gauss(0, 0.1)


class AtomTests(unittest.TestCase):
    def test_masses_sum_to_one(self):
        for config in (PRICE, {**PRICE, "offset_min": 0.05}, {**PRICE, "reference_match_probability": 0},
                       {**PRICE, "reference_match_probability": 1}, {**PRICE, "offset_standard_deviation": 0},
                       {**PRICE, "offset_min": 0.0, "offset_max": 0}):
            for references in ((51000,), (49900, 50000), (9900, 19000, 51000)):
                found = prices.atoms(references, config)
                self.assertAlmostEqual(sum(a[0] for a in found), 1, places=9)
                for atom in found:
                    self.assertTrue(edits._producible(prices.representative(atom), config))

    def test_joint_price_distribution_matches_the_producer_expression(self):
        references, rng, trials = (49900, 50000), Random(3), 200000
        expected = Counter()
        for atom in prices.atoms(references, PRICE):
            draw = prices.representative(atom)
            expected[tuple(native.rounded_price(r * (1 + draw[1]), r, PRICE) for r in references)] += atom[0]
        seen = Counter()
        for _ in range(trials):
            match = rng.random() < PRICE["reference_match_probability"]
            offset = 0 if match else max(PRICE["offset_min"], min(PRICE["offset_max"], rng.gauss(0, PRICE["offset_standard_deviation"])))
            seen[tuple(native.rounded_price(r * (1 + offset), r, PRICE) for r in references)] += 1
        distance = sum(abs(expected[k] - seen[k] / trials) for k in set(expected) | set(seen)) / 2
        self.assertLess(distance, 0.01)

    def test_draw_within_an_interval_keeps_its_prices(self):
        group = [{"price_trace": {"reference_minor": r}} for r in (49900, 50000)]
        rng = Random(1)
        for atom in prices.atoms((49900, 50000), PRICE):
            middle = prices.representative(atom)
            for _ in range(20):
                draw = prices.draw_within(atom, group, PRICE, native.rounded_price, rng)
                self.assertTrue(edits._producible(draw, PRICE))
                self.assertEqual([edits._price(o["price_trace"]["reference_minor"], draw, PRICE, native.rounded_price) for o in group],
                                 [edits._price(o["price_trace"]["reference_minor"], middle, PRICE, native.rounded_price) for o in group])


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.api = toy_api(NARROW)
        self.session = streams.Session(self.api, INPUTS)
        self.natural, _ = self.session.generate()

    def brute_force(self, need):
        """Enumerate every combination of the pairs' cheapest prices."""
        pairs = prices.block(self.natural, need, self.api)
        spread = {pair: {price: sum(a[0] for a in found) for price, found in
                         prices.distribution(entry, NARROW, native.rounded_price).items()}
                  for pair, entry in pairs.items()}
        names = sorted(spread)
        designated = {(rid, need["product_id"]) for rid in need["retailer_ids"]}
        outcomes = Counter()
        for combo in combinations(*(spread[name].items() for name in names)):
            low = min(price for price, _ in combo)
            if {name for name, (price, _) in zip(names, combo) if price == low} == designated:
                weight = 1
                for _, m in combo:
                    weight *= m
                outcomes[tuple(price for price, _ in combo)] += weight
        return names, outcomes

    def test_probability_equals_brute_force_enumeration(self):
        for need in (requirement("north", "south"), requirement("west"), requirement("north", "west", product_id="boot")):
            _, outcomes = self.brute_force(need)
            _, probability, _ = prices.plan(self.natural, need, self.api, Random(0))
            self.assertAlmostEqual(probability, sum(outcomes.values()), places=12)
            self.assertGreater(probability, 0)

    def test_steered_worlds_come_from_the_producer_and_satisfy_the_oracle(self):
        need = requirement("north", "south")
        for index in range(25):
            world, _, reference, record = prices.steer(self.session, self.natural, need, self.api, Random(index))
            self.assertEqual({(w["retailer_id"], w["product_id"]) for w in reference["winners"]},
                             {("north", "shoe"), ("south", "shoe")})
            self.assertEqual(edits.price_rule_violations(world, native.rounded_price), [])
            self.assertEqual(world["status"], streams.STATUS)
            self.assertEqual(record["winning_price_minor"], reference["minimum_price_minor"])
            self.assertNotEqual(world["world_id"], self.natural["world_id"])
            self.assertEqual(record["streams_steered"], 5)
            self.assertTrue(world["limitations"][0].startswith("Natural-draw declaration: "))
        self.assertEqual(self.api.manufactured, list(REFERENCES))

    def test_repeated_samples_of_one_world_follow_the_conditional_distribution(self):
        # One frozen natural world, many plans: every pair, competitors
        # included, must follow its conditional price distribution. Reusing the
        # world's own draws where they happen to fit would freeze them instead.
        need, trials = requirement("north", "south"), 4000
        names, outcomes = self.brute_force(need)
        total = sum(outcomes.values())
        pairs = prices.block(self.natural, need, self.api)
        seen, offsets = Counter(), {name: set() for name in names}
        for index in range(trials):
            draws, _, _ = prices.plan(self.natural, need, self.api, Random(index))
            self.assertEqual(sorted(draws), names)
            seen[tuple(prices.cheapest(pairs[name], draws[name], NARROW, native.rounded_price) for name in names)] += 1
            for name in names:
                offsets[name].add(draws[name])
        self.assertLessEqual(set(seen), set(outcomes))
        for position, name in enumerate(names):
            expected, found = Counter(), Counter()
            for combo, weight in outcomes.items():
                expected[combo[position]] += weight / total
            for combo, count in seen.items():
                found[combo[position]] += count / trials
            self.assertLess(sum(abs(expected[k] - found[k]) for k in expected) / 2, 0.04, name)
            self.assertGreater(len(offsets[name]), 50, name)
        # The competitor whose natural price always fits is not frozen at it.
        position = names.index(("west", "boot"))
        natural_price = min(o["price_minor"] for o in pairs[("west", "boot")]["buyable"])
        share = sum(count for combo, count in seen.items() if combo[position] == natural_price) / trials
        self.assertLess(share, 0.2)

    def test_computed_probability_and_winning_prices_match_real_redraws(self):
        need, trials = requirement("west"), 20000
        block_model = prices.model(self.natural, need, self.api)
        winning = prices.empirical(self.natural, need, self.api, trials, 10 ** 6)
        hits, probability = sum(winning.values()), block_model.probability
        self.assertLess(abs(hits / trials - probability), 4 * (probability * (1 - probability) / trials) ** .5)
        distance = sum(abs(block_model.terms.get(p, 0) / probability - winning.get(p, 0) / hits)
                       for p in set(block_model.terms) | set(winning)) / 2
        self.assertLess(distance, 0.06)

    def test_zero_probability_is_a_coded_refusal(self):
        api = toy_api(empty={("south", "shoe-39"), ("south", "shoe-40"), ("south", "shoe-41")})
        natural, _ = streams.Session(api, INPUTS).generate()
        with self.assertRaises(prices.ZeroMass) as caught:
            prices.plan(natural, requirement("north", "south"), api, Random(0))
        self.assertEqual(caught.exception.reason, "unavailable")
        api = toy_api({**PRICE, "reference_match_probability": 1})
        natural, _ = streams.Session(api, INPUTS).generate()
        with self.assertRaises(prices.ZeroMass) as caught:
            prices.plan(natural, requirement("north"), api, Random(0))
        self.assertEqual(caught.exception.reason, "no_common_price")


class ManufactureTests(unittest.TestCase):
    def test_products_are_made_once_and_unsteered_passes_repeat_the_world(self):
        api = toy_api()
        session = streams.Session(api, INPUTS)
        first, opened = session.generate()
        second, _ = session.generate()
        self.assertEqual(first, second)
        self.assertEqual(api.manufactured, list(REFERENCES))
        self.assertEqual(len(set(opened)), 5)
        second["products"][0]["public"]["name"] = "mutated"
        third, _ = session.generate()
        self.assertEqual(first, third)

    def test_changed_upstream_arguments_miss_the_cache(self):
        api = toy_api()
        session = streams.Session(api, INPUTS)
        session.generate()
        session.inputs["review_count"] = 3
        session.generate()
        self.assertEqual(api.manufactured, list(REFERENCES) * 2)


if __name__ == "__main__":
    unittest.main()
