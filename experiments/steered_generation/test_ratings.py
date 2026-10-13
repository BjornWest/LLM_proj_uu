"""Tests of the carrier-stars block against the real producer, on a small world of pilot products.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_ratings.py
"""
from collections import Counter
from copy import deepcopy
from itertools import permutations
from math import exp, prod
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from environments.website_world import basic_offer_task
from experiments.accepted_catalog_commerce import model as commerce, package_export
from experiments.footwear_world_pilot import model as native
from experiments.world_sampling_defaults import model as population

from experiments.steered_generation import blocks, carriers, combined, policies, prices, ratings, run, sellers, shipments, streams

SHOES, SANDALS = "footwear.walking_shoes", "footwear.walking_sandals"
INPUTS = {"seed": 5, "concept_ids": [SHOES, SANDALS], "tasks": [SHOES], "controls": None,
          "city_id": "uppsala", "review_count": 0}


class Ratings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = SimpleNamespace(basic=basic_offer_task, native=native, population=population,
                                  commerce=commerce, package_export=package_export)
        cls.session = streams.Session(cls.api, INPUTS)
        cls.natural, cls.opened = cls.session.generate()
        cls.frozen = deepcopy(cls.natural)
        cls.carriers = [row["carrier_id"] for row in cls.natural["carrier_evidence"]["public"]["carriers"]]

    def tearDown(self):
        self.assertEqual(self.natural, self.frozen, "A test changed the natural world")

    def need(self, carrier=0, **stated):
        return {"schema": ratings.VERSION, "carrier_id": self.carriers[carrier], **stated}

    def requirements(self):
        return [self.need(average_stars={"max": 3.7}), self.need(1, average_stars={"min": 4.6}),
                self.need(2, levels={"punctuality": "weak"}), self.need(3, levels={"punctuality": "weak", "handling": "weak"},
                                                                       average_stars={"max": 3.9}),
                self.need(4, average_stars={"min": 4.0, "max": 4.25}),
                self.need(5, levels={"handoff": "strong", "communication": "mixed"}, average_stars={"min": 4.4})]


