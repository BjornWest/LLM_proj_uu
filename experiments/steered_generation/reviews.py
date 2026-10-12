"""Conditional sampling of what a product's reviews say about one topic.

A requirement names a product and a topic of the native review-summary task
(an aspect and its context), and states the verdict of the task's count, the
number of positive comments, the number of negative ones, or several of these.
The task counts written comments by what they report first hand about the
topic: positive, negative or not assessed; a rating without a comment is not
counted at all.

This covers the pilot concepts, whose reviews `footwear_context_pilot`
samples with one named stream per draw under the product's own seed. A review
says something about a topic when it has a comment (its length is not zero)
and the topic is among those chosen for it; what it says is the sign of the
reviewer's score for the aspect, a normal draw around a centre set by the
star rating. The rating, the aspect's score, the length and the topic choices
of every review are the block. Reviews draw independently and alike, so the
counts are multinomial, and their probability is a sum over the counts that
satisfy the requirement.

Sampling picks the counts, places them on reviews at random and then redraws
each review's block streams under fresh seeds until the review falls in its
class. That is rejection inside one review, where the classes are never rare
by more than the review's own probabilities; the rare part, the counts, is
chosen exactly. Every other draw of the review (the option bought, sizing, the
other aspects' scores, phrasing) is the seed's own and reads the block's
draws where the producer makes it depend on them.
"""
from collections import Counter
from functools import lru_cache
from importlib import import_module
import json
from math import erfc, exp, fsum, lgamma, log, sqrt
from types import SimpleNamespace

from . import blocks, streams
from .blocks import NumericalLimit, Step, Unmet, bound, within
from .cheapest import pick_log
from .prices import ZeroMass

VERSION = "steered-review-topic-v1"
VERDICTS = ("more_positive", "more_negative", "tie", "insufficient_evidence")
POSITIVE, NEGATIVE, REST = "positive", "negative", "rest"
# Aspects whose score depends on more than the rating and the product: the option bought and the wearer.
UNMODELLED = ("size_fit", "forefoot_room")
# A review's class is redrawn at most this often before the block gives up as numerically out of reach.
TRIES = 10 ** 6


def resolve(requirement):
    required, stated = {"schema", "product_id", "topic"}, {"verdict", POSITIVE, NEGATIVE}
    if (type(requirement) is not dict or not required <= set(requirement) <= required | stated | {"min_assessed"} or
            requirement["schema"] != VERSION or not stated & set(requirement) or
            type(requirement["product_id"]) is not str or not requirement["product_id"]):
        raise ValueError("Declare a product, a topic and a verdict, a number of positive or of negative comments")
    topic = requirement["topic"]
    if (type(topic) is not dict or set(topic) != {"aspect", "context"} or type(topic["aspect"]) is not str or
            type(topic["context"]) is not dict):
        raise ValueError("A topic is an aspect and its context")
    if requirement.get("verdict", VERDICTS[0]) not in VERDICTS:
        raise ValueError("A verdict is one of " + ", ".join(VERDICTS))
    if any(key in requirement and not bound(requirement[key]) for key in (POSITIVE, NEGATIVE)):
        raise ValueError("A number of comments is a non-negative min, max or both")
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
    if public["concept_id"] not in api.package_export.PILOTS:
        raise ValueError("Only the reviews of the pilot concepts are modelled")
    native, declared = inventory(api.basic.__package__, public["concept_id"])
    topic, concept, spec = requirement["topic"], public["concept"], footwear.load_spec()
    if not any(row["aspect"] == topic["aspect"] and native.context_matches(row["context"], topic["context"])
               for row in declared.topics):
        raise ValueError("The topic is not one the native review task accepts for this concept")
    if topic["aspect"] in UNMODELLED:
        raise ValueError("Not modelled: a topic whose score depends on the option bought or the wearer")
    bank = json.loads((footwear.DATA / "statements.json").read_text())
    eligible = {name: row for name, row in bank["aspects"].items() if concept in row.get("concepts", [concept])}
    seed = api.commerce.seed_for(world["seed"], public["product_id"])
    if item.get("sample_seed", seed) != seed:
        raise ValueError("The product was not manufactured under the seed this producer gives it")
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
    return SimpleNamespace(
        requirement=requirement, product_id=public["product_id"], concept=concept, concept_id=public["concept_id"],
        aspect=topic["aspect"], seed=seed, count=len(item["reviews"]), footwear=footwear, shift=shift,
        execution=private["execution"], concentration=spec["rating_concentration"], spread=spec["reviewer_spread"],
        lengths=lengths, policy=footwear.review_topic_policy(item, spec, eligible),
        index=sorted(p["public"]["product_id"] for p in world["products"]
                     if p["public"]["concept_id"] == public["concept_id"]).index(public["product_id"]))


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


