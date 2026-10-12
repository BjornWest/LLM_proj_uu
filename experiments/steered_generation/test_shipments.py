"""Tests of the carrier-shipments block against the real producer.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_shipments.py
The world is the review tests' own. Histories are read with the producer's
own `history`, and the native carrier-review task reads the steered worlds.
"""
from collections import Counter
from datetime import datetime
from math import exp, prod
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from environments.website_world import carrier_review_task

from experiments.steered_generation import blocks, carriers, combined, prices, reviews, run, shipments, streams, variants
from experiments.steered_generation.test_carriers import Carriers
from experiments.steered_generation.test_reviews import GRIP

NARROW = {"shipping_class": "regular", "date_from": "2026-08-14"}
SCOPES = ({}, NARROW, {"shipping_class": "bulky"}, {"date_from": "2026-07-20", "date_to": "2026-08-20"})


class Shipments(Carriers):
    def need(self, carrier=None, aspect="handoff", **stated):
        return {"schema": shipments.VERSION, "carrier_id": carrier or self.names[0], "aspect": aspect, **stated}

    def place(self, carrier, aspect, **scope):
        return carriers.site(self.natural, {"schema": carriers.VERSION, "carrier_id": carrier, "aspect": aspect,
                                            "verdict": "tie", **scope}, self.api)

    def site(self, carrier, aspect, **scope):
        return shipments.site(self.natural, self.need(carrier, aspect, verdict="tie", **scope), self.api)

    def kinds(self):
        """One carrier for every combination of what the model reads of a carrier's services and levels."""
        found = {}
        for name in self.names:
            place = self.site(name, "handoff")
            key = (tuple((s["shipping_class"], s["scheduling"], s["unattended_allowed"], tuple(s["notifications"].values()))
                         for s in place.policy["services"]), bool(place.policy["collection_point_ids"]),
                   place.levels["handoff"], place.levels["punctuality"])
            found.setdefault(key, name)
        return list(found.values())

    @property
    def clean(self):
        """A carrier and aspect on which nothing went wrong in the natural world."""
        return next((name, aspect) for name in self.names for aspect in shipments.MODELLED
                    if not shipments.counted(self.site(name, aspect), [(history, [aspect]) for history, _ in
                                                                       shipments.written(self.natural, self.site(name, aspect))])[1])

    def requirements(self):
        name, aspect = self.clean
        return [self.need(verdict="more_positive"), self.need(verdict="insufficient_evidence", min_assessed=2),
                # Complaints about something that went well for every shipment of the natural world.
                self.need(name, aspect, verdict="more_negative"), self.need(name, aspect, negative={"min": 3}, positive={"max": 0}),
                self.need(self.names[1], "punctuality", verdict="tie", min_assessed=4, **NARROW),
                self.need(self.names[2], "punctuality", positive={"min": 7}, shipping_class="bulky")]


