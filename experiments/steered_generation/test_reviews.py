"""Tests of the review block against the real producer, with really manufactured pilot products.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_reviews.py
The pilot concepts manufacture in milliseconds, so nothing is replaced here:
products, their reviews and the commerce pass are the producer's own, and the
native review-summary task reads the steered worlds.
"""
from collections import Counter
from copy import deepcopy
from itertools import permutations
from math import prod
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from environments.website_world import basic_offer_task, catalog_review_task
from experiments.accepted_catalog_commerce import model as commerce, package_export
from experiments.footwear_world_pilot import model as native
from experiments.world_sampling_defaults import model as population

from experiments.steered_generation import blocks, combined, prices, reviews, run, stock, streams, variants

SHOES, SANDALS = "footwear.walking_shoes", "footwear.walking_sandals"
INPUTS = {"seed": 5, "concept_ids": [SHOES, SANDALS], "tasks": [SHOES], "controls": None,
          "city_id": "uppsala", "review_count": 40}
GRIP = {"aspect": "wet_paving_grip", "context": {"activity": "walking", "surface": "wet paving"}}
VALUE = {"aspect": "value", "context": {"basis": "recorded purchase price"}}
COMFORT = {"aspect": "walking_comfort", "context": {"source": "first_hand"}}
HEAT = {"aspect": "footbed_heat", "context": {"body_contact": "footbed"}}


class Reviews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = SimpleNamespace(basic=basic_offer_task, native=native, population=population,
                                  commerce=commerce, package_export=package_export)
        cls.session = streams.Session(cls.api, INPUTS)
        cls.natural, cls.opened = cls.session.generate()
        cls.frozen = deepcopy(cls.natural)
        cls.shoes, cls.sandals = (sorted(p["public"]["product_id"] for p in cls.natural["products"]
                                         if p["public"]["concept_id"] == concept) for concept in (SHOES, SANDALS))

    def tearDown(self):
        self.assertEqual(self.natural, self.frozen, "A test changed the natural world")

    def need(self, product=None, topic=GRIP, **stated):
        return {"schema": reviews.VERSION, "product_id": product or self.shoes[0], "topic": topic, **stated}

    def item(self, world, product_id):
        return next(p for p in world["products"] if p["public"]["product_id"] == product_id)

    def requirements(self):
        return [self.need(verdict="more_negative"), self.need(verdict="more_positive"),
                self.need(verdict="tie", min_assessed=4), self.need(verdict="insufficient_evidence", min_assessed=3),
                # Rare counts: a pile of complaints; praise and not one complaint.
                self.need(negative={"min": 12}), self.need(positive={"min": 6}, negative={"max": 0}),
                self.need(self.shoes[3], VALUE, verdict="more_positive", positive={"min": 5}),
                self.need(self.sandals[0], HEAT, verdict="tie", positive={"min": 2, "max": 3})]

    def cases(self):
        """A product and a topic for every adjustment the producer makes to an aspect's centre."""
        cushioned = next(p["public"]["product_id"] for p in self.natural["products"]
                         if p["public"]["concept_id"] == SHOES and p["public"]["facts"]["cushioning"] == "substantial")
        return [(self.shoes[0], GRIP), (self.shoes[1], VALUE), (cushioned, COMFORT), (self.sandals[0], HEAT),
                (self.sandals[1], {"aspect": "heel_rubbing", "context": {}})]


