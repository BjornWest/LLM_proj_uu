"""Conditional sampling of a carrier's star rating and of how good its service is.

A requirement names a carrier and bounds its average stars as its summary
publishes them, states the level of one or more aspects of its service
(strong, mixed or weak punctuality, handling, handoff, communication), or
both: "a carrier rated at most 3.7", "a carrier that is weak on punctuality".

The producer draws a carrier's four levels first, each on its own stream.
Each shipment's history then follows on the shipment's stream, where a level
is the chance that the aspect goes well. Last, on one more stream per
shipment, comes the review: whether it has a comment and which observations
that mentions, and the stars, which are likelier high the more of the
history went well and are held to the comment's tone (no fewer than three
with praise only, no more than three with complaints only, no more than four
with both).

The block is the four level streams and every review stream of the carrier.
The history streams are the seed's own and the block is sampled given them:
for each choice of levels the histories are known (not simply the same or
worse under a worse level, since what a stream's later draws decide shifts
with the earlier outcomes), and with them every review's distribution of stars; the
reviews draw independently, so the total is a sum of independent numbers.
The requirement's probability is a sum over the level choices it allows of
the chance of the levels times the chance that the average is as required.
A sample picks the levels in proportion, then the total, then each review's
stars given the total, and redraws each stream until it gives what was
picked. A low rating therefore comes mostly from a carrier that serves
badly, to the extent the producer ties the two, and only then from harsher
reviews of what happened.

A requirement may add what the carrier's comments say about one aspect
(`topic`, in the ninth requirement's words: a verdict or counts of positive
and negative comments, in a shipping class or a range of dates). The two
are statements about the same reviews, so they are one block here: samples
of the block given the stars and levels are drawn until the comments are as
stated, and the probability is the stars' own times the share of a fixed
number of such samples that qualify, an estimate.
"""
from datetime import datetime
from functools import lru_cache
from itertools import product
import json
from math import exp, lgamma, log
from random import Random
import sys
from types import SimpleNamespace

from . import blocks, carriers, streams
from .blocks import NumericalLimit, Step, Unmet
from .carriers import MENTIONED, joined, weight
from .cheapest import pick_log
from .prices import ZeroMass
from .reviews import NEGATIVE, POSITIVE, TRIES

VERSION = "steered-carrier-stars-v1"
STARS = (1, 2, 3, 4, 5)
# With a topic: how many samples of the block estimate the share whose comments are as stated, and the estimates
# made in this process.
PROPOSALS, ESTIMATES = 200, {}
# The producer's own figures for the stars, which it does not keep in its configuration: how far the share of a
# history that went well moves the chance of a star, how concentrated a review's own leaning is, and the weight of
# timeliness among the groups of observations. The reading of a redrawn stream runs the producer's own lines.
FLOOR, SPAN, CONCENTRATION, TIMELINESS = .1, .8, 1.5, 2


def resolve(requirement):
    stated = {"average_stars", "levels"}
    if type(requirement) is dict and "topic" in requirement:
        topic = requirement["topic"]
        if type(topic) is not dict or {"schema", "carrier_id"} & set(topic) or type(requirement.get("carrier_id")) is not str:
            raise ValueError("A topic is the carrier-review requirement's statement, without its schema and carrier")
        carriers.resolve(spoken(requirement))
        requirement = {key: value for key, value in requirement.items() if key != "topic"} | {"topic": topic}
    if (type(requirement) is not dict or not {"schema", "carrier_id"} <= set(requirement) <= {"schema", "carrier_id", "topic"} | stated or
            requirement["schema"] != VERSION or not stated & set(requirement) or
            type(requirement["carrier_id"]) is not str or not requirement["carrier_id"]):
        raise ValueError("Declare a carrier and its average stars, the levels of its service, or both")
    limits = requirement.get("average_stars", {"min": 1})
    if (type(limits) is not dict or not limits or set(limits) - {"min", "max"} or
            any(type(value) not in (int, float) or not 1 <= value <= 5 for value in limits.values()) or
            limits.get("min", 1) > limits.get("max", 5)):
        raise ValueError("Average stars are bounded by a min, a max or both, between 1 and 5")
    levels = requirement.get("levels", {"aspect": "level"})
    if type(levels) is not dict or not levels or any(type(value) is not str for value in levels.values()):
        raise ValueError("Levels are stated per aspect, one level each")
    return json.loads(json.dumps(requirement))


def spoken(requirement):
    """The carrier-review requirement a topic states."""
    return {"schema": carriers.VERSION, "carrier_id": requirement["carrier_id"], **requirement["topic"]}


