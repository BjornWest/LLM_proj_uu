"""Tests of the cheapest-available block under the native tasks' other rankings.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_rankings.py
The real commerce producer with stand-in products that carry what the native
priority, relaxation and unit-price oracles read: a reference mass on shoes
(missing on one model) and a net food mass on cat-food packs. Each ranking is
checked with its native oracle, and its probability against redraws under
other seeds read by a rule written out separately in `cheapest.judged`.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from itertools import combinations
from math import log
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from environments.website_world import (catalog_priority_task, catalog_relaxation_task, catalog_shortlist_task,
                                        catalog_unit_price_task)

from experiments.steered_generation import blocks, cheapest, combined, prices, run, shortlist, streams
from experiments.steered_generation.test_stock import INPUTS, RealProducer, stand_in

SHOES, FOOD = "footwear.walking_shoes", "cat_food.dry_food"
SIZE_40 = [{"field": "sku.size_eu", "operator": "eq", "value": 40}]
LIGHT = {"field": "product.facts.reference_mass_g", "operator": "le", "value": 290, "unit": "g"}
LIGHTEST = [{"field": "product.facts.reference_mass_g", "direction": "min", "unit": "g"}]
WIDER = "Allow up to 320 g"
RELAXED = [{"label": WIDER, "drop_fields": [], "replacements": [{**LIGHT, "value": 320}]}]


def faceted(seed, concept_id, brand, product_id, *, earlier, review_count):
    product = stand_in(seed, concept_id, brand, product_id, earlier=earlier, review_count=review_count)
    public = product["public"]
    public["facts"] = {}
    if concept_id == FOOD:
        # Three pack sizes; the smallest costs more per kilogram.
        public["skus"] = [{"sku_id": f"{product_id}-{grams}", "product_id": product_id, "net_mass_g": grams,
                           "reference_price_sek": round(public["reference_price_sek"] * grams / 2000 *
                                                        (1.15 if grams < 1000 else 1))}
                          for grams in (400, 2000, 7000)]
        product["variant_fields"] = {"net_mass_g": {"retail_presentation": {"allowed": ["selector"]}}}
        product["sku_status"] = {sku["sku_id"]: {"sku.net_mass_g": "known"} for sku in public["skus"]}
    elif int(product_id.rsplit("/", 1)[1]) % 4 != 3:
        public["facts"] = {"reference_mass_g": 280 + 30 * (int(product_id.rsplit("/", 1)[1]) % 3)}
    else:
        # Every fourth model has no known reference mass.
        product["catalog_status"] = {"product.facts.reference_mass_g": "unknown"}
    return product


class Ranked(RealProducer):
    product = staticmethod(faceted)
    concept = SHOES
    inputs = {**INPUTS, "concept_ids": [SHOES, FOOD], "tasks": [SHOES]}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scarce = deepcopy(cls.natural)
        cls.scarce["config"]["stock"]["zero_probability"] = {"well_stocked": .85, "patchy": .92, "mostly_depleted": .98}
        cls.readings = {}

    def listed(self):
        """Every SKU of the concept that some retailer lists."""
        return {o["sku_id"] for r in self.natural["retailers"] for o in r["offers"]
                if o["product_id"].split("/")[1] == self.concept}

    def need(self, rid, product, **stated):
        return {"schema": cheapest.VERSION, "concept_id": self.concept, "product_id": product, "retailer_ids": [rid],
                **stated}

    def likeliest(self, world, stated, count=1):
        """The retailer/product pairs most likely to win alone under a ranking, with the probability."""
        scope = cheapest.scope(world, self.need("x", "x", **stated), self.api)
        found = []
        for rid, product in sorted(cheapest.competing(world, None, scope)):
            try:
                found.append((cheapest.model(world, self.need(rid, product, **stated), self.api).probability, rid, product))
            except prices.ZeroMass:
                pass
        return sorted(found, reverse=True)[:count]

    def sold_out(self, world, requirement, scope):
        """The requirement with the likeliest single offer of another pair listed below the winner."""
        found = []
        for retailer in world["retailers"]:
            for offer in retailer["offers"]:
                pair = (retailer["retailer_id"], offer["product_id"])
                if offer["sku_id"] in scope.skus and pair != (requirement["retailer_ids"][0], requirement["product_id"]):
                    stated = {**requirement, "listed_below": [{"retailer_id": pair[0], "sku_id": offer["sku_id"]}]}
                    try:
                        found.append((cheapest.model(world, stated, self.api).probability, offer["offer_id"], stated))
                    except prices.ZeroMass:
                        pass
        return max(found)[2]

    def redraws(self, world, trials):
        if id(world) not in self.readings:
            rid, product = sorted(prices.competing(world, self.concept))[0]
            reading = cheapest.trial(world, self.need(rid, product), self.api).reading
            self.readings[id(world)] = [reading(seed) for seed in range(10 ** 6, 10 ** 6 + trials)]
        return self.readings[id(world)]

    def agrees(self, world, requirement, trials, least):
        """The model's probability and winning ranks against the redraws read by `judged`."""
        block = cheapest.model(world, requirement, self.api)
        seen = Counter(cheapest.judged(found, requirement, block.scope) for found in self.redraws(world, trials))
        del seen[None]
        hits, chance = sum(seen.values()), block.probability
        self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5, requirement)
        self.assertGreater(hits, least, requirement)
        distance = sum(abs(block.shares.get(rank, 0) - seen.get(rank, 0) / hits) for rank in set(block.shares) | set(seen)) / 2
        self.assertLess(distance, .03 + .6 * (len(block.shares) / hits) ** .5)
        self.assertLessEqual(set(seen), set(block.shares))
        return block

    def steered(self, requirement, index=0):
        world, found, record = cheapest.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))
        scope = cheapest.scope(self.natural, requirement, self.api)
        winning = cheapest.judged(cheapest.recorded(world, self.concept), requirement, scope)
        self.assertIsNotNone(winning)
        self.assertEqual(record.get("winning_price_minor", record.get("winning_rank")), cheapest.plain(winning))
        self.assertTrue(cheapest.satisfied(world, requirement, self.api))
        writes = cheapest.footprint(self.natural, requirement, self.api).writes
        self.assertEqual(blocks.background(world, writes), blocks.background(self.natural, writes))
        self.assertEqual(world["status"], streams.STATUS)
        return world, found, record, scope


