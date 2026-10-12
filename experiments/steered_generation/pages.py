"""The first page of a product's written comments, against all of them.

A review site lists a product's written comments a page at a time, in the
order of their review ids or with the highest or the lowest star ratings
first (ties in the order of the ids). A reader who stops at the first page
sees its comments only. This module gives the probability that the first
page and the whole satisfy two conditions together, and samples what every
review must then be.

Every review is, independently and alike, of some star rating and one of
four kinds: a comment that is positive about the topic, one that is
negative, another comment, or a rating without a comment. Take the ratings
in the page's order as levels. If fewer comments are written than the page
holds, the page is all of them. Otherwise the page ends inside one level,
the cut: it holds every comment above the cut, `u` of them, and the first
`j` comments at the cut in the order of the ids, `u + j` being the page's
size. Which comments at the cut come first does not depend on what they say,
so the page's comments and the others at the cut are independent draws of
that level's kinds. Summing the reviews outside the page over how many, `e`,
are further comments at the cut leaves one factor that depends on `e`,
`e! / (e + j)!`, which is an integral of `x ** e * (1 - x) ** (j - 1)` over
0..1; under the integral the reviews outside the page are independent again,
each a comment at the cut with its probability times `x`, a comment below
the cut, or silent. So, with `n` reviews, of which `m = n - u - j` are
outside the page, and for totals `X`, `Y` of positive and negative comments
outside it,

    P(page parts, X, Y) = n! / (u! m! (j-1)!) * W_above * W_cut
                          * integral of (1-x)^(j-1) T_m(X, Y; x) dx

where `W_above` and `W_cut` are the multinomial weights of the page's
comments above and at the cut, and `T_m` is the trinomial weight of `m`
reviews being positive, negative or neither with the probabilities just
named. The integrand is a polynomial of degree below `n`, which a
Gauss-Legendre rule of enough points integrates exactly up to rounding.
"""
from functools import lru_cache
from math import comb, cos, exp, fsum, lgamma, perm, pi
from types import SimpleNamespace

from .blocks import NumericalLimit, pick

ORDERS = ("highest", "lowest", "identity")
POSITIVE, NEGATIVE, OTHER, SILENT = "positive", "negative", "other", "silent"
WRITTEN = (POSITIVE, NEGATIVE, OTHER)
# The sizes this arithmetic is written for: binomial and multinomial numbers of this many reviews stay far inside
# the floats, and so do the rule's points.
REVIEWS, SIZES = 400, 100


def levels(order):
    """The groups of star ratings in the order a page takes them."""
    return {"highest": [(5,), (4,), (3,), (2,), (1,)], "lowest": [(1,), (2,), (3,), (4,), (5,)],
            "identity": [(1, 2, 3, 4, 5)]}[order]


@lru_cache(maxsize=64)
def rule(count):
    """Gauss-Legendre points and weights on 0..1: exact for polynomials of degree below twice their number."""
    def legendre(x):
        before, value = 1.0, x
        for degree in range(2, count + 1):
            before, value = value, ((2 * degree - 1) * x * value - (degree - 1) * before) / degree
        return value, count * (x * value - before) / (x * x - 1)

    found = []
    for index in range(count):
        x = cos(pi * (index + .75) / (count + .5))
        for _ in range(100):
            value, slope = legendre(x)
            x, moved = x - value / slope, abs(value / slope)
            if moved < 1e-16:
                break
        found.append(((x + 1) / 2, 1 / ((1 - x * x) * legendre(x)[1] ** 2)))
    return found


def parts(number):
    """The ways a number of comments split into positive, negative and other."""
    return [(positive, negative, number - positive - negative)
            for positive in range(number + 1) for negative in range(number + 1 - positive)]


def weight(numbers, masses):
    """The multinomial weight of so many comments of each kind, and whether it can occur at all."""
    total = sum(numbers)
    value = comb(total, numbers[0]) * comb(total - numbers[0], numbers[1])
    for number, mass in zip(numbers, masses):
        value *= mass ** number
    return value, all(mass > 0 or not number for number, mass in zip(numbers, masses))