class ModelTests(Ratings):
    def test_the_reading_is_what_the_producer_recorded(self):
        for index in range(len(self.carriers)):
            found = ratings.trial(self.natural, self.need(index, average_stars={"max": 5}), self.api)
            place = ratings.site(self.natural, self.need(index, average_stars={"max": 5}), self.api)
            self.assertEqual(found.reading(place.seed), found.recorded(self.natural))
            self.assertEqual(ratings.histories(place, place.natural), [
                row for row in self.natural["carrier_evidence"]["private"]["shipments"] if row["carrier_id"] == place.carrier_id])
            self.assertEqual(len(found.keys), 4 + place.count)

    def test_a_comments_tone_matches_enumeration(self):
        """Every order in which a comment can mention a shipment's observations, by the producer's weights."""
        place = ratings.site(self.natural, self.need(average_stars={"max": 5}), self.api)
        seen = set()
        for history in ratings.histories(place, dict.fromkeys(place.aspects, "weak")):
            observations = history["observations"]
            signature = tuple(sorted((row["aspect"], row["sentiment"]) for row in observations))
            if signature in seen or len(seen) > 5:
                continue
            seen.add(signature)
            for slots in range(1, min(4, len(observations)) + 1):
                direct = Counter()
                for order in permutations(observations, slots):
                    left, chance = list(observations), 1.0
                    for row in order:
                        chance *= carriers.weight(row["aspect"]) / sum(carriers.weight(other["aspect"]) for other in left)
                        left.remove(row)
                    signs = {row["sentiment"] for row in order}
                    direct[("positive" in signs, "negative" in signs)] += chance
                counted = Counter((carriers.weight(row["aspect"]), row["sentiment"]) for row in observations)
                found = ratings.tones(tuple(sorted(counted.items())), slots)
                self.assertEqual(set(found), set(direct))
                for key, value in direct.items():
                    self.assertAlmostEqual(found[key], value, places=12)
        self.assertGreater(len(seen), 3)
        self.assertEqual([ratings.held(stars, *tone) for tone in ((False, False), (True, False), (False, True), (True, True))
                          for stars in ratings.STARS],
                         [1, 2, 3, 4, 5, 3, 3, 3, 4, 5, 1, 2, 3, 3, 3, 1, 2, 3, 4, 4])

    def test_a_reviews_stars_match_the_producers_draws(self):
        place = ratings.site(self.natural, self.need(average_stars={"max": 5}), self.api)
        trials, pooled, drawn = 4000, Counter(), Counter()
        for levels in (place.natural, dict.fromkeys(place.aspects, "weak")):
            for index, history in enumerate(ratings.histories(place, levels)[:12]):
                share = ratings.chances(place, history)
                self.assertAlmostEqual(sum(share.values()), 1, places=12)
                seen = Counter(ratings.rated(place, index, history, seed) for seed in range(10 ** 6, 10 ** 6 + trials))
                for stars in ratings.STARS:
                    pooled[stars] += share[stars] * trials
                    drawn[stars] += seen[stars]
                    self.assertLess(abs(seen[stars] / trials - share[stars]),
                                    5 * (share[stars] * (1 - share[stars]) / trials) ** .5 + 1e-9, (index, stars))
        total = sum(drawn.values())
        for stars in ratings.STARS:
            chance = pooled[stars] / total
            self.assertLess(abs(drawn[stars] / total - chance), 4 * (chance * (1 - chance) / total) ** .5, stars)

    def test_probabilities_match_other_seeds(self):
        trials = 2500
        for requirement in self.requirements():
            with self.subTest(requirement=requirement):
                chance = ratings.model(self.natural, requirement, self.api).probability
                hits = ratings.empirical(self.natural, requirement, self.api, trials, 10 ** 6)
                self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5 + 1e-9)
        whole = ratings.model(self.natural, self.need(average_stars={"min": 1}), self.api)
        self.assertAlmostEqual(whole.probability, 1, places=10)
        self.assertEqual(len(whole.alternatives), 81)
        table = ratings.site(self.natural, self.need(average_stars={"min": 1}), self.api).table
        stated = ratings.model(self.natural, self.need(levels={"punctuality": "weak", "handoff": "mixed"}), self.api)
        self.assertAlmostEqual(stated.probability, table["weak"] * table["mixed"], places=12)
        halves = [ratings.model(self.natural, self.need(average_stars=limits), self.api).probability
                  for limits in ({"max": 4.2}, {"min": 4.21})]
        self.assertAlmostEqual(sum(halves), 1, places=10)

    def test_low_ratings_come_with_worse_service(self):
        """Given a low average the levels lean weak, in the proportion the alternatives state, and samples follow it."""
        requirement = self.need(average_stars={"max": 3.4})
        block = ratings.model(self.natural, requirement, self.api)
        place = block.site
        weak = lambda levels: sum(level == "weak" for level in levels.values())
        expected = sum(exp(row.value - block.log_probability) * weak(row.levels) for row in block.alternatives)
        self.assertGreater(expected, 2.5 * 4 * place.table["weak"])
        rng, seen, totals = Random(3), [], []
        for _ in range(120):
            step = ratings.prepare(self.natural, requirement, self.api, rng)
            levels = {aspect: ratings.level(place, aspect, step.script[place.quality[aspect]].seed) for aspect in place.aspects}
            stars = [ratings.rated(place, index, history, step.script[place.review(index)].seed)
                     for index, history in enumerate(ratings.histories(place, levels))]
            self.assertTrue(ratings.holds(place.requirement, levels, stars))
            seen.append(weak(levels))
            totals.append(sum(stars))
        spread = (sum((value - expected) ** 2 for value in seen) / len(seen)) ** .5
        self.assertLess(abs(sum(seen) / len(seen) - expected), 4.5 * spread / len(seen) ** .5)
        # Under the bound the total is not pushed further down than it needs to be.
        self.assertGreater(sum(totals) / len(totals), 3.2 * place.count)

    def test_samples_match_rejection_sampling(self):
        """With the levels stated the histories are fixed; the planned stars are compared with the producer's own
        draws of every review, kept when the average is as required."""
        place = ratings.site(self.natural, self.need(average_stars={"max": 5}), self.api)
        requirement = self.need(levels=dict(place.natural), average_stars={"max": 4.2})
        happened = ratings.histories(place, place.natural)
        drawn = ([ratings.rated(place, index, history, seed) for index, history in enumerate(happened)]
                 for seed in range(10 ** 6, 10 ** 6 + 4000))
        accepted = [stars for stars in drawn if ratings.average(sum(stars), len(stars)) <= 4.2]
        self.assertGreater(len(accepted), 400)
        rng, planned = Random(5), []
        for _ in range(300):
            step = ratings.prepare(self.natural, requirement, self.api, rng)
            planned.append([ratings.rated(place, index, history, step.script[place.review(index)].seed)
                            for index, history in enumerate(happened)])
            self.assertLessEqual(ratings.average(sum(planned[-1]), place.count), 4.2)
        features = {"total": sum, "ones": lambda stars: stars.count(1), "threes": lambda stars: stars.count(3),
                    "fives": lambda stars: stars.count(5), "first": lambda stars: stars[0], "last": lambda stars: stars[-1],
                    "first_half": lambda stars: sum(stars[:len(stars) // 2]),
                    "at_the_bound": lambda stars: ratings.average(sum(stars), len(stars)) > 4.1}
        for name, feature in features.items():
            with self.subTest(feature=name):
                mine, theirs = [feature(stars) for stars in planned], [feature(stars) for stars in accepted]
                error = lambda values: (sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values) ** 2) ** .5
                self.assertLess(abs(sum(mine) / len(mine) - sum(theirs) / len(theirs)),
                                4.5 * (error(mine) ** 2 + error(theirs) ** 2) ** .5 + 1e-9)

    def test_zero_probability_and_bad_requirements(self):
        good = self.need(average_stars={"max": 3.7})
        for bad in ({**good, "carrier_id": "nobody"}, {k: v for k, v in good.items() if k != "average_stars"},
                    {**good, "average_stars": {}}, {**good, "average_stars": {"max": 5.5}}, {**good, "average_stars": {"min": 4, "max": 3}},
                    {**good, "average_stars": {"max": "3"}}, {**good, "average_stars": {"most": 3}}, {**good, "levels": {}},
                    {**good, "levels": {"speed": "weak"}}, {**good, "levels": {"punctuality": "awful"}},
                    {**good, "levels": {"punctuality": ["weak"]}}, {**good, "aspect": "punctuality"}, None):
            for call in (ratings.model, ratings.trial, lambda *a: ratings.prepare(*a, Random(0))):
                with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        place = ratings.site(self.natural, good, self.api)
        # An average no thirty-two whole ratings give.
        between = (4 * place.count + 1) / place.count
        with self.assertRaises(prices.ZeroMass):
            ratings.model(self.natural, self.need(average_stars={"min": round(between - .02, 3), "max": round(between - .012, 3)}),
                          self.api)
        # Extremes are possible, and reported in logarithms.
        lowest = ratings.model(self.natural, self.need(average_stars={"max": 1}), self.api)
        self.assertLess(lowest.log_probability, -50)


class ProducerTests(Ratings):
    def test_steered_worlds_hold_through_the_producer(self):
        for index, requirement in enumerate(self.requirements()):
            with self.subTest(requirement=requirement):
                world, found, record = ratings.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))
                carrier = requirement["carrier_id"]
                corpus, before = world["carrier_evidence"], self.natural["carrier_evidence"]
                summary = next(row["summary"] for row in corpus["public"]["carriers"] if row["carrier_id"] == carrier)
                stars = [row["stars"] for row in corpus["public"]["reviews"] if row["carrier_id"] == carrier]
                self.assertEqual(summary["average_stars"], round(sum(stars) / len(stars), 2))
                limits = requirement.get("average_stars", {})
                self.assertTrue(limits.get("min", 1) <= summary["average_stars"] <= limits.get("max", 5))
                levels = next(row["aspect_levels"] for row in corpus["private"]["carrier_parameters"] if row["carrier_id"] == carrier)
                self.assertEqual({aspect: levels[aspect] for aspect in requirement.get("levels", {})}, requirement.get("levels", {}))
                self.assertEqual(found["aspect_levels"], levels)
                self.assertEqual(world["status"], streams.STATUS)
                # Every other carrier's levels, shipments, stars and summary figures are the seed's own.
                for name in ("carrier_parameters", "shipments"):
                    self.assertEqual([row for row in corpus["private"][name] if row["carrier_id"] != carrier],
                                     [row for row in before["private"][name] if row["carrier_id"] != carrier])
                rest = lambda value: [(row["review_id"], row["stars"], [found["aspect"] for found in row["statements"]])
                                      for row in value["private"]["reviews"] if row["carrier_id"] != carrier]
                self.assertEqual(rest(corpus), rest(before))
                self.assertEqual((world["products"], world["retailers"]), (self.natural["products"], self.natural["retailers"]))
                # A review's stars are held to its comment's tone, as the producer holds them.
                for row in corpus["private"]["reviews"]:
                    signs = {found["sentiment"] for found in row["statements"]} - {"neutral"}
                    if row["carrier_id"] == carrier and signs:
                        self.assertTrue(row["stars"] >= 3 if signs == {"positive"} else row["stars"] <= 3 if signs == {"negative"}
                                        else row["stars"] <= 4)
        self.assertEqual(self.session.generate()[0]["world_id"], self.natural["world_id"])

    def test_repeated_samples_differ_and_redraws_equal_the_reading(self):
        requirement = self.need(average_stars={"max": 3.8})
        worlds = [ratings.steer(self.session, self.natural, self.opened, requirement, self.api, Random(seed))[1]
                  for seed in range(6)]
        self.assertGreater(len({json_levels(found) for found in worlds}), 2)
        reading = ratings.trial(self.natural, requirement, self.api)
        for seed in range(900, 905):
            found = blocks.redraw(self.session, self.natural, [reading], seed)
            self.assertEqual((found.identical, found.agreed), ([True], [True]))
            self.assertEqual(found.satisfied, reading.holds(seed))

    def test_it_combines_with_other_requirements(self):
        carrier, other = self.carriers[2], self.carriers[5]
        rated = {"schema": ratings.VERSION, "carrier_id": carrier, "average_stars": {"max": 3.9}}
        seller = {"schema": sellers.VERSION, "cheapest": {"concept_id": SANDALS},
                  "policy": {"carriers": {"include": [carrier]}, "carrier_count": {"max": 1}}}
        told = {"schema": carriers.VERSION, "carrier_id": other, "aspect": "handling", "positive": {"min": 1}}
        together = {"schema": combined.VERSION, "all": [rated, seller, told]}
        world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(2))
        self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in together["all"]))
        winner = next(row for row in world["retailers"] if row["retailer_id"] == found[1]["retailer_id"])
        self.assertEqual([row["carrier_id"] for row in winner["contracts"]], [carrier])
        self.assertLessEqual(found[0]["average_stars"], 3.9)
        self.assertAlmostEqual(record["log_probability_given_upstream"], sum(
            combined.KINDS[part["schema"]].model(self.natural, part, self.api).log_probability for part in together["all"]),
            places=9)
        # A carrier's stars are its reviews: another statement about the same carrier's reviews or shipments is coupled.
        for same in ({**told, "carrier_id": carrier},
                     {"schema": shipments.VERSION, "carrier_id": carrier, "aspect": "punctuality", "negative": {"min": 1}},
                     {**rated, "levels": {"handoff": "weak"}}):
            with self.subTest(same=same), self.assertRaises(blocks.Coupled):
                combined.prepare(self.natural, {"schema": combined.VERSION, "all": [rated, same]}, self.api, Random(0))

    def test_the_runner_samples_and_checks(self):
        args = SimpleNamespace(samples=2, producer_redraws=2, validate_trials=1500)
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.stars_case(args, self.session, self.natural, self.opened, self.api,
                           self.need(average_stars={"max": 3.9}, levels={"handling": "weak"}), case,
                           lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], len(case["samples"])), ("sampled", 2))
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertEqual(case["producer_redraws"]["identical_to_reading"], 2)