class PriorityTests(Ranked):
    stated = {"predicates": SIZE_40, "availability": cheapest.PHYSICAL, "priorities": LIGHTEST}

    def test_only_shoes_with_a_known_mass_compete_lightest_first(self):
        scope = cheapest.scope(self.natural, self.need("x", "x", **self.stated), self.api)
        shoes = [p["public"] for p in self.natural["products"] if p["public"]["concept_id"] == SHOES]
        known = {sku["sku_id"] for p in shoes if p["facts"] for sku in p["skus"] if sku["size_eu"] == 40} & self.listed()
        self.assertEqual(scope.skus, known)
        self.assertTrue(any(not p["facts"] for p in shoes) and len({p["facts"].get("reference_mass_g") for p in shoes}) > 2)
        some = sorted(known)[0]
        self.assertEqual(scope.key(some, 500), (Decimal(next(
            p["facts"]["reference_mass_g"] for p in shoes if some.startswith(p["product_id"]))), 500))
        # A lighter shoe at any price is ahead of a heavier one; among equals the price decides.
        self.assertLess((Decimal(280), 99900), (Decimal(310), 100))
        self.assertLess((Decimal(280), 100), (Decimal(280), 200))

    def test_probability_matches_redraws_and_differs_from_ranking_by_price(self):
        chance, rid, product = self.likeliest(self.natural, self.stated)[0]
        block = self.agrees(self.natural, self.need(rid, product, **self.stated), 2500, 300)
        by_price = {key: value for key, value in self.stated.items() if key != "priorities"}
        self.assertNotAlmostEqual(cheapest.model(self.natural, self.need(rid, product, **by_price), self.api).probability,
                                  chance, places=3)
        self.assertTrue(all(type(rank) is tuple and len(rank) == 2 for rank in block.shares))
        # A lighter or equally light and cheaper offer elsewhere is sold out.
        _, rid, product = self.likeliest(self.scarce, self.stated)[0]
        self.agrees(self.scarce, self.sold_out(self.scarce, self.need(rid, product, **self.stated), block.scope), 4000, 30)

    def test_steered_worlds_pass_the_native_priority_oracle(self):
        ranked = self.likeliest(self.natural, self.stated, 3)
        for index, (_, rid, product) in enumerate(ranked):
            with self.subTest(winner=(rid, product)):
                requirement = self.need(rid, product, **self.stated)
                world, found, record, scope = self.steered(requirement, index)
                reference = found["reference"]
                self.assertEqual(found["task"]["kind"], catalog_priority_task.KIND)
                self.assertEqual({(w["retailer_id"], w["product_id"]) for w in reference["winners"]}, {(rid, product)})
                self.assertEqual(record["winning_rank"], [str(Decimal(str(reference["best_priority_values"][0]))),
                                                          reference["tie_price_minor"]])
                self.assertNotIn("winning_price_minor", record)
        # An unlikely winner: a heavier shoe, so every lighter one in the size must be out of stock.
        heavy = max((p["public"] for p in self.natural["products"] if p["public"]["concept_id"] == SHOES and
                     p["public"]["facts"]), key=lambda p: p["facts"]["reference_mass_g"])
        rid = next(r["retailer_id"] for r in self.natural["retailers"]
                   if any(o["product_id"] == heavy["product_id"] and o["sku_id"].endswith("-40") for o in r["offers"]))
        requirement = self.need(rid, heavy["product_id"], **self.stated)
        world, found, record, scope = self.steered(requirement, 5)
        self.assertLess(record["log_probability_given_upstream"], log(1e-6))
        self.assertEqual(found["reference"]["best_priority_values"], [heavy["facts"]["reference_mass_g"]])
        self.assertEqual(self.natural, self.frozen)


