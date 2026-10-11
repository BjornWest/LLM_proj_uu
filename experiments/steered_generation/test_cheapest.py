"""Tests of the joint stock-and-price block for the cheapest available offer.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_cheapest.py
The real commerce producer with stand-in products, as in test_combined.py.
Here the largest size of every product costs more, so a retailer/product pair
has two price levels. Sold-out offers are rare under the producer's stock
configuration, so the frequency tests of them run on a copy of the world with
a scarcer configuration; the block model and the reading of the producer's
lines both take the configuration from the world.
"""
from collections import Counter
from copy import deepcopy
from fractions import Fraction
from itertools import product as combinations
from math import exp, fsum, log, prod
from random import Random
from types import SimpleNamespace
from unittest import mock

from experiments.accepted_catalog_commerce import model as commerce
from experiments.world_requirement_construction import model as edits

from environments.website_world import comparison_sku_task, native_review_ecosystem

from experiments.steered_generation import blocks, cheapest, combined, listed, prices, run, stock, streams
from experiments.steered_generation.test_combined import BOTH, PLAIN, SHIRTS, SHOES, SMALL, TwoConcepts
from experiments.steered_generation.test_stock import stand_in

LARGE = "department_store-04"  # eleven locations, no supplier orders, no branch in Uppsala
EMPTY = "footwear-06"          # lists nothing
SIZE_40 = [{"field": "sku.size_eu", "operator": "eq", "value": 40}]
# The native tasks' three readings of "available", each with a size requirement.
READINGS = ({"predicates": SIZE_40}, {"predicates": SIZE_40, "availability": cheapest.PHYSICAL},
            {"predicates": SIZE_40, "availability": cheapest.BRANCH, "city": "Uppsala"})


def two_prices(seed, concept_id, brand, product_id, *, earlier, review_count):
    product = stand_in(seed, concept_id, brand, product_id, earlier=earlier, review_count=review_count)
    product["public"]["skus"][-1]["reference_price_sek"] = product["public"]["reference_price_sek"] + 40
    # The surrounding-site generator reads published facts; the stand-in has none.
    product["public"]["facts"] = {}
    return product


def unavailable(found):
    return sum(not (any(row["stock_by_source"].values()) or row["supplier_order"]) for row in found["offers"].values())


class Cheapest(TwoConcepts):
    product = staticmethod(two_prices)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _, reference = edits._reference(cls.natural, {"concept_id": SHOES}, cls.api)
        # The natural world's winners: two retailers tied on one product.
        cls.shoe = reference["winners"][0]["product_id"]
        cls.first, cls.second = sorted({w["retailer_id"] for w in reference["winners"]})
        # Stock is scarce and a quantity draw can itself be zero.
        cls.scarce = deepcopy(cls.natural)
        cls.scarce["config"]["stock"]["zero_probability"] = {"well_stocked": .85, "patchy": .92, "mostly_depleted": .98}
        for ranges in cls.scarce["config"]["stock"]["quantity_ranges"].values():
            ranges["mostly_depleted"] = [0, 2]

    def need(self, *retailers, product=None, below=()):
        requirement = {"schema": cheapest.VERSION, "concept_id": SHOES, "product_id": product or self.shoe,
                       "retailer_ids": list(retailers)}
        return {**requirement, "listed_below": [{"retailer_id": rid, "sku_id": sku} for rid, sku in below]} if below \
            else requirement

    def size(self, rid, index, product=None):
        return [o["sku_id"] for o in self.retailer(rid)["offers"] if o["product_id"] == (product or self.shoe)][index]

    def requirements(self):
        other = next(o["product_id"] for o in self.retailer(LARGE)["offers"])
        return [self.need(self.first), self.need(self.first, self.second),
                # The other natural winner is listed cheaper and has nothing available.
                self.need(self.second, below=[(self.first, self.size(self.first, 0))]),
                # The winner's own cheaper sizes are sold out; its largest size wins.
                self.need(self.second, below=[(self.second, self.size(self.second, 0))]),
                # An unlikely winner, with two retailers listed cheaper.
                self.need(LARGE, product=other, below=[(self.first, self.size(self.first, -1)),
                                                       (self.second, self.size(self.second, 1))])]