def drawn(place, index, seed):
    """One review's block draws as the producer makes them, with its streams opened under a seed.

    Returns the star rating, the aspect's score, the comment's length and the
    topics chosen for it, in the producer's order.
    """
    footwear, key = place.footwear, f"reviews/{place.concept}/{index}"
    rating = footwear.sample_rating(footwear.stream(seed, key + "/rating"), place.execution, place.concentration)["rating"]
    score = max(0, min(1, footwear.stream(seed, key + "/" + place.aspect).gauss(centre(place, rating), place.spread)))
    length = int(footwear.choose(seed, key + "/length", place.lengths))
    return rating, score, length, footwear.select_review_topics(seed, key, length, place.policy)


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
    """The probability of each star rating: one more than a beta-binomial count of four."""
    mean = .05 + .9 * place.execution
    a, b = mean * place.concentration, (1 - mean) * place.concentration
    beta = lambda x, y: lgamma(x) + lgamma(y) - lgamma(x + y)
    return {1 + hits: exp(log((1, 4, 6, 4, 1)[hits]) + beta(a + hits, b + 4 - hits) - beta(a, b)) for hits in range(5)}


def favourable(place, rating):
    """The probability that a reviewer of this rating scores the aspect at one half or above."""
    return erfc((.5 - centre(place, rating)) / (place.spread * sqrt(2))) / 2


def shares(place):
    """The probability that one review is positive, negative or neither about the topic.

    The score is a normal draw around the rating's centre, positive from one
    half up; the length and the topic choices do not depend on either.
    """
    praise = fsum(mass * favourable(place, rating) for rating, mass in stars(place).items())
    _, length = place.footwear.weighted_options(place.lengths)
    weights = place.policy.get("effective_weights", place.policy["base_weights"])
    value = min(1, max(0, place.policy["value_probability_given_comment"])) if "value" in weights else 0
    others = {name: weight for name, weight in weights.items() if name != "value"}
    about = lambda slots: (value if place.aspect == "value" else
                           value * included(others, place.aspect, slots - 1) + (1 - value) * included(others, place.aspect, slots))
    # A rating without a comment (length zero) says nothing; neither does a comment on other topics.
    told = {int(slots): mass * about(int(slots)) if int(slots) else 0.0 for slots, mass in length.items()}
    assessed = fsum(told.values())
    return {POSITIVE: assessed * praise, NEGATIVE: assessed * (1 - praise),
            REST: fsum(mass - told[int(slots)] for slots, mass in length.items())}


def verdict(requirement, positive, negative):
    """The native task's verdict on the counts (the pilot's reviews are never neutral or mixed)."""
    if positive + negative < requirement.get("min_assessed", 1):
        return VERDICTS[3]
    return VERDICTS[0] if positive > negative else VERDICTS[1] if negative > positive else VERDICTS[2]


def holds(requirement, positive, negative):
    return (requirement.get("verdict") in (None, verdict(requirement, positive, negative)) and
            within(requirement.get(POSITIVE, {}), positive) and within(requirement.get(NEGATIVE, {}), negative))


