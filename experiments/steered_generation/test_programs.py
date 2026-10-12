"""Tests of the review block on concepts whose reviews a package's review program writes.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_programs.py
Products, their review programs and the commerce pass are the producer's own;
the native review-summary task reads the steered worlds. The T-shirt package
wraps its review program in checks that make one review take most of a
second, so tests that run it through the producer use few of its products.
"""
from collections import Counter
from copy import deepcopy
from itertools import permutations
from math import erfc, nextafter, prod, sqrt
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from environments.website_world import basic_offer_task, catalog_review_task
from experiments.accepted_catalog_commerce import model as commerce, package_export
from experiments.footwear_world_pilot import model as native
from experiments.world_sampling_defaults import model as population

from experiments.steered_generation import blocks, combined, prices, programs, reviews, run, stock, streams, variants

TRAINERS, SHIRTS, TABLETS = "footwear.casual_trainers", "tops.t_shirts", "tablets.everyday_media_tablets"
INPUTS = {"seed": 5, "concept_ids": [TRAINERS, SHIRTS, TABLETS], "tasks": [TRAINERS], "controls": None,
          "city_id": "uppsala", "review_count": 16}


class Programs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = SimpleNamespace(basic=basic_offer_task, native=native, population=population,
                                  commerce=commerce, package_export=package_export)
        cls.session = streams.Session(cls.api, INPUTS)
        cls.natural, cls.opened = cls.session.generate()
        cls.frozen = deepcopy(cls.natural)
        cls.products = {concept: sorted(p["public"]["product_id"] for p in cls.natural["products"]
                                        if p["public"]["concept_id"] == concept) for concept in INPUTS["concept_ids"]}
        cls.declared = {concept: catalog_review_task.ReviewInventory(concept) for concept in INPUTS["concept_ids"]}

    def tearDown(self):
        self.assertEqual(self.natural, self.frozen, "A test changed the natural world")

    def topic(self, concept, aspect):
        return next(row for row in self.declared[concept].topics if row["aspect"] == aspect)

    def need(self, concept=TRAINERS, aspect="everyday_comfort", product=0, **stated):
        return {"schema": reviews.VERSION, "product_id": self.products[concept][product],
                "topic": self.topic(concept, aspect), **stated}

    def item(self, world, product_id):
        return next(p for p in world["products"] if p["public"]["product_id"] == product_id)

    def place(self, *args, **kwargs):
        return reviews.site(self.natural, self.need(*args, verdict="tie", **kwargs), self.api)

    def cases(self):
        """One topic for every way a review program decides what a review says."""
        return [(TRAINERS, "value"),             # a normal draw read through a threshold
                (TRAINERS, "everyday_comfort"),  # a weighted choice whose weights follow the rating
                (SHIRTS, "value"),               # the price paid is the option's, and the option is drawn
                (SHIRTS, "wear_feel"),
                (TABLETS, "value"),
                (TABLETS, "pen_marks")]          # eligible only for some owners, a draw of its own

    def requirements(self):
        return [self.need(verdict="more_negative"), self.need(TRAINERS, "value", 1, verdict="tie", min_assessed=2),
                # Rare counts: praise and not one complaint; several comments on a topic few owners can raise.
                self.need(positive={"min": 5}, negative={"max": 0}),
                self.need(TABLETS, "pen_marks", verdict="more_positive", min_assessed=3),
                self.need(TABLETS, "value", negative={"min": 4}),
                self.need(SHIRTS, "wear_feel", verdict="more_negative", negative={"min": 3}),
                # Against the stars: complaints under a high mean rating; a low mean with nothing said of the topic.
                self.need(verdict="more_negative", mean_rating={"min": 4}),
                self.need(TABLETS, "value", verdict="insufficient_evidence", mean_rating={"max": 2.5})]


