"""Conditional sampling of what a product's reviews say about one topic.

A requirement names a product and a topic of the native review-summary task
(an aspect and its context), and states the verdict of the task's count, the
number of positive comments, the number of negative ones, the mean of the
product's star ratings, or several of these. The task counts written comments
by what they report first hand about the topic: positive, negative or not
assessed; a rating without a comment is not counted at all. The mean is over
every rating, with or without a comment, as the product's rating summary has
it.

The pilot concepts' reviews are sampled by `footwear_context_pilot` with one
named stream per draw under the product's own seed, and are read here. A
review says something about a topic when it has a comment (its length is not
zero) and the topic is among those chosen for it; what it says is the sign of
the reviewer's score for the aspect, a normal draw around a centre set by the
star rating. The rating, the aspect's score, the length and the topic choices
of every review are the block. Every other concept's reviews come from its
package's review program, which `programs` reads; there the block is the
draws the topic's statements depend on. Either way reviews draw independently
and alike, so the counts are multinomial, and their probability is a sum over
the counts that satisfy the requirement.

Sampling picks the counts, places them on reviews at random and then redraws
each review's block streams under fresh seeds until the review falls in its
class. That is rejection inside one review, where the classes are never rare
by more than the review's own probabilities; the rare part, the counts, is
chosen exactly. Every other draw of the review (the option bought, sizing, the
other aspects' scores, phrasing) is the seed's own and reads the block's
draws where the producer makes it depend on them.

A star rating and what the review says are drawn together: the rating moves
the topic's score. With a mean stated, each count's probability carries the
chance that the stars then total within the bounds (the stars of the reviews
of one class are independent and alike, so their total is a repeated
convolution), and sampling goes on to choose every review's rating exactly:
the totals of the three classes, then each review's stars in turn. A review
is then redrawn in two steps, its rating stream until it gives the rating and
its other streams until it is of its class; nothing but the rating itself
passes from the first to the second. That holds where no other draw of the
block sets the rating's chances, as in every program so far; where one does,
the whole block is redrawn until rating and class are both met.
"""
from collections import Counter
from fractions import Fraction
from functools import lru_cache, reduce
from importlib import import_module
import json
from operator import or_
from math import ceil, erfc, exp, floor, fsum, lgamma, log, sqrt
import sys
from types import SimpleNamespace

from . import blocks, programs, streams
from .blocks import NumericalLimit, Step, Unmet, bound, pick, within
from .cheapest import pick_log
from .prices import ZeroMass

VERSION = "steered-review-topic-v1"
VERDICTS = ("more_positive", "more_negative", "tie", "insufficient_evidence")
POSITIVE, NEGATIVE, REST = "positive", "negative", "rest"
STARS = "mean_rating"
# Aspects whose score depends on more than the rating and the product: the option bought and the wearer.
UNMODELLED = ("size_fit", "forefoot_room")
# A review's class is redrawn at most this often before the block gives up as numerically out of reach.
TRIES = 10 ** 6


def resolve(requirement):
    required, stated = {"schema", "product_id", "topic"}, {"verdict", POSITIVE, NEGATIVE, STARS}
    if (type(requirement) is not dict or not required <= set(requirement) <= required | stated | {"min_assessed"} or
            requirement["schema"] != VERSION or not stated & set(requirement) or
            type(requirement["product_id"]) is not str or not requirement["product_id"]):
        raise ValueError("Declare a product, a topic and a verdict, a number of positive or of negative comments, "
                         "or a mean rating")
    topic = requirement["topic"]
    if type(topic) is not dict or set(topic) != {"aspect", "context"} or type(topic["aspect"]) is not str:
        raise ValueError("A topic is an aspect and its context")
    if requirement.get("verdict", VERDICTS[0]) not in VERDICTS:
        raise ValueError("A verdict is one of " + ", ".join(VERDICTS))
    if any(key in requirement and not bound(requirement[key]) for key in (POSITIVE, NEGATIVE)):
        raise ValueError("A number of comments is a non-negative min, max or both")
    mean = requirement.get(STARS, {"min": 1})
    if (type(mean) is not dict or not mean or set(mean) - {"min", "max"} or
            not all(type(value) in (int, float) and 1 <= value <= 5 for value in mean.values()) or
            mean.get("min", 1) > mean.get("max", 5)):
        raise ValueError("A mean rating is a min, a max or both, from 1 to 5")
    least = requirement.get("min_assessed", 1)
    if type(least) is not int or not 1 <= least <= 1000 or "min_assessed" in requirement and "verdict" not in requirement:
        raise ValueError("The least number of assessing comments is 1 to 1000 and goes with a verdict")
    return json.loads(json.dumps(requirement))