class RelaxationTests(Ranked):
    stated = {"predicates": SIZE_40 + [LIGHT], "availability": cheapest.PHYSICAL, "relaxations": RELAXED}

    def test_earlier_criteria_sets_are_barred(self):
        strict = cheapest.scope(self.natural, self.need("x", "x", **self.stated,
                                                       selected=catalog_relaxation_task.ORIGINAL), self.api)
        wider = cheapest.scope(self.natural, self.need("x", "x", **self.stated, selected=WIDER), self.api)
        mass = {sku["sku_id"]: p["public"]["facts"].get("reference_mass_g") for p in self.natural["products"]
                if p["public"]["concept_id"] == SHOES for sku in p["public"]["skus"] if sku["size_eu"] == 40}
        self.assertEqual((strict.skus, strict.barred), ({s for s, m in mass.items() if m and m <= 290}, frozenset()))
        self.assertEqual(wider.barred, strict.skus)
        self.assertEqual(wider.skus, {s for s, m in mass.items() if m and 290 < m <= 320})
        self.assertTrue(strict.skus & self.listed() and wider.skus & self.listed())
        self.assertTrue(strict.skus and wider.skus)

    def test_probability_matches_redraws(self):
        for selected, least in ((catalog_relaxation_task.ORIGINAL, 300), (WIDER, 15)):
            stated = {**self.stated, "selected": selected}
            _, rid, product = self.likeliest(self.scarce, stated)[0]
            with self.subTest(selected=selected):
                self.agrees(self.scarce, self.need(rid, product, **stated), 4000, least)

    def test_steered_worlds_pass_the_native_relaxation_oracle(self):
        for index, selected in enumerate((catalog_relaxation_task.ORIGINAL, WIDER)):
            stated = {**self.stated, "selected": selected}
            _, rid, product = self.likeliest(self.natural, stated)[0]
            with self.subTest(selected=selected):
                world, found, record, scope = self.steered(self.need(rid, product, **stated), index)
                reference = found["reference"]
                self.assertEqual(found["task"]["kind"], catalog_relaxation_task.KIND)
                self.assertEqual((reference["selected_index"], reference["selected_label"]), (index, selected))
                self.assertEqual(reference["minimum_price_minor"], record["winning_price_minor"])
                chosen = reference["scenario_references"][index]
                self.assertEqual({(w["retailer_id"], w["product_id"]) for w in chosen["winners"]}, {(rid, product)})
                # Every offer meeting an earlier set holds nothing anywhere in the steered world.
                barred = [o for r in world["retailers"] for o in r["offers"] if o["sku_id"] in scope.barred]
                self.assertEqual(bool(barred), bool(index))
                self.assertFalse(any(quantity for o in barred for quantity in o["stock_by_source"].values()))
        with self.assertRaises(ValueError):
            cheapest.scope(self.natural, self.need("x", "x", **self.stated, selected="Allow anything"), self.api)


