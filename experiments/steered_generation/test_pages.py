"""Tests of the first page's arithmetic against enumeration of every way a few reviews can fall.

Run from the repository root:
    python -m pytest -q experiments/steered_generation/test_pages.py
Nothing here runs the producer: the module is given one review's chances and
judged against all assignments of a rating and a kind to each review, read by
the page rule itself.
"""
from collections import Counter
from itertools import product
from math import prod
from random import Random
import unittest

from experiments.steered_generation import blocks, pages

KINDS = (*pages.WRITTEN, pages.SILENT)


def chances(seed, absent=()):
    """One review's chance of each star rating and kind, arbitrary and uneven; some cells impossible."""
    rng = Random(seed)
    weights = {(rating, kind): 0.0 if (rating, kind) in absent else rng.random() * (3 if kind == pages.SILENT else 1)
               for rating in range(1, 6) for kind in KINDS}
    return {cell: weight / sum(weights.values()) for cell, weight in weights.items()}


def option(rows, ranks, size, order):
    """The option of the model that an assignment of reviews falls under."""
    shown = pages.first(rows, ranks, size, order)
    seen = Counter(rows[index][1] for index in shown)
    written = [index for index, (_, kind) in enumerate(rows) if kind != pages.SILENT]
    if len(written) < size:
        return "short", tuple(seen[kind] for kind in pages.WRITTEN)
    groups = pages.levels(order)
    level = next(index for index, group in enumerate(groups) if rows[shown[-1]][0] in group)
    above = sum(rows[index][0] in group for index in shown for group in groups[:level])
    return "cut", level, above, (seen[pages.POSITIVE], seen[pages.NEGATIVE])


def judged(rows, ranks, size, order):
    shown = Counter(rows[index][1] for index in pages.first(rows, ranks, size, order))
    whole = Counter(kind for _, kind in rows)
    return (shown[pages.POSITIVE], shown[pages.NEGATIVE]), (whole[pages.POSITIVE], whole[pages.NEGATIVE])


CONDITIONS = {
    "anything": (lambda p, n: True, lambda p, n: True),
    "page praises, whole complains": (lambda p, n: p > n, lambda p, n: n > p),
    "page silent on it, whole tied": (lambda p, n: p + n == 0, lambda p, n: p == n and p > 0),
    "one complaint on the page": (lambda p, n: n == 1, lambda p, n: True),
    "two praising in all": (lambda p, n: True, lambda p, n: p == 2),
    "impossible": (lambda p, n: p > 1, lambda p, n: p == 0),
}