class ModelTests(Shipments):
    def test_the_reading_of_every_shipment_is_what_the_producer_recorded(self):
        for name in self.names:
            place = self.site(name, "handoff")
            with shipments.readings(place) as read:
                self.assertEqual(shipments.written(self.natural, place), [read(index, None) for index in range(place.count)])
            self.assertEqual(place.producer.rng.__name__, "rng", "the producer's stream function is put back")
            # The class the block gives a shipment is the native task's count, in every scope.
            for aspect in shipments.MODELLED:
                for scope in SCOPES:
                    found = shipments.check(self.natural, self.need(name, aspect, positive={"min": 0}, **scope), self.api)
                    self.assertEqual((found["counts"]["neutral"], found["counts"]["mixed"]), (0, 0))

    def test_one_shipments_class_probabilities_match_other_seeds(self):
        trials, carriers_seen = 5000, self.kinds()
        self.assertGreater(len(carriers_seen), 2)
        for name in carriers_seen:
            # A shipment's history and review do not depend on the aspect asked about.
            reading = shipments.trial(self.natural, self.need(name, verdict="tie"), self.api).reading
            rows = [row for seed in range(trials) for row in reading(seed)]
            for aspect in shipments.MODELLED:
                for scope in SCOPES:
                    with self.subTest(carrier=name, aspect=aspect, scope=scope):
                        place = self.site(name, aspect, **scope)
                        share, seen = shipments.shares(place), Counter(shipments.said(place, row) for row in rows)
                        self.assertAlmostEqual(sum(share.values()), 1, places=12)
                        for sign, chance in share.items():
                            self.assertLess(abs(seen[sign] / len(rows) - chance),
                                            4.5 * (chance * (1 - chance) / len(rows)) ** .5 + 1e-12, sign)

    def test_the_parts_of_the_model_match_other_seeds(self):
        """Where the shipment went and when, apart from what the review says: each factor by itself."""
        for name in self.kinds():
            place = self.site(name, "handoff")
            reading = shipments.trial(self.natural, self.need(name, verdict="tie"), self.api).reading
            rows = [row[0] for seed in range(4000) for row in reading(seed)]
            first = place.policy["services"][0]["service_id"]
            share = sum(row["service_id"] == first for row in rows) / len(rows)
            self.assertLess(abs(share - shipments.FIRST_SERVICE), 4.5 * (.21 / len(rows)) ** .5)
            for service in place.policy["services"]:
                mine = [row for row in rows if row["service_id"] == service["service_id"]]
                collected = sum(row["destination_type"] == "collection" for row in mine) / len(mine)
                expected = shipments.COLLECTED if service["shipping_class"] == "regular" and place.policy["collection_point_ids"] else 0
                self.assertLess(abs(collected - expected), 4.5 * (expected * (1 - expected) / len(mine)) ** .5 + 1e-12)
                home = [row for row in mine if row["destination_type"] == "home"]
                failed = sum(row["failed_first_attempt"] for row in home) / len(home)
                works = shipments.AT_HOME + (1 - shipments.AT_HOME) * (shipments.PERMITTED if service["unattended_allowed"] else 0) * (
                    shipments.AUTHORISED + shipments.CODE * shipments.CODE_GIVEN)
                self.assertLess(abs(failed - (1 - works)), 4.5 * (works * (1 - works) / len(home)) ** .5)
                done = [row for row in home if not row["failed_first_attempt"]]
                for field, rate, level in (("handoff_complied", "promised_handoff_complied_with", "handoff"),
                                           ("first_attempt_on_promised_day", "arrival_on_promised_day", "punctuality")):
                    chance = place.rates[rate][place.levels[level]]
                    self.assertLess(abs(sum(row[field] for row in done) / len(done) - chance),
                                    4.5 * (chance * (1 - chance) / len(done)) ** .5, field)
                # When the first attempt falls: mean and spread of the day, overall and for the late ones.
                quote = datetime.fromisoformat(place.base["quote_as_of"]).date()
                model = shipments.dated(place, service)
                self.assertAlmostEqual(sum(model.values()), 1, places=12)
                days = lambda rows: [(datetime.fromisoformat(row["receipt_at"]).date() - quote).days for row in rows]
                for label, seen, part in (("all", days(done), model),
                                          ("late", days([row for row in done if not row["first_attempt_on_promised_day"]]),
                                           {key: mass for key, mass in model.items() if not key[1]})):
                    mass = sum(part.values())
                    mean = sum(key[0] * value for key, value in part.items()) / mass
                    spread = (sum((key[0] - mean) ** 2 * value for key, value in part.items()) / mass) ** .5
                    self.assertLess(abs(sum(seen) / len(seen) - mean), 4.5 * spread / len(seen) ** .5, label)
                    ahead = sum(value for key, value in part.items() if key[0] > mean + 30) / mass
                    self.assertLess(abs(sum(day > mean + 30 for day in seen) / len(seen) - ahead),
                                    4.5 * (ahead * (1 - ahead) / len(seen)) ** .5, label)
                # The days from the planned handover to the first attempt, by themselves: every value with its share.
                gap = Counter(((datetime.fromisoformat(row["first_attempt_at"]).date() -
                                datetime.fromisoformat(row["planned_handover_at"]).date()).days,
                               bool(row["first_attempt_on_promised_day"])) for row in done)
                lead = shipments.leads(place, service)
                self.assertLessEqual(set(gap), set(lead))
                for key, chance in lead.items():
                    self.assertLess(abs(gap[key] / len(done) - chance), 4.5 * (chance * (1 - chance) / len(done)) ** .5 + 1e-12,
                                    (key, service["service_id"]))
                # The review's date: a window of two weeks holds the share the model's enumeration gives it.
                window = self.site(name, "handoff", shipping_class=service["shipping_class"], date_from="2026-08-10", date_to="2026-08-23")
                inside = sum("2026-08-10" <= datetime.fromisoformat(row["receipt_at"]).date().isoformat() <= "2026-08-23"
                             for row in done) / len(done)
                told = carriers.mention(1, ["handoff"], "handoff")
                self.assertEqual(told, 1)
                whole = self.site(name, "handoff", shipping_class=service["shipping_class"])
                ratio = (1 - shipments.shares(window)[reviews.REST]) / (1 - shipments.shares(whole)[reviews.REST])
                self.assertLess(abs(inside - ratio), 4.5 * (ratio * (1 - ratio) / len(done)) ** .5)

    def test_probabilities_match_other_seeds(self):
        trials = 4000
        for requirement in self.requirements():
            with self.subTest(requirement=requirement):
                block = shipments.model(self.natural, requirement, self.api)
                hits, chance = sum(shipments.empirical(self.natural, requirement, self.api, trials, 10 ** 6).values()), block.probability
                self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5 + 1e-12)
                self.assertGreater(hits, 100 if chance > .05 else -1)
        for name in self.names:
            for aspect in shipments.MODELLED:
                total = sum(shipments.model(self.natural, self.need(name, aspect, verdict=verdict, min_assessed=2, **NARROW),
                                            self.api).probability for verdict in carriers.VERDICTS)
                self.assertAlmostEqual(total, 1, places=10)

    def test_samples_match_rejection_sampling(self):
        requirement = self.need(self.names[1], "punctuality", verdict="tie", min_assessed=2)
        place = shipments.site(self.natural, requirement, self.api)
        reading = shipments.trial(self.natural, requirement, self.api)
        accepted = [rows for rows in map(reading.reading, range(10 ** 6, 10 ** 6 + 20000))
                    if shipments.holds(requirement, *shipments.counted(place, rows))]
        rng, sampled = Random(13), []
        for _ in range(len(accepted)):
            step = shipments.prepare(self.natural, requirement, self.api, rng)
            with shipments.readings(place) as read:
                sampled.append([read(index, step.script[place.keys(index)[0]].seed) for index in range(place.count)])
            self.assertTrue(shipments.holds(requirement, *shipments.counted(place, sampled[-1])))
        self.assertGreater(len(accepted), 250)
        day = lambda row: datetime.fromisoformat(row[0]["receipt_at"]).date().toordinal()
        features = {"positive": lambda rows: shipments.counted(place, rows)[0],
                    "written": lambda rows: sum(bool(row[1]) for row in rows),
                    "on_time": lambda rows: sum(bool(row[0]["first_attempt_on_promised_day"]) for row in rows),
                    "collected": lambda rows: sum(row[0]["destination_type"] == "collection" for row in rows),
                    "failed": lambda rows: sum(row[0]["failed_first_attempt"] for row in rows),
                    "bulky": lambda rows: sum(row[0]["shipping_class"] == "bulky" for row in rows),
                    "day": lambda rows: sum(map(day, rows)) / len(rows),
                    "day_of_complaint": lambda rows: sum(day(row) - 739000 for row in rows if shipments.said(place, row) == "negative"),
                    "place_of_praise": lambda rows: sum(i for i, row in enumerate(rows) if shipments.said(place, row) == "positive"),
                    "handover_kept": lambda rows: sum(bool(row[0]["handoff_complied"]) for row in rows)}
        for name, feature in features.items():
            with self.subTest(feature=name):
                mine, theirs = [feature(rows) for rows in sampled], [feature(rows) for rows in accepted]
                spread = lambda values: (sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values) ** 2) ** .5
                self.assertLess(abs(sum(mine) / len(mine) - sum(theirs) / len(theirs)),
                                4.5 * (spread(mine) ** 2 + spread(theirs) ** 2) ** .5 + 1e-9)

    def test_a_sample_redraws_every_shipment_of_the_carrier(self):
        requirement = self.need(negative={"min": 2})
        place = shipments.site(self.natural, requirement, self.api)
        step = shipments.prepare(self.natural, requirement, self.api, Random(3))
        self.assertEqual(len(step.script), 2 * place.count)
        self.assertEqual({key[1].split("/")[1] for key in step.script}, {"history", "review"})
        self.assertEqual(len({entry.seed for entry in step.script.values()}), place.count)
        self.assertEqual(step.writes, {("carrier_reviews", "", self.names[0]), ("carrier_shipments", "", self.names[0])})