def footprint(world, requirement, api):
    """What the block decides: the product's reviews."""
    requirement = resolve(requirement)
    if not any(p["public"]["product_id"] == requirement["product_id"] for p in world["products"]):
        raise ValueError("Unknown product")
    return SimpleNamespace(writes={("reviews", "", requirement["product_id"])}, reads=set())


@lru_cache(maxsize=8)
def inventory(package, concept_id):
    """The native review task's module and its declarations for a concept."""
    native = import_module(package + ".catalog_review_task")
    return native, native.ReviewInventory(concept_id)


def site(world, requirement, api):
    """Where one product's review draws sit, and what the producer reads them with."""
    requirement = resolve(requirement)
    footprint(world, requirement, api)
    item = next(p for p in world["products"] if p["public"]["product_id"] == requirement["product_id"])
    public, private, footwear = item["public"], item["private"], api.package_export.footwear
    native, declared = inventory(api.basic.__package__, public["concept_id"])
    topic = requirement["topic"]
    if not any(row["aspect"] == topic["aspect"] and native.context_matches(row["context"], topic["context"])
               for row in declared.topics):
        raise ValueError("The topic is not one the native review task accepts for this concept")
    seed = api.commerce.seed_for(world["seed"], public["product_id"])
    if item.get("sample_seed", seed) != seed:
        raise ValueError("The product was not manufactured under the seed this producer gives it")
    common = dict(
        requirement=requirement, product_id=public["product_id"], concept_id=public["concept_id"],
        aspect=topic["aspect"], seed=seed, count=len(item["reviews"]),
        index=sorted(p["public"]["product_id"] for p in world["products"]
                     if p["public"]["concept_id"] == public["concept_id"]).index(public["product_id"]))
    if public["concept_id"] not in api.package_export.PILOTS:
        return programs.site(world, item, api, native, **common)
    concept, spec = public["concept"], footwear.load_spec()
    if topic["aspect"] in UNMODELLED:
        raise ValueError("Not modelled: a topic whose score depends on the option bought or the wearer")
    bank = json.loads((footwear.DATA / "statements.json").read_text())
    eligible = {name: row for name, row in bank["aspects"].items() if concept in row.get("concepts", [concept])}
    lengths = footwear.effective_review_lengths(spec["review_length_weights"],
                                                footwear.resolve_review_site(spec["review_site"]))
    shift = 0
    # The two adjustments the producer makes to an aspect's centre from the product alone.
    if topic["aspect"] == "walking_comfort" and public["facts"]["cushioning"] == "substantial":
        shift = spec["execution_to_review"]["comfort_match_bonus"]
    if topic["aspect"] == "value":
        ranges = spec["concepts"][concept]["price_ranges_sek"]
        low, high = min(v[0] for v in ranges.values()), max(v[1] for v in ranges.values())
        shift = -(spec["execution_to_review"]["value_price_penalty"] * ((public["reference_price_sek"] - low) / (high - low) - .5))
    # The rating's own draw has no other draw above it: it can be redrawn alone.
    return SimpleNamespace(
        **common, reader=sys.modules[__name__], staged=True, concept=concept, footwear=footwear, shift=shift,
        execution=private["execution"], concentration=spec["rating_concentration"], spread=spec["reviewer_spread"],
        lengths=lengths, policy=footwear.review_topic_policy(item, spec, eligible))


