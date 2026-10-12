"""Conditional sampling of what a carrier's reviews say about one aspect.

A requirement names a carrier, an aspect of the native carrier-review task
and the scope the task counts in (a shipping class, a range of dates), and
states the verdict of the task's count, the number of positive comments, the
number of negative ones, or several of these.

The producer first draws every shipment's history, which settles what
happened to it: whether the parcel came on the promised day, how it was
handed over, and so on, each an observation with a sentiment. Then, on one
stream per shipment, it draws the review: whether there is a comment, how
many of the shipment's observations it mentions and which, the wording, and
the stars. The histories are upstream here. The block is the review stream
of every shipment in scope whose history has an observation of the aspect:
such a review counts as positive, negative or neutral, by what happened,
exactly when it has a comment that mentions the aspect.

Shipments differ in what there is to mention, so the probability that a
review mentions the aspect is the shipment's own, and each count is a sum of
independent yes/no draws with different probabilities. The three counts come
from different shipments and are independent. A requirement that asks for
more complaints than there were bad experiences has probability zero: what
happened is not steered.

Sampling picks the counts, then which shipments mention the aspect given how
many do, then redraws each of those shipments' review streams under fresh
seeds until the review does or does not mention it. A shipment's whole review
is on that stream, so its stars, wording and reviewer are redrawn with it.
"""
from collections import Counter
from importlib import import_module
import json
from math import exp, fsum, inf, log
import sys
from types import SimpleNamespace

from . import blocks, streams
from .blocks import NumericalLimit, Step, Unmet, bound, within
from .cheapest import pick_log
from .prices import ZeroMass
from .reviews import NEGATIVE, POSITIVE, TRIES, VERDICTS, included

VERSION = "steered-carrier-review-topic-v1"
NEUTRAL = "neutral"
SIGNS = (POSITIVE, NEGATIVE, NEUTRAL)
# How many observations a comment mentions, and how much likelier some are to be picked: the producer's own
# figures, which it does not keep in its configuration. The reading of a redrawn stream checks them.
MENTIONED = {1: .4, 2: .35, 3: .2, 4: .05}


def weight(aspect):
    return 2 if aspect == "punctuality" else .35 if aspect.startswith("notification_") else 1


def resolve(requirement, version=VERSION):
    required, stated = {"schema", "carrier_id", "aspect"}, {"verdict", POSITIVE, NEGATIVE}
    scope = {"shipping_class", "date_from", "date_to"}
    if (type(requirement) is not dict or not required <= set(requirement) <= required | stated | scope | {"min_assessed"} or
            requirement["schema"] != version or not stated & set(requirement) or
            any(type(requirement[key]) is not str or not requirement[key]
                for key in (required | scope) & set(requirement))):
        raise ValueError("Declare a carrier, an aspect and a verdict, a number of positive or of negative comments")
    if requirement.get("verdict", VERDICTS[0]) not in VERDICTS:
        raise ValueError("A verdict is one of " + ", ".join(VERDICTS))
    if any(key in requirement and not bound(requirement[key]) for key in (POSITIVE, NEGATIVE)):
        raise ValueError("A number of comments is a non-negative min, max or both")
    least = requirement.get("min_assessed", 1)
    if type(least) is not int or not 1 <= least <= 1000 or "min_assessed" in requirement and "verdict" not in requirement:
        raise ValueError("The least number of assessing comments is 1 to 1000 and goes with a verdict")
    return json.loads(json.dumps(requirement))


def footprint(world, requirement, api):
    """What the block decides, the carrier's reviews, and what its probability reads: its shipments' histories."""
    requirement = resolve(requirement)
    if not any(c["carrier_id"] == requirement["carrier_id"] for c in world["carrier_evidence"]["public"]["carriers"]):
        raise ValueError("Unknown carrier")
    return SimpleNamespace(writes={("carrier_reviews", "", requirement["carrier_id"])},
                           reads={("carrier_shipments", "", requirement["carrier_id"])})


def task(world, requirement):
    """The native task specification the requirement is a scenario of."""
    carriers = sorted(c["carrier_id"] for c in world["carrier_evidence"]["public"]["carriers"])
    return {"kind": "summarize_carrier_reviews", "operation": "topic_counts",
            "carrier_index": carriers.index(requirement["carrier_id"]), "aspect": requirement["aspect"],
            "min_assessed": requirement.get("min_assessed", 1),
            **{key: requirement[key] for key in ("shipping_class", "date_from", "date_to") if key in requirement}}