class UnitPriceTests(Ranked):
    concept = FOOD
    inputs = {**INPUTS, "concept_ids": [FOOD, SHOES], "tasks": [FOOD]}
    stated = {"availability": cheapest.PHYSICAL, "unit_basis": catalog_unit_price_task.BASIS}

    def test_packs_are_ranked_by_price_per_gram(self):
        scope = cheapest.scope(self.natural, self.need("x", "x", **self.stated), self.api)
        packs = {sku["sku_id"]: sku["net_mass_g"] for p in self.natural["products"]
                 if p["public"]["concept_id"] == FOOD for sku in p["public"]["skus"]}
        self.assertEqual(scope.skus, set(packs) & self.listed())
        small, large = (next(s for s, grams in sorted(packs.items()) if grams == wanted) for wanted in (400, 7000))
        self.assertEqual(scope.key(small, 10000), Fraction(10000 * 1000, 400))
        self.assertLess(scope.key(large, 100000), scope.key(small, 10000))
        self.assertGreater(len(cheapest.competing(self.natural, None, scope)), 2)

    def test_probability_matches_redraws(self):
        chance, rid, product = self.likeliest(self.natural, self.stated)[0]
        block = self.agrees(self.natural, self.need(rid, product, **self.stated), 3000, 300)
        self.assertTrue(all(isinstance(rank, Fraction) for rank in block.shares))
        by_price = cheapest.model(self.natural, self.need(rid, product, predicates=[
            {"field": "sku.net_mass_g", "operator": "gt", "value": 0, "unit": "g"}], availability=cheapest.PHYSICAL), self.api)
        self.assertNotAlmostEqual(by_price.probability, chance, places=3)
        # A pack that is cheaper per kilogram elsewhere is sold out.
        _, rid, product = self.likeliest(self.scarce, self.stated)[0]
        # Rare even with scarce stock: every pack at that retailer with a better price per kilogram must be out.
        self.agrees(self.scarce, self.sold_out(self.scarce, self.need(rid, product, **self.stated), block.scope), 4000, 4)

    def test_steered_worlds_pass_the_native_unit_price_oracle(self):
        for index, (_, rid, product) in enumerate(self.likeliest(self.natural, self.stated, 2)):
            with self.subTest(winner=(rid, product)):
                world, found, record, scope = self.steered(self.need(rid, product, **self.stated), index)
                reference = found["reference"]
                self.assertEqual(found["task"]["kind"], catalog_unit_price_task.KIND)
                self.assertEqual({(w["retailer_id"], w["product_id"]) for w in reference["winners"]}, {(rid, product)})
                self.assertEqual(record["winning_rank"], reference["minimum_unit_price_exact"])