def keys(place, index):
    """The streams of one review that decide what it says about the topic."""
    base = f"reviews/{place.concept}/{index}"
    names = ["rating", place.aspect, "length", "topics/value"] + [
        f"topics/other/{slot}" for slot in range(max(map(int, place.lengths)))]
    return [(streams.REVIEW, place.seed, base + "/" + name) for name in names]


def centre(place, rating):
    """The centre of the aspect's score for a star rating, in the producer's own order of arithmetic."""
    value = (rating - 1) / 4
    if place.shift:
        value += place.shift
    return value


def drawn(place, index, seed, stars=None):
    """One review's block draws as the producer makes them, with its streams opened under a seed.

    Returns the star rating, the aspect's score, the comment's length and the
    topics chosen for it, in the producer's order. The rating's stream opens
    under `stars` where that is given.
    """
    footwear, key = place.footwear, f"reviews/{place.concept}/{index}"
    rating = footwear.sample_rating(footwear.stream(seed if stars is None else stars, key + "/rating"),
                                    place.execution, place.concentration)["rating"]
    score = max(0, min(1, footwear.stream(seed, key + "/" + place.aspect).gauss(centre(place, rating), place.spread)))
    length = int(footwear.choose(seed, key + "/length", place.lengths))
    return rating, score, length, footwear.select_review_topics(seed, key, length, place.policy)


def redrawn(place, index, fresh, stars=None):
    """One review's block draws with its streams opened under a fresh seed, the rating's under one of its own if given."""
    return drawn(place, index, streams.review_seed(fresh, place.seed),
                 None if stars is None else streams.review_seed(stars, place.seed))


def rated(place, found):
    return found[0]


def rating_key(place, index):
    """The stream of one review that draws its star rating."""
    return keys(place, index)[0]


def said(place, found):
    """What a review with these draws says about the topic: positive, negative, or neither."""
    _, score, length, topics = found
    return REST if not length or place.aspect not in topics else POSITIVE if score >= .5 else NEGATIVE


def included(weights, aspect, slots):
    """The probability that an aspect is among some weighted draws without replacement."""
    total = fsum(weights.values())
    if not slots or weights.get(aspect, 0) <= 0:
        return 0.0
    return fsum(weight / total * (1.0 if name == aspect else
                                  included({k: v for k, v in weights.items() if k != name}, aspect, slots - 1))
                for name, weight in weights.items() if weight > 0)


def stars(place):
    """The probability of each star rating."""
    return programs.stars(place.execution, place.concentration)


def favourable(place, rating):
    """The probability that a reviewer of this rating scores the aspect at one half or above."""
    return erfc((.5 - centre(place, rating)) / (place.spread * sqrt(2))) / 2


def cells(place):
    """The probability that one review has each star rating and is positive, negative or neither about the topic.

    The score is a normal draw around the rating's centre, positive from one
    half up; the length and the topic choices do not depend on either.
    """
    _, length = place.footwear.weighted_options(place.lengths)
    weights = place.policy.get("effective_weights", place.policy["base_weights"])
    value = min(1, max(0, place.policy["value_probability_given_comment"])) if "value" in weights else 0
    others = {name: weight for name, weight in weights.items() if name != "value"}
    about = lambda slots: (value if place.aspect == "value" else
                           value * included(others, place.aspect, slots - 1) + (1 - value) * included(others, place.aspect, slots))
    # A rating without a comment (length zero) says nothing; neither does a comment on other topics.
    told = {int(slots): mass * about(int(slots)) if int(slots) else 0.0 for slots, mass in length.items()}
    assessed, silent = fsum(told.values()), fsum(mass - told[int(slots)] for slots, mass in length.items())
    against = lambda rating: erfc((centre(place, rating) - .5) / (place.spread * sqrt(2))) / 2
    return {(rating, name): mass * part for rating, mass in stars(place).items()
            for name, part in ((POSITIVE, assessed * favourable(place, rating)), (NEGATIVE, assessed * against(rating)),
                               (REST, silent))}