class ModelTests(Programs):
    def test_the_reading_of_every_review_is_what_the_producer_recorded(self):
        for concept, products in self.products.items():
            self.assertTrue(products, concept)
            for product in range(min(2, len(products))):
                for topic in self.declared[concept].topics:
                    with self.subTest(concept=concept, product=product, aspect=topic["aspect"]):
                        place = self.place(concept, topic["aspect"], product)
                        self.assertIs(place.reader, programs)
                        self.assertEqual(place.count, INPUTS["review_count"])
                        rows = programs.written(self.natural, place)
                        self.assertEqual(rows, [programs.redrawn(place, index) for index in range(place.count)])
                        self.assertTrue(all({name for name, _ in row[0]} == place.drawn for row in rows))
                        found = reviews.check(self.natural, self.need(concept, topic["aspect"], product, positive={"min": 0}),
                                              self.api)
                        self.assertEqual((found["counts"]["positive"], found["counts"]["negative"]),
                                         reviews.counted(place, rows))
                        self.assertEqual(found["written_review_count"], sum(
                            bool(row["text"].strip()) for row in self.item(self.natural, place.product_id)["reviews"]))

    def test_the_plain_copy_draws_what_the_producers_own_program_draws(self):
        for concept, trials in ((TRAINERS, 150), (TABLETS, 150), (SHIRTS, 12)):
            with self.subTest(concept=concept):
                item = self.item(self.natural, self.products[concept][0])
                found, caught, real = programs.program(self.natural, item, self.api), [], package_export._package
                package_export._package = lambda *args: caught.append(real(*args)) or caught[-1]
                try:
                    package_export.sample(item["sample_seed"], concept, next(
                        b for b in self.natural["brands"] if b["brand_id"] == item["public"]["brand_id"]),
                        item["public"]["product_id"], earlier=(), review_count=0)
                finally:
                    package_export._package = real
                stage = caught[0].make_review() if hasattr(caught[0], "make_review") else caught[0].programs["review"]
                self.assertEqual(hasattr(caught[0], "make_review"), concept == SHIRTS)
                for seed in range(10 ** 6, 10 ** 6 + trials):
                    theirs = stage.sample(seed, inputs=deepcopy(found.entities))
                    mine = found.twin.sample(seed, inputs=deepcopy(found.entities))
                    self.assertEqual((mine["trace"], mine["entities"]), (theirs["trace"], theirs["entities"]))
                    for pool in stage.document["language"]:
                        self.assertEqual(found.twin._eval(pool["when"], mine["entities"]),
                                         stage._eval(pool["when"], theirs["entities"]))

    def test_one_reviews_class_probabilities_match_other_seeds(self):
        trials = 6000
        for concept, aspect in self.cases():
            with self.subTest(concept=concept, aspect=aspect):
                place = self.place(concept, aspect)
                cells, share = programs.cells(place), programs.shares(place)
                self.assertAlmostEqual(sum(cells.values()), 1, places=12)
                self.assertEqual((len(cells), share), (15, reviews.marginal(cells)))
                block = Counter(programs.redrawn(place, seed % place.count, 10 ** 6 + seed)[:0:-1] for seed in range(trials))
                # Whole reviews under seeds of their own: nothing here decides which draws matter.
                whole = Counter()
                for seed in range(trials):
                    entities = place.program.twin.sample(10 ** 7 + seed, inputs=deepcopy(place.program.entities))["entities"]
                    whole[entities["review"]["rating"], programs.told(place, entities)] += 1
                for seen in (block, whole):
                    for cell, chance in cells.items():
                        self.assertLess(abs(seen[cell] / trials - chance), 4.5 * (chance * (1 - chance) / trials) ** .5 + 1e-9, cell)
                    for name, chance in share.items():
                        hits = sum(times for (_, own), times in seen.items() if own == name)
                        self.assertLess(abs(hits / trials - chance), 4.5 * (chance * (1 - chance) / trials) ** .5, name)
                self.assertGreater(sum(times for (_, own), times in block.items() if own != reviews.REST), 30)
        # A topic only some owners can raise is rarer than one all can; the price paid moves the value shares.
        pen, touch = (programs.shares(self.place(TABLETS, aspect)) for aspect in ("pen_marks", "touch_navigation"))
        self.assertLess(pen[reviews.POSITIVE] + pen[reviews.NEGATIVE], (touch[reviews.POSITIVE] + touch[reviews.NEGATIVE]) / 2)
        value, comfort = (programs.shares(self.place(TRAINERS, aspect)) for aspect in ("value", "everyday_comfort"))
        self.assertNotAlmostEqual(value[reviews.POSITIVE] / (value[reviews.POSITIVE] + value[reviews.NEGATIVE]),
                                  comfort[reviews.POSITIVE] / (comfort[reviews.POSITIVE] + comfort[reviews.NEGATIVE]), places=3)

    def test_only_the_draws_the_topic_depends_on_are_in_the_block(self):
        place = self.place(TRAINERS, "everyday_comfort")
        self.assertEqual(place.drawn, {"rating", "topics", "sentiment_everyday_comfort"})
        self.assertEqual(place.block, {"rating", "sentiment_everyday_comfort", "topics/length", "topics/value",
                                       "topics/other/0", "topics/other/1", "topics/other/2"})
        self.assertEqual(self.place(TRAINERS, "value").drawn, {"rating", "topics", "value_favourability"})
        # The option reviewed is drawn where the statement's condition or the price paid names it.
        self.assertIn("tested_sku", self.place(SHIRTS, "value").drawn)
        # No program in git lets another draw set the rating's chances: the rating can be redrawn alone.
        self.assertTrue(all(self.place(concept, aspect).staged for concept, aspect in self.cases()))
        self.assertIn("tested_sku", self.place(TABLETS, "value").drawn)
        self.assertLessEqual({"owner_pen", "owner_keyboard", "topic_applicability"}, self.place(TABLETS, "pen_marks").drawn)
        self.assertEqual(programs.keys(place, 3), [(streams.PROGRAM, place.seed, 3, name) for name in sorted(place.block)])

    def test_topic_sets_match_enumeration_and_the_producers_draw(self):
        policy = {"effective_weights": {"value": 1.0, "a": 1.3, "b": 1.0, "c": .4, "d": 2.0, "e": 0},
                  "value_probability_given_comment": .3}
        lengths = {"0": 5, "1": 2, "2": 2, "3": 1, "4": 0}
        for eligible in (list(policy["effective_weights"]), ["a", "b", "c", "d", "e"]):
            found = programs.topic_sets(policy, eligible, lengths)
            others = {name: weight for name, weight in policy["effective_weights"].items() if name != "value" and weight}
            direct, value = Counter(), .3 if "value" in eligible else 0
            for slots, weight in lengths.items():
                for has, chance in ((1, value), (0, 1 - value)) if int(slots) else ((0, 1),):
                    for order in permutations(others, int(slots) - has):
                        left, mass = sum(others.values()), weight / 10 * chance
                        for name in order:
                            mass, left = mass * others[name] / left, left - others[name]
                        direct[tuple(sorted([*order, *(["value"] * has)]))] += mass
            self.assertEqual(set(found), {topics for topics, mass in direct.items() if mass})
            for topics, mass in found.items():
                self.assertAlmostEqual(mass, direct[topics], places=12, msg=topics)
            self.assertAlmostEqual(sum(found.values()), 1, places=12)
        # A value probability outside zero to one acts as certainty either way, as the producer's comparison does.
        for chance, has in ((1.5, True), (-.2, False)):
            found = programs.topic_sets({**policy, "value_probability_given_comment": chance}, ["value", "a", "b"], {"1": 1})
            self.assertEqual(all("value" in topics for topics in found), has)
        # The producer's own draw of the step, for a product of the world.
        place, trials = self.place(TRAINERS, "everyday_comfort"), 12000
        twin, step = place.program.twin, next(step for step in place.steps if step["id"] == "topics")
        context = deepcopy(place.program.entities)
        for path, definition in twin.fields.items():
            if "constant" in definition:
                place.program.module.set_path(context, path, deepcopy(definition["constant"]))
        model = {tuple(value): share for value, share in programs.outcomes(place, step, context)}
        self.assertAlmostEqual(sum(model.values()), 1, places=12)
        seen = Counter(tuple(twin.draw(twin.resolve(step, context), seed, "topics", context)[0]) for seed in range(trials))
        self.assertLessEqual(set(seen), set(model))
        for topics, chance in model.items():
            self.assertLess(abs(seen[topics] / trials - chance), 4.5 * (chance * (1 - chance) / trials) ** .5, topics)

    def test_a_normal_draws_tails_match_the_producers_draw(self):
        place = self.place(TRAINERS, "value")
        twin, step = place.program.twin, next(step for step in place.steps if step["id"] == "value_favourability")
        context, trials = deepcopy(place.program.entities), 20000
        for path, definition in twin.fields.items():
            if "constant" in definition:
                place.program.module.set_path(context, path, deepcopy(definition["constant"]))
        for other in place.steps:
            if "derive" in other and other["id"] != "sentiment_value":
                place.program.module.set_path(context, other["target"], twin._eval(other["derive"], context))
        self.assertEqual(place.bounds, {"value_favourability": [.5]})
        for rating in (1, 3, 4):
            place.program.module.set_path(context, "review.rating", rating)
            params = twin.resolve(step, context)
            above, below = programs.tails(params, .5)
            self.assertAlmostEqual(above + below, 1, places=12)
            hits = sum(twin.draw(params, seed, "value_favourability", context)[0] >= .5 for seed in range(trials))
            self.assertLess(abs(hits / trials - above), 4.5 * (above * below / trials) ** .5 + 1e-9, rating)
        # The bound is the draw's own: the smallest number whose clipped, rounded value reaches the stated one.
        params = {"min": 0, "max": 1, "mean": .42, "sd": .1, "bounds_mode": "clip", "round_to": .1}
        ended = lambda x: round(x / .1) * .1
        above, _ = programs.tails(params, .5)
        near = [.45]
        for _ in range(4):
            near = [nextafter(near[0], 0), *near, nextafter(near[-1], 1)]
        edge = next(x for x in near[1:] if ended(x) >= .5)
        self.assertLess(ended(nextafter(edge, 0)), .5)
        self.assertEqual(above, erfc((edge - .42) / (.1 * sqrt(2))) / 2)
        self.assertEqual(programs.tails({**params, "round_to": None}, .5)[0], erfc((.5 - .42) / (.1 * sqrt(2))) / 2)
        self.assertEqual(programs.tails(params, 0), (1.0, 0.0))
        self.assertEqual(programs.tails(params, 1.05), (0.0, 1.0))
        self.assertGreater(programs.tails(params, 1)[0], 0)
        # Far tails keep their own precision.
        self.assertEqual(programs.tails({**params, "mean": 10, "sd": .5}, .5)[0], 1.0)
        self.assertLess(0, programs.tails({**params, "mean": 10, "sd": .5}, .5)[1])
        self.assertLess(programs.tails({**params, "mean": 10, "sd": .5}, .5)[1], 1e-50)
        for bad in ({**params, "bounds_mode": "truncate"}, {**params, "sd": 0}, {**params, "min": 1}):
            with self.assertRaises(ValueError):
                programs.tails(bad, .5)

    def test_probabilities_match_other_seeds(self):
        for requirement, trials in zip(self.requirements(), (2500, 2500, 2500, 1200, 1200, 600, 2500, 1200)):
            with self.subTest(requirement=requirement):
                block = reviews.model(self.natural, requirement, self.api)
                hits, chance = sum(reviews.empirical(self.natural, requirement, self.api, trials, 10 ** 6).values()), block.probability
                self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5 + 1e-9)
                self.assertGreater(hits, 100 if chance > .05 else -1)
        for concept, aspect in self.cases():
            for least in (1, 3):
                total = sum(reviews.model(self.natural, self.need(concept, aspect, verdict=verdict, min_assessed=least),
                                          self.api).probability for verdict in reviews.VERDICTS)
                self.assertAlmostEqual(total, 1, places=10)

    def test_a_sample_redraws_every_review_and_only_its_block(self):
        requirement = self.need(negative={"min": 6})
        place = reviews.site(self.natural, requirement, self.api)
        step = reviews.prepare(self.natural, requirement, self.api, Random(3))
        self.assertEqual(set(step.script), {key for index in range(place.count) for key in programs.keys(place, index)})
        seeds = [{step.script[key].seed for key in programs.keys(place, index)} for index in range(place.count)]
        self.assertTrue(all(len(found) == 1 for found in seeds))
        self.assertEqual(len(set.union(*seeds)), place.count)
        self.assertEqual((step.writes, step.reads), ({("reviews", "", self.products[TRAINERS][0])}, set()))
        self.assertLess(step.probability, 1e-3)