class ProducerTests(Shipments):
    def test_steered_worlds_hold_through_the_producer_and_the_native_carrier_review_task(self):
        declared = carrier_review_task.ReviewInventory()
        for index, requirement in enumerate(self.requirements()):
            with self.subTest(requirement=requirement):
                world, found, record = shipments.steer(self.session, self.natural, self.opened, requirement, self.api, Random(index))
                counts, carrier = found["counts"], requirement["carrier_id"]
                self.assertTrue(shipments.holds(requirement, counts["positive"], counts["negative"]))
                self.assertEqual(record["steered_counts"], {"positive": counts["positive"], "negative": counts["negative"]})
                spec = {"kind": carrier_review_task.KIND, "operation": "topic_counts", "aspect": requirement["aspect"],
                        "carrier_index": self.names.index(carrier), "min_assessed": requirement.get("min_assessed", 1),
                        **{key: requirement[key] for key in ("shipping_class", "date_from", "date_to") if key in requirement}}
                reference = carrier_review_task.reference(world, carrier_review_task.make(world, spec, inventory=declared),
                                                          inventory=declared)
                self.assertEqual((reference["subject"]["carrier_id"], reference["counts"]), (carrier, counts))
                self.assertEqual(requirement.get("verdict", reference["verdict"]), reference["verdict"])
                # This carrier's shipments are all new; the other carriers' are untouched, and so is what their reviews say.
                before, after = self.corpus["private"], world["carrier_evidence"]["private"]
                mine = lambda rows: [row for row in rows if row["carrier_id"] == carrier]
                others = lambda rows: [row for row in rows if row["carrier_id"] != carrier]
                self.assertEqual(others(after["shipments"]), others(before["shipments"]))
                self.assertFalse(any(new == old for new, old in zip(mine(after["shipments"]), mine(before["shipments"]))))
                said = lambda rows: [(row["review_id"], row["stars"], [(s["aspect"], s["sentiment"]) for s in row["statements"]])
                                     for row in others(rows)]
                self.assertEqual(said(after["reviews"]), said(before["reviews"]))
                policy = lambda corpus: [{k: v for k, v in row.items() if k != "summary"} for row in corpus["public"]["carriers"]]
                self.assertEqual(policy(world["carrier_evidence"]), policy(self.corpus))
                self.assertEqual([row["aspect_levels"] for row in after["carrier_parameters"]],
                                 [row["aspect_levels"] for row in before["carrier_parameters"]])
                self.assertEqual((world["products"], world["retailers"]), (self.natural["products"], self.natural["retailers"]))
        self.assertEqual(self.session.generate()[0]["world_id"], self.natural["world_id"])

    def test_what_the_reviews_only_block_cannot_ask_this_one_can(self):
        name, aspect = self.clean
        stated = {"carrier_id": name, "aspect": aspect, "verdict": "more_negative"}
        with self.assertRaises(prices.ZeroMass):
            carriers.model(self.natural, {"schema": carriers.VERSION, **stated}, self.api)
        block = shipments.model(self.natural, {"schema": shipments.VERSION, **stated}, self.api)
        self.assertTrue(0 < block.probability < .2)

    def test_redraws_through_the_producer_equal_the_reading(self):
        for requirement in (self.requirements()[0], self.requirements()[4]):
            reading = shipments.trial(self.natural, requirement, self.api)
            for seed in range(900, 904):
                found = blocks.redraw(self.session, self.natural, [reading], seed)
                self.assertEqual((found.identical, found.agreed), ([True], [True]))
                self.assertEqual(found.satisfied, reading.holds(seed))

    def test_it_combines_with_other_carriers_and_is_coupled_with_the_same_carriers_reviews(self):
        first = self.need(verdict="more_positive")
        other = {"schema": carriers.VERSION, "carrier_id": self.mixed if self.mixed != self.names[0] else self.names[1],
                 "aspect": "tracking", "verdict": "more_positive"}
        shoes = {"schema": reviews.VERSION, "product_id": self.shoes[0], "topic": GRIP, "verdict": "tie"}
        together = {"schema": combined.VERSION, "all": [first, other, shoes]}
        world, found, record = combined.steer(self.session, self.natural, self.opened, together, self.api, Random(4))
        self.assertTrue(all(combined.KINDS[part["schema"]].satisfied(world, part, self.api) for part in together["all"]))
        pair = {"schema": combined.VERSION, "all": [first, other]}
        chances = [shipments.model(self.natural, first, self.api).probability, carriers.model(self.natural, other, self.api).probability]
        trials = 3000
        alone, both = combined.empirical(self.natural, pair, self.api, trials, 10 ** 6)
        for hits, chance in zip(alone + [both], chances + [prod(chances)]):
            self.assertLess(abs(hits / trials - chance), 4 * (chance * (1 - chance) / trials) ** .5)
        for seed in range(700, 703):
            found = combined.redraw(self.session, self.natural, pair, self.api, seed)
            self.assertEqual((found.identical, found.agreed), ([True, True], [True, True]))
        # The reviews-only block reads the histories this block redraws, whichever comes first.
        same = {"schema": carriers.VERSION, "carrier_id": self.names[0], "aspect": "tracking", "verdict": "more_positive"}
        for parts in ([first, same], [same, first], [first, self.need(aspect="punctuality", verdict="tie")]):
            with self.subTest(parts=parts), self.assertRaises(blocks.Coupled) as caught:
                combined.prepare(self.natural, {"schema": combined.VERSION, "all": parts}, self.api, Random(0))
            self.assertIn(self.names[0], str(caught.exception))

    def test_the_runner_samples_and_checks_a_shipments_requirement(self):
        args = SimpleNamespace(samples=2, producer_redraws=2, validate_trials=1500)
        case = {"samples": [], "requirement_sha256": "x"}
        with TemporaryDirectory() as folder:
            run.reviews_case(args, self.session, self.natural, self.opened, self.api, self.need(verdict="more_positive"),
                             case, lambda index: Path(folder) / str(index))
        self.assertEqual((case["status"], len(case["samples"]), case["shipments"]), ("sampled", 2, 32))
        self.assertTrue(all(sample["verdict"] == "more_positive" and sample["review_redraws"] >= 32 for sample in case["samples"]))
        self.assertTrue(case["validation"]["within_four_standard_errors"])
        self.assertEqual(case["producer_redraws"]["identical_to_reading"], 2)

    def test_bad_requirements_and_impossible_ones(self):
        good = self.need(verdict="tie")
        for bad in ({**good, "aspect": "tracking"}, {**good, "aspect": "collection"}, {**good, "carrier_id": "nobody"},
                    {**good, "schema": carriers.VERSION + "x"}, {**good, "shipping_class": "fragile"}, {**good, "min_assessed": 0},
                    {k: v for k, v in good.items() if k != "verdict"}, None):
            for call in (shipments.model, shipments.trial, lambda *a: shipments.prepare(*a, Random(0))):
                with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                    call(self.natural, bad, self.api)
                self.assertNotIsInstance(caught.exception, prices.ZeroMass)
        for impossible in (self.need(positive={"min": 33}), self.need(verdict="more_positive", date_from="2030-01-01"),
                           self.need(verdict="tie", positive={"min": 1}, negative={"max": 0})):
            with self.subTest(impossible=impossible), self.assertRaises(prices.ZeroMass):
                shipments.model(self.natural, impossible, self.api)

    def test_candidates_with_the_shipments_redrawn(self):
        name, aspect = self.clean
        task = {"kind": "summarize_carrier_reviews", "operation": "topic_counts", "carrier_index": self.names.index(name),
                "aspect": aspect, "min_assessed": 2, **NARROW}
        found = variants.of(self.natural, task, self.api)
        redrawn = [row for row in found if row["name"].startswith("redrawn_shipments_")]
        self.assertEqual({row["name"] for row in redrawn}, {"redrawn_shipments_verdict_" + verdict for verdict in carriers.VERDICTS})
        self.assertAlmostEqual(sum(exp(row["log_probability"]) for row in redrawn), 1, places=10)
        self.assertNotIn("verdict_more_negative", {row["name"] for row in found})
        for index, row in enumerate(redrawn):
            self.assertEqual({key: row["requirement"][key] for key in ("schema", "carrier_id", "min_assessed", *NARROW)},
                             {"schema": shipments.VERSION, "carrier_id": name, "min_assessed": 2, **NARROW})
            world, seen, _ = shipments.steer(self.session, self.natural, self.opened, row["requirement"], self.api, Random(index))
            self.assertEqual("redrawn_shipments_verdict_" + seen["verdict"], row["name"])
        # An aspect whose history is not modelled gets the reviews-only candidates alone.
        names = {row["name"] for row in variants.of(self.natural, {**task, "aspect": "tracking"}, self.api)}
        self.assertFalse(any(name.startswith("redrawn") for name in names))