def marginal(found):
    """What a review says about the topic, whatever its rating."""
    return {name: fsum(mass for (_, own), mass in found.items() if own == name) for name in (POSITIVE, NEGATIVE, REST)}


def shares(place):
    """The probability that one review is positive, negative or neither about the topic."""
    return marginal(place.reader.cells(place))


def verdict(requirement, positive, negative):
    """The native task's verdict on the counts (no producer writes a neutral or a mixed comment)."""
    if positive + negative < requirement.get("min_assessed", 1):
        return VERDICTS[3]
    return VERDICTS[0] if positive > negative else VERDICTS[1] if negative > positive else VERDICTS[2]


def agreed(requirement, positive, negative):
    """Whether the counts are as the requirement states them."""
    return (requirement.get("verdict") in (None, verdict(requirement, positive, negative)) and
            within(requirement.get(POSITIVE, {}), positive) and within(requirement.get(NEGATIVE, {}), negative))


def holds(requirement, positive, negative, mean=None):
    """Whether the counts and, where one is stated, the mean rating (a fraction; None without ratings) are as required."""
    limits = requirement.get(STARS)
    return agreed(requirement, positive, negative) and (limits is None or mean is not None and
                                                        Fraction(str(limits.get("min", 1))) <= mean <= Fraction(str(limits.get("max", 5))))


def span(requirement, count):
    """The least and the greatest total of `count` ratings' stars that keep their mean within the stated bounds."""
    limits = requirement.get(STARS, {})
    return (ceil(Fraction(str(limits["min"])) * count) if "min" in limits else count,
            floor(Fraction(str(limits["max"])) * count) if "max" in limits else 5 * count)


def sums(given, most):
    """How far above one star each the ratings of 0 to `most` alike, independent reviews total: a distribution per number."""
    rows = [[1.0]]
    for _ in range(most):
        rows.append(spread(rows[-1], given))
    return rows


def spread(row, given):
    """The distribution of a total with one more rating added to it."""
    return [fsum(row[index - extra] * given[extra + 1] for extra in range(5) if 0 <= index - extra < len(row))
            for index in range(len(row) + 4)]


def window(row, low, high):
    """The probability that a total is within two bounds."""
    return fsum(row[max(0, low):max(0, high + 1)])


def conditional(found, share):
    """The star ratings of a review of each class that can occur."""
    return {name: {rating: found[rating, name] / share[name] for rating in range(1, 6)}
            for name in share if share[name] > 0}


def reachable(given, numbers, low, high):
    """Whether so many reviews of each class can total within two bounds at all, by the ratings each class can have."""
    totals = 1
    for name, number in numbers.items():
        for _ in range(number):
            totals = reduce(or_, (totals << rating - 1 for rating, share in given[name].items() if share > 0))
    low = max(low, 0)
    return low <= high and bool(totals >> low & (1 << high - low + 1) - 1)


def starred(place, found, share, terms):
    """Each count's log probability with the chance that the stars then total within the stated mean.

    Given the counts, the stars of the three classes of reviews total
    independently. Counts under which the mean cannot be met drop out. One
    under which it can, but with a chance below the smallest float, drops out
    with them unless no count is left: then the requirement is possible and
    cannot be weighed.
    """
    count, given = place.count, conditional(found, share)
    low, high = (total - count for total in span(place.requirement, count))
    rest = sums(given.get(REST), max(count - positive - negative for positive, negative in terms))
    most = {positive: max(n for p, n in terms if p == positive) for positive, _ in terms}
    weighed, first, lost = {}, [1.0], False
    for positive in range(max(most) + 1):
        both = first
        for negative in range(most.get(positive, -1) + 1):
            if (positive, negative) in terms:
                tail = rest[count - positive - negative]
                chance = fsum(mass * window(tail, low - index, high - index) for index, mass in enumerate(both) if mass)
                if chance > 0:
                    weighed[positive, negative] = terms[positive, negative] + log(chance)
                lost = lost or not chance and reachable(given, {
                    POSITIVE: positive, NEGATIVE: negative, REST: count - positive - negative}, low, high)
            if negative < most.get(positive, -1):
                both = spread(both, given[NEGATIVE])
        if positive < max(most):
            first = spread(first, given[POSITIVE])
    if not weighed and lost and count:
        raise NumericalLimit("The stated mean rating is too unlikely under every count to weigh")
    return weighed