class ProducerTests(Programs):
    def test_steered_worlds_hold_through_the_producer_and_the_native_review_task(self):
        for index, requirement in enumerate(self.requirements()):
            with self.subTest(requirement=requirement):
                product = requirement["product_id"]
                world, found, record = reviews.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))
                counts = found["counts"]
                self.assertTrue(reviews.agreed(requirement, counts["positive"], counts["negative"]))
                self.assertEqual(record["steered_counts"], {"positive": counts["positive"], "negative": counts["negative"]})
                self.assertEqual((world["status"], record["reviews"]), (streams.STATUS, INPUTS["review_count"]))
                # The native task itself, built here and not by the module under test.
                concept = self.item(world, product)["public"]["concept_id"]
                spec = {"kind": catalog_review_task.KIND, "concept_id": concept, "operation": "topic_counts",
                        "product_index": self.products[concept].index(product), "topic": requirement["topic"],
                        "min_assessed": requirement.get("min_assessed", 1)}
                reference = catalog_review_task.reference(
                    world, catalog_review_task.make(world, spec, inventory=self.declared[concept]),
                    inventory=self.declared[concept])
                self.assertEqual((reference["subject"]["product_id"], reference["counts"]), (product, counts))
                self.assertEqual(requirement.get("verdict", reference["verdict"]), reference["verdict"])
                if "mean_rating" in requirement:
                    stars = [row["rating"] for row in self.item(world, product)["reviews"]]
                    self.assertEqual((record["steered_star_total"], found["mean_rating"]), (sum(stars), sum(stars) / len(stars)))
                    self.assertTrue(requirement["mean_rating"].get("min", 1) <= found["mean_rating"]
                                    <= requirement["mean_rating"].get("max", 5))
                # Only this product's reviews moved, and in them only what the block's draws reach.
                place = reviews.site(self.natural, requirement, self.api)
                before, after = self.item(self.natural, product), self.item(world, product)
                self.assertEqual("tested_sku" in place.drawn, concept != TRAINERS)
                if concept == TRAINERS:
                    self.assertEqual([row["sku_id"] for row in after["reviews"]], [row["sku_id"] for row in before["reviews"]])
                self.assertNotEqual([row["private_trace"] for row in after["reviews"]],
                                    [row["private_trace"] for row in before["reviews"]])
                self.assertEqual({k: v for k, v in after.items() if k not in ("reviews", "rating_summary")},
                                 {k: v for k, v in before.items() if k not in ("reviews", "rating_summary")})
                self.assertEqual([p for p in world["products"] if p is not after],
                                 [p for p in self.natural["products"] if p is not before])
                self.assertEqual(world["retailers"], self.natural["retailers"])
        self.assertEqual(self.session.generate()[0]["world_id"], self.natural["world_id"])

    def test_repeated_samples_differ(self):
        requirement = self.need(verdict="more_positive")
        worlds = [reviews.steer(self.session, self.natural, self.opened, requirement, self.api, Random(seed))[0]
                  for seed in range(4)]
        self.assertEqual(len({world["world_id"] for world in worlds}), 4)

    def test_redraws_through_the_producer_equal_the_reading(self):
        for requirement, seeds in ((self.requirements()[0], range(900, 904)), (self.requirements()[3], range(900, 902)),
                                   (self.requirements()[5], range(900, 901))):
            with self.subTest(requirement=requirement):
                reading = reviews.trial(self.natural, requirement, self.api)
                for seed in seeds:
                    found = blocks.redraw(self.session, self.natural, [reading], seed)
                    self.assertEqual((found.identical, found.agreed), ([True], [True]))
                    self.assertEqual(found.satisfied, reading.holds(seed))

    def test_it_combines_with_other_products_and_with_commerce_blocks(self):
        first, second = self.need(verdict="more_negative"), self.need(TABLETS, "value", verdict="more_negative")
        retailer = next(r for r in self.natural["retailers"] if r["offers"])
        held = {"schema": stock.VERSION, "retailer_id": retailer["retailer_id"], "sku_id": retailer["offers"][0]["sku_id"],
                "availability": "in_stock"}
        together = {"schema": combined.VERSION, "all": [first, second, held]}
        world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(4))
        self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in together["all"]))
        chances = [reviews.model(self.natural, part, self.api).probability for part in (first, second)]
        self.assertAlmostEqual(record["probability_given_upstream"],
                               prod(chances) * stock.model(self.natural, held, self.api).probability, places=12)
        for seed in range(700, 702):
            found = combined.redraw(self.session, self.natural, {"schema": combined.VERSION, "all": [first, second]}, self.api, seed)
            self.assertEqual((found.identical, found.agreed), ([True, True], [True, True]))
        with self.assertRaises(blocks.Coupled) as caught:
            combined.prepare(self.natural, {"schema": combined.VERSION, "all": [
                first, self.need(TRAINERS, "value", positive={"min": 1})]}, self.api, Random(0))
        self.assertIn(self.products[TRAINERS][0], str(caught.exception))

    def test_the_runner_samples_and_checks_a_review_requirement(self):
        args = SimpleNamespace(samples=2, producer_redraws=2, validate_trials=1500)
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.reviews_case(args, self.session, self.natural, self.opened, self.api,
                             self.need(TRAINERS, "value", verdict="tie", min_assessed=2), case,
                             lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], len(case["samples"])), ("sampled", 2))
        self.assertTrue(all(sample["verdict"] == "tie" for sample in case["samples"]))
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertEqual(case["producer_redraws"]["identical_to_reading"], 2)

    def test_candidates_for_the_review_summary_task(self):
        task = {"kind": "summarize_product_reviews", "concept_id": TABLETS, "operation": "topic_counts", "product_index": 0,
                "topic": self.topic(TABLETS, "reading"), "min_assessed": 2}
        found = variants.of(self.natural, task, self.api)
        self.assertEqual({row["name"] for row in found[:4]}, {"verdict_" + verdict for verdict in reviews.VERDICTS})
        self.assertAlmostEqual(sum(2.718281828459045 ** row["log_probability"] for row in found[:4]), 1, places=10)
        self.assertEqual([row["name"] for row in found[4:]], ["high_stars_verdict_more_negative", "low_stars_verdict_more_positive"])
        for index, row in enumerate(found):
            world, seen, _ = reviews.steer(self.session, self.natural, self.opened, row["requirement"], self.api, Random(index))
            self.assertTrue(row["name"].endswith("verdict_" + seen["verdict"]))
            limits = row["requirement"].get("mean_rating", {})
            self.assertTrue(limits.get("min", 1) <= seen.get("mean_rating", 3) <= limits.get("max", 5))