class ShortlistTests(Ranked):
    stated = {"predicates": SIZE_40, "availability": cheapest.PHYSICAL}

    def listing(self, models, limit=3):
        return {"schema": shortlist.VERSION, "concept_id": SHOES, "limit": limit, "product_ids": list(models),
                **self.stated}

    def likeliest_listing(self, world, candidates):
        """The candidate shortlist with the highest probability on a world, among those that are possible."""
        found = []
        for need in candidates:
            try:
                found.append((shortlist.model(world, need, self.api).log_probability, need["product_ids"], need))
            except prices.ZeroMass:
                pass
        return max(found)[2]

    def natural_models(self):
        """The natural world's models in the native shortlist's order: (price, product)."""
        _, reference = shortlist.reference(self.natural, self.listing(["x"], 10), self.api)
        return [(row["price_minor"], row["product_id"]) for row in reference["all_models"]]

    def agrees(self, world, requirement, trials, least):
        block = shortlist.model(world, requirement, self.api)
        seen = Counter(shortlist.listing(found, requirement, block.scope) for found in self.redraws(world, trials))
        del seen[None]
        hits, chance = sum(seen.values()), block.probability
        self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5, requirement)
        self.assertGreater(hits, least, requirement)
        self.assertLessEqual(set(seen), set(block.shares))
        if hits > 200:
            distance = sum(abs(block.shares.get(c, 0) - seen.get(c, 0) / hits) for c in set(block.shares) | set(seen)) / 2
            self.assertLess(distance, .03 + .6 * (len(block.shares) / hits) ** .5)
        return block

    def test_a_shortlist_of_one_is_the_cheapest_model_at_any_of_its_retailers(self):
        """Two computations of one probability: this block with limit 1, and the cheapest-available block."""
        for _, model in self.natural_models()[:3]:
            sellers = sorted({r["retailer_id"] for r in self.natural["retailers"] for o in r["offers"]
                              if o["product_id"] == model and o["sku_id"].endswith("-40")})
            other = 0
            for size in range(1, len(sellers) + 1):
                for group in combinations(sellers, size):
                    try:
                        other += cheapest.model(self.natural, {
                            "schema": cheapest.VERSION, "concept_id": SHOES, "product_id": model,
                            "retailer_ids": list(group), **self.stated}, self.api).probability
                    except prices.ZeroMass:
                        pass
            with self.subTest(model=model, sellers=len(sellers)):
                self.assertAlmostEqual(shortlist.model(self.natural, self.listing([model], 1), self.api).probability,
                                       other, places=12)

    def test_probability_matches_redraws(self):
        models = [model for _, model in self.natural_models()]
        self.assertGreater(len(models), 4)
        self.agrees(self.natural, self.listing(models[:3]), 2500, 100)
        self.agrees(self.natural, self.listing(models[:2], 2), 2500, 100)
        # A tie at the cutoff: four models for a limit of three.
        tied = self.likeliest_listing(self.natural, [self.listing(models[:2] + list(pair))
                                                     for pair in combinations(models[2:6], 2)])
        self.agrees(self.natural, tied, 2500, 4)
        self.agrees(self.scarce, self.listing(models[:3]), 4000, 20)
        # Fewer models than the limit: nothing else in the size has stock anywhere.
        bare = deepcopy(self.natural)
        bare["config"]["stock"]["zero_probability"] = dict.fromkeys(bare["config"]["stock"]["zero_probability"], .97)
        few = self.likeliest_listing(bare, [self.listing(list(group), 4) for group in combinations(models[:6], 2)])
        block = self.agrees(bare, few, 4000, 20)
        self.assertEqual(set(block.shares), {shortlist.EVERY})

    def test_samples_match_rejection_sampling(self):
        models = [model for _, model in self.natural_models()]
        requirement = self.listing(models[:3])
        block = shortlist.model(self.natural, requirement, self.api)
        rejection = [found for found in self.redraws(self.natural, 2500)
                     if shortlist.listing(found, requirement, block.scope) is not None]
        steered = [cheapest.planned(block, shortlist.sample(block, Random(index))[1]) for index in range(1200)]
        self.assertGreater(len(rejection), 100)
        for found in steered[:100]:
            self.assertIsNotNone(shortlist.listing(found, requirement, block.scope))

        def compare(statistic):
            ours, theirs = [statistic(found) for found in steered], [statistic(found) for found in rejection]
            mean = lambda values: sum(values) / len(values)
            spread = (sum((value - mean(theirs)) ** 2 for value in theirs) / len(theirs)) ** .5
            self.assertLessEqual(abs(mean(ours) - mean(theirs)),
                                 4 * spread * (1 / len(ours) + 1 / len(theirs)) ** .5)

        # The redraws read every pair of the concept; the block is the pairs with a size-40 offer.
        rows = lambda found: [row for row in found["offers"].values()
                              if (row["retailer_id"], row["product_id"]) in block.places]
        compare(lambda found: shortlist.listing(found, requirement, block.scope))
        compare(lambda found: sum(sum(row["stock_by_source"].values()) for row in rows(found)))
        compare(lambda found: sum(not any(row["stock_by_source"].values()) for row in rows(found)))
        compare(lambda found: sum(row["supplier_order"] for row in rows(found)))
        compare(lambda found: sum(row["price_minor"] for row in rows(found)) / len(rows(found)))
        for model in models[:4]:
            # How many of the named and of the next model's size-40 offers hold stock, and their lowest price.
            compare(lambda found: sum(any(row["stock_by_source"].values()) for row in rows(found)
                                      if row["product_id"] == model and row["sku_id"] in block.scope.skus))
            compare(lambda found: min(row["price_minor"] for row in rows(found) if row["product_id"] == model))

    def test_steered_worlds_pass_the_native_shortlist_oracle(self):
        models = [model for _, model in self.natural_models()]
        tied = self.likeliest_listing(self.natural, [self.listing(models[:2] + list(pair))
                                                     for pair in combinations(models[2:6], 2)])
        few = self.listing(models[1:3], 4)
        for index, requirement in enumerate((self.listing(models[:3]), self.listing(models[2:5]), tied, few)):
            with self.subTest(requirement=requirement["product_ids"], limit=requirement["limit"]):
                world, found, record = shortlist.steer(self.session, self.natural, self.opened, requirement,
                                                       self.api, Random(index))
                reference, scope = found["reference"], cheapest.scope(self.natural, requirement, self.api)
                self.assertEqual(found["task"]["kind"], catalog_shortlist_task.KIND)
                self.assertEqual({m["product_id"] for m in reference["selected_models"]}, set(requirement["product_ids"]))
                self.assertEqual(shortlist.listing(cheapest.recorded(world, SHOES), requirement, scope), record["cutoff"])
                if record["cutoff"] == shortlist.EVERY:
                    self.assertEqual(reference["population_count"], len(requirement["product_ids"]))
                else:
                    self.assertEqual(reference["cutoff_price_minor"], record["cutoff"])
                    at_cutoff = [m for m in reference["selected_models"] if m["price_minor"] == record["cutoff"]]
                    self.assertGreaterEqual(len(at_cutoff), len(requirement["product_ids"]) - requirement["limit"] + 1)
                writes = shortlist.footprint(self.natural, requirement, self.api).writes
                self.assertEqual(blocks.background(world, writes), blocks.background(self.natural, writes))
                self.assertTrue(shortlist.satisfied(world, requirement, self.api))
        reading = shortlist.trial(self.natural, self.listing(models[:3]), self.api)
        redrawn = blocks.redraw(self.session, self.natural, [reading], 905)
        self.assertEqual((redrawn.identical, redrawn.agreed), ([True], [True]))
        self.assertEqual(self.natural, self.frozen)

    def test_shortlists_are_validated_and_coupled_with_their_concept(self):
        models = [model for _, model in self.natural_models()]
        good = self.listing(models[:3])
        food = next(p["public"]["product_id"] for p in self.natural["products"] if p["public"]["concept_id"] == FOOD)
        for bad in ({**good, "limit": 0}, {**good, "limit": 11}, {**good, "limit": "3"}, {**good, "product_ids": []},
                    {**good, "product_ids": models[:1] * 2}, {**good, "product_ids": ["nothing"]},
                    {**good, "product_ids": [food]}, {**good, "concept_id": "no.such"},
                    {**good, "priorities": LIGHTEST}, {**good, "retailer_ids": ["x"]},
                    {key: value for key, value in good.items() if key != "predicates"},
                    {**good, "availability": cheapest.BRANCH}):
            for call in (shortlist.model, shortlist.footprint, shortlist.trial):
                with self.subTest(bad=bad, call=call), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        # No shoe is listed in this size, so no named model has a competing offer.
        with self.assertRaises(prices.ZeroMass) as caught:
            shortlist.model(self.natural, {**good, "predicates": [{"field": "sku.size_eu", "operator": "eq", "value": 47}]},
                            self.api)
        self.assertEqual(caught.exception.reason, "not_listed")
        winner = {"schema": cheapest.VERSION, "concept_id": SHOES, "product_id": models[0],
                  "retailer_ids": [next(r["retailer_id"] for r in self.natural["retailers"]
                                        if any(o["product_id"] == models[0] for o in r["offers"]))]}
        with self.assertRaises(blocks.Coupled):
            combined.prepare(self.natural, {"schema": combined.VERSION, "all": [good, winner]}, self.api, Random(0))


