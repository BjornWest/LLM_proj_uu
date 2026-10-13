"""Tests of the candidate that keeps a delivery task's answer and rates its carriers below every other.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_answers.py
Each candidate is steered through the real producer; the answer is then read
again by the native task and the carriers' stars off the published summaries.
"""
from random import Random
from unittest.mock import patch

from environments.website_world import catalog_basket_task, catalog_checkout_domain, delivery_options
from experiments.accepted_catalog_commerce import basket_quote, delivery_admission

from experiments.steered_generation import cheapest, combined, menus, prices, ratings, variants
from experiments.steered_generation.test_delivered import INPUTS, SANDALS, SHOES, SIZE, Delivered

NAME, ANYWHERE = "answer_carrier_rated_lowest", ["home", "parcel_locker", "staffed_counter"]
ITEM = {"kind": "matching_single_item_delivery", "concept_id": SHOES, "predicates": SIZE}
ORDERS = {"kind": "cheapest_matching_order_set", "requirements": [
    {"requirement_id": "shoes", "quantity": 1, "concept_id": SHOES, "predicates": SIZE},
    {"requirement_id": "sandals", "quantity": 1, "concept_id": SANDALS, "predicates": SIZE}],
    "domain": {"destination": "user_home", "allowed_destination_types": ["home"]}}


def stars(world):
    return {row["carrier_id"]: row["summary"]["average_stars"] for row in world["carrier_evidence"]["public"]["carriers"]}


class Answers(Delivered):
    def item(self, world, task):
        """The single-item task's winning options and their carriers.

        The ranking is written out here, apart from the candidates module:
        the native task's options for the lowest total (those of the methods
        asked for, under any cap), kept when they are estimated to arrive by
        the deadline, and ranked by the latest arrival date first when the
        task asks for the earliest.
        """
        delivered = {"delivery_types": sorted(task["delivery_types"])} if "delivery_types" in task else {}
        scope = cheapest.scope(self.natural, {"concept_id": SHOES, "predicates": SIZE, "delivered": {
            **delivered, **{key: task[key] for key in ("max_total_minor",) if key in task}}}, self.api)
        early, last = task.get("objective") == "fastest_then_cheapest", task.get("arrival_deadline")
        rows = [(row["offer_id"], row["choice_id"], row["option"]["total_minor"], row["option"]["arrival"]["latest_date"],
                 row["delivery"]["carrier_id"]) for row in scope.reference(world)[1]["candidates"]
                if not (early or last) or row["option"]["arrival"]["status"] == "estimated" and
                row["option"]["arrival"]["latest_date"] <= (last or "9999")]
        score = lambda row: (row[3], row[2]) if early else (row[2],)
        rows = sorted(row for row in rows if score(row) == min(map(score, rows)))
        return rows, {row[-1] for row in rows}

    def orders(self, world, task):
        """The order-set task's cheapest sets of orders and their carriers, by the native task's solver.

        Written apart from the candidates module: the public plan and the
        admission plan under version 2, as `test_delivered.totals` makes them.
        """
        settings = delivery_options.options({"enabled": True, "admission_plan": menus.VERSION})
        plan, domain = basket_quote.make_plan(world), catalog_checkout_domain.make(world, task.get("checkout_domain"))
        sidecar = delivery_admission.make_plan(world, plan, seed=world["seed"], plan_version=menus.VERSION,
                                               count_weights=delivery_options.producer_weights(settings))
        bound = catalog_basket_task.make(world, {key: task[key] for key in ("kind", "requirements", "domain")},
                                         checkout_domain=domain)
        result = catalog_basket_task.reference(world, bound, plan=plan, checkout_domain=domain, admission_plan=sidecar)["result"]
        self.assertEqual((result["status"], result["complete"], result["ties_truncated"]), ("optimal", True, False))
        rows = [(result["total_minor"], [(order["retailer_id"], order["lines"], order["quote"]["selection"],
                                          [shipment["delivery"]["carrier_id"] for shipment in order["quote"]["shipments"]])
                                         for order in found["orders"]]) for found in result["solutions"]]
        return rows, {carrier for _, found in rows for order in found for carrier in order[3]}

    def dates(self):
        scope = cheapest.scope(self.natural, {"concept_id": SHOES, "predicates": SIZE, "delivered": {}}, self.api)
        found = scope.reference(self.natural, objective="fastest_then_cheapest")[1]["candidates"]
        return sorted({row["option"]["arrival"]["latest_date"] for row in found})

    def kept(self, task, read, seed=0):
        """One candidate steered: the answer is the natural one and its carriers are rated below every other."""
        answer, used = read(self.natural, task)
        self.assertTrue(answer)
        found = [row for row in variants.of(self.natural, task, self.api) if row["name"] == NAME]
        self.assertEqual(len(found), 1, task)
        requirement = found[0]["requirement"]
        parts = requirement.get("all", [requirement])
        self.assertEqual([part["carrier_id"] for part in parts], sorted(used))
        self.assertTrue(all(part["schema"] == ratings.VERSION for part in parts))
        before = stars(self.natural)
        limit = round(min(value for carrier, value in before.items() if carrier not in used) - .01, 2)
        self.assertTrue(all(part["average_stars"] == {"max": limit} for part in parts))
        module = combined if len(parts) > 1 else ratings
        world, _, record = module.steer(self.session, self.natural, self.opened, requirement, self.api, Random(seed))
        self.assertEqual(read(world, task), (answer, used))
        after = stars(world)
        self.assertEqual({carrier: value for carrier, value in after.items() if carrier not in used},
                         {carrier: value for carrier, value in before.items() if carrier not in used})
        self.assertLess(max(after[carrier] for carrier in used), min(after[carrier] for carrier in after if carrier not in used))
        self.assertAlmostEqual(record.get("log_probability_given_upstream", found[0]["log_probability"]),
                               found[0]["log_probability"], places=9)
        for key in ("retailers", "products", "address_context"):
            self.assertEqual(world[key], self.natural[key], key)
        return used