def pool(document, name):
    return next(row for row in document["language"] if row["id"] == name)


def step(document, name):
    return next(row for row in document["steps"] if row["id"] == name)


class RefusalTests(Programs):
    def altered(self, change):
        """The trainers' review program with its document changed, in place of the one the reading rebuilds."""
        item = self.item(self.natural, self.products[TRAINERS][0])
        found = programs.program(self.natural, item, self.api)
        document = deepcopy(found.twin.document)
        change(document)
        key = next(key for key, value in programs.BUILT.items() if value is found)
        programs.BUILT[key] = SimpleNamespace(**{**vars(found), "twin": package_export.ProductPackage(document), "cells": {}})
        self.addCleanup(programs.BUILT.pop, key, None)

    @staticmethod
    def half(document):
        """The value threshold written without its leading zero."""
        step(document, "sentiment_value")["derive"] = "review.value_favourability >= .5"

    @staticmethod
    def banded(document):
        """The value score read through two more thresholds: one in a statement's condition, one in a derived value."""
        document["fields"]["review.keen"] = {"type": "boolean"}
        document["steps"].append({"id": "keen", "target": "review.keen", "derive": "review.value_favourability  >=  0.9"})
        pool(document, "value.positive")["when"] += " and review.value_favourability >= .7 and not review.keen"

    @staticmethod
    def spaced(document):
        """A second threshold on the value score, written as the expression language also allows."""
        step(document, "sentiment_value")["derive"] = "review.value_favourability >= .5 and review . value_favourability >= .7"

    @staticmethod
    def fielded(document):
        """A threshold on the value score in a field's own condition, which no step's text shows."""
        document["fields"]["review.keen"] = {"type": "boolean", "applicable_when": "review.value_favourability >= .7"}
        document["steps"].append({"id": "keen", "target": "review.keen", "derive": "True"})
        pool(document, "value.positive")["when"] += " and known(review.keen)"

    @staticmethod
    def swayed(document):
        """A rating whose chances another draw of the block sets."""
        document["fields"]["review.quality"] = {"type": "number", "min": 0, "max": 1}
        rating = step(document, "rating")
        document["steps"].insert(document["steps"].index(rating), {
            "id": "quality", "target": "review.quality", "sample": "weighted_choice", "weights": {"low": 1, "high": 1},
            "values": {"low": 0, "high": 1}})
        rating["execution"] = "review.quality"

    def drawn_by(self, place):
        """The natural world with one product's reviews as the altered program in place draws them."""
        world, twin = deepcopy(self.natural), place.program.twin
        for index, row in enumerate(self.item(world, place.product_id)["reviews"]):
            review = twin.sample(place.seeds[index], inputs=deepcopy(place.program.entities))
            row.update(private_trace=review["trace"], rating=review["entities"]["review"]["rating"],
                       statements=[{"meaning_id": found["id"]} for found in twin.document["language"]
                                   if "when" not in found or twin._eval(found["when"], review["entities"])])
        return world

    @staticmethod
    def counted(document):
        """A whole-number draw that the comfort statements' conditions read."""
        document["fields"]["review.wears"] = {"type": "integer", "min": 1, "max": 4}
        document["steps"].append({"id": "wears", "target": "review.wears", "sample": "uniform_int", "min": 1, "max": 4})
        for name in ("everyday_comfort.positive", "everyday_comfort.negative"):
            pool(document, name)["when"] += " and review.wears >= 2"

    @staticmethod
    def looped(document):
        """A loop that collects two rows per review; the comfort statements need the reviewed option among them."""
        option = {"sku_id": {"type": "string"}, "product_id": {"type": "string"}, "colour": {"type": "string"},
                  "width": {"type": "string"}, "size_eu": {"type": "integer"}}
        document["fields"].update({
            "internal.kinds": {"type": "array", "items": {"type": "enum", "values": ["a", "b"]}, "constant": ["a", "b"]},
            "group.kind": {"type": "enum", "values": ["a", "b"]},
            "internal.rows": {"type": "array", "items": {"type": "object", "properties": option}}})
        # The second row is the option itself up to three stars; a row left from another rating would show.
        row = {**{name: "review.subject." + name for name in option},
               "size_eu": "review.subject.size_eu if review.rating <= 3 and group.kind == 'b' else 0"}
        document["steps"].append({"id": "rows", "for_each": {"binding": "group.kind", "from": "internal.kinds"},
                                  "steps": [{"id": "row", "target": "internal.rows", "emit": row}]})
        for name in ("everyday_comfort.positive", "everyday_comfort.negative"):
            pool(document, name)["when"] += " and review.subject in internal.rows"

    @staticmethod
    def gated(document):
        """A draw and a derived value that apply only to some ratings; the comfort statements need both known."""
        document["fields"].update({"review.wears": {"type": "integer", "min": 1, "max": 2},
                                   "review.keen": {"type": "boolean"}})
        document["steps"] += [
            {"id": "wears", "target": "review.wears", "sample": "uniform_int", "min": 1, "max": 2, "when": "review.rating >= 2"},
            {"id": "keen", "target": "review.keen", "derive": "review.rating >= 3", "when": "review.rating <= 4"}]
        for name in ("everyday_comfort.positive", "everyday_comfort.negative"):
            pool(document, name)["when"] += " and known(review.wears) and known(review.keen)"

    def test_steps_no_program_in_git_has_are_followed(self):
        plain = programs.cells(self.place())
        worth = programs.cells(self.place(TRAINERS, "value"))
        for change, aspect in ((self.half, "value"), (self.banded, "value"), (self.spaced, "value"), (self.fielded, "value"),
                               (self.swayed, "everyday_comfort"), (self.counted, "everyday_comfort"),
                               (self.looped, "everyday_comfort"), (self.gated, "everyday_comfort")):
            with self.subTest(change=change.__name__):
                self.altered(change)
                place = self.place(TRAINERS, aspect)
                cells, twin, trials = programs.cells(place), place.program.twin, 6000
                self.assertAlmostEqual(sum(cells.values()), 1, places=12)
                seen = Counter()
                for seed in range(10 ** 7, 10 ** 7 + trials):
                    review = twin.sample(seed, inputs=deepcopy(place.program.entities))
                    found = (programs.draws(place, review["trace"]), programs.told(place, review["entities"]),
                             review["entities"]["review"]["rating"])
                    seen[found[2], found[1]] += 1
                    # Following the steps from the draws alone says what the program's own run says.
                    self.assertEqual(programs.replayed(place, found), found[1:])
                for cell, chance in cells.items():
                    self.assertLess(abs(seen[cell] / trials - chance), 4.5 * (chance * (1 - chance) / trials) ** .5 + 1e-9, cell)
                if change is self.half:
                    self.assertEqual(cells, worth)
                elif change is self.banded:
                    # Praise needs a score from 0.7 up to 0.9; the complaints are as they were.
                    self.assertEqual(place.bounds, {"value_favourability": [.5, .7, .9]})
                    for rating in range(1, 6):
                        self.assertAlmostEqual(cells[rating, reviews.NEGATIVE], worth[rating, reviews.NEGATIVE], places=12)
                        self.assertLess(cells[rating, reviews.POSITIVE], worth[rating, reviews.POSITIVE])
                    self.assertGreater(sum(seen[rating, reviews.POSITIVE] for rating in range(1, 6)), 20)
                elif change in (self.spaced, self.fielded):
                    # Praise needs a score of 0.7; found though no step's text has the threshold in the usual form.
                    self.assertEqual(place.bounds, {"value_favourability": [.5, .7]})
                    self.assertGreater(sum(seen[rating, reviews.POSITIVE] for rating in range(1, 6)), 20)
                    for rating in range(1, 6):
                        self.assertLess(cells[rating, reviews.POSITIVE], worth[rating, reviews.POSITIVE])
                elif change is self.swayed:
                    self.assertEqual((place.staged, "quality" in place.drawn), (False, True))
                    self.assertGreater(min(seen[1, reviews.REST], seen[5, reviews.REST]), 1500)
                    # A mean to meet: every review's planned rating holds, though the rating's own stream is not enough.
                    world = self.drawn_by(place)
                    for seed, limits in enumerate(({"min": 5}, {"max": 1.5}, {"min": 3, "max": 3})):
                        need = self.need(verdict="more_negative", mean_rating=limits)
                        plan = reviews.prepare(world, need, self.api, Random(seed))
                        found = reviews.site(world, need, self.api)
                        rows = [programs.redrawn(found, index, plan.script[programs.keys(found, index)[0]].seed)
                                for index in range(found.count)]
                        self.assertTrue(reviews.holds(need, *reviews.counted(found, rows)), limits)
                        self.assertTrue(all(len({plan.script[key].seed for key in programs.keys(found, index)}) == 1
                                            for index in range(found.count)))
                elif change is self.counted:
                    self.assertIn("wears", place.drawn)
                    self.assertIn("wears", place.block)
                    for rating in range(1, 6):
                        self.assertAlmostEqual(cells[rating, reviews.POSITIVE], plain[rating, reviews.POSITIVE] * 3 / 4, places=12)
                else:
                    self.assertEqual("internal.rows" in place.emits, change is not self.gated)
                    kept = {self.looped: (1, 2, 3), self.gated: (2, 3, 4)}[change]
                    for rating in range(1, 6):
                        for side in (reviews.POSITIVE, reviews.NEGATIVE):
                            self.assertAlmostEqual(cells[rating, side], plain[rating, side] * (rating in kept), places=12)
                programs.BUILT.clear()

    def test_a_program_the_reading_cannot_follow_is_refused(self):
        def neutral(document):
            pool(document, "everyday_comfort.negative")["meaning"]["polarity"] = "neutral"

        def both(document):
            pool(document, "everyday_comfort.negative")["when"] = "'everyday_comfort' in review.topics"

        def strict(document):
            pool(document, "value.positive")["when"] += " and review.value_favourability > 0.7"

        def scaled(document):
            pool(document, "value.positive")["when"] += " and review.value_favourability >= 0.7 * 1"

        def doubled(document):
            pool(document, "value.positive")["when"] += " and 2 * review.value_favourability >= 1.4"

        def chained(document):
            pool(document, "value.positive")["when"] += " and 1 >= review.value_favourability >= 0.7"

        def whole(document):
            pool(document, "value.positive")["when"] += " and known(review.value_favourability)"

        def unclipped(document):
            step(document, "value_favourability")["bounds_mode"] = "truncate"

        def wide(document):
            self.counted(document)
            step(document, "wears")["max"] = 20000

        def guarded(document):
            self.looped(document)
            step(document, "rows")["steps"][0]["when"] = "review.rating >= 2"

        for change, topic in ((neutral, "everyday_comfort"), (both, "everyday_comfort"), (strict, "value"), (scaled, "value"),
                              (doubled, "value"), (chained, "value"), (whole, "value"),
                              (unclipped, "value"), (wide, "everyday_comfort"), (guarded, "everyday_comfort")):
            with self.subTest(change=change.__name__):
                self.altered(change)
                with self.assertRaises(ValueError) as caught:
                    programs.shares(reviews.site(self.natural, self.need(TRAINERS, topic, verdict="tie"), self.api))
                self.assertIn("Not modelled", str(caught.exception))
                programs.BUILT.clear()
        # A change the topic does not depend on is no obstacle.
        self.altered(neutral)
        self.assertGreater(reviews.model(self.natural, self.need(TRAINERS, "value", verdict="tie"), self.api).probability, 0)

    def test_a_reading_that_follows_the_steps_wrongly_is_refused(self):
        # A product with praise of its value, followed with the value score's threshold out of reach.
        place = next(found for found in (self.place(TRAINERS, "value", index) for index in range(len(self.products[TRAINERS])))
                     if any(row[1] == reviews.POSITIVE for row in programs.written(self.natural, found)))
        rows = programs.written(self.natural, place)
        self.assertEqual([programs.replayed(place, row) for row in rows], [row[1:] for row in rows])
        programs.reads(self.natural, place)
        place.steps = [{**row, "derive": "review.value_favourability >= 1.5"} if row["id"] == "sentiment_value" else row
                       for row in place.steps]
        with self.assertRaises(ValueError) as caught:
            programs.reads(self.natural, place)
        self.assertIn("Following", str(caught.exception))

    def test_a_world_the_program_does_not_reproduce_is_refused(self):
        requirement = self.need(verdict="tie")
        other = deepcopy(self.natural)
        review = self.item(other, self.products[TRAINERS][0])["reviews"][2]
        row = next(row for row in review["private_trace"] if row["id"] == "rating")
        row["outcome"] = row["rating"] = 1 + row["outcome"] % 5
        for call in (reviews.model, reviews.trial, lambda *a: reviews.prepare(*a, Random(0))):
            with self.assertRaises(ValueError) as caught:
                call(other, requirement, self.api)
            self.assertIn("recorded reviews", str(caught.exception))
        moved = deepcopy(self.natural)
        self.item(moved, self.products[TRAINERS][0])["private"]["sample"]["entities"]["profile"]["execution"] = .123
        with self.assertRaises(ValueError) as caught:
            reviews.model(moved, requirement, self.api)
        self.assertIn("manufactured again", str(caught.exception))

    def test_zero_probability_and_bad_requirements(self):
        good = self.need(verdict="tie")
        for impossible in (self.need(positive={"min": 17}), self.need(verdict="more_positive", positive={"max": 0})):
            with self.subTest(impossible=impossible), self.assertRaises(prices.ZeroMass):
                reviews.model(self.natural, impossible, self.api)
        for bad in ({**good, "topic": {"aspect": "everyday_comfort", "context": "another context"}},
                    {**good, "topic": {"aspect": "wet_paving_grip", "context": {}}},
                    {**good, "topic": {"aspect": "everyday_comfort"}}, {**good, "product_id": "nothing"}):
            for call in (reviews.model, reviews.trial, lambda *a: reviews.prepare(*a, Random(0))):
                with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)

    def test_plan_keys_and_streams(self):
        place = self.place()
        with self.assertRaises(streams.PlanMismatch):
            self.session.generate({(streams.PROGRAM, place.seed, 0, "rating"): [("random", .5)]})
        for key in ((streams.PROGRAM,), (streams.PROGRAM, 1), (streams.PROGRAM, 1, 2), (streams.PROGRAM, 1, "2", "key"),
                    (streams.PROGRAM, "1", 2, "key"), (streams.PROGRAM, 1, 2, ""), (streams.PROGRAM, 1, 2, 3),
                    (streams.PROGRAM, 1, 2, "key", "more"), (streams.REVIEW, 1, 2, "key")):
            with self.subTest(key=key), self.assertRaises(streams.PlanMismatch):
                self.session.generate({key: streams.Reseeded(1)})
        # A well-formed key the producer never opens is not an error for a reseeded stream.
        untouched = self.session.generate({(streams.PROGRAM, 1, 0, "no/such/stream"): streams.Reseeded(1)})[0]
        self.assertEqual(untouched["world_id"], self.natural["world_id"])

        class Package:
            def rng(self, seed, key):
                return seed, key

        own = streams.program_review_seed(7, 3)
        with streams.programmed(Package, {(7, 3, "rating"): streams.Reseeded(11)}):
            self.assertEqual(Package().rng(own, "rating"), (streams.program_seed(11, own), "rating"))
            self.assertEqual(Package().rng(own, "topics"), (own, "topics"))
            self.assertEqual(Package().rng(own + 1, "rating"), (own + 1, "rating"))
        self.assertEqual(Package().rng(own, "rating"), (own, "rating"))
        # A stream some other draw of the pass opens as well would be reseeded with it: the pass fails.
        with self.assertRaises(streams.PlanMismatch):
            with streams.programmed(Package, {(7, 3, "rating"): streams.Reseeded(11)}):
                Package().rng(own, "rating"), Package().rng(own, "rating")
        self.assertEqual(Package().rng(own, "rating"), (own, "rating"))


if __name__ == "__main__":
    unittest.main()