def footprint(world, requirement, api):
    """What the block decides: the carrier's levels, its shipments' histories through them, and its reviews."""
    carrier = resolve(requirement)["carrier_id"]
    if not any(row["carrier_id"] == carrier for row in world["carrier_evidence"]["public"]["carriers"]):
        raise ValueError("Unknown carrier")
    return SimpleNamespace(writes={(kind, "", carrier) for kind in ("carrier_quality", "carrier_shipments", "carrier_reviews")},
                           reads=set())


def site(world, requirement, api):
    """The carrier, the level table and everything the producer's `history` reads for its shipments."""
    requirement = resolve(requirement)
    footprint(world, requirement, api)
    corpus, producer = world["carrier_evidence"], sys.modules[api.commerce.carrier_reviews.__module__]
    addresses = sys.modules[producer.address_world.__module__]
    base = producer.address_world(corpus["seed"], corpus["city"]["city_id"])
    if base["world_id"] != corpus["private"]["source_address_world_id"]:
        raise ValueError("The carrier corpus was not drawn from the address world this producer makes")
    experience = json.loads(addresses.PLAN.read_text())["carrier_review_backlog"]["experience_sampling_proposal"]
    carrier, table = requirement["carrier_id"], experience["aspect_level_probabilities"]
    natural = next(row["aspect_levels"] for row in corpus["private"]["carrier_parameters"] if row["carrier_id"] == carrier)
    aspects = tuple(natural)
    if aspects != tuple(producer.ASPECTS) or any(level not in table for level in natural.values()):
        raise ValueError("The carrier's recorded levels are not ones this producer draws")
    for aspect, level in requirement.get("levels", {}).items():
        if aspect not in aspects or level not in table:
            raise ValueError(f"Unknown aspect or level: {aspect} {level}")
    scope = None
    if "topic" in requirement:
        # The native task's own reading of the aspect, the shipping class and the dates.
        below = carriers.site(world, spoken(requirement), api)
        scope = below.native.resolve(carriers.task(world, below.requirement))
    return SimpleNamespace(
        requirement=requirement, carrier_id=carrier, seed=corpus["seed"], producer=producer, base=base, scope=scope,
        text=corpus["parameters"]["text_probability"], count=corpus["parameters"]["shipments_per_carrier"],
        policy=next(row for row in corpus["public"]["carriers"] if row["carrier_id"] == carrier),
        rates=experience["success_probabilities_by_aspect_level"], table=table, aspects=aspects, natural=natural,
        quality={aspect: (streams.CARRIER, f"{producer.VERSION}/quality/{carrier}/{aspect}") for aspect in aspects},
        review=lambda index: (streams.CARRIER, f"{producer.VERSION}/review/{carrier}-shipment-{index:04d}"))


def histories(place, levels):
    """Every shipment's history under some levels, from the producer's own `history` on the seed's streams."""
    found = [place.producer.history(place.base, place.policy, levels, index, place.rates) for index in range(place.count)]
    for history in found:
        aspects = [row["aspect"] for row in history["observations"]]
        if len(set(aspects)) != len(aspects):
            raise ValueError("Not modelled: a shipment with two observations of one aspect")
    return found


def leaning(observations):
    """The share of a history that went well, as the stars read it: by groups of observations, timeliness doubled."""
    groups = {}
    for found in observations:
        if found["sentiment"] == "neutral" or found["aspect"] == "locker":
            continue
        group = ("timeliness" if found["aspect"] in ("window", "punctuality") else
                 "communication" if found["aspect"] == "tracking" or found["aspect"].startswith("notification_") else
                 found["aspect"])
        groups.setdefault(group, []).append(found["sentiment"] == POSITIVE)
    total = sum(TIMELINESS if group == "timeliness" else 1 for group in groups)
    return sum((TIMELINESS if group == "timeliness" else 1) * sum(values) / len(values)
               for group, values in groups.items()) / total if total else .5


@lru_cache(maxsize=None)
def drawn_stars(share):
    """The probability of each number of stars before the comment's tone holds it: one and four coins of one leaning.

    The leaning is a beta draw around the share of the history that went
    well, so the number of coins that come up is beta-binomial.
    """
    chance = FLOOR + SPAN * share
    first, second = chance * CONCENTRATION, (1 - chance) * CONCENTRATION
    beta = lambda a, b: lgamma(a) + lgamma(b) - lgamma(a + b)
    return tuple(exp(lgamma(5) - lgamma(k + 1) - lgamma(5 - k) + beta(k + first, 4 - k + second) - beta(first, second))
                 for k in range(5))


