"""Tests of the carrier-review block against the real producer.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_carriers.py
The world is the review tests' own (really manufactured pilot products); the
carrier corpus, its histories and its reviews are the producer's, and the
native carrier-review task reads the steered worlds.
"""
from collections import Counter
from itertools import product as combinations
from math import exp, prod
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from environments.website_world import carrier_review_task

from experiments.steered_generation import blocks, carriers, combined, prices, reviews, run, stock, streams, variants
from experiments.steered_generation.test_reviews import GRIP, Reviews

ASPECTS = ("handoff", "punctuality", "tracking", "handling", "collection", "notification_dispatch")
SCOPES = ({}, {"shipping_class": "regular"}, {"date_from": "2026-08-14"}, {"shipping_class": "regular", "date_to": "2026-08-31"})


class Carriers(Reviews):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.corpus = cls.natural["carrier_evidence"]
        cls.names = sorted(c["carrier_id"] for c in cls.corpus["public"]["carriers"])

    def need(self, carrier=None, aspect="tracking", **stated):
        return {"schema": carriers.VERSION, "carrier_id": carrier or self.mixed, "aspect": aspect, **stated}

    def place(self, carrier, aspect, **scope):
        return carriers.site(self.natural, self.need(carrier, aspect, verdict="tie", **scope), self.api)

    @property
    def mixed(self):
        """A carrier whose shipments had good and bad tracking, several of each."""
        return next(name for name in self.names
                    if min(Counter(s.sign for s in self.place(name, "tracking").shipments).get(sign, 0)
                           for sign in ("positive", "negative")) >= 3)

    @property
    def spotless(self):
        """A carrier with some aspect on which nothing went wrong."""
        return next((name, aspect) for name in self.names for aspect in ASPECTS[:3]
                    if {s.sign for s in self.place(name, aspect).shipments} == {"positive"})

    def requirements(self):
        clean, aspect = self.spotless
        return [self.need(verdict="more_negative"), self.need(verdict="tie", min_assessed=2),
                self.need(verdict="insufficient_evidence", min_assessed=3),
                # Rare: every complaint there could be and no praise; a pile of praise in a narrower scope.
                self.need(negative={"min": 3}, positive={"max": 0}),
                self.need(positive={"min": 8}, shipping_class="regular", date_from="2026-08-01"),
                self.need(clean, aspect, verdict="more_positive", positive={"min": 5}),
                self.need(next(name for name in self.names if self.place(name, "collection").shipments), "collection",
                          verdict="tie", min_assessed=2)]