class PageTests(unittest.TestCase):
    def test_the_rule_integrates_polynomials(self):
        for count in (1, 2, 3, 7, 20, 51, 120):
            found = pages.rule(count)
            self.assertEqual(len(found), count)
            self.assertTrue(all(0 < x < 1 and share > 0 for x, share in found))
            for degree in (0, 1, count, 2 * count - 2, 2 * count - 1):
                self.assertAlmostEqual(sum(share * x ** degree for x, share in found) * (degree + 1), 1, places=12,
                                       msg=(count, degree))
        # One degree further it is no longer exact, which is what sizes the rule in `model`.
        self.assertGreater(abs(sum(share * x ** 4 for x, share in pages.rule(2)) * 5 - 1), 1e-3)

    def test_probabilities_match_enumeration(self):
        cases = [(count, size, order, seed, absent)
                 for count in (0, 1, 2, 3) for size in (1, 2, 3, 5) for order in pages.ORDERS
                 for seed, absent in ((1, ()), (2, ((5, pages.POSITIVE), (4, pages.NEGATIVE), (3, pages.OTHER))),
                                      (3, tuple((rating, pages.SILENT) for rating in range(1, 6))))]
        cases += [(4, 2, "highest", 4, ()), (4, 3, "lowest", 5, ((1, pages.OTHER),)), (4, 4, "identity", 6, ()),
                  (4, 1, "highest", 7, tuple((rating, kind) for rating in (4, 5) for kind in KINDS))]
        for count, size, order, seed, absent in cases:
            cells = chances(seed, absent)
            ranks = Random(seed).sample(range(count), count)
            for name, (page_ok, whole_ok) in CONDITIONS.items():
                with self.subTest(count=count, size=size, order=order, seed=seed, condition=name):
                    direct = Counter()
                    for rows in product([cell for cell, mass in cells.items() if mass], repeat=count):
                        page, whole = judged(rows, ranks, size, order)
                        if page_ok(*page) and whole_ok(*whole):
                            direct[option(rows, ranks, size, order)] += prod(cells[cell] for cell in rows)
                    found = pages.model(cells, count, size, order, page_ok, whole_ok)
                    self.assertEqual(set(found.options), set(direct))
                    for key, value in found.options.items():
                        self.assertAlmostEqual(value / direct[key], 1, places=10, msg=key)
                    self.assertFalse(found.lost)

    def test_everything_adds_up_for_many_reviews(self):
        for count, size, order in ((40, 4, "highest"), (100, 4, "highest"), (100, 12, "lowest"), (60, 100, "identity"),
                                   (100, 1, "identity"), (400, 3, "highest")):
            with self.subTest(count=count, size=size, order=order):
                found = pages.model(chances(count + size), count, size, order, lambda p, n: True, lambda p, n: True)
                self.assertAlmostEqual(sum(found.options.values()), 1, places=9)
        # A page's own distribution does not depend on the order where no rating is likelier to praise.
        even = {(rating, kind): .05 for rating in range(1, 6) for kind in KINDS}
        totals = [sum(value for key, value in pages.model(even, 30, 4, order, lambda p, n: p > n, lambda p, n: n > p)
                      .options.items()) for order in pages.ORDERS]
        self.assertAlmostEqual(totals[0], totals[1], places=12)
        self.assertAlmostEqual(totals[0], totals[2], places=12)

    def test_samples_match_enumeration(self):
        for count, size, order, seed, name in ((4, 1, "highest", 11, "page praises, whole complains"),
                                               (3, 2, "lowest", 12, "one complaint on the page"),
                                               (3, 1, "identity", 13, "two praising in all"),
                                               (4, 2, "highest", 14, "page silent on it, whole tied"),
                                               (2, 5, "highest", 15, "one complaint on the page")):
            with self.subTest(count=count, size=size, order=order, condition=name):
                cells, (page_ok, whole_ok) = chances(seed), CONDITIONS[name]
                ranks = Random(seed).sample(range(count), count)
                direct = {}
                for rows in product(cells, repeat=count):
                    page, whole = judged(rows, ranks, size, order)
                    if page_ok(*page) and whole_ok(*whole):
                        direct[rows] = prod(cells[cell] for cell in rows)
                block, rng, trials, seen = pages.model(cells, count, size, order, page_ok, whole_ok), Random(seed), 40000, Counter()
                for _ in range(trials):
                    targets = pages.placed(rng, pages.sample(rng, block), ranks)
                    seen[tuple((pages.choose(rng, group, [cells[rating, kind] for rating in group]), kind)
                               for group, kind in targets)] += 1
                self.assertLessEqual(set(seen), set(direct))
                total = sum(direct.values())
                self.assertAlmostEqual(total, sum(block.options.values()), places=12)
                for rows, value in direct.items():
                    chance = value / total
                    # Two draws of allowance for the outcomes too rare to expect even one of.
                    self.assertLess(abs(seen[rows] / trials - chance), 4.5 * (chance * (1 - chance) / trials) ** .5 + 2 / trials, rows)
                self.assertGreater(len(seen), 20)

    def test_reading_a_page(self):
        rows = [(3, pages.SILENT), (5, pages.OTHER), (4, pages.POSITIVE), (5, pages.NEGATIVE), (1, pages.OTHER), (4, pages.SILENT)]
        ranks = [0, 5, 2, 1, 4, 3]
        self.assertEqual(pages.first(rows, ranks, 3, "highest"), [3, 1, 2])
        self.assertEqual(pages.first(rows, ranks, 2, "lowest"), [4, 2])
        self.assertEqual(pages.first(rows, ranks, 10, "identity"), [3, 2, 4, 1])
        self.assertEqual(pages.first(rows, ranks, 1, "identity"), [3])

    def test_limits_and_refusals(self):
        cells = chances(1)
        for count, size, order in ((-1, 4, "highest"), (401, 4, "highest"), (10, 0, "highest"), (10, 101, "highest"),
                                   (10, 4, "newest"), (10, True, "highest"), (10.0, 4, "highest")):
            with self.assertRaises(ValueError):
                pages.model(cells, count, size, order, lambda p, n: True, lambda p, n: True)
        # Possible, but with a chance below the smallest float: lost, which the caller refuses as a numerical limit.
        rare = {(rating, kind): {(1, pages.SILENT): 1 - 1e-200, (5, pages.POSITIVE): 1e-200}.get((rating, kind), 0.0)
                for rating in range(1, 6) for kind in KINDS}
        found = pages.model(rare, 10, 4, "highest", lambda p, n: p == 4, lambda p, n: True)
        self.assertEqual((found.options, found.lost), ({}, True))
        with self.assertRaises(blocks.NumericalLimit):
            pages.sample(Random(0), found)
        # Impossible by the kinds themselves: nothing is lost.
        found = pages.model(rare, 10, 4, "highest", lambda p, n: n == 1, lambda p, n: True)
        self.assertEqual((found.options, found.lost), ({}, False))


if __name__ == "__main__":
    unittest.main()