@lru_cache(maxsize=None)
def tones(kinds, slots):
    """The probability that a comment of so many statements has praise, complaints, both or neither.

    `kinds` counts the observations left to mention by (weight, sentiment);
    they are mentioned one after another, each in proportion to its weight.
    Returns {(has praise, has complaints): probability}.
    """
    if not slots:
        return {(False, False): 1.0}
    total, found = sum(kind[0] * count for kind, count in kinds), {}
    for index, ((heavy, sentiment), count) in enumerate(kinds):
        if not count:
            continue
        rest = kinds[:index] + (((heavy, sentiment), count - 1),) + kinds[index + 1:]
        for (praise, complaint), share in tones(rest, slots - 1).items():
            key = (praise or sentiment == POSITIVE, complaint or sentiment == NEGATIVE)
            found[key] = found.get(key, 0.0) + heavy * count / total * share
    return found


def held(stars, praise, complaint):
    """The stars a review shows, given what its comment says."""
    return min(4, stars) if praise and complaint else max(3, stars) if praise else min(3, stars) if complaint else stars


def chances(place, history):
    """The probability of each number of stars for the review of a shipment with this history."""
    observations = history["observations"]
    counted = {}
    for found in observations:
        kind = (weight(found["aspect"]), found["sentiment"])
        counted[kind] = counted.get(kind, 0) + 1
    kinds, toned = tuple(sorted(counted.items())), {(False, False): 1 - place.text}
    for slots, share in MENTIONED.items():
        for key, part in tones(kinds, min(len(observations), slots)).items():
            toned[key] = toned.get(key, 0.0) + place.text * share * part
    found = dict.fromkeys(STARS, 0.0)
    for (praise, complaint), tone in toned.items():
        for coins, share in enumerate(drawn_stars(leaning(observations))):
            found[held(1 + coins, praise, complaint)] += tone * share
    return found


def rated(place, index, history, seed):
    """A shipment's stars as the producer draws its review with the stream under a seed."""
    return reviewed(place, index, history, seed)[0]


def reviewed(place, index, history, seed):
    """A shipment's stars and the aspects its comment mentions, as the producer draws its review with the stream
    under a seed: its own lines.

    The comment's observations as `carriers.drawn` reads them, one draw for
    the wording of each statement, then the producer's `stars` and the hold.
    """
    stream = place.producer.rng(seed, place.review(index)[1])
    chosen = []
    if stream.random() < place.text:
        observations = history["observations"]
        available = {found["aspect"]: found for found in observations}
        for _ in range(min(len(observations), stream.choices(list(MENTIONED), list(MENTIONED.values()))[0])):
            chosen.append(available.pop(stream.choices(list(available), [weight(name) for name in available])[0]))
        stream.shuffle(chosen)
        for _ in chosen:
            stream.random()
    signs = {found["sentiment"] for found in chosen}
    return (held(place.producer.stars(history["observations"], stream), POSITIVE in signs, NEGATIVE in signs),
            [found["aspect"] for found in chosen])


def said(place, happened, mentions):
    """Whether the comments on the topic's aspect, in its scope, are as the topic states them.

    A review counts when its shipment's history has an observation of the
    aspect and its comment mentions it; it takes the observation's side.
    """
    topic, seen = spoken(place.requirement), dict.fromkeys(carriers.SIGNS, 0)
    for history, mentioned in zip(happened, mentions):
        day = datetime.fromisoformat(history["receipt_at"]).date().isoformat()
        sign = next((found["sentiment"] for found in history["observations"] if found["aspect"] == topic["aspect"]), None)
        if (sign is not None and topic["aspect"] in mentioned and
                place.scope["shipping_class"] in ("all", history["shipping_class"]) and
                place.scope.get("date_from", "0001-01-01") <= day <= place.scope.get("date_to", "9999-12-31")):
            seen[sign] += 1
    return carriers.holds(topic, *(seen[sign] for sign in carriers.SIGNS))


def level(place, aspect, seed):
    """An aspect's level as the producer draws it with the stream under a seed."""
    return place.producer.rng(seed, place.quality[aspect][1]).choices(list(place.table), list(place.table.values()))[0]


def sums(shares):
    """The logarithm of the probability of each total of stars, for the reviews from the j-th on, for every j."""
    tails = [{0: 0.0}]
    for share in reversed(shares):
        after, found = tails[0], {}
        for total, value in after.items():
            for stars, part in share.items():
                if part > 0:
                    found.setdefault(total + stars, []).append(value + log(part))
        tails.insert(0, {total: joined(parts) for total, parts in found.items()})
    return tails


def average(total, count):
    """The average a carrier's summary publishes."""
    return round(total / count, 2)