def site(world, requirement, api):
    """The shipments whose review can say something about the aspect, with the chance that it does."""
    requirement = resolve(requirement)
    footprint(world, requirement, api)
    native = import_module(api.basic.__package__ + ".carrier_review_task")
    # The native resolver's own checks of the aspect, the shipping class and the dates.
    stated = native.resolve(task(world, requirement))
    corpus, producer = world["carrier_evidence"], sys.modules[api.commerce.carrier_reviews.__module__]
    written = {row["shipment_id"]: row for row in corpus["private"]["reviews"]}
    text, shipments = corpus["parameters"]["text_probability"], []
    for history in corpus["private"]["shipments"]:
        review = written[history["shipment_id"]]
        aspects = [found["aspect"] for found in history["observations"]]
        if len(set(aspects)) != len(aspects):
            raise ValueError("Not modelled: a shipment with two observations of one aspect")
        if (history["carrier_id"] != requirement["carrier_id"] or requirement["aspect"] not in aspects or
                stated["shipping_class"] not in ("all", review["shipping_class"]) or
                not stated.get("date_from", "0001-01-01") <= review["date"] <= stated.get("date_to", "9999-12-31")):
            continue
        shipments.append(SimpleNamespace(
            id=history["shipment_id"], history=history, chance=mention(text, aspects, requirement["aspect"]),
            sign=next(found["sentiment"] for found in history["observations"] if found["aspect"] == requirement["aspect"]),
            key=(streams.CARRIER, producer.VERSION + "/review/" + history["shipment_id"])))
    return SimpleNamespace(requirement=requirement, carrier_id=requirement["carrier_id"], aspect=requirement["aspect"],
                           seed=corpus["seed"], text=text, shipments=shipments, producer=producer, native=native)


def mention(text, aspects, aspect):
    """The probability that a review mentions an aspect, given the aspects its shipment's history observed."""
    weights = {name: weight(name) for name in aspects}
    return text * fsum(share * included(weights, aspect, min(len(aspects), slots)) for slots, share in MENTIONED.items())


def drawn(place, shipment, seed):
    """The aspects a shipment's review mentions, in order, as the producer draws them with the stream under a seed."""
    stream = place.producer.rng(seed, shipment.key[1])
    if not stream.random() < place.text:
        return []
    observations = shipment.history["observations"]
    available, chosen = [found["aspect"] for found in observations], []
    for _ in range(min(len(observations), stream.choices(list(MENTIONED), list(MENTIONED.values()))[0])):
        chosen.append(stream.choices(available, [weight(name) for name in available])[0])
        available.remove(chosen[-1])
    stream.shuffle(chosen)
    return chosen


def counts(shipments):
    """The logarithm of the probability of each number of mentions among some shipments, and the same for every tail.

    `tails[j][m]` is for the shipments from the j-th on, which is what choosing
    them one after another needs.
    """
    tails = [[0.0]]
    for shipment in reversed(shipments):
        after, yes, no = tails[0], shipment.chance, 1 - shipment.chance
        parts = lambda m: [value + log(share) for value, share in
                           ((after[m] if m < len(after) else -inf, no), (after[m - 1] if m else -inf, yes))
                           if share > 0 and value > -inf]
        tails.insert(0, [joined(parts(m)) for m in range(len(after) + 1)])
    return tails


def joined(values):
    """The logarithm of a sum of exponentials; minus infinity for none."""
    if not values:
        return -inf
    top = max(values)
    return top + log(fsum(exp(value - top) for value in values))


def verdict(requirement, positive, negative, neutral):
    """The native task's verdict: neutral comments assess the aspect and take no side."""
    if positive + negative + neutral < requirement.get("min_assessed", 1):
        return VERDICTS[3]
    return VERDICTS[0] if positive > negative else VERDICTS[1] if negative > positive else VERDICTS[2]


def holds(requirement, positive, negative, neutral):
    return (requirement.get("verdict") in (None, verdict(requirement, positive, negative, neutral)) and
            within(requirement.get(POSITIVE, {}), positive) and within(requirement.get(NEGATIVE, {}), negative))


def model(world, requirement, api):
    """The counts that satisfy the requirement, with the logarithm of each one's probability."""
    place = site(world, requirement, api)
    groups = {sign: [shipment for shipment in place.shipments if shipment.sign == sign] for sign in SIGNS}
    if sum(map(len, groups.values())) != len(place.shipments):
        raise ValueError("Not modelled: an observation that is neither positive, negative nor neutral")
    tails = {sign: counts(found) for sign, found in groups.items()}
    terms = {}
    for positive, first in enumerate(tails[POSITIVE][0]):
        for negative, second in enumerate(tails[NEGATIVE][0]):
            for neutral, third in enumerate(tails[NEUTRAL][0]):
                if min(first, second, third) > -inf and holds(place.requirement, positive, negative, neutral):
                    terms[positive, negative, neutral] = first + second + third
    if not terms:
        raise ZeroMass("no_outcome", "No counts of this carrier's reviews satisfy the requirement in this world")
    log_probability = min(0.0, joined(list(terms.values())))
    return SimpleNamespace(site=place, groups=groups, tails=tails, log_terms=terms, log_probability=log_probability,
                           probability=exp(log_probability))


def written(world, place):
    """What a world records of each block shipment's review: the aspects its comment mentions, in order."""
    rows = {row["shipment_id"]: row for row in world["carrier_evidence"]["private"]["reviews"]}
    return [[found["aspect"] for found in rows[shipment.id]["statements"]] for shipment in place.shipments]


def counted(place, rows):
    seen = Counter(shipment.sign for shipment, mentioned in zip(place.shipments, rows) if place.aspect in mentioned)
    return tuple(seen[sign] for sign in SIGNS)