def model(cells, count, size, order, page_ok, whole_ok):
    """The ways the first page and the whole can both be as required, each with its probability.

    `cells` gives one review's probability of each (star rating, kind);
    `page_ok` and `whole_ok` judge numbers of positive and negative comments
    on the page and in all. Returns the options with a positive probability
    (a short list of comments that all fit on the page, or a cut with the
    page's positive and negative comments), what sampling needs, and whether
    any option that the kinds allow at all was lost to the floats.
    """
    if not (type(count) is int and 0 <= count <= REVIEWS and type(size) is int and 1 <= size <= SIZES and order in ORDERS):
        raise ValueError("A first page has a size of 1 to 100 and an order, over at most 400 reviews")
    mass = lambda group, kind: fsum(cells[rating, kind] for rating in group)
    silent, all_stars = mass(range(1, 6), SILENT), tuple(range(1, 6))
    written = [mass(all_stars, kind) for kind in WRITTEN]
    options, tables, possible = {}, {}, False
    # Fewer comments than the page holds: the page is the whole.
    for number in range(min(size, count + 1)):
        for split in parts(number):
            if page_ok(*split[:2]) and whole_ok(*split[:2]):
                value, can = weight(split, written)
                can = can and (silent > 0 or number == count)
                possible = possible or can
                value *= comb(count, number) * silent ** (count - number)
                if value > 0:
                    options["short", split] = value
    outside = count - size
    for index, group in enumerate(levels(order) if outside >= 0 else []):
        above = [fsum(mass(other, kind) for other in levels(order)[:index]) for kind in WRITTEN]
        cut = [mass(group, kind) for kind in WRITTEN]
        below = [fsum(mass(other, kind) for other in levels(order)[index + 1:]) for kind in WRITTEN]
        rest = below[2] + silent
        for high in range(size if fsum(above) > 0 else 1):
            low = size - high
            if not fsum(cut) > 0:
                continue
            # The integral, for every number of positive and negative comments outside the page.
            table = [[0.0] * (outside + 1 - positive) for positive in range(outside + 1)]
            for x, share in rule((outside + low - 1) // 2 + 1):
                powers = [[1.0] for _ in range(3)]
                for row, base in zip(powers, (x * cut[0] + below[0], x * cut[1] + below[1], x * cut[2] + rest)):
                    for _ in range(outside):
                        row.append(row[-1] * base)
                scale = share * (1 - x) ** (low - 1)
                for positive in range(outside + 1):
                    for negative in range(outside + 1 - positive):
                        table[positive][negative] += (scale * powers[0][positive] * powers[1][negative] *
                                                      powers[2][outside - positive - negative])
            many = lgamma(outside + 1)
            for positive in range(outside + 1):
                for negative in range(outside + 1 - positive):
                    table[positive][negative] *= exp(many - lgamma(positive + 1) - lgamma(negative + 1) -
                                                     lgamma(outside - positive - negative + 1))
            can_outside = lambda positive, negative: (
                (cut[0] + below[0] > 0 or not positive) and (cut[1] + below[1] > 0 or not negative) and
                (cut[2] + rest > 0 or outside == positive + negative))
            constant = perm(count, size) / (perm(high, high) * perm(low - 1, low - 1))
            pages = {}
            for first in parts(high):
                for second in parts(low):
                    found = (first[0] + second[0], first[1] + second[1])
                    if page_ok(*found):
                        (one, can_one), (two, can_two) = weight(first, above), weight(second, cut)
                        pages.setdefault(found, []).append((one * two, first, second, can_one and can_two))
            tables[index, high] = SimpleNamespace(table=table, pages=pages, above=above, cut=cut, below=below, rest=rest,
                                                  silent=silent, group=group)
            for found, rows in pages.items():
                fits = [(positive, negative) for positive in range(outside + 1) for negative in range(outside + 1 - positive)
                        if whole_ok(found[0] + positive, found[1] + negative)]
                possible = possible or any(row[3] for row in rows) and any(can_outside(*pair) for pair in fits)
                value = constant * fsum(row[0] for row in rows) * fsum(table[positive][negative] for positive, negative in fits)
                if value > 0:
                    options["cut", index, high, found] = value
    return SimpleNamespace(options=options, tables=tables, lost=possible and not options, count=count, size=size,
                           order=order, page_ok=page_ok, whole_ok=whole_ok, cells=cells, written=written, silent=silent)


def choose(rng, options, weights):
    """One of some options in proportion to its weight; a numerical limit where none has any."""
    kept = [(option, value) for option, value in zip(options, weights) if value > 0]
    if not kept:
        raise NumericalLimit("The kinds of review under the first page's requirement are too unlikely to choose among")
    return pick(rng, [option for option, _ in kept], [value for _, value in kept])


def sample(rng, block):
    """What the reviews are, from their distribution given the requirement: groups of reviews alike.

    Each group is the star ratings its reviews may have, their kind, their
    number, and where they stand: "page" and "after" for the comments at the
    cut that the page takes first and the others there, None elsewhere.
    """
    option = choose(rng, list(block.options), list(block.options.values()))
    stars, count, size = tuple(range(1, 6)), block.count, block.size
    if option[0] == "short":
        split = option[1]
        return [(stars, kind, number, None) for kind, number in zip(WRITTEN, split)] + [
            (stars, SILENT, count - sum(split), None)]
    _, index, high, found = option
    low, outside, place = size - high, count - size, block.tables[option[1], option[2]]
    order = levels(block.order)
    before = tuple(rating for group in order[:index] for rating in group)
    after = tuple(rating for group in order[index + 1:] for rating in group)
    pairs = [(positive, negative) for positive in range(outside + 1) for negative in range(outside + 1 - positive)
             if block.whole_ok(found[0] + positive, found[1] + negative)]
    positive, negative = choose(rng, pairs, [place.table[a][b] for a, b in pairs])
    neither = outside - positive - negative
    _, first, second, _ = choose(rng, place.pages[found], [row[0] for row in place.pages[found]])
    # Of the reviews outside the page: which are further comments at the cut, by kind.
    further = [(a, b, c) for a in range(positive + 1) for b in range(negative + 1) for c in range(neither + 1)]
    chance = lambda a, b, c: (
        comb(positive, a) * place.cut[0] ** a * place.below[0] ** (positive - a) *
        comb(negative, b) * place.cut[1] ** b * place.below[1] ** (negative - b) *
        comb(neither, c) * place.cut[2] ** c * place.rest ** (neither - c) /
        perm(a + b + c + low, low))
    at = choose(rng, further, [chance(*row) for row in further])
    left = neither - at[2]
    quiet = choose(rng, range(left + 1), [comb(left, number) * place.below[2] ** (left - number) * place.silent ** number
                                         for number in range(left + 1)])
    groups = [(before, kind, number, None) for kind, number in zip(WRITTEN, first)]
    groups += [(place.group, kind, number, "page") for kind, number in zip(WRITTEN, second)]
    groups += [(place.group, kind, number, "after") for kind, number in zip(WRITTEN, at)]
    groups += [(after, kind, number, None) for kind, number in zip(WRITTEN, (positive - at[0], negative - at[1], left - quiet))]
    return groups + [(stars, SILENT, quiet, None)]


def placed(rng, groups, ranks):
    """Reviews for the groups: for every review, the star ratings it may have and its kind.

    Reviews are alike, so any review may be of any group, except that of the
    comments at the cut the page's are the ones whose ids come first.
    """
    free = rng.sample(range(len(ranks)), len(ranks))
    cut = sum(number for _, _, number, where in groups if where)
    level = sorted(free[:cut], key=lambda index: ranks[index])
    turn = {"page": [], "after": []}
    for stars, kind, number, where in groups:
        if where:
            turn[where] += [(stars, kind)] * number
    for rows in turn.values():
        rng.shuffle(rows)
    found = dict(zip(level, turn["page"] + turn["after"]))
    others = [(stars, kind) for stars, kind, number, where in groups if not where for _ in range(number)]
    found.update(zip(free[cut:], others))
    if len(found) != len(ranks):
        raise AssertionError("The groups are not one for every review")
    return [found[index] for index in range(len(ranks))]


def first(rows, ranks, size, order):
    """The reviews on the first page, as the site lists them: written comments, in the order, a page's worth."""
    sign = {"highest": -1, "lowest": 1, "identity": 0}[order]
    shown = sorted((index for index, (_, kind) in enumerate(rows) if kind != SILENT),
                   key=lambda index: (sign * rows[index][0], ranks[index]))
    return shown[:size]