def holds(requirement, levels, stars):
    limits = requirement.get("average_stars", {})
    return (all(levels[aspect] == value for aspect, value in requirement.get("levels", {}).items()) and
            limits.get("min", 1) <= average(sum(stars), len(stars)) <= limits.get("max", 5))


def model(world, requirement, api):
    """The level choices that can occur with the requirement, each with its shipments and the logarithm of its probability."""
    place = site(world, requirement, api)
    requirement, limits, found = place.requirement, place.requirement.get("average_stars", {}), []
    for choice in product(place.table, repeat=len(place.aspects)):
        levels = dict(zip(place.aspects, choice))
        if any(levels[aspect] != value for aspect, value in requirement.get("levels", {}).items()):
            continue
        happened = histories(place, levels)
        tails = sums([chances(place, history) for history in happened])
        totals = {total: value for total, value in tails[0].items()
                  if limits.get("min", 1) <= average(total, place.count) <= limits.get("max", 5)}
        if totals:
            found.append(SimpleNamespace(levels=levels, histories=happened, tails=tails, totals=totals,
                                         value=sum(log(place.table[name]) for name in choice) + joined(list(totals.values()))))
    if not found:
        raise ZeroMass("no_outcome", "No levels and stars of this carrier satisfy the requirement in this world")
    total = min(0.0, joined([row.value for row in found]))
    block = SimpleNamespace(site=place, alternatives=found, log_probability=total, probability=exp(total),
                            estimated="topic" in requirement, accepted=None, error=0.0)
    if block.estimated:
        key = world["world_id"], json.dumps(requirement, sort_keys=True)
        if key not in ESTIMATES:
            # The same draws for the same world and requirement, in this process and the next.
            rng = Random(api.native.digest({"world_id": world["world_id"], "requirement": requirement}))
            ESTIMATES[key] = 0
            for _ in range(PROPOSALS):
                drawn = draw(block, rng)
                ESTIMATES[key] += said(place, drawn.histories, drawn.mentions)
        block.accepted = ESTIMATES[key]
        if not block.accepted:
            # Not a proof that it cannot occur: callers report it as not found.
            raise ZeroMass("not_found", f"None of {PROPOSALS} samples of the carrier's reviews has the comments as stated")
        share = block.accepted / PROPOSALS
        block.log_probability += log(share)
        block.probability *= share
        block.error = block.probability * ((1 - share) / (share * PROPOSALS)) ** .5
    return block


def written(world, place):
    """What a world records of the block: the carrier's levels and its reviews' stars, by shipment."""
    corpus = world["carrier_evidence"]["private"]
    levels = next(row["aspect_levels"] for row in corpus["carrier_parameters"] if row["carrier_id"] == place.carrier_id)
    stars = {row["shipment_id"]: row["stars"] for row in corpus["reviews"]}
    return levels, [stars[row["shipment_id"]] for row in corpus["shipments"] if row["carrier_id"] == place.carrier_id]


def check(world, requirement, api):
    """Read the requirement off a world: the recorded levels and the average the carrier's summary publishes."""
    place = site(world, requirement, api)
    levels, stars = written(world, place)
    summary = next(row["summary"] for row in world["carrier_evidence"]["public"]["carriers"]
                   if row["carrier_id"] == place.carrier_id)
    if summary["average_stars"] != average(sum(stars), len(stars)) or summary["rating_count"] != len(stars):
        raise AssertionError("The carrier's summary is not counted from its reviews")
    if not holds(place.requirement, levels, stars):
        raise Unmet("The carrier's levels and average stars are not as required")
    return {"carrier_id": place.carrier_id, "aspect_levels": levels, "average_stars": summary["average_stars"],
            "rating_counts": summary["rating_counts"],
            # The comments by the native carrier-review task's own reference.
            **({"topic": carriers.check(world, spoken(place.requirement), api)} if "topic" in place.requirement else {})}