def model(world, requirement, api):
    """The counts that satisfy the requirement, with the logarithm of each one's probability."""
    place = site(world, requirement, api)
    share, count = shares(place), place.count
    terms = {}
    for positive in range(count + 1):
        for negative in range(count + 1 - positive):
            parts = ((positive, share[POSITIVE]), (negative, share[NEGATIVE]), (count - positive - negative, share[REST]))
            if holds(place.requirement, positive, negative) and all(mass > 0 or not number for number, mass in parts):
                terms[positive, negative] = lgamma(count + 1) + fsum(
                    number * log(mass) - lgamma(number + 1) for number, mass in parts if number)
    if not terms:
        raise ZeroMass("no_outcome", "No counts of this product's reviews satisfy the requirement in this world")
    top = max(terms.values())
    log_probability = top + log(fsum(exp(value - top) for value in terms.values()))
    return SimpleNamespace(site=place, shares=share, log_terms=terms, log_probability=min(0.0, log_probability),
                           probability=exp(min(0.0, log_probability)))


def written(world, place):
    """What a world records of each review's block draws, in `drawn`'s shape."""
    item = next(p for p in world["products"] if p["public"]["product_id"] == place.product_id)
    return [(row["private"]["overall_experience"]["rating"],
             row["private"]["underlying_assessments"][place.aspect]["favourability"], row["private"]["length"],
             [s["meaning"] for s in row["evidence"]["statements"]]) for row in item["reviews"]]


def counted(place, rows):
    seen = Counter(said(place, row) for row in rows)
    return seen[POSITIVE], seen[NEGATIVE]


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
        raise AssertionError("The native review task read another product or a class the pilot does not write")
    if (counts[POSITIVE], counts[NEGATIVE]) != counted(place, written(world, place)):
        raise AssertionError("The native review task and the recorded draws disagree about the counts")
    if (reference["verdict"] != verdict(place.requirement, counts[POSITIVE], counts[NEGATIVE]) or
            not holds(place.requirement, counts[POSITIVE], counts[NEGATIVE])):
        raise Unmet(f"{place.product_id}: {counts[POSITIVE]} positive, {counts[NEGATIVE]} negative, {reference['verdict']}")
    return {"product_id": place.product_id, "counts": counts, "verdict": reference["verdict"],
            "written_review_count": reference["written_review_count"], "assessed_count": reference["assessed_count"]}


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    block = model(natural, requirement, api)
    place = block.site
    positive, negative = pick_log(rng, list(block.log_terms), list(block.log_terms.values()))
    order = rng.sample(range(place.count), place.count)
    wanted = {index: POSITIVE if rank < positive else NEGATIVE if rank < positive + negative else REST
              for rank, index in enumerate(order)}
    seeds, tries = {}, 0
    for index in range(place.count):
        for _ in range(TRIES):
            seeds[index], tries = rng.getrandbits(64), tries + 1
            if said(place, drawn(place, index, streams.review_seed(seeds[index], place.seed))) == wanted[index]:
                break
        else:
            raise NumericalLimit("A review's class is too rare to reach by redrawing the review")
    script = {key: streams.Reseeded(seeds[index]) for index in range(place.count) for key in keys(place, index)}

    def record(world):
        planned = [drawn(place, index, streams.review_seed(seeds[index], place.seed)) for index in range(place.count)]
        if written(world, place) != planned:
            raise streams.PlanMismatch(f"{place.product_id}: producer recorded other review draws than planned")
        return {"method": "exact_counts_then_per_review_rejection", "requirement": place.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": block.probability,
                "log_probability_given_upstream": block.log_probability,
                "review_class_probabilities": block.shares, "reviews": place.count, "review_redraws": tries,
                "natural_counts": dict(zip((POSITIVE, NEGATIVE), counted(place, written(natural, place)))),
                "steered_counts": {POSITIVE: positive, NEGATIVE: negative},
                "distribution_claim": "The star rating, the topic's score, the comment length and the topic choices "
                                      "of every review of this product are sampled from their distribution given "
                                      "the requirement: the counts exactly, then each review by redrawing those "
                                      "draws until it is of its class. Every other draw is the seed's own; the "
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
    place = site(natural, requirement, api)
    reading = lambda seed: [drawn(place, index, streams.review_seed(seed, place.seed)) for index in range(place.count)]
    return SimpleNamespace(
        keys={key for index in range(place.count) for key in keys(place, index)},
        **vars(footprint(natural, requirement, api)), reading=reading,
        counts=lambda seed: counted(place, reading(seed)),
        holds=lambda seed: holds(place.requirement, *counted(place, reading(seed))),
        recorded=lambda world: written(world, place),
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