def check(world, requirement, api):
    """Read the requirement off a world with the native carrier-review task's reference."""
    place = site(world, requirement, api)
    declared = place.native.ReviewInventory()
    reference = place.native.reference(world, place.native.make(world, task(world, place.requirement), inventory=declared),
                                       inventory=declared)
    found = reference["counts"]
    if reference["subject"]["carrier_id"] != place.carrier_id or found["mixed"]:
        raise AssertionError("The native carrier-review task read another carrier or a mixed comment")
    if tuple(found[sign] for sign in SIGNS) != counted(place, written(world, place)):
        raise AssertionError("The native carrier-review task and the recorded reviews disagree about the counts")
    seen = tuple(found[sign] for sign in SIGNS)
    if reference["verdict"] != verdict(place.requirement, *seen) or not holds(place.requirement, *seen):
        raise Unmet(f"{place.carrier_id}: {seen[0]} positive, {seen[1]} negative, {reference['verdict']}")
    return {"carrier_id": place.carrier_id, "counts": found, "verdict": reference["verdict"],
            "written_review_count": reference["written_review_count"], "assessed_count": reference["assessed_count"]}


def placed(rng, shipments, tails, count):
    """Which of some shipments mention the aspect, given that `count` of them do.

    Decided one after another: a shipment mentions it with its chance times
    the probability that the rest make up the remainder, over the probability
    that it and the rest make up what is left. The ratio is formed in
    logarithms, since the tails can be far below the float range while it is
    not; when as many are still needed as are left, all of them must.
    """
    found, left = [], count
    for index, shipment in enumerate(shipments):
        found.append(bool(left) and (left == len(shipments) - index or shipment.chance > 0 and rng.random() < exp(
            log(shipment.chance) + tails[index + 1][left - 1] - tails[index][left])))
        left -= found[-1]
    if left:
        raise AssertionError("The mentions placed do not add up to the count")
    return found


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    block = model(natural, requirement, api)
    place = block.site
    picked = dict(zip(SIGNS, pick_log(rng, list(block.log_terms), list(block.log_terms.values()))))
    seeds, tries = {}, 0
    for sign, shipments in block.groups.items():
        for shipment, mention in zip(shipments, placed(rng, shipments, block.tails[sign], picked[sign])):
            for _ in range(TRIES):
                seeds[shipment.id], tries = rng.getrandbits(64), tries + 1
                if (place.aspect in drawn(place, shipment, seeds[shipment.id])) == mention:
                    break
            else:
                raise NumericalLimit("A review's class is too rare to reach by redrawing the review")
    script = {shipment.key: streams.Reseeded(seeds[shipment.id]) for shipment in place.shipments}

    def record(world):
        if written(world, place) != [drawn(place, shipment, seeds[shipment.id]) for shipment in place.shipments]:
            raise streams.PlanMismatch(f"{place.carrier_id}: producer recorded other reviews than planned")
        return {"method": "exact_counts_then_per_review_rejection", "requirement": place.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": block.probability,
                "log_probability_given_upstream": block.log_probability,
                "shipments_that_could_mention": {sign: len(found) for sign, found in block.groups.items()},
                "review_redraws": tries,
                "natural_counts": dict(zip(SIGNS, counted(place, written(natural, place)))),
                "steered_counts": picked,
                "distribution_claim": "The review streams of this carrier's shipments in the task's scope whose "
                                      "history has an observation of the aspect are sampled from their distribution "
                                      "given the requirement: the counts exactly, then which shipments mention the "
                                      "aspect, then each review by redrawing its stream until it does or does not. "
                                      "The shipments' histories and every other draw are the seed's own; the "
                                      "requirement depends on no other draw. Use the probability as the importance "
                                      "weight across seeds."}

    return Step(script=script, probability=block.probability, log_probability=block.log_probability,
                **vars(footprint(natural, requirement, api)), record=record,
                check=lambda world: check(world, requirement, api))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def trial(natural, requirement, api):
    """Every block shipment's review from the producer's own lines under another seed; independent of the model."""
    place = site(natural, requirement, api)
    reading = lambda seed: [drawn(place, shipment, seed) for shipment in place.shipments]
    return SimpleNamespace(
        keys={shipment.key for shipment in place.shipments}, **vars(footprint(natural, requirement, api)),
        reading=reading, counts=lambda seed: counted(place, reading(seed)),
        holds=lambda seed: holds(place.requirement, *counted(place, reading(seed))),
        recorded=lambda world: written(world, place),
        satisfied=lambda world: satisfied(world, requirement, api))


def satisfied(world, requirement, api):
    try:
        return bool(check(world, requirement, api))
    except Unmet:
        return False


def empirical(natural, requirement, api, trials, first_seed):
    """How often the requirement holds under other seeds, by (positive, negative, neutral) counts."""
    found, stated = trial(natural, requirement, api), resolve(requirement)
    seen = (found.counts(seed) for seed in range(first_seed, first_seed + trials))
    return Counter(row for row in seen if holds(stated, *row))