class ModelTests(Reviews):
    def test_the_reading_of_every_review_is_what_the_producer_recorded(self):
        for product, topic in self.cases():
            with self.subTest(product=product, aspect=topic["aspect"]):
                place = reviews.site(self.natural, self.need(product, topic, verdict="tie"), self.api)
                self.assertEqual(place.count, INPUTS["review_count"])
                self.assertEqual(reviews.written(self.natural, place),
                                 [reviews.drawn(place, index, place.seed) for index in range(place.count)])
        # And the native task counts what the recorded draws say, for every product.
        for product in self.shoes + self.sandals:
            found = reviews.check(self.natural, self.need(product, positive={"min": 0}), self.api)
            self.assertEqual(found["written_review_count"],
                             sum(bool(row["text"].strip()) for row in self.item(self.natural, product)["reviews"]))

    def test_one_reviews_class_probabilities_match_other_seeds(self):
        trials = 2500
        for product, topic in self.cases():
            with self.subTest(product=product, aspect=topic["aspect"]):
                place = reviews.site(self.natural, self.need(product, topic, verdict="tie"), self.api)
                share = reviews.shares(place)
                self.assertAlmostEqual(sum(share.values()), 1, places=12)
                seen = Counter(reviews.said(place, row) for seed in range(trials)
                               for row in reviews.trial(self.natural, self.need(product, topic, verdict="tie"),
                                                        self.api).reading(seed))
                count = trials * place.count
                for name, chance in share.items():
                    self.assertLess(abs(seen[name] / count - chance), 4.5 * (chance * (1 - chance) / count) ** .5, name)
                    self.assertGreater(seen[name], 300, name)
        # The centre's adjustments are in the model: the shares differ where the producer shifts it.
        shares = [reviews.shares(reviews.site(self.natural, self.need(product, topic, verdict="tie"), self.api))
                  for product, topic in self.cases()[:3]]
        self.assertEqual(len({round(row[reviews.POSITIVE] / (row[reviews.POSITIVE] + row[reviews.NEGATIVE]), 6)
                              for row in shares}), 3)

    def test_stars_and_scores_match_other_seeds(self):
        for product, topic in self.cases()[:3]:
            with self.subTest(product=product, aspect=topic["aspect"]):
                requirement = self.need(product, topic, verdict="tie")
                place, reading = reviews.site(self.natural, requirement, self.api), reviews.trial(self.natural, requirement, self.api)
                rows = [row for seed in range(1500) for row in reading.reading(seed)]
                seen, praised = Counter(row[0] for row in rows), Counter(row[0] for row in rows if row[1] >= .5)
                model = reviews.stars(place)
                self.assertAlmostEqual(sum(model.values()), 1, places=12)
                for rating, chance in model.items():
                    self.assertLess(abs(seen[rating] / len(rows) - chance), 4.5 * (chance * (1 - chance) / len(rows)) ** .5, rating)
                    tail = reviews.favourable(place, rating)
                    self.assertLess(abs(praised[rating] / seen[rating] - tail), 4.5 * (tail * (1 - tail) / seen[rating]) ** .5 + 1e-9, rating)
                self.assertGreater(min(seen.values()), 1500)
                # The rating says nothing about whether there is a comment or what it is about.
                for rating in model:
                    written = sum(bool(row[2]) for row in rows if row[0] == rating) / seen[rating]
                    self.assertLess(abs(written - .25), 4.5 * (.25 * .75 / seen[rating]) ** .5, rating)

    def test_topic_inclusion_matches_enumeration(self):
        weights = {"a": 1.3, "b": 1.0, "c": 1.25, "d": .4, "e": 2.0, "f": 0}
        for slots in range(0, 5):
            for aspect in ("a", "d", "f", "missing"):
                direct = 0
                for order in permutations([name for name, weight in weights.items() if weight], slots):
                    left, mass = sum(weights.values()), 1
                    for name in order:
                        mass, left = mass * weights[name] / left, left - weights[name]
                    direct += mass * (aspect in order)
                self.assertAlmostEqual(reviews.included(weights, aspect, slots), direct, places=12, msg=(aspect, slots))
        self.assertAlmostEqual(reviews.included(weights, "a", 5), 1, places=12)

    def test_probabilities_match_other_seeds(self):
        trials = 4000
        for requirement in self.requirements():
            with self.subTest(requirement=requirement):
                block = reviews.model(self.natural, requirement, self.api)
                hits, chance = sum(reviews.empirical(self.natural, requirement, self.api, trials, 10 ** 6).values()), block.probability
                self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5)
                self.assertGreater(hits, 100 if chance > .05 else -1)
        for product, topic in self.cases():
            for least in (1, 3):
                total = sum(reviews.model(self.natural, self.need(product, topic, verdict=verdict, min_assessed=least),
                                          self.api).probability for verdict in reviews.VERDICTS)
                self.assertAlmostEqual(total, 1, places=10)
        # The counts' distribution itself, where it is not rare.
        requirement = self.need(positive={"min": 0})
        block = reviews.model(self.natural, requirement, self.api)
        seen = reviews.empirical(self.natural, requirement, self.api, trials, 10 ** 6)
        model = {counts: 2.718281828459045 ** value for counts, value in block.log_terms.items()}
        self.assertLess(sum(abs(model.get(counts, 0) - seen.get(counts, 0) / trials) for counts in set(model) | set(seen)) / 2, .04)

    def test_samples_match_rejection_sampling(self):
        requirement = self.need(verdict="tie", min_assessed=2)
        place = reviews.site(self.natural, requirement, self.api)
        reading = reviews.trial(self.natural, requirement, self.api)
        accepted = [rows for rows in map(reading.reading, range(10 ** 6, 10 ** 6 + 5000))
                    if reviews.holds(requirement, *reviews.counted(place, rows))]
        rng, sampled = Random(11), []
        for _ in range(len(accepted)):
            step = reviews.prepare(self.natural, requirement, self.api, rng)
            sampled.append([reviews.drawn(place, index, streams.review_seed(step.script[reviews.keys(place, index)[0]].seed, place.seed))
                            for index in range(place.count)])
            self.assertTrue(reviews.holds(requirement, *reviews.counted(place, sampled[-1])))
        self.assertGreater(len(accepted), 500)
        # Per world: comments written, the mean star rating, the stars of the reviews that praise and of those
        # that complain, where in the list the praise sits, and the score of a review that says nothing.
        features = {
            "positive": lambda rows: reviews.counted(place, rows)[0],
            "written": lambda rows: sum(bool(row[2]) for row in rows),
            "stars": lambda rows: sum(row[0] for row in rows) / len(rows),
            "stars_praising": lambda rows: sum(row[0] for row in rows if reviews.said(place, row) == reviews.POSITIVE),
            "stars_complaining": lambda rows: sum(row[0] for row in rows if reviews.said(place, row) == reviews.NEGATIVE),
            "place_of_praise": lambda rows: sum(i for i, row in enumerate(rows) if reviews.said(place, row) == reviews.POSITIVE),
            "silent_score": lambda rows: sum(row[1] for row in rows if reviews.said(place, row) == reviews.REST),
            "topics": lambda rows: sum(len(row[3]) for row in rows)}
        for name, feature in features.items():
            with self.subTest(feature=name):
                mine, theirs = [feature(rows) for rows in sampled], [feature(rows) for rows in accepted]
                spread = lambda values: (sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values) ** 2) ** .5
                self.assertLess(abs(sum(mine) / len(mine) - sum(theirs) / len(theirs)),
                                4.5 * (spread(mine) ** 2 + spread(theirs) ** 2) ** .5 + 1e-9)
        counts = [Counter(reviews.counted(place, rows) for rows in group) for group in (sampled, accepted)]
        self.assertLess(sum(abs(counts[0][key] - counts[1][key]) for key in set(counts[0]) | set(counts[1])) / 2 / len(accepted), .07)

    def test_a_sample_redraws_every_review_and_keeps_no_block_draw_of_its_world(self):
        requirement = self.need(negative={"min": 12})
        place = reviews.site(self.natural, requirement, self.api)
        step = reviews.prepare(self.natural, requirement, self.api, Random(3))
        self.assertEqual(set(step.script), {key for index in range(place.count) for key in reviews.keys(place, index)})
        seeds = [{step.script[key].seed for key in reviews.keys(place, index)} for index in range(place.count)]
        self.assertTrue(all(len(found) == 1 for found in seeds))
        self.assertEqual(len(set.union(*seeds)), place.count)
        self.assertTrue(all(key[:2] == (streams.REVIEW, place.seed) for key in step.script))
        self.assertEqual((step.writes, step.reads), ({("reviews", "", self.shoes[0])}, set()))