def ratings(rng, place, found, share, positive, negative):
    """Star ratings for the reviews of each class, from their distribution given the counts and the stated mean.

    The three classes' totals first, in proportion to their joint probability
    within the bounds; then within a class each review's rating in turn,
    given what the remaining ones must total.
    """
    count, given = place.count, conditional(found, share)
    low, high = (total - count for total in span(place.requirement, count))
    numbers = {POSITIVE: positive, NEGATIVE: negative, REST: count - positive - negative}
    tables = {name: sums(given.get(name), number) for name, number in numbers.items()}
    first, second, third = (tables[name][-1] for name in (POSITIVE, NEGATIVE, REST))
    both = [fsum(first[a] * second[total - a] for a in range(len(first)) if 0 <= total - a < len(second))
            for total in range(len(first) + len(second) - 1)]

    def choose(options, weights):
        options, weights = zip(*((option, weight) for option, weight in zip(options, weights) if weight > 0))
        return pick(rng, list(options), list(weights))

    try:
        total = choose(range(len(both)), [mass * window(third, low - index, high - index) for index, mass in enumerate(both)])
        a = choose(range(len(first)), [mass * second[total - index] if 0 <= total - index < len(second) else 0
                                       for index, mass in enumerate(first)])
        c = choose(range(len(third)), [mass if low - total <= index <= high - total else 0 for index, mass in enumerate(third)])
        drawn = {}
        for name, left in ((POSITIVE, a), (NEGATIVE, total - a), (REST, c)):
            drawn[name] = []
            for remaining in range(numbers[name], 0, -1):
                before = tables[name][remaining - 1]
                rating = choose(range(1, 6), [given[name][rating] * before[left - rating + 1]
                                              if 0 <= left - rating + 1 < len(before) else 0 for rating in range(1, 6)])
                drawn[name].append(rating)
                left -= rating - 1
    except ValueError:
        raise NumericalLimit("The star ratings under the stated mean are too unlikely to choose among") from None
    return drawn


def multinomial(count, share, accepts):
    """The accepted (positive, negative) counts among `count` alike, independent draws, with log probabilities.

    Returns the terms and the logarithm of their sum, or None when no count
    with a positive probability is accepted.
    """
    terms = {}
    for positive in range(count + 1):
        for negative in range(count + 1 - positive):
            parts = ((positive, share[POSITIVE]), (negative, share[NEGATIVE]), (count - positive - negative, share[REST]))
            if accepts(positive, negative) and all(mass > 0 or not number for number, mass in parts):
                terms[positive, negative] = lgamma(count + 1) + fsum(
                    number * log(mass) - lgamma(number + 1) for number, mass in parts if number)
    if not terms:
        return None
    top = max(terms.values())
    return terms, min(0.0, top + log(fsum(exp(value - top) for value in terms.values())))


def origin(natural, requirement, api):
    """The site in a natural world, where a package's review program must draw the reviews the world records."""
    place = site(natural, requirement, api)
    if place.reader is programs:
        programs.reads(natural, place)
    return place


def model(world, requirement, api):
    """The counts that satisfy the requirement in a natural world, with the logarithm of each one's probability."""
    place = origin(world, requirement, api)
    joint = place.reader.cells(place)
    share = marginal(joint)
    found = multinomial(place.count, share, lambda positive, negative: agreed(place.requirement, positive, negative))
    terms = found[0] if found else {}
    if terms and STARS in place.requirement:
        terms = starred(place, joint, share, terms)
    if not terms or STARS in place.requirement and not place.count:
        raise ZeroMass("no_outcome", "No counts of this product's reviews satisfy the requirement in this world")
    top = max(terms.values())
    total = min(0.0, top + log(fsum(exp(value - top) for value in terms.values())))
    return SimpleNamespace(site=place, cells=joint, shares=share, log_terms=terms, log_probability=total,
                           probability=exp(total))