class ModelTests(Cheapest):
    def test_every_pair_has_one_cheapest_available_price_or_none(self):
        for world in (self.natural, self.scarce):
            block = cheapest.model(world, self.need(self.first), self.api)
            self.assertEqual(len(block.places), len(prices.competing(world, SHOES)))
            for pair, spread in block.spread.items():
                self.assertAlmostEqual(fsum(o.mass for o in spread.outcomes), 1, places=8, msg=pair)
                self.assertGreater(len({o.price for o in spread.outcomes}), 3)

    def test_stock_probabilities_match_enumeration_of_the_configuration(self):
        for world in (self.natural, self.scarce):
            stock_config = world["config"]["stock"]
            block = cheapest.model(world, self.need(self.first), self.api)
            for pair, place in block.places.items():
                retailer = self.retailer(pair[0])
                if len(retailer["source_locations"]) > 4:
                    continue
                order = world["config"]["supplier"]["sku_eligible_probability"] if retailer["supplier_enabled"] else 0
                rows = {row["source_id"]: row["probabilities"] for row in retailer["conditions"]
                        if row["product_id"] == pair[1]}

                def empty(condition):
                    low, high = stock_config["quantity_ranges"][retailer["scale"]][condition]
                    zero = stock_config["zero_probability"][condition]
                    return zero + (1 - zero) * (low <= 0 <= high) / (high - low + 1)

                for count in range(4):
                    none = some = 0
                    for found in combinations(*(rows[s["source_id"]].items() for s in retailer["source_locations"])):
                        chance = prod(weight for _, weight in found) / prod(
                            sum(rows[s["source_id"]].values()) for s in retailer["source_locations"])
                        # One SKU is unavailable: held nowhere and left without a supplier order.
                        out = prod(empty(condition) for condition, _ in found) * (1 - order)
                        none += chance * out ** count
                        some += chance * out ** count * (1 - out)
                    self.assertAlmostEqual(cheapest.nothing(place, count), none, places=12)
                    self.assertAlmostEqual(cheapest.chain(place, count).probability, some, places=12)

    def test_tabulated_sums_equal_the_direct_ones(self):
        block = cheapest.model(self.scarce, self.need(self.first), self.api)
        for spread in block.spread.values():
            self.assertTrue(spread.table)
            for winning in spread.prices[::7] + [spread.prices[0] - 1, spread.prices[-1] + 1, spread.prices[3] + 1]:
                for designated in (False, True):
                    direct = fsum(o.mass for o in spread.outcomes if cheapest.accepts(o, winning, designated))
                    self.assertAlmostEqual(spread.mass(winning, designated), direct, places=14)

    def redraws(self, world, trials):
        """The concept's leaves under other seeds, read once per world for every requirement."""
        store = self.__class__.__dict__.get("_redraws") or {}
        type(self)._redraws = store
        if id(world) not in store:
            reading = cheapest.trial(world, self.need(self.first), self.api).reading
            store[id(world)] = [reading(seed) for seed in range(10 ** 6, 10 ** 6 + trials)]
        return store[id(world)]

    def sold_out(self):
        """On the scarce world: a cheaper retailer has nothing available; the winner's own cheaper sizes have not."""
        return [self.need(self.second, below=[(self.first, self.size(self.first, 0))]),
                self.need(self.second, below=[(self.second, self.size(self.second, 0))])]

    def test_probability_and_winning_price_match_other_seeds(self):
        cases = [(self.natural, 2500, self.need(self.first), 500), (self.natural, 2500, self.need(self.first, self.second), 200),
                 (self.scarce, 4000, self.need(self.first), 500), (self.scarce, 4000, self.sold_out()[0], 200),
                 (self.scarce, 4000, self.sold_out()[1], 30)]
        for world, trials, requirement, least in cases:
            with self.subTest(requirement=requirement, scarce=world is self.scarce):
                block = cheapest.model(world, requirement, self.api)
                seen = Counter(cheapest.judged(found, requirement) for found in self.redraws(world, trials))
                del seen[None]
                hits, chance = sum(seen.values()), block.probability
                self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5)
                self.assertGreater(hits, least)
                distance = sum(abs(block.shares.get(price, 0) - seen.get(price, 0) / hits)
                               for price in set(block.shares) | set(seen)) / 2
                self.assertLess(distance, .03 + .6 * (len(block.shares) / hits) ** .5)
                self.assertLessEqual(set(seen), set(block.shares))
                self.assertAlmostEqual(fsum(block.shares.values()), 1, places=12)
                self.assertAlmostEqual(exp(block.log_probability), chance, places=15)

    def test_samples_match_rejection_sampling(self):
        """Planned leaves against the redraws under other seeds that happen to satisfy the requirement."""
        requirement = self.sold_out()[0]
        block = cheapest.model(self.scarce, requirement, self.api)
        rejection = [found for found in self.redraws(self.scarce, 4000)
                     if cheapest.judged(found, requirement) is not None]
        steered = [cheapest.planned(block, cheapest.sample(block, Random(index))[1]) for index in range(1500)]
        self.assertGreater(len(rejection), 200)
        for found in steered[:100]:
            self.assertIsNotNone(cheapest.judged(found, requirement))

        def compare(statistic):
            ours, theirs = [statistic(found) for found in steered], [statistic(found) for found in rejection]
            mean = lambda values: sum(values) / len(values)
            spread = (sum((value - mean(theirs)) ** 2 for value in theirs) / len(theirs)) ** .5
            self.assertLessEqual(abs(mean(ours) - mean(theirs)),
                                 4 * spread * (1 / len(ours) + 1 / len(theirs)) ** .5)

        compare(unavailable)
        compare(lambda found: sum(sum(row["stock_by_source"].values()) for row in found["offers"].values()))
        compare(lambda found: sum(row["supplier_order"] for row in found["offers"].values()))
        compare(lambda found: sum(value == "mostly_depleted" for value in found["conditions"].values()))
        compare(lambda found: cheapest.judged(found, requirement))
        compare(lambda found: sum(row["price_minor"] for row in found["offers"].values()) / len(found["offers"]))
        # The retailer listed below the winner, and the winner itself.
        for rid in (self.first, self.second):
            compare(lambda found: sum(value == "mostly_depleted" for key, value in found["conditions"].items()
                                      if key.startswith(rid + "/" + self.shoe)))
            compare(lambda found: min(row["price_minor"] for row in found["offers"].values()
                                      if (row["retailer_id"], row["product_id"]) == (rid, self.shoe)))
            compare(lambda found: sum(sum(row["stock_by_source"].values()) for row in found["offers"].values()
                                      if (row["retailer_id"], row["product_id"]) == (rid, self.shoe)))

    def test_a_possible_event_below_the_float_range_is_sampled_not_called_impossible(self):
        """Many pairs with nothing available: every pair's factor is a float, their product is not."""
        full = deepcopy(self.natural)
        full["config"]["stock"]["zero_probability"] = dict.fromkeys(self.natural["config"]["stock"]["zero_probability"], 1e-5)
        shoes = [(r["retailer_id"], o) for r in self.natural["retailers"] for o in r["offers"]
                 if o["product_id"].split("/")[1] == SHOES]
        rid, dear = max(shoes, key=lambda row: row[1]["price_trace"]["reference_minor"])
        # The dearest pair wins, with one offer of every other pair listed below it.
        others = {(other, o["product_id"]): (other, o["sku_id"]) for other, o in reversed(shoes)
                  if (other, o["product_id"]) != (rid, dear["product_id"])}
        requirement = self.need(rid, product=dear["product_id"], below=list(others.values()))
        self.assertEqual(len(others), 23)
        block = cheapest.model(full, requirement, self.api)
        self.assertEqual(block.probability, 0.0)
        # Some winning prices are so much less likely than others that their share is no float either;
        # sampling still reaches them.
        rare = sorted(block.log_terms, key=block.log_terms.get, reverse=True)
        self.assertEqual(block.shares[rare[-1]], 0.0)
        self.assertEqual(cheapest.pick_log(Top(), rare, [block.log_terms[price] for price in rare]), rare[-1])
        self.assertLess(block.log_probability, log(5e-324))
        self.assertGreater(block.log_probability, -1e5)
        self.assertAlmostEqual(fsum(block.shares.values()), 1, places=12)
        for pair, spread in block.spread.items():
            self.assertGreater(min(o.mass for o in spread.outcomes), 0)
        for index in range(3):
            winning, draws = cheapest.sample(block, Random(index))
            self.assertEqual(cheapest.judged(cheapest.planned(block, draws), requirement), winning)
        step = cheapest.prepare(full, requirement, self.api, Random(0))
        self.assertEqual((step.probability, step.log_probability), (0.0, block.log_probability))
        # The same event on the natural configuration is merely unlikely.
        usual = cheapest.model(self.natural, requirement, self.api)
        self.assertGreater(usual.probability, 0)
        self.assertAlmostEqual(log(usual.probability), usual.log_probability, places=9)

    def sized(self, rid, index=0):
        """The size-40 offer of the natural winners' shoe at a retailer."""
        return next(sku for sku in (self.size(rid, i) for i in range(4)) if sku.endswith("-40"))

    def test_predicates_and_availability_match_other_seeds(self):
        """Each native reading of who competes and what is available, against the redraws read by that rule."""
        for reading in READINGS:
            sold_out = {**self.need(self.second, below=[(self.first, self.sized(self.first))]), **reading}
            for world, trials, requirement, least in (
                    (self.natural, 2500, {**self.need(self.first), **reading}, 400),
                    (self.scarce, 4000, {**self.need(self.first), **reading}, 400), (self.scarce, 4000, sold_out, 100)):
                with self.subTest(requirement=requirement, scarce=world is self.scarce):
                    block = cheapest.model(world, requirement, self.api)
                    seen = Counter(cheapest.judged(found, requirement, block.scope)
                                   for found in self.redraws(world, trials))
                    del seen[None]
                    hits, chance = sum(seen.values()), block.probability
                    self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5)
                    self.assertGreater(hits, least)
                    distance = sum(abs(block.shares.get(price, 0) - seen.get(price, 0) / hits)
                                   for price in set(block.shares) | set(seen)) / 2
                    self.assertLess(distance, .03 + .6 * (len(block.shares) / hits) ** .5)
        # The readings differ: the same redraws give other verdicts.
        blocks_by_reading = [cheapest.model(self.scarce, {**self.need(self.first), **reading}, self.api)
                             for reading in ({},) + READINGS]
        chances = [block.probability for block in blocks_by_reading]
        self.assertEqual(len({round(chance, 6) for chance in chances}), 4)

    def test_samples_under_a_branch_reading_match_rejection_sampling(self):
        requirement = {**self.need(self.second, below=[(self.first, self.sized(self.first))]), **READINGS[2]}
        block = cheapest.model(self.scarce, requirement, self.api)
        rejection = [found for found in self.redraws(self.scarce, 4000)
                     if cheapest.judged(found, requirement, block.scope) is not None]
        steered = [cheapest.planned(block, cheapest.sample(block, Random(index))[1]) for index in range(1500)]
        self.assertGreater(len(rejection), 100)
        for found in steered[:100]:
            self.assertIsNotNone(cheapest.judged(found, requirement, block.scope))
        counting = block.scope.sources

        def compare(statistic):
            ours, theirs = [statistic(found) for found in steered], [statistic(found) for found in rejection]
            mean = lambda values: sum(values) / len(values)
            spread = (sum((value - mean(theirs)) ** 2 for value in theirs) / len(theirs)) ** .5
            self.assertLessEqual(abs(mean(ours) - mean(theirs)),
                                 4 * spread * (1 / len(ours) + 1 / len(theirs)) ** .5)

        rows = lambda found: found["offers"].values()
        compare(lambda found: cheapest.judged(found, requirement, block.scope))
        # Stock where it counts and where it does not, for offers that compete and offers that do not.
        for competes in (True, False):
            for counts in (True, False):
                compare(lambda found: sum(
                    quantity for row in rows(found) if (row["sku_id"] in block.scope.skus) == competes
                    for name, quantity in row["stock_by_source"].items()
                    if (name in counting[row["retailer_id"]]) == counts))
        compare(lambda found: sum(row["supplier_order"] for row in rows(found)))
        compare(lambda found: sum(value == "mostly_depleted" for value in found["conditions"].values()))
        compare(lambda found: sum(value == "mostly_depleted" for key, value in found["conditions"].items()
                                  if key.rsplit("/", 1)[1] in counting[key.split("/", 1)[0]]))
        compare(lambda found: sum(row["price_minor"] for row in rows(found)) / len(found["offers"]))

    def test_every_option_with_a_positive_weight_can_be_picked(self):
        self.assertEqual(blocks.pick(Top(), "ab", [1.0, 1e-300]), "b")
        self.assertEqual(blocks.pick(Top(), "abc", [1.0, 1e-300, 0.0]), "b")
        self.assertEqual(blocks.pick(Top(), "ab", [Fraction(1), Fraction(1, 10 ** 400)]), "b")
        self.assertEqual(cheapest.pick_log(Top(), "ab", [-237.5, -1050.5]), "b")
        self.assertEqual(cheapest.pick_log(Top(), "abc", [-1050.5, -237.5, -5000.0]), "c")
        # Uneven weights take the exact route and keep their proportions.
        rng = Random(0)
        seen = Counter(blocks.pick(rng, "abc", [3.0, 1.0, 2.0 ** -40]) for _ in range(4000))
        self.assertLess(abs(seen["a"] / 4000 - .75), .03)
        self.assertEqual(seen["a"] + seen["b"], 4000)
        seen = Counter(blocks.pick(rng, "abc", [Fraction(1, 4), Fraction(3, 4), 0]) for _ in range(4000))
        self.assertLess(abs(seen["b"] / 4000 - .75), .03)
        # Ordinary weights are the generator's own choice, draw for draw.
        self.assertEqual([blocks.pick(Random(index), "abc", [.2, .3, .5]) for index in range(20)],
                         [Random(index).choices("abc", weights=[.2, .3, .5])[0] for index in range(20)])
        with self.assertRaises(ValueError):
            blocks.pick(Random(0), "ab", [0.0, 0.0])
        # Subnormal weights: an option of weight zero never comes out, and equal weights stay equal.
        last = SimpleNamespace(random=lambda: 1 - 2 ** -53)
        last.choices = lambda names, weights: Random.choices(last, names, weights=weights)
        self.assertEqual(blocks.pick(last, "ab", [5e-324, 0.0]), "a")
        self.assertEqual(blocks.pick(last, "abc", [5e-324, 5e-324, 0.0]), "b")
        for weights in ([5e-324, 0.0], [5e-324, 5e-324, 0.0], [1e-320, 3e-320, 0.0], [0.0, 2e-310, 2e-310]):
            seen = Counter(blocks.pick(Random(index), "abc"[:len(weights)], weights) for index in range(1000))
            total = sum(weights)
            for option, weight in zip("abc", weights):
                self.assertLess(abs(seen[option] / 1000 - weight / total), .06, (weights, seen))
                self.assertEqual(seen[option] > 0, weight > 0)
        with self.assertRaises(cheapest.NumericalLimit):
            cheapest.pick_log(Random(0), "ab", [0.0, -3e18])

    def test_a_first_available_size_of_subnormal_weight_is_sampled_as_such(self):
        """Stock all but impossible: the first size at a price is the only possible witness, at a subnormal weight."""
        rare = deepcopy(self.natural)
        rare["config"]["stock"]["zero_probability"] = {"well_stocked": 0.0, "patchy": 1.0, "mostly_depleted": 1.0}
        for ranges in rare["config"]["stock"]["quantity_ranges"].values():
            ranges["well_stocked"] = [1, 1]
        # Every price at its reference, so that no factor below one meets the subnormal stock probability.
        rare["config"]["retailer_price"]["reference_match_probability"] = 1
        # One retailer with a single location and no supplier orders can hold stock, at a subnormal
        # probability; nobody else ever does.
        lone = "marketplace-00"
        for retailer in rare["retailers"]:
            alone = retailer["retailer_id"] == lone
            retailer["supplier_enabled"] = retailer["supplier_enabled"] and not alone
            for row in retailer["conditions"]:
                row["probabilities"] = {"well_stocked": 5e-324, "patchy": 1.0} if alone else {"patchy": 1.0}
        self.assertEqual(len(self.retailer(lone)["source_locations"]), 1)
        product = next(o["product_id"] for o in self.retailer(lone)["offers"] if o["product_id"].split("/")[1] == SHOES)
        requirement = self.need(lone, product=product)
        block = cheapest.model(rare, requirement, self.api)
        place = block.places[(lone, product)]
        # Under the one condition with stock every size holds some, so only the first can be the first available.
        self.assertEqual([cheapest.chain(place, count).probability > 0 for count in range(3)], [True, False, False])
        self.assertLess(cheapest.chain(place, 0).probability, 1e-300)
        self.assertLess(block.log_probability, -700)
        for index in range(20):
            winning, draws = cheapest.sample(block, Random(index))
            self.assertEqual(cheapest.judged(cheapest.planned(block, draws), requirement), winning)
            self.assertEqual(draws[(lone, product)].stock.witness, place.offers[0]["offer_id"])

    def test_a_stock_probability_at_the_edge_of_the_floats_is_not_lost(self):
        """A zero probability one step below 1: 'nothing here' rounds to certain, 'something here' must survive."""
        edge = deepcopy(self.natural)
        edge["config"]["stock"]["zero_probability"] = dict.fromkeys(
            self.natural["config"]["stock"]["zero_probability"], 1 - 2 ** -53)
        for ranges in edge["config"]["stock"]["quantity_ranges"].values():
            for condition in ranges:
                ranges[condition] = [0, 1]
        for rid in (PLAIN, LARGE):
            self.assertFalse(self.retailer(rid)["supplier_enabled"])
            product = next(o["product_id"] for o in self.retailer(rid)["offers"] if o["product_id"].split("/")[1] == SHOES)
            requirement = self.need(rid, product=product)
            block = cheapest.model(edge, requirement, self.api)
            found = next(iter(block.places[(rid, product)].locations[0].conditions.values()))
            self.assertEqual((found.empty, found.full > 0), (1.0, True))
            self.assertLess(block.log_probability, -30)
            winning, draws = cheapest.sample(block, Random(0))
            self.assertEqual(cheapest.judged(cheapest.planned(block, draws), requirement), winning)
        # A positive stock outcome that no float holds is an error, not an outcome left out.
        with self.assertRaises(blocks.NumericalLimit):
            stock.atoms({"usual": 1.0, "rare": 1e-200}, {"usual": .5, "rare": 1e-200}, {"usual": [1, 2], "rare": [1, 2]})
        self.assertEqual(len(stock.atoms({"usual": 1.0, "never": 0.0}, {"usual": 1.0, "never": .5},
                                         {"usual": [1, 2], "never": [1, 2]})), 1)
        lost = deepcopy(self.natural)
        for retailer in lost["retailers"]:
            for row in retailer["conditions"]:
                row["probabilities"] = {**row["probabilities"], "patchy": 1e-200}
        lost["config"]["stock"]["zero_probability"]["patchy"] = 1e-200
        with self.assertRaises(blocks.NumericalLimit):
            cheapest.model(lost, self.need(self.first), self.api)

    def test_a_numerical_limit_met_while_sampling_is_reported_by_the_runner(self):
        requirement, case = self.need(self.first), {"samples": [], "requirement_sha256": "x"}
        with mock.patch.object(cheapest, "steer", side_effect=cheapest.NumericalLimit("too small")):
            run.cheapest_case(SimpleNamespace(samples=1, producer_redraws=0, validate_trials=0), self.session,
                              self.natural, self.opened, self.api, requirement, case, None)
        self.assertEqual((case["status"], case["reason"], case["samples"]), ("refused", "numerical_limit", []))
        case = {"samples": []}
        with mock.patch.object(stock, "model", side_effect=blocks.NumericalLimit("too small")):
            run.stock_case(None, self.session, self.natural, self.opened, self.api, {}, case, None)
        self.assertEqual((case["status"], case["reason"]), ("refused", "numerical_limit"))

    def test_a_factor_within_one_pair_that_underflows_is_an_error_not_a_zero(self):
        full = deepcopy(self.natural)
        full["config"]["stock"]["zero_probability"] = dict.fromkeys(self.natural["config"]["stock"]["zero_probability"], 1e-40)
        with self.assertRaises(cheapest.NumericalLimit) as caught:
            cheapest.model(full, self.need(self.first), self.api)
        self.assertEqual(caught.exception.reason, "numerical_limit")
        self.assertNotIsInstance(caught.exception, ValueError)
        self.assertEqual(cheapest.times(.5, 0, 1e-300, 1e-300), 0)
        self.assertEqual(cheapest.power(0, 3), 0)
        self.assertEqual(cheapest.power(0.0, 0), 1)
        for call in (lambda: cheapest.times(1e-200, 1e-200), lambda: cheapest.power(1e-200, 2)):
            with self.assertRaises(cheapest.NumericalLimit):
                call()

    def test_a_sample_consults_no_draw_of_the_world_it_starts_from(self):
        requirement = self.requirements()[2]
        keys = cheapest.trial(self.natural, requirement, self.api).keys
        other, _ = self.session.generate({key: streams.Reseeded(77) for key in keys})
        self.assertNotEqual(cheapest.recorded(other, SHOES), cheapest.recorded(self.natural, SHOES))
        ours, theirs = (cheapest.model(world, requirement, self.api) for world in (self.natural, other))
        self.assertEqual(ours.log_terms, theirs.log_terms)
        for index in range(3):
            first, second = (cheapest.sample(block, Random(index)) for block in (ours, theirs))
            self.assertEqual(first[0], second[0])
            self.assertEqual(cheapest.planned(ours, first[1]), cheapest.planned(theirs, second[1]))