def draw(block, rng):
    """One sample of the block given the stars and levels: the levels, the histories under them, every review's stars,
    the seed of every stream that gives them, and what each review's comment mentions."""
    place = block.site
    chosen = pick_log(rng, block.alternatives, [row.value for row in block.alternatives])
    left, stars = pick_log(rng, list(chosen.totals), list(chosen.totals.values())), []
    for index, history in enumerate(chosen.histories):
        share, after = chances(place, history), chosen.tails[index + 1]
        options = [value for value in STARS if share[value] > 0 and left - value in after]
        stars.append(pick_log(rng, options, [log(share[value]) + after[left - value] for value in options]))
        left -= stars[-1]
    seeds, tries = {}, 0

    def redraw(key, reading, wanted):
        nonlocal tries
        for _ in range(TRIES):
            seeds[key], tries = rng.getrandbits(64), tries + 1
            if reading(seeds[key]) == wanted:
                return
        raise NumericalLimit("A draw of the block is too rare to reach by redrawing its stream")

    for aspect in place.aspects:
        redraw(place.quality[aspect], lambda seed: level(place, aspect, seed), chosen.levels[aspect])
    for index, history in enumerate(chosen.histories):
        redraw(place.review(index), lambda seed: rated(place, index, history, seed), stars[index])
    return SimpleNamespace(levels=chosen.levels, histories=chosen.histories, stars=stars, seeds=seeds, tries=tries,
                           mentions=[reviewed(place, index, history, seeds[place.review(index)])[1]
                                     for index, history in enumerate(chosen.histories)])


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    block = model(natural, requirement, api)
    place = block.site
    for samples in range(1, (TRIES if block.estimated else 1) + 1):
        chosen = draw(block, rng)
        if not block.estimated or said(place, chosen.histories, chosen.mentions):
            break
    else:
        raise NumericalLimit("Reviews whose comments are as stated are too rare to reach")
    stars, seeds, tries = chosen.stars, chosen.seeds, chosen.tries
    before = written(natural, place)

    def record(world):
        if written(world, place) != (chosen.levels, stars):
            raise streams.PlanMismatch(f"{place.carrier_id}: producer recorded other levels or stars than planned")
        return {"method": "one_of_level_choices_then_exact_total_then_per_review_rejection" + (
                    "_then_rejection_on_comments" if block.estimated else ""),
                "requirement": place.requirement, "natural_world_id": natural["world_id"],
                **({"probability_is_estimated": True, "probability_standard_error": block.error, "proposals": PROPOSALS,
                    "proposals_accepted": block.accepted, "block_samples_for_this_sample": samples} if block.estimated else {}),
                "probability_given_upstream": block.probability, "log_probability_given_upstream": block.log_probability,
                "level_choices_modelled": len(block.alternatives), "shipments": place.count, "stream_redraws": tries,
                "natural": {"aspect_levels": before[0], "average_stars": average(sum(before[1]), len(before[1]))},
                "steered": {"aspect_levels": chosen.levels, "average_stars": average(sum(stars), len(stars))},
                "distribution_claim": "The carrier's four quality levels and the review of every one of its shipments "
                                      "are sampled from their distribution given the requirement: the levels in "
                                      "proportion to their chance times the chance of the required average under "
                                      "them, then the total of stars exactly, then each review by redrawing its "
                                      "stream until it gives its stars. The shipments' history streams are the "
                                      "seed's own, read under the sampled levels: the sample and its probability "
                                      "are given those streams, which the requirement depends on. Every other draw "
                                      "is the seed's own too, and the requirement depends on none of them. Use the "
                                      "probability as the importance weight across seeds."}

    return Step(script={key: streams.Reseeded(seed) for key, seed in seeds.items()}, probability=block.probability,
                log_probability=block.log_probability, error=block.error, estimated=block.estimated,
                **vars(footprint(natural, requirement, api)), record=record,
                check=lambda world: check(world, requirement, api))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def trial(natural, requirement, api):
    """The levels and every review's stars from the producer's own lines under another seed; independent of the model."""
    place = site(natural, requirement, api)

    def reading(seed):
        levels = {aspect: level(place, aspect, seed) for aspect in place.aspects}
        return levels, [rated(place, index, history, seed) for index, history in enumerate(histories(place, levels))]

    def met(seed):
        levels = {aspect: level(place, aspect, seed) for aspect in place.aspects}
        happened = histories(place, levels)
        found = [reviewed(place, index, history, seed) for index, history in enumerate(happened)]
        return holds(place.requirement, levels, [stars for stars, _ in found]) and (
            "topic" not in place.requirement or said(place, happened, [mentioned for _, mentioned in found]))

    return SimpleNamespace(
        keys=set(place.quality.values()) | {place.review(index) for index in range(place.count)},
        **vars(footprint(natural, requirement, api)), reading=reading, holds=met,
        recorded=lambda world: written(world, place),
        satisfied=lambda world: satisfied(world, requirement, api))


def satisfied(world, requirement, api):
    try:
        return bool(check(world, requirement, api))
    except Unmet:
        return False


def empirical(natural, requirement, api, trials, first_seed):
    """How often the requirement holds under other seeds."""
    found = trial(natural, requirement, api)
    return sum(found.holds(seed) for seed in range(first_seed, first_seed + trials))