class ModelTests(Carriers):
    def test_the_reading_of_every_review_is_what_the_producer_recorded(self):
        seen = Counter()
        for name in self.names:
            for aspect in ASPECTS:
                for scope in SCOPES:
                    place = self.place(name, aspect, **scope)
                    self.assertEqual(carriers.written(self.natural, place),
                                     [carriers.drawn(place, shipment, place.seed) for shipment in place.shipments])
                    # The native task counts what the recorded reviews say, in every scope.
                    found = carriers.check(self.natural, self.need(name, aspect, positive={"min": 0}, **scope), self.api)
                    seen.update({sign: found["counts"][sign] for sign in carriers.SIGNS})
                    self.assertEqual(found["counts"]["mixed"], 0)
        self.assertTrue(all(seen[sign] > 5 for sign in carriers.SIGNS), seen)
        # Scopes narrow the block.
        sizes = [len(self.place(self.mixed, "tracking", **scope).shipments) for scope in SCOPES]
        self.assertTrue(sizes[0] > sizes[1] > sizes[3] > 0 and sizes[0] > sizes[2] > 0, sizes)

    def test_each_shipments_chance_of_a_mention_matches_other_seeds(self):
        trials = 6000
        for aspect in ("tracking", "punctuality", "notification_dispatch", "collection"):
            name = next(name for name in self.names if self.place(name, aspect).shipments)
            place = self.place(name, aspect)
            hits = Counter(shipment.id for seed in range(trials) for shipment in place.shipments
                           if aspect in carriers.drawn(place, shipment, seed))
            for shipment in place.shipments:
                with self.subTest(aspect=aspect, shipment=shipment.id):
                    self.assertLess(abs(hits[shipment.id] / trials - shipment.chance),
                                    4.5 * (shipment.chance * (1 - shipment.chance) / trials) ** .5)
            total, expected = sum(hits.values()), trials * sum(s.chance for s in place.shipments)
            self.assertLess(abs(total - expected), 4 * expected ** .5)
            self.assertGreater(len({round(s.chance, 9) for s in place.shipments}), 1, "shipments differ in what there is to mention")

    def test_counts_match_enumeration(self):
        for chances in ([.3], [.1, .9, .5], [0, .25, 1, .6, .05], [.07, .08, .2, .2, .9, .33, .5]):
            shipments = [SimpleNamespace(chance=chance) for chance in chances]
            tails = carriers.counts(shipments)
            for start in range(len(chances) + 1):
                direct = Counter()
                for outcome in combinations((0, 1), repeat=len(chances) - start):
                    direct[sum(outcome)] += prod(c if hit else 1 - c for c, hit in zip(chances[start:], outcome))
                self.assertEqual(len(tails[start]), len(chances) - start + 1)
                for number, value in enumerate(tails[start]):
                    self.assertAlmostEqual(exp(value), direct[number], places=12, msg=(chances, start, number))

    def test_probabilities_match_other_seeds(self):
        trials = 5000
        for requirement in self.requirements():
            with self.subTest(requirement=requirement):
                block = carriers.model(self.natural, requirement, self.api)
                hits, chance = sum(carriers.empirical(self.natural, requirement, self.api, trials, 10 ** 6).values()), block.probability
                self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5)
                self.assertGreater(hits, 100 if chance > .05 else -1)
        for name in self.names:
            for aspect in ASPECTS:
                for least in (1, 3):
                    total = 0
                    for verdict in carriers.VERDICTS:
                        try:
                            total += carriers.model(self.natural, self.need(name, aspect, verdict=verdict, min_assessed=least),
                                                    self.api).probability
                        except prices.ZeroMass:
                            pass
                    self.assertAlmostEqual(total, 1, places=10)

    def test_samples_match_rejection_sampling(self):
        requirement = self.need(verdict="tie", min_assessed=2)
        place = carriers.site(self.natural, requirement, self.api)
        reading = carriers.trial(self.natural, requirement, self.api)
        accepted = [rows for rows in map(reading.reading, range(10 ** 6, 10 ** 6 + 40000))
                    if carriers.holds(requirement, *carriers.counted(place, rows))]
        rng, sampled = Random(12), []
        for _ in range(len(accepted)):
            step = carriers.prepare(self.natural, requirement, self.api, rng)
            sampled.append([carriers.drawn(place, shipment, step.script[shipment.key].seed) for shipment in place.shipments])
            self.assertTrue(carriers.holds(requirement, *carriers.counted(place, sampled[-1])))
        self.assertGreater(len(accepted), 400)
        # Which shipments speak of the aspect, how much is written at all, and what else is mentioned.
        features = {"count": lambda rows: carriers.counted(place, rows)[0],
                    "written": lambda rows: sum(bool(row) for row in rows),
                    "statements": lambda rows: sum(map(len, rows)),
                    "first_place": lambda rows: sum(row[:1] == [place.aspect] for row in rows),
                    **{"mentions_of_" + str(index): (lambda rows, index=index: place.aspect in rows[index])
                       for index in range(len(place.shipments))}}
        for name, feature in features.items():
            with self.subTest(feature=name):
                mine, theirs = [feature(rows) for rows in sampled], [feature(rows) for rows in accepted]
                spread = lambda values: (sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values) ** 2) ** .5
                self.assertLess(abs(sum(mine) / len(mine) - sum(theirs) / len(theirs)),
                                4.5 * (spread(mine) ** 2 + spread(theirs) ** 2) ** .5 + 1e-9)

    def test_a_sample_redraws_every_review_of_the_block(self):
        requirement = self.need(negative={"min": 3})
        place = carriers.site(self.natural, requirement, self.api)
        step = carriers.prepare(self.natural, requirement, self.api, Random(3))
        self.assertEqual(set(step.script), {shipment.key for shipment in place.shipments})
        self.assertEqual(len({entry.seed for entry in step.script.values()}), len(place.shipments))
        self.assertEqual((step.writes, step.reads), ({("carrier_reviews", "", self.mixed)}, set()))