class ProducerTests(Cheapest):
    def test_steered_worlds_satisfy_the_requirement_through_the_producer(self):
        chances = []
        for index, requirement in enumerate(self.requirements()):
            with self.subTest(requirement=requirement):
                world, found, record = cheapest.steer(self.session, self.natural, self.opened, requirement,
                                                      self.api, Random(index))
                chances.append(record["probability_given_upstream"])
                block = cheapest.model(self.natural, requirement, self.api)
                self.assertEqual((chances[-1], record["log_probability_given_upstream"]),
                                 (block.probability, block.log_probability))
                self.assertTrue(cheapest.satisfied(world, requirement, self.api))
                self.assertEqual(cheapest.satisfied(self.natural, requirement, self.api), index == 1)
                reference = found["reference"]
                self.assertEqual({(w["retailer_id"], w["product_id"]) for w in reference["winners"]},
                                 {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]})
                # The saved leaves themselves, read without the block model or the oracle.
                self.assertEqual(cheapest.judged(cheapest.recorded(world, SHOES), requirement),
                                 record["winning_price_minor"])
                self.assertEqual(reference["minimum_price_minor"], record["winning_price_minor"])
                self.assertEqual(len(found["listed_below"]), len(requirement.get("listed_below", [])))
                for row in found["listed_below"]:
                    self.assertIn(row["offer_id"], reference["unavailable_offer_ids"])
                    self.assertLess(row["price_minor"], reference["minimum_price_minor"])
                self.assertEqual(world["status"], streams.STATUS)
                self.assertTrue(commerce.validate({**world, "world_id": world["world_id"]})["valid"])
                self.assertEqual(world["provenance"]["steered_generation"], record)
                self.assertEqual(record["method"], "exact_conditional_stock_and_price_block")
                self.assertEqual(len(record["repriced"]), len(record["restocked"]))
                writes = cheapest.footprint(self.natural, requirement, self.api).writes
                self.assertEqual(len(writes), 2 * len(record["restocked"]))
                self.assertEqual(blocks.background(world, writes), blocks.background(self.natural, writes))
        self.assertGreater(chances[0], .1)
        self.assertLess(max(chances[2:]), .001)
        self.assertEqual(self.natural, self.frozen)

    def test_steered_worlds_satisfy_each_native_reading_through_the_producer(self):
        for index, reading in enumerate(READINGS):
            for below in ((), [(self.first, next(sku for sku in (self.size(self.first, i) for i in range(2))
                                                 if sku.endswith("-40")))]):
                requirement = {**self.need(self.second, below=below), **reading}
                with self.subTest(requirement=requirement):
                    world, found, record = cheapest.steer(self.session, self.natural, self.opened, requirement,
                                                          self.api, Random(index))
                    reference, scope = found["reference"], cheapest.scope(self.natural, requirement, self.api)
                    self.assertEqual({(w["retailer_id"], w["product_id"]) for w in reference["winners"]},
                                     {(self.second, self.shoe)})
                    self.assertTrue(all(w["sku_id"].endswith("-40") for w in reference["candidates"]))
                    self.assertEqual(found["task"]["availability"], reading.get("availability", cheapest.PURCHASABLE))
                    self.assertEqual(cheapest.judged(cheapest.recorded(world, SHOES), requirement, scope),
                                     record["winning_price_minor"])
                    self.assertEqual(reference["minimum_price_minor"], record["winning_price_minor"])
                    self.assertEqual(len(found["listed_below"]), len(below))
                    for row in found["listed_below"]:
                        self.assertNotIn(row["offer_id"], {c["offer_id"] for c in reference["candidates"]})
                        self.assertLess(row["price_minor"], reference["minimum_price_minor"])
                    self.assertTrue(cheapest.satisfied(world, requirement, self.api))
                    self.assertTrue(commerce.validate({**world, "world_id": world["world_id"]})["valid"])
                    writes = cheapest.footprint(self.natural, requirement, self.api).writes
                    self.assertEqual(blocks.background(world, writes), blocks.background(self.natural, writes))
                    if reading.get("availability") == cheapest.BRANCH:
                        winner = next(w for w in reference["branch_winners"])
                        self.assertEqual((winner["city"], winner["pickup_enabled"]), ("Uppsala", True))
                        self.assertGreater(winner["physical_stock"], 0)
        self.assertEqual(self.natural, self.frozen)

    def test_a_comparison_site_confines_who_competes(self):
        site = {"comparison_site_id": "comparison-00"}
        every = cheapest.scope(self.natural, self.need(self.first), self.api)
        scope = cheapest.scope(self.natural, {**self.need(self.first), **site}, self.api)
        listed = cheapest.competing(self.natural, None, scope)
        shoes = cheapest.competing(self.natural, None, every)
        self.assertTrue(listed < shoes and len(listed) > 4)
        # A listed pair that is not the natural winner, with every listed pair of the natural winners below it or not.
        winner = sorted(listed - {(self.first, self.shoe), (self.second, self.shoe)})[0]
        requirement = {**self.need(winner[0], product=winner[1]), **site}
        block = cheapest.model(self.natural, requirement, self.api)
        self.assertEqual(set(block.places), listed)
        confined, free = block.probability, cheapest.model(
            self.natural, self.need(winner[0], product=winner[1]), self.api).probability
        self.assertGreater(confined, free)
        reading = cheapest.trial(self.natural, requirement, self.api)
        world, found, record = cheapest.steer(self.session, self.natural, self.opened, requirement, self.api, Random(1))
        reference = found["reference"]
        self.assertEqual({(w["retailer_id"], w["product_id"]) for w in reference["winners"]}, {winner})
        self.assertEqual({tuple(pair[::-1]) for pair in found["task"]["comparison_scope"]["product_retailer_pairs"]
                          if pair[0].split("/")[1] == SHOES}, listed)
        self.assertEqual(cheapest.judged(cheapest.recorded(world, SHOES), requirement, scope),
                         record["winning_price_minor"])
        self.assertTrue(reading.satisfied(world))
        writes = cheapest.footprint(self.natural, requirement, self.api).writes
        self.assertEqual({tuple(pair) for _, *pair in writes}, set(listed))
        self.assertEqual(blocks.background(world, writes), blocks.background(self.natural, writes))
        # The same site with a size requirement and physical stock only.
        sized = {**self.need(self.second, below=[(self.first, next(
            sku for sku in (self.size(self.first, i) for i in range(2)) if sku.endswith("-40")))]),
            **site, **READINGS[1]}
        if {(self.first, self.shoe), (self.second, self.shoe)} <= listed:
            world, found, record = cheapest.steer(self.session, self.natural, self.opened, sized, self.api, Random(2))
            self.assertEqual(found["task"]["comparison_site_id"], "comparison-00")
            self.assertEqual(found["reference"]["minimum_price_minor"], record["winning_price_minor"])
        trials = 1500
        seen = sum(reading.holds(seed) for seed in range(10 ** 6, 10 ** 6 + trials))
        self.assertLess(abs(seen / trials - confined), 4 * (confined * (1 - confined) / trials) ** .5)
        unlisted = sorted(shoes - listed)[0]
        with self.assertRaises(prices.ZeroMass) as caught:
            cheapest.model(self.natural, {**self.need(unlisted[0], product=unlisted[1]), **site}, self.api)
        self.assertEqual(caught.exception.reason, "not_listed")
        for extra in ({"comparison_site_id": "comparison-99"}, {"comparison_site_id": ""},
                      {"surrounding": {}}, {**site, "surrounding": {"no_such_control": 1}}, {**site, "surrounding": 3},
                      {**site, "listed_below": [{"retailer_id": unlisted[0], "sku_id": next(
                          o["sku_id"] for o in self.retailer(unlisted[0])["offers"] if o["product_id"] == unlisted[1])}]}):
            with self.subTest(extra=extra), self.assertRaises(ValueError) as caught:
                cheapest.model(self.natural, {**self.need(winner[0], product=winner[1]), **extra}, self.api)
            self.assertNotIsInstance(caught.exception, prices.ZeroMass)

    def test_the_retailer_advertised_cheapest_has_the_variant_only_on_supplier_order(self):
        """The comparison-stock task's hard case: who the site shows cheapest, and that offer's stock there."""
        site = {"comparison_site_id": "comparison-00"}
        pairs = cheapest.scope(self.natural, {**self.need(self.first), **site}, self.api).pairs
        # A listed pair at a retailer that takes supplier orders, for a product several listed retailers sell.
        rid, product = next(pair for pair in sorted(pairs) if self.retailer(pair[0])["supplier_enabled"] and
                            sum(other[1] == pair[1] for other in pairs) > 2)
        cheapest_listed = {"schema": listed.VERSION, "product_id": product, "retailer_ids": [rid], **site}
        block = listed.model(self.natural, cheapest_listed, self.api)
        self.assertEqual(set(block.groups), {pair for pair in pairs if pair[1] == product})
        trials = 3000
        seen = listed.empirical(self.natural, cheapest_listed, self.api, trials, 10 ** 6)
        hits, chance = sum(seen.values()), block.probability
        self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5)
        self.assertGreater(hits, 100)
        distance = sum(abs(block.shares.get(p, 0) - seen.get(p, 0) / hits) for p in set(block.shares) | set(seen)) / 2
        self.assertLess(distance, .03 + .6 * (len(block.shares) / hits) ** .5)
        found = blocks.redraw(self.session, self.natural, [listed.trial(self.natural, cheapest_listed, self.api)], 901)
        self.assertEqual((found.identical, found.agreed), ([True], [True]))

        variant = self.size(rid, 0, product)
        # The comparison-stock task counts stock at any location as in stock, so "only on supplier order"
        # is a supplier order with nothing held anywhere.
        on_order = {"schema": stock.VERSION, "retailer_id": rid, "sku_id": variant, "availability": "backorder",
                    "stock": {source: {"max": 0} for source in self.sources(rid)}}
        requirement = self.together(cheapest_listed, on_order)
        world, read, record = combined.steer(self.session, self.natural, self.opened, requirement, self.api, Random(4))
        self.assertAlmostEqual(record["log_probability_given_upstream"],
                               block.log_probability + log(self.alone(on_order)), places=12)
        self.assertEqual(read[0]["retailer_ids"], [rid])
        # The native comparison-stock oracle on the steered world and its own surrounding sidecar.
        surrounding = native_review_ecosystem.generate(world)
        task = comparison_sku_task.make(world, surrounding, comparison_site_id="comparison-00", sku_id=variant)
        winners = comparison_sku_task.reference(world, surrounding, task)["winners"]
        self.assertEqual([(w["retailer_id"], w["availability"], w["in_stock"]) for w in winners],
                         [(rid, "backorder", False)])
        self.assertEqual(winners[0]["advertised_price_minor"], read[0]["minimum_listed_price_minor"])
        natural = comparison_sku_task.reference(self.natural, native_review_ecosystem.generate(self.natural),
                                                comparison_sku_task.make(
                                                    self.natural, native_review_ecosystem.generate(self.natural),
                                                    comparison_site_id="comparison-00", sku_id=variant))["winners"]
        self.assertNotEqual([(w["retailer_id"], w["availability"]) for w in natural], [(rid, "backorder")])
        # A who-is-cheapest-available requirement on the same concept redraws the same prices: coupled.
        with self.assertRaises(blocks.Coupled):
            combined.prepare(self.natural, self.together(cheapest_listed, {
                **self.need(rid, product=product), "concept_id": product.split("/")[1]}), self.api, Random(0))
        for bad in ({**cheapest_listed, "retailer_ids": ["nobody"]}, {**cheapest_listed, "product_id": "nothing"},
                    {**cheapest_listed, "comparison_site_id": "comparison-99"}, {**cheapest_listed, "concept_id": SHOES},
                    {"schema": listed.VERSION, "product_id": product, "retailer_ids": []}):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                listed.model(self.natural, bad, self.api)
            self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        with self.assertRaises(prices.ZeroMass):
            listed.model(self.natural, {**cheapest_listed, "retailer_ids": [EMPTY]}, self.api)

    def test_only_pairs_with_a_competing_offer_are_in_the_block(self):
        largest = [{"field": "sku.size_eu", "operator": "eq", "value": 41}]
        requirement = {**self.need(LARGE, product=next(o["product_id"] for o in self.retailer(LARGE)["offers"])),
                       "predicates": largest}
        every = cheapest.footprint(self.natural, self.need(self.first), self.api).writes
        some = cheapest.footprint(self.natural, requirement, self.api).writes
        self.assertTrue(some < every)
        # The natural winner lists no size 41 at its first retailer, so that pair keeps the seed's own draws.
        self.assertNotIn(("price", self.first, self.shoe), some)
        world, found, record = cheapest.steer(self.session, self.natural, self.opened, requirement, self.api, Random(0))
        self.assertEqual(blocks.background(world, some), blocks.background(self.natural, some))
        self.assertEqual({row["retailer_id"] + "/" + row["product_id"] for row in record["restocked"]},
                         {"/".join(pair) for _, *pair in some})
        self.assertTrue(all(w["sku_id"].endswith("-41") for w in found["reference"]["winners"]))

    def test_readings_of_scope_are_validated_and_impossible_ones_named(self):
        good = self.need(self.first)
        for extra in ({"predicates": []}, {"predicates": "size"}, {"availability": cheapest.PHYSICAL},
                      {"availability": "soon", "predicates": SIZE_40}, {"city": "Uppsala", "predicates": SIZE_40},
                      {"availability": cheapest.BRANCH, "predicates": SIZE_40},
                      {"availability": cheapest.PHYSICAL, "predicates": SIZE_40, "country": "SE"},
                      {"availability": cheapest.BRANCH, "predicates": SIZE_40, "city": ""},
                      {"predicates": [{"field": "sku.no_such_field", "operator": "eq", "value": 1}]},
                      {"predicates": [{"field": "sku.size_eu", "operator": "about", "value": 40}]},
                      # An offer listed below the winner must itself compete.
                      {"predicates": SIZE_40, "listed_below": [{"retailer_id": self.second,
                                                                "sku_id": self.size(self.second, 0)}]}):
            for call in (cheapest.model, cheapest.footprint, cheapest.trial):
                with self.subTest(extra=extra, call=call), self.assertRaises(ValueError) as caught:
                    call(self.natural, {**good, **extra}, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        self.assertFalse(self.size(self.second, 0).endswith("-40"))
        for requirement, reason in (
                # No branch of this retailer is in the city.
                ({**self.need(LARGE, product=next(o["product_id"] for o in self.retailer(LARGE)["offers"])),
                  **READINGS[2]}, "no_outcome"),
                ({**good, **READINGS[2], "city": "Kiruna"}, "no_outcome"),
                # No shoe comes in this size.
                ({**good, "predicates": [{"field": "sku.size_eu", "operator": "eq", "value": 47}]}, "not_listed")):
            with self.subTest(requirement=requirement), self.assertRaises(prices.ZeroMass) as caught:
                cheapest.model(self.natural, requirement, self.api)
            self.assertEqual(caught.exception.reason, reason)

    def test_repeated_samples_differ(self):
        requirement = self.requirements()[2]
        worlds = [cheapest.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))[0]
                  for index in range(3)]
        self.assertEqual(len({world["world_id"] for world in worlds}), 3)
        self.assertEqual(len({json_of(cheapest.recorded(world, SHOES)) for world in worlds}), 3)
        again = cheapest.steer(self.session, self.natural, self.opened, requirement, self.api, Random(0))[0]
        self.assertEqual(again, worlds[0])

    def test_readings_equal_the_producer_under_other_seeds(self):
        requirement = self.need(self.first)
        reading = cheapest.trial(self.natural, requirement, self.api)
        held = 0
        for seed in range(900, 906):
            found = blocks.redraw(self.session, self.natural, [reading], seed)
            self.assertEqual((found.identical, found.agreed), ([True], [True]))
            held += found.satisfied
        self.assertTrue(0 < held < 6)
        self.assertEqual(self.session.generate()[0], self.frozen)

    def test_zero_probability_and_bad_requirements(self):
        own = self.size(self.second, -1)
        for requirement, reason in (
                (self.need(EMPTY), "not_listed"),
                (self.need(self.first, below=[(EMPTY, self.size(self.first, 0))]), "not_listed"),
                # The winner's dearest size cannot be listed below the winner.
                (self.need(self.second, below=[(self.second, own)]), "no_outcome")):
            with self.subTest(requirement=requirement), self.assertRaises(prices.ZeroMass) as caught:
                cheapest.model(self.natural, requirement, self.api)
            self.assertEqual(caught.exception.reason, reason)
        shirt = self.offer(BOTH, SHIRTS)
        good = self.need(self.first)
        for requirement in (
                {**good, "retailer_ids": []}, {**good, "retailer_ids": [self.first, self.first]},
                {**good, "retailer_ids": ["nobody"]}, {**good, "product_id": "nothing"},
                {**good, "product_id": shirt["product_id"]}, {**good, "concept_id": "no.such"},
                {**good, "listed_below": []}, {**good, "listed_below": [{"retailer_id": self.first}]},
                {**good, "listed_below": [{"retailer_id": self.first, "sku_id": own}] * 2},
                {**good, "listed_below": [{"retailer_id": "nobody", "sku_id": own}]},
                {**good, "listed_below": [{"retailer_id": self.first, "sku_id": "nothing"}]},
                {**good, "listed_below": [{"retailer_id": BOTH, "sku_id": shirt["sku_id"]}]},
                {**good, "kind": edits.KIND}, {**good, "schema": edits.VERSION}, [good]):
            with self.subTest(requirement=requirement), self.assertRaises(ValueError) as caught:
                cheapest.model(self.natural, requirement, self.api)
            self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        # A bad name is an error whatever else the requirement makes impossible, in any order.
        unlisted = (EMPTY, self.size(self.first, 0))
        for bad in ({"retailer_id": "nobody", "sku_id": own}, {"retailer_id": self.first, "sku_id": "nothing"},
                    {"retailer_id": BOTH, "sku_id": shirt["sku_id"]}):
            rows = [{"retailer_id": unlisted[0], "sku_id": unlisted[1]}, bad]
            for requirement in ({**self.need(EMPTY), "listed_below": [bad]}, {**good, "listed_below": rows},
                                {**good, "listed_below": rows[::-1]}):
                for call in (cheapest.model, cheapest.footprint, cheapest.trial):
                    with self.subTest(requirement=requirement, call=call), self.assertRaises(ValueError) as caught:
                        call(self.natural, requirement, self.api)
                    self.assertNotIsInstance(caught.exception, prices.ZeroMass)
                case = {"samples": []}
                with self.assertRaises(ValueError) as caught:
                    run.cheapest_case(None, self.session, self.natural, self.opened, self.api, requirement, case, None)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
                self.assertNotIn("status", case)

    def test_it_combines_with_other_concepts_and_is_coupled_within_its_own(self):
        winner = self.requirements()[2]
        reference = self.offer(BOTH, SHIRTS)["price_trace"]["reference_minor"]
        shirt = self.priced(BOTH, SHIRTS, max=reference - 1)
        requirement = self.together(winner, shirt, self.held(PLAIN, SHIRTS, availability="in_stock"))
        world, found, record = combined.steer(self.session, self.natural, self.opened, requirement, self.api, Random(3))
        self.assertEqual(record["probability_given_upstream"],
                         prod(self.alone(part) for part in requirement["all"]))
        self.assertAlmostEqual(record["log_probability_given_upstream"],
                               log(record["probability_given_upstream"]), places=9)
        self.assertEqual(record["blocks"][0]["log_probability_given_upstream"],
                         cheapest.model(self.natural, winner, self.api).log_probability)
        for part in requirement["all"]:
            self.assertTrue(combined.KINDS[part["schema"]].satisfied(world, part, self.api))
        self.assertLess(found[0]["listed_below"][0]["price_minor"], found[0]["reference"]["minimum_price_minor"])
        for part in (self.held(SMALL, SHOES, availability="in_stock"), self.priced(PLAIN, SHOES, min=0),
                     self.need(self.first), self.cheapest()):
            for parts in ((winner, part), (part, winner)):
                with self.subTest(part=part), self.assertRaises(blocks.Coupled):
                    combined.prepare(self.natural, self.together(*parts), self.api, Random(0))


class Top:
    """A generator whose uniform draw is as close to one as its bits allow, and that has no float draw."""

    def getrandbits(self, bits):
        return (1 << bits) - 1


def json_of(value):
    return blocks.json.dumps(value, sort_keys=True)