class AnswerTests(Answers):
    def test_every_ranking_of_the_single_item_task_keeps_its_answer(self):
        dates = self.dates()
        tasks = [ITEM, {**ITEM, "objective": "fastest_then_cheapest"}, {**ITEM, "arrival_deadline": dates[0]},
                 {**ITEM, "arrival_deadline": dates[len(dates) // 2], "max_total_minor": 10 ** 7},
                 {**ITEM, "objective": "fastest_then_cheapest", "arrival_deadline": dates[-1], "delivery_types": ANYWHERE}]
        seen = [self.kept(task, self.item, seed) for seed, task in enumerate(tasks)]
        # The cheapest and the earliest are not delivered by the same carriers on this world, the later deadline
        # leaves the cheapest as it is, and one answer has several winning carriers.
        self.assertNotEqual(seen[0], seen[1])
        self.assertEqual((seen[2], seen[3]), (seen[1], seen[0]))
        self.assertGreater(max(len(used) for used in seen), 1)
        # The native task's own winners are the ones written out in `item`.
        scope = cheapest.scope(self.natural, {"concept_id": SHOES, "predicates": SIZE, "delivered": {}}, self.api)
        for task in tasks[:4]:
            asked = {key: task[key] for key in ("objective", "arrival_deadline") if key in task}
            native = scope.reference(self.natural, **asked)[1]
            self.assertEqual(sorted((row["offer_id"], row["choice_id"]) for row in native["winners"]),
                             [row[:2] for row in self.item(self.natural, task)[0]])
            self.assertEqual(native["objective"], task.get("objective", "cheapest_total"))
        # Under a ranking the block does not model, the kept answer is the only candidate.
        for task in tasks[1:]:
            self.assertEqual([row["name"] for row in variants.of(self.natural, task, self.api)], [NAME])
        # Asked for alone it is the same candidate, listed without modelling the others; other names filter.
        every = variants.of(self.natural, ITEM, self.api)
        with patch.object(cheapest, "frame", side_effect=AssertionError("the block was modelled")):
            self.assertEqual(variants.of(self.natural, ITEM, self.api, only=[NAME]), every[-1:])
        self.assertEqual(variants.of(self.natural, ITEM, self.api, only=["likeliest_winner", NAME]), [every[0], every[-1]])
        self.assertEqual(variants.of(self.natural, ITEM, self.api, only=["no_such_candidate"]), [])
        self.assertEqual(variants.of(self.natural, ITEM, self.api, only=[]), [])
        self.assertEqual(variants.of(self.natural, ORDERS, self.api, only=["likeliest_winner"]), [])
        # A deadline nothing meets leaves no answer to keep.
        self.assertEqual(variants.of(self.natural, {**ITEM, "arrival_deadline": "2020-01-01"}, self.api), [])
        self.assertEqual(variants.of(self.natural, {**ITEM, "objective": "fastest_then_cheapest", "max_total_minor": 0},
                                     self.api), [])

    def test_the_order_set_task_keeps_its_cheapest_orders(self):
        dates = self.dates()
        tasks = [ORDERS, {**ORDERS, "domain": {**ORDERS["domain"], "deadline": dates[1], "allow_extras": False}},
                 {**ORDERS, "checkout_domain": {"max_lines_per_order": 1}}]
        seen = [self.kept(task, self.orders, seed) for seed, task in enumerate(tasks)]
        self.assertGreater(max(len(used) for used in seen), 1)
        self.assertEqual([row["name"] for row in variants.of(self.natural, ORDERS, self.api)], [NAME])
        # No feasible set of orders: nothing to keep.
        self.assertEqual(variants.of(self.natural, {**ORDERS, "domain": {
            **ORDERS["domain"], "deadline": "2020-01-01", "allow_extras": False}}, self.api), [])
        # A search the solver did not finish, or more tied sets than it lists, is not an answer to keep.
        settled = catalog_basket_task.reference
        for unsettled in ({"status": "inconclusive", "complete": False}, {"ties_truncated": True}):
            def reference(*args, **more):
                found = settled(*args, **more)
                return {**found, "result": {**found["result"], **unsettled}}
            with self.subTest(unsettled=unsettled), patch.object(catalog_basket_task, "reference", reference), \
                    self.assertRaises(ValueError) as caught:
                variants.of(self.natural, ORDERS, self.api)
            self.assertIn("did not settle", str(caught.exception))
        for bad in ({"delivery_options": {"admission_plan": "retailer-delivery-admission-plan-v1"}},
                    {"delivery_options": {"enabled": False}}, {"checkout_domain": {"max_lines_per_order": 0}},
                    {"domain": {"destination": "work"}}, {"requirements": []}, {"concept_id": SHOES}, {"budget": {}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                variants.of(self.natural, {**ORDERS, **bad}, self.api)

    def test_when_no_carrier_can_be_rated_lowest_there_is_no_candidate(self):
        every = sorted(stars(self.natural))
        self.assertEqual(variants.answer_rated(self.natural, [], self.api), [])
        self.assertEqual(variants.answer_rated(self.natural, [None], self.api), [])
        self.assertEqual(variants.answer_rated(self.natural, every, self.api), [])
        self.assertEqual(variants.answer_rated(self.natural, ["carrier-99"], self.api), [])
        # A carrier that cannot fall under the others: with every other carrier at one star there is no room below.
        world = {**self.natural, "carrier_evidence": {**self.natural["carrier_evidence"], "public": {
            **self.natural["carrier_evidence"]["public"], "carriers": [
                {**row, "summary": {**row["summary"], "average_stars": 1.0}} if row["carrier_id"] != every[0] else row
                for row in self.natural["carrier_evidence"]["public"]["carriers"]]}}}
        self.assertEqual(variants.answer_rated(world, every[:1], self.api), [])
        # One of the answer's carriers that cannot be rated so low leaves no candidate, whatever the others can be.
        model = ratings.model

        def stuck(found, need, api):
            if need["carrier_id"] == every[1]:
                raise prices.ZeroMass("no_outcome", "nothing")
            return model(found, need, api)
        with patch.object(ratings, "model", stuck):
            self.assertEqual(variants.answer_rated(self.natural, every[:2], self.api), [])
            self.assertEqual(len(variants.answer_rated(self.natural, every[:1], self.api)), 1)
        # One carrier is a single requirement, two are a combined one whose chance is the product.
        one, two = (variants.answer_rated(self.natural, every[:count], self.api)[0] for count in (1, 2))
        self.assertEqual(one["requirement"]["schema"], ratings.VERSION)
        self.assertEqual([part["carrier_id"] for part in two["requirement"]["all"]], every[:2])
        self.assertAlmostEqual(two["log_probability"], sum(
            variants.ranked(self.natural, [part], self.api, ratings)[0][0] for part in two["requirement"]["all"]), places=12)


class ByLocationAnswers(Answers):
    """Where charges depend on the location that ships: the block's own candidates are fewer, this one is there."""
    inputs = {**INPUTS, "seed": 7}

    def test_the_answer_is_kept_where_charges_depend_on_the_location(self):
        self.kept(ITEM, self.item)
        self.kept({**ITEM, "objective": "fastest_then_cheapest", "delivery_types": ANYWHERE}, self.item, 1)
        self.kept(ORDERS, self.orders, 2)