class ProducerTests(Reviews):
    def test_steered_worlds_hold_through_the_producer_and_the_native_review_task(self):
        for index, requirement in enumerate(self.requirements()):
            with self.subTest(requirement=requirement):
                product = requirement["product_id"]
                world, found, record = reviews.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))
                counts = found["counts"]
                self.assertTrue(reviews.holds(requirement, counts["positive"], counts["negative"]))
                self.assertEqual(record["steered_counts"], {"positive": counts["positive"], "negative": counts["negative"]})
                self.assertEqual((world["status"], record["reviews"]), (streams.STATUS, INPUTS["review_count"]))
                # The native task itself, built here and not by the module under test.
                declared = catalog_review_task.ReviewInventory(self.item(world, product)["public"]["concept_id"])
                spec = {"kind": catalog_review_task.KIND, "concept_id": declared.concept_id, "operation": "topic_counts",
                        "product_index": sorted(self.shoes if product in self.shoes else self.sandals).index(product),
                        "topic": requirement["topic"], "min_assessed": requirement.get("min_assessed", 1)}
                reference = catalog_review_task.reference(world, catalog_review_task.make(world, spec, inventory=declared),
                                                          inventory=declared)
                self.assertEqual((reference["subject"]["product_id"], reference["counts"]), (product, counts))
                self.assertEqual(requirement.get("verdict", reference["verdict"]), reference["verdict"])
                # Only this product's reviews moved; who bought which option is the seed's own.
                before, after = self.item(self.natural, product), self.item(world, product)
                self.assertEqual([row["sku_id"] for row in after["reviews"]], [row["sku_id"] for row in before["reviews"]])
                self.assertNotEqual([row["rating"] for row in after["reviews"]], [row["rating"] for row in before["reviews"]])
                self.assertEqual({k: v for k, v in after.items() if k not in ("reviews", "rating_summary")},
                                 {k: v for k, v in before.items() if k not in ("reviews", "rating_summary")})
                self.assertEqual([p for p in world["products"] if p is not after],
                                 [p for p in self.natural["products"] if p is not before])
                self.assertEqual(world["retailers"], self.natural["retailers"])
        self.assertEqual(self.session.generate()[0]["world_id"], self.natural["world_id"])

    def test_repeated_samples_differ_and_start_from_no_draw_of_the_natural_world(self):
        requirement = self.need(verdict="more_positive")
        worlds = [reviews.steer(self.session, self.natural, self.opened, requirement, self.api, Random(seed))[0]
                  for seed in range(4)]
        self.assertEqual(len({world["world_id"] for world in worlds}), 4)
        place = reviews.site(self.natural, requirement, self.api)
        natural = reviews.written(self.natural, place)
        for world in worlds:
            # Scores are continuous: a review that kept its natural score kept a draw.
            self.assertFalse({row[1] for row in natural if 0 < row[1] < 1} & {row[1] for row in reviews.written(world, place)})

    def test_redraws_through_the_producer_equal_the_reading(self):
        for requirement in (self.requirements()[0], self.requirements()[-1]):
            reading = reviews.trial(self.natural, requirement, self.api)
            for seed in range(900, 904):
                found = blocks.redraw(self.session, self.natural, [reading], seed)
                self.assertEqual((found.identical, found.agreed), ([True], [True]))
                self.assertEqual(found.satisfied, reading.holds(seed))

    def test_it_combines_with_other_products_and_with_commerce_blocks(self):
        first, second = self.need(verdict="more_negative"), self.need(self.shoes[1], verdict="more_negative")
        retailer = next(r for r in self.natural["retailers"] if r["offers"])
        held = {"schema": stock.VERSION, "retailer_id": retailer["retailer_id"], "sku_id": retailer["offers"][0]["sku_id"],
                "availability": "in_stock"}
        together = {"schema": combined.VERSION, "all": [first, second, held]}
        world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(4))
        self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in together["all"]))
        chances = [reviews.model(self.natural, part, self.api).probability for part in (first, second)]
        self.assertAlmostEqual(record["probability_given_upstream"],
                               prod(chances) * stock.model(self.natural, held, self.api).probability, places=12)
        # Two products reseeded alike still draw apart: together they hold as often as independence says.
        trials = 3000
        alone, both = combined.empirical(self.natural, {"schema": combined.VERSION, "all": [first, second]}, self.api, trials, 10 ** 6)
        for hits, chance in zip(alone + [both], chances + [prod(chances)]):
            self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5)
        for seed in range(700, 703):
            found = combined.redraw(self.session, self.natural, {"schema": combined.VERSION, "all": [first, second]}, self.api, seed)
            self.assertEqual((found.identical, found.agreed), ([True, True], [True, True]))
        with self.assertRaises(blocks.Coupled) as caught:
            combined.prepare(self.natural, {"schema": combined.VERSION, "all": [first, self.need(topic=VALUE, positive={"min": 1})]},
                             self.api, Random(0))
        self.assertIn(self.shoes[0], str(caught.exception))

    def test_the_runner_samples_and_checks_a_review_requirement(self):
        args = SimpleNamespace(samples=2, producer_redraws=2, validate_trials=1500)
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.reviews_case(args, self.session, self.natural, self.opened, self.api, self.need(verdict="tie"),
                             case, lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], len(case["samples"])), ("sampled", 2))
        self.assertTrue(all(sample["verdict"] == "tie" for sample in case["samples"]))
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertEqual(case["producer_redraws"]["identical_to_reading"], 2)
        impossible = {"samples": [], "requirement_sha256": "x"}
        run.reviews_case(args, self.session, self.natural, self.opened, self.api, self.need(positive={"min": 41}), impossible, None)
        self.assertEqual(impossible["status"], "zero_probability_given_upstream")

    def test_zero_probability_and_bad_requirements(self):
        good = self.need(verdict="tie")
        for impossible in (self.need(positive={"min": 41}), self.need(positive={"min": 30}, negative={"min": 11}),
                           self.need(verdict="more_positive", positive={"max": 0}),
                           self.need(verdict="insufficient_evidence", negative={"min": 1})):
            with self.subTest(impossible=impossible), self.assertRaises(prices.ZeroMass) as caught:
                reviews.model(self.natural, impossible, self.api)
            self.assertEqual(caught.exception.reason, "no_outcome")
        other = deepcopy(self.natural)
        self.item(other, self.shoes[0])["public"]["concept_id"] = "tops.t_shirts"
        with self.assertRaises(ValueError):
            reviews.model(other, good, self.api)
        for bad in ({**good, "product_id": "nothing"}, {**good, "verdict": "mostly_fine"}, {**good, "positive": {}},
                    {**good, "negative": {"min": 3, "max": 2}}, {**good, "min_assessed": 0},
                    {k: v for k, v in good.items() if k != "verdict"}, self.need(positive={"min": 1}, min_assessed=2),
                    {**good, "topic": {"aspect": "wet_paving_grip"}}, {**good, "topic": {**GRIP, "context": {"surface": "ice"}}},
                    {**good, "topic": {"aspect": "size_fit", "context": {}}}, {**good, "topic": {"aspect": "forefoot_room", "context": {}}},
                    {**good, "topic": {"aspect": "footbed_heat", "context": {}}}, {**good, "sku_id": "x"}, None):
            for call in (reviews.model, reviews.trial, lambda *a: reviews.prepare(*a, Random(0))):
                with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        with self.assertRaises(streams.PlanMismatch):
            self.session.generate({(streams.REVIEW, 1, "reviews/walking_shoes/0/rating"): [("random", .5)]})
        with self.assertRaises(streams.PlanMismatch):
            self.session.generate({("other", 1, "key"): streams.Reseeded(1)})

    def test_candidates_for_the_review_summary_task(self):
        task = {"kind": "summarize_product_reviews", "concept_id": SHOES, "operation": "topic_counts", "product_index": 2,
                "topic": GRIP, "min_assessed": 2}
        found = variants.of(self.natural, task, self.api)
        self.assertEqual({row["name"] for row in found}, {"verdict_" + verdict for verdict in reviews.VERDICTS})
        self.assertEqual([row["log_probability"] for row in found], sorted((row["log_probability"] for row in found), reverse=True))
        self.assertAlmostEqual(sum(2.718281828459045 ** row["log_probability"] for row in found), 1, places=10)
        for index, row in enumerate(found):
            self.assertEqual((row["requirement"]["product_id"], row["requirement"]["min_assessed"]), (self.shoes[2], 2))
            world, seen, _ = reviews.steer(self.session, self.natural, self.opened, row["requirement"], self.api, Random(index))
            self.assertEqual("verdict_" + seen["verdict"], row["name"])
        for bad in ({**task, "operation": "rating_summary"}, {**task, "subject_scope": "sku"}, {**task, "product_index": 99},
                    {**task, "sku_index": 0}, {**task, "topic": {"aspect": "size_fit", "context": {}}},
                    {k: v for k, v in task.items() if k != "topic"}, {k: v for k, v in task.items() if k != "concept_id"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                variants.of(self.natural, bad, self.api)


if __name__ == "__main__":
    unittest.main()