class TopicTests(Ratings):
    """Stars and levels together with what the carrier's comments say of one aspect."""

    def topics(self):
        return [self.need(average_stars={"max": 3.8}, topic={"aspect": "punctuality", "verdict": "more_negative"}),
                self.need(average_stars={"max": 3.8}, topic={"aspect": "handling", "negative": {"min": 2}}),
                self.need(1, levels={"punctuality": "weak"}, topic={"aspect": "punctuality", "verdict": "more_positive",
                                                                     "shipping_class": "regular"}),
                self.need(2, average_stars={"min": 4.3}, topic={"aspect": "handoff", "positive": {"min": 1}, "negative": {"max": 0}})]

    def test_probabilities_are_estimates_that_match_other_seeds(self):
        trials = 3000
        for requirement in self.topics():
            with self.subTest(requirement=requirement):
                block = ratings.model(self.natural, requirement, self.api)
                alone = ratings.model(self.natural, {k: v for k, v in requirement.items() if k != "topic"}, self.api)
                self.assertTrue(block.estimated and not alone.estimated)
                self.assertAlmostEqual(block.probability, alone.probability * block.accepted / ratings.PROPOSALS, places=12)
                hits, chance = ratings.empirical(self.natural, requirement, self.api, trials, 10 ** 6), block.probability
                self.assertLess(abs(hits / trials - chance), 4.5 * (chance * (1 - chance) / trials + block.error ** 2) ** .5 + 1e-9)
                self.assertEqual(ratings.model(self.natural, requirement, self.api).probability, chance)

    def test_steered_worlds_pass_the_native_review_task(self):
        for index, requirement in enumerate(self.topics()):
            with self.subTest(requirement=requirement):
                world, found, record = ratings.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))
                topic = {"schema": carriers.VERSION, "carrier_id": requirement["carrier_id"], **requirement["topic"]}
                self.assertEqual(found["topic"], carriers.check(world, topic, self.api))
                self.assertTrue(carriers.satisfied(world, topic, self.api))
                self.assertTrue(ratings.satisfied(world, {k: v for k, v in requirement.items() if k != "topic"}, self.api))
                self.assertTrue(record["probability_is_estimated"])
                self.assertGreaterEqual(record["block_samples_for_this_sample"], 1)
                self.assertEqual((world["products"], world["retailers"]), (self.natural["products"], self.natural["retailers"]))
        reading = ratings.trial(self.natural, self.topics()[0], self.api)
        for seed in range(900, 904):
            found = blocks.redraw(self.session, self.natural, [reading], seed)
            self.assertEqual((found.identical, found.agreed), ([True], [True]))
            self.assertEqual(found.satisfied, reading.holds(seed))

    def test_a_topic_counts_in_its_shipping_class_only_and_the_runner_labels_the_estimate(self):
        from collections import Counter
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from experiments.steered_generation import run
        carrier = self.carriers[3]
        classes = Counter(row["shipping_class"] for row in self.natural["carrier_evidence"]["private"]["shipments"]
                          if row["carrier_id"] == carrier)
        self.assertEqual(len(classes), 2)
        rare = min(classes, key=classes.get)
        requirement = self.need(3, average_stars={"min": 4.0}, topic={"aspect": "handling", "shipping_class": rare, "positive": {"min": 1}})
        topic = {"schema": carriers.VERSION, "carrier_id": carrier, **requirement["topic"]}
        everywhere = {key: value for key, value in topic.items() if key != "shipping_class"}
        only_elsewhere = 0
        for seed in range(8):
            world, found, record = ratings.steer(self.session, self.natural, self.opened, requirement, self.api, Random(seed))
            self.assertGreaterEqual(found["topic"]["counts"]["positive"], 1)
            self.assertTrue(carriers.satisfied(world, topic, self.api))
        # The same statement over every class is likelier, and holds in redraws where the class's own does not.
        place = ratings.site(self.natural, requirement, self.api)
        wide = ratings.site(self.natural, {**requirement, "topic": {k: v for k, v in requirement["topic"].items() if k != "shipping_class"}}, self.api)
        for seed in range(10 ** 6, 10 ** 6 + 400):
            levels = {name: ratings.level(place, name, seed) for name in place.aspects}
            happened = ratings.histories(place, levels)
            mentions = [ratings.reviewed(place, index, history, seed)[1] for index, history in enumerate(happened)]
            narrow, broad = ratings.said(place, happened, mentions), ratings.said(wide, happened, mentions)
            self.assertLessEqual(narrow, broad)
            only_elsewhere += broad and not narrow
        self.assertGreater(only_elsewhere, 10)
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.stars_case(SimpleNamespace(samples=1, producer_redraws=1, validate_trials=1500), self.session, self.natural,
                           self.opened, self.api, requirement, case, lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], case["probability_is_estimated"]), ("sampled", True))
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertIn("computed_standard_error", case["validation"])

    def test_samples_match_rejection_sampling(self):
        requirement = self.need(1, levels={"punctuality": "weak"}, topic={"aspect": "punctuality", "verdict": "more_positive"})
        place = ratings.site(self.natural, requirement, self.api)
        aspect = "punctuality"

        def features(levels, happened, found):
            signs = [next((row["sentiment"] for row in history["observations"] if row["aspect"] == aspect), None)
                     for history in happened]
            said = [sign for sign, (_, mentioned) in zip(signs, found) if sign and aspect in mentioned]
            return {"stars": sum(stars for stars, _ in found), "weak": sum(level == "weak" for level in levels.values()),
                    "positive": said.count("positive"), "negative": said.count("negative"),
                    "comments": sum(bool(mentioned) for _, mentioned in found)}

        theirs = []
        for seed in range(10 ** 6, 10 ** 6 + 4000):
            levels = {name: ratings.level(place, name, seed) for name in place.aspects}
            happened = ratings.histories(place, levels)
            found = [ratings.reviewed(place, index, history, seed) for index, history in enumerate(happened)]
            if ratings.holds(place.requirement, levels, [stars for stars, _ in found]) and ratings.said(
                    place, happened, [mentioned for _, mentioned in found]):
                theirs.append(features(levels, happened, found))
        self.assertGreater(len(theirs), 150)
        block, rng, mine = ratings.model(self.natural, requirement, self.api), Random(3), []
        while len(mine) < 250:
            drawn = ratings.draw(block, rng)
            if ratings.said(place, drawn.histories, drawn.mentions):
                mine.append(features(drawn.levels, drawn.histories, list(zip(drawn.stars, drawn.mentions))))
        for name in mine[0]:
            with self.subTest(feature=name):
                a, b = [float(row[name]) for row in mine], [float(row[name]) for row in theirs]
                error = lambda values: (sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values) ** 2) ** .5
                self.assertLess(abs(sum(a) / len(a) - sum(b) / len(b)), 4.5 * (error(a) ** 2 + error(b) ** 2) ** .5 + 1e-9)

    def test_refusals_not_found_and_combination(self):
        good = self.topics()[0]
        for bad in ({**good, "topic": {}}, {**good, "topic": {"aspect": "punctuality"}},
                    {**good, "topic": {"aspect": "speed", "verdict": "more_negative"}},
                    {**good, "topic": {"aspect": "punctuality", "verdict": "awful"}},
                    {**good, "topic": {"schema": carriers.VERSION, "aspect": "punctuality", "verdict": "more_negative"}},
                    {**good, "topic": {"carrier_id": self.carriers[1], "aspect": "punctuality", "verdict": "more_negative"}},
                    {"schema": ratings.VERSION, "carrier_id": self.carriers[0], "topic": good["topic"]}, {**good, "topic": []}):
            for call in (ratings.model, ratings.trial):
                with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        with self.assertRaises(prices.ZeroMass) as caught:
            ratings.model(self.natural, {**good, "topic": {"aspect": "punctuality", "positive": {"min": 30}}}, self.api)
        self.assertEqual(caught.exception.reason, "not_found")
        # The comments are the block's own reviews: another statement about them is coupled; another carrier's is not.
        told = lambda carrier: {"schema": carriers.VERSION, "carrier_id": carrier, "aspect": "handling", "positive": {"min": 1}}
        with self.assertRaises(blocks.Coupled):
            combined.prepare(self.natural, {"schema": combined.VERSION, "all": [good, told(good["carrier_id"])]}, self.api, Random(0))
        together = {"schema": combined.VERSION, "all": [good, told(self.carriers[5])]}
        world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(4))
        self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in together["all"]))
        self.assertTrue(record["probability_is_estimated"])
        plain = ratings.prepare(self.natural, self.need(average_stars={"max": 3.8}), self.api, Random(0))
        self.assertEqual((plain.estimated, plain.error), (False, 0.0))


def json_levels(found):
    return tuple(sorted(found["aspect_levels"].items())), found["average_stars"]


if __name__ == "__main__":
    unittest.main()