def written(world, place):
    """What a world records of each review's block draws, in `drawn`'s shape (or its review program's)."""
    if place.reader is programs:
        return programs.written(world, place)
    item = next(p for p in world["products"] if p["public"]["product_id"] == place.product_id)
    return [(row["private"]["overall_experience"]["rating"],
             row["private"]["underlying_assessments"][place.aspect]["favourability"], row["private"]["length"],
             [s["meaning"] for s in row["evidence"]["statements"]]) for row in item["reviews"]]


def counted(place, rows):
    """The positive and the negative comments among some reviews; with a mean stated, their mean rating as well."""
    seen = Counter(place.reader.said(place, row) for row in rows)
    if STARS not in place.requirement:
        return seen[POSITIVE], seen[NEGATIVE]
    return (seen[POSITIVE], seen[NEGATIVE],
            Fraction(sum(place.reader.rated(place, row) for row in rows), len(rows)) if rows else None)


def check(world, requirement, api):
    """Read the requirement off a world with the native review task's reference."""
    place = site(world, requirement, api)
    native, declared = inventory(api.basic.__package__, place.concept_id)
    spec = {"kind": native.KIND, "concept_id": place.concept_id, "operation": "topic_counts", "subject_scope": "product",
            "product_index": place.index, "topic": place.requirement["topic"],
            "min_assessed": place.requirement.get("min_assessed", 1)}
    reference = native.reference(world, native.make(world, spec, inventory=declared), inventory=declared)
    counts = reference["counts"]
    if reference["subject"]["product_id"] != place.product_id or counts["neutral"] or counts["mixed"]:
        raise AssertionError("The native review task read another product or a class no producer writes")
    read = counted(place, place.reader.written(world, place))
    if (counts[POSITIVE], counts[NEGATIVE]) != read[:2]:
        raise AssertionError("The native review task and the recorded draws disagree about the counts")
    # The product's own rating summary, which the native rating task reports.
    summary = next(p for p in world["products"] if p["public"]["product_id"] == place.product_id)["rating_summary"]
    mean = Fraction(summary["rating_sum"], summary["rating_count"]) if summary["rating_count"] else None
    if read[2:] not in ((), (mean,)):
        raise AssertionError("The product's rating summary and the recorded draws disagree about the mean rating")
    if (reference["verdict"] != verdict(place.requirement, counts[POSITIVE], counts[NEGATIVE]) or
            not holds(place.requirement, counts[POSITIVE], counts[NEGATIVE], mean)):
        raise Unmet(f"{place.product_id}: {counts[POSITIVE]} positive, {counts[NEGATIVE]} negative, "
                    f"{reference['verdict']}, mean rating {mean}")
    return {"product_id": place.product_id, "counts": counts, "verdict": reference["verdict"],
            "written_review_count": reference["written_review_count"], "assessed_count": reference["assessed_count"],
            **({"mean_rating": summary["average_rating"]} if STARS in place.requirement else {})}


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    block = model(natural, requirement, api)
    place, reader = block.site, block.site.reader
    positive, negative = pick_log(rng, list(block.log_terms), list(block.log_terms.values()))
    order = rng.sample(range(place.count), place.count)
    wanted = {index: POSITIVE if rank < positive else NEGATIVE if rank < positive + negative else REST
              for rank, index in enumerate(order)}
    stars = {}
    if STARS in place.requirement:
        chosen = ratings(rng, place, block.cells, block.shares, positive, negative)
        stars = {index: chosen[wanted[index]].pop() for index in order}
    seeds, starts, tries = {}, {}, 0
    for index in range(place.count):
        if index in stars and not place.staged:
            # Other draws of the block set the rating's chances: the whole block, until rating and class are both met.
            for _ in range(TRIES):
                seeds[index], tries = rng.getrandbits(64), tries + 1
                found = reader.redrawn(place, index, seeds[index])
                if (reader.rated(place, found), reader.said(place, found)) == (stars[index], wanted[index]):
                    break
            else:
                raise NumericalLimit("A review's rating and class are too rare to reach by redrawing the review")
            continue
        # With a rating to meet, the rating's stream first and on its own: only the rating passes to the rest.
        for _ in range(TRIES if index in stars else 0):
            starts[index], tries = rng.getrandbits(64), tries + 1
            if reader.rated(place, reader.redrawn(place, index, starts[index], starts[index])) == stars[index]:
                break
        else:
            if index in stars:
                raise NumericalLimit("A review's rating is too rare to reach by redrawing it")
        for _ in range(TRIES):
            seeds[index], tries = rng.getrandbits(64), tries + 1
            if reader.said(place, reader.redrawn(place, index, seeds[index], starts.get(index))) == wanted[index]:
                break
        else:
            raise NumericalLimit("A review's class is too rare to reach by redrawing the review")
    script = {key: streams.Reseeded(starts[index] if index in starts and key == reader.rating_key(place, index)
                                    else seeds[index])
              for index in range(place.count) for key in reader.keys(place, index)}

    def record(world):
        planned = [reader.redrawn(place, index, seeds[index], starts.get(index)) for index in range(place.count)]
        if reader.written(world, place) != planned:
            raise streams.PlanMismatch(f"{place.product_id}: producer recorded other review draws than planned")
        return {"method": "exact_counts_then_per_review_rejection", "requirement": place.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": block.probability,
                "log_probability_given_upstream": block.log_probability,
                "review_class_probabilities": block.shares, "reviews": place.count, "review_redraws": tries,
                "natural_counts": dict(zip((POSITIVE, NEGATIVE), counted(place, reader.written(natural, place)))),
                "steered_counts": {POSITIVE: positive, NEGATIVE: negative},
                **({"steered_star_total": sum(stars.values())} if stars else {}),
                "distribution_claim": "The draws of every review of this product that decide what it says about "
                                      "the topic (" + (
                                          "the star rating, the topic's score, the comment length and the topic "
                                          "choices" if reader is not programs else
                                          "the review program's steps " + ", ".join(sorted(place.drawn))) +
                                      ") are sampled from their distribution given "
                                      "the requirement: the counts exactly, " + (
                                          "every review's star rating exactly given the counts and the stated mean, "
                                          "then each review by redrawing its rating until it is that rating and its "
                                          "other draws until it is of its class. " if stars and place.staged else
                                          "every review's star rating exactly given the counts and the stated mean, "
                                          "then each review by redrawing those draws until it has that rating and "
                                          "is of its class. " if stars else
                                          "then each review by redrawing those draws until it is of its class. ") +
                                      "Every other draw is the seed's own; the "
                                      "requirement depends on no other draw. Use the probability as the importance "
                                      "weight across seeds."}

    return Step(script=script, probability=block.probability, log_probability=block.log_probability,
                **vars(footprint(natural, requirement, api)), record=record,
                check=lambda world: check(world, requirement, api))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def trial(natural, requirement, api):
    """Every review's block draws from the producer's own lines under another seed; independent of the model."""
    place = origin(natural, requirement, api)
    reader = place.reader
    reading = lambda seed: [reader.redrawn(place, index, seed) for index in range(place.count)]
    return SimpleNamespace(
        keys={key for index in range(place.count) for key in reader.keys(place, index)},
        **vars(footprint(natural, requirement, api)), reading=reading,
        counts=lambda seed: counted(place, reading(seed)),
        holds=lambda seed: holds(place.requirement, *counted(place, reading(seed))),
        recorded=lambda world: reader.written(world, place),
        satisfied=lambda world: satisfied(world, requirement, api))


def satisfied(world, requirement, api):
    try:
        return bool(check(world, requirement, api))
    except Unmet:
        return False


def empirical(natural, requirement, api, trials, first_seed):
    """How often the requirement holds under other seeds, by (positive, negative) counts."""
    found, stated = trial(natural, requirement, api), resolve(requirement)
    seen = (found.counts(seed) for seed in range(first_seed, first_seed + trials))
    return Counter(row for row in seen if holds(stated, *row))