class RankingRules(Ranked):
    def test_rankings_are_validated(self):
        _, rid, product = self.likeliest(self.natural, PriorityTests.stated)[0]
        good = self.need(rid, product, **PriorityTests.stated)
        for bad in ({**good, "unit_basis": catalog_unit_price_task.BASIS}, {**good, "relaxations": RELAXED},
                    {**good, "selected": WIDER}, {**good, "priorities": []},
                    {**good, "priorities": [{"field": "product.facts.no_such", "direction": "min"}]},
                    {**good, "availability": cheapest.BRANCH, "city": "Uppsala"},
                    {key: value for key, value in good.items() if key != "predicates"},
                    self.need(rid, product, **RelaxationTests.stated),
                    self.need(rid, product, **RelaxationTests.stated, selected=3),
                    self.need(rid, product, unit_basis=catalog_unit_price_task.BASIS),
                    self.need(rid, product, predicates=SIZE_40, unit_basis="per_item")):
            for call in (cheapest.model, cheapest.footprint, cheapest.trial):
                with self.subTest(bad=sorted(set(bad) - {"schema", "concept_id", "product_id", "retailer_ids"}),
                                  call=call), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)

    def test_the_runner_samples_and_checks_every_ranking(self):
        args = SimpleNamespace(samples=1, producer_redraws=1, validate_trials=300)
        for stated in (PriorityTests.stated, {**RelaxationTests.stated, "selected": catalog_relaxation_task.ORIGINAL},
                       {**RelaxationTests.stated, "selected": WIDER}):
            _, rid, product = self.likeliest(self.natural, stated)[0]
            case = {"samples": [], "requirement_sha256": "x"}
            with self.subTest(stated=sorted(stated)), TemporaryDirectory() as folder:
                run.cheapest_case(args, self.session, self.natural, self.opened, self.api,
                                  self.need(rid, product, **stated), case, lambda index: Path(folder) / str(index))
                self.assertEqual(case["status"], "sampled")
                sample = case["samples"][0]
                self.assertEqual("winning_rank" in sample, "priorities" in stated)
                self.assertEqual(sample["winner_count"] > 0, True)
                self.assertTrue(case["validation"]["within_four_standard_errors"])
                self.assertEqual(case["producer_redraws"]["identical_to_reading"], 1)

    def test_the_runner_samples_and_checks_a_shortlist_and_reports_numerical_limits(self):
        args = SimpleNamespace(samples=1, producer_redraws=1, validate_trials=300)
        _, reference = shortlist.reference(self.natural, {"concept_id": SHOES, "limit": 3, **ShortlistTests.stated}, self.api)
        requirement = {"schema": shortlist.VERSION, "concept_id": SHOES, "limit": 3, **ShortlistTests.stated,
                       "product_ids": [m["product_id"] for m in reference["selected_models"]]}
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.shortlist_case(args, self.session, self.natural, self.opened, self.api, requirement, case,
                               lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], case["samples"][0]["selected_models"]), ("sampled", 3))
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertEqual(case["producer_redraws"]["identical_to_reading"], 1)
        for module, call in ((shortlist, run.shortlist_case), (run.listed, run.listed_case)):
            case = {"samples": [], "requirement_sha256": "x"}
            need = requirement if module is shortlist else {
                "schema": run.listed.VERSION, "product_id": requirement["product_ids"][0],
                "retailer_ids": [next(r["retailer_id"] for r in self.natural["retailers"] if any(
                    o["product_id"] == requirement["product_ids"][0] for o in r["offers"]))]}
            with mock.patch.object(module, "steer", side_effect=blocks.NumericalLimit("too small")):
                call(args, self.session, self.natural, self.opened, self.api, need, case, None)
            self.assertEqual((case["status"], case["reason"], case["samples"]), ("refused", "numerical_limit", []))

    def test_a_comparison_site_that_lists_nothing_leaves_a_listed_requirement_unmet(self):
        product = next(o["product_id"] for r in self.natural["retailers"] for o in r["offers"])
        rid = next(r["retailer_id"] for r in self.natural["retailers"] if any(o["product_id"] == product for o in r["offers"]))
        requirement = {"schema": run.listed.VERSION, "product_id": product, "retailer_ids": [rid],
                       "comparison_site_id": "comparison-00", "surrounding": {"model_probability": 0}}
        with self.assertRaises(prices.ZeroMass):
            run.listed.model(self.natural, requirement, self.api)
        self.assertFalse(run.listed.satisfied(self.natural, requirement, self.api))
        with self.assertRaises(blocks.Unmet):
            run.listed.check(self.natural, requirement, self.api)

    def test_two_rankings_in_two_concepts_hold_together(self):
        _, rid, product = self.likeliest(self.natural, PriorityTests.stated)[0]
        shoe = self.need(rid, product, **PriorityTests.stated)
        food = cheapest.scope(self.natural, {**self.need("x", "x", **UnitPriceTests.stated), "concept_id": FOOD}, self.api)
        seller, pack = sorted(cheapest.competing(self.natural, None, food))[0]
        packs = {**self.need(seller, pack, **UnitPriceTests.stated), "concept_id": FOOD}
        requirement = {"schema": combined.VERSION, "all": [shoe, packs]}
        world, found, record = combined.steer(self.session, self.natural, self.opened, requirement, self.api, Random(1))
        self.assertAlmostEqual(record["log_probability_given_upstream"], sum(
            cheapest.model(self.natural, part, self.api).log_probability for part in (shoe, packs)), places=12)
        for part in (shoe, packs):
            self.assertTrue(cheapest.satisfied(world, part, self.api))
        with self.assertRaises(blocks.Coupled):
            combined.prepare(self.natural, {"schema": combined.VERSION, "all": [shoe, self.need(rid, product)]},
                             self.api, Random(0))