class ProducerTests(Carriers):
    def test_steered_worlds_hold_through_the_producer_and_the_native_carrier_review_task(self):
        declared = carrier_review_task.ReviewInventory()
        for index, requirement in enumerate(self.requirements()):
            with self.subTest(requirement=requirement):
                world, found, record = carriers.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))
                counts = found["counts"]
                self.assertTrue(carriers.holds(requirement, counts["positive"], counts["negative"], counts["neutral"]))
                self.assertEqual(record["steered_counts"], {sign: counts[sign] for sign in carriers.SIGNS})
                # The native task itself, built here and not by the module under test.
                spec = {"kind": carrier_review_task.KIND, "operation": "topic_counts", "aspect": requirement["aspect"],
                        "carrier_index": self.names.index(requirement["carrier_id"]),
                        "min_assessed": requirement.get("min_assessed", 1),
                        **{key: requirement[key] for key in ("shipping_class", "date_from", "date_to") if key in requirement}}
                reference = carrier_review_task.reference(world, carrier_review_task.make(world, spec, inventory=declared),
                                                          inventory=declared)
                self.assertEqual((reference["subject"]["carrier_id"], reference["counts"]), (requirement["carrier_id"], counts))
                self.assertEqual(requirement.get("verdict", reference["verdict"]), reference["verdict"])
                # What happened to the shipments is untouched, and so is what other carriers' reviews say.
                before, after = self.corpus, world["carrier_evidence"]
                self.assertEqual(after["private"]["shipments"], before["private"]["shipments"])
                block = {shipment.id for shipment in carriers.site(self.natural, requirement, self.api).shipments}
                said = lambda corpus: [(row["review_id"], row["stars"], [(s["aspect"], s["sentiment"]) for s in row["statements"]])
                                       for row in corpus["private"]["reviews"] if row["shipment_id"] not in block]
                self.assertEqual(said(after), said(before))
                self.assertGreater(len(said(before)), len(before["private"]["reviews"]) - 33)
                self.assertNotEqual(after["corpus_id"], before["corpus_id"])
                self.assertEqual((world["products"], world["retailers"]), (self.natural["products"], self.natural["retailers"]))
        self.assertEqual(self.session.generate()[0]["world_id"], self.natural["world_id"])

    def test_what_happened_to_the_shipments_bounds_what_can_be_asked(self):
        clean, aspect = self.spotless
        for impossible in (self.need(clean, aspect, verdict="more_negative"), self.need(clean, aspect, negative={"min": 1}),
                           self.need(positive={"min": 33}), self.need(verdict="more_positive", date_from="2030-01-01"),
                           self.need(verdict="tie", positive={"min": 1}, negative={"max": 0})):
            with self.subTest(impossible=impossible), self.assertRaises(prices.ZeroMass) as caught:
                carriers.model(self.natural, impossible, self.api)
            self.assertEqual(caught.exception.reason, "no_outcome")
        # Nothing in scope: only "no comment assesses it" is left, and it is certain.
        block = carriers.model(self.natural, self.need(verdict="insufficient_evidence", date_from="2030-01-01"), self.api)
        self.assertEqual((block.probability, block.site.shipments), (1.0, []))

    def test_redraws_through_the_producer_equal_the_reading(self):
        for requirement in (self.requirements()[0], self.requirements()[4]):
            reading = carriers.trial(self.natural, requirement, self.api)
            for seed in range(900, 904):
                found = blocks.redraw(self.session, self.natural, [reading], seed)
                self.assertEqual((found.identical, found.agreed), ([True], [True]))
                self.assertEqual(found.satisfied, reading.holds(seed))

    def test_it_combines_with_other_carriers_products_and_commerce_blocks(self):
        other = next(name for name in self.names if name != self.mixed)
        first, second = self.need(verdict="more_negative"), self.need(other, "punctuality", verdict="more_positive")
        retailer = next(r for r in self.natural["retailers"] if r["offers"])
        held = {"schema": stock.VERSION, "retailer_id": retailer["retailer_id"], "sku_id": retailer["offers"][0]["sku_id"],
                "availability": "in_stock"}
        shoes = {"schema": reviews.VERSION, "product_id": self.shoes[0], "topic": GRIP, "verdict": "tie"}
        together = {"schema": combined.VERSION, "all": [first, second, held, shoes]}
        world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(4))
        self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in together["all"]))
        chances = [carriers.model(self.natural, part, self.api).probability for part in (first, second)]
        pair = {"schema": combined.VERSION, "all": [first, second]}
        trials = 4000
        alone, both = combined.empirical(self.natural, pair, self.api, trials, 10 ** 6)
        for hits, chance in zip(alone + [both], chances + [prod(chances)]):
            self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5)
        for seed in range(700, 703):
            found = combined.redraw(self.session, self.natural, pair, self.api, seed)
            self.assertEqual((found.identical, found.agreed), ([True, True], [True, True]))
        with self.assertRaises(blocks.Coupled) as caught:
            combined.prepare(self.natural, {"schema": combined.VERSION, "all": [first, self.need(aspect="handling", positive={"min": 1})]},
                             self.api, Random(0))
        self.assertIn(self.mixed, str(caught.exception))

    def test_the_runner_samples_and_checks_a_carrier_requirement(self):
        args = SimpleNamespace(samples=2, producer_redraws=2, validate_trials=1500)
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.reviews_case(args, self.session, self.natural, self.opened, self.api, self.need(verdict="more_negative"),
                             case, lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], len(case["samples"]), case["carrier_id"]), ("sampled", 2, self.mixed))
        self.assertTrue(all(sample["verdict"] == "more_negative" for sample in case["samples"]))
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertEqual(case["producer_redraws"]["identical_to_reading"], 2)
        self.assertEqual(run.CASES[carriers.VERSION][1], run.reviews_case)

    def test_bad_requirements(self):
        good = self.need(verdict="tie")
        for bad in ({**good, "carrier_id": "nobody"}, {**good, "aspect": "politeness"}, {**good, "verdict": "fine"},
                    {**good, "positive": {}}, {**good, "min_assessed": 0}, {**good, "shipping_class": "fragile"},
                    {**good, "date_from": "14 August"}, {**good, "date_from": "2026-09-01", "date_to": "2026-08-01"},
                    {k: v for k, v in good.items() if k != "verdict"}, self.need(positive={"min": 1}, min_assessed=2),
                    {**good, "product_id": "x"}, None):
            for call in (carriers.model, carriers.trial, lambda *a: carriers.prepare(*a, Random(0))):
                with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        with self.assertRaises(streams.PlanMismatch):
            self.session.generate({(streams.CARRIER, "carrier-service-evidence-v1/review/x"): [("random", .5)]})

    def test_candidates_for_the_carrier_review_task(self):
        task = {"kind": "summarize_carrier_reviews", "operation": "topic_counts", "carrier_index": self.names.index(self.mixed),
                "shipping_class": "regular", "date_from": "2026-08-01", "aspect": "tracking", "min_assessed": 2}
        found = variants.of(self.natural, task, self.api)
        self.assertEqual({row["name"] for row in found}, {"verdict_" + verdict for verdict in carriers.VERDICTS})
        self.assertAlmostEqual(sum(exp(row["log_probability"]) for row in found), 1, places=10)
        for index, row in enumerate(found):
            self.assertEqual({key: row["requirement"][key] for key in ("carrier_id", "shipping_class", "date_from", "min_assessed")},
                             {"carrier_id": self.mixed, "shipping_class": "regular", "date_from": "2026-08-01", "min_assessed": 2})
            world, seen, _ = carriers.steer(self.session, self.natural, self.opened, row["requirement"], self.api, Random(index))
            self.assertEqual("verdict_" + seen["verdict"], row["name"])
        # A verdict the shipments' histories rule out is not offered.
        clean, aspect = self.spotless
        names = {row["name"] for row in variants.of(self.natural, {**task, "carrier_index": self.names.index(clean), "aspect": aspect},
                                                    self.api)}
        self.assertNotIn("verdict_more_negative", names)
        self.assertIn("verdict_more_positive", names)
        for bad in ({**task, "operation": "rating_summary"}, {**task, "carrier_index": 99}, {**task, "aspect": "politeness"},
                    {k: v for k, v in task.items() if k != "aspect"}, {**task, "concept_id": "footwear.walking_shoes"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                variants.of(self.natural, bad, self.api)
