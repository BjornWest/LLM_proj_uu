"""Conditional sampling of what happened to a carrier's shipments and what its reviews say of it.

The same requirement as `carriers` (a carrier, an aspect of the native
carrier-review task, the task's scope, and a verdict or numbers of positive
and negative comments), with the shipments' histories inside the block. Where
`carriers` keeps what happened and steers which reviews mention it, this
block redraws every shipment of the carrier, history and review, so a carrier
whose handovers all went well can come out with complaints about them.

It covers the two aspects whose observation has a short story in the
producer: `handoff` and `punctuality`. Both are observed exactly when a
shipment is not collected and its first home-delivery attempt does not fail
(a parcel left in the lobby is the negative handoff). Which service the shipment used, whether it
went to a collection point, whether the first attempt failed, the dates and
whether the promise was kept are each a draw of fixed probability in
`carrier_service_pilot.model.history`; `shares` multiplies them out, with the
review's chance of mentioning the aspect, into the probability that one
shipment yields a positive comment in scope, a negative one, or neither. A
carrier's shipments draw independently and alike, so the counts are
multinomial.

A sample picks the counts, places them on shipments at random, and redraws
each shipment's history and review streams under fresh seeds until the
producer's own `history` and the review read from it give the shipment's
class. Nothing of the carrier's own shipments is kept. The carrier's quality
levels, its policy and services are upstream.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from math import exp
import sys
from types import SimpleNamespace

from . import blocks, carriers, streams
from .blocks import NumericalLimit, Step
from .cheapest import pick_log
from .prices import ZeroMass
from .reviews import NEGATIVE, POSITIVE, REST, TRIES, multinomial

VERSION = "steered-carrier-shipments-topic-v1"
MODELLED = ("handoff", "punctuality")
# The producer's own figures for a shipment's history, which it does not keep in its configuration: the share
# of the first service, of collection, of a retailer's delay, of a recipient at home, of permission to leave the
# parcel, of the ways into the building and of a code given. The readings of redrawn streams check them.
FIRST_SERVICE, COLLECTED, DELAYED, AT_HOME, PERMITTED, AUTHORISED, CODE, CODE_GIVEN = .7, .25, .15, .9, .5, .25, .35, .8
DAYS_BACK = range(10, 91)


def resolve(requirement):
    requirement = carriers.resolve(requirement, VERSION)
    if requirement["aspect"] not in MODELLED:
        raise ValueError("Shipments are modelled for the aspects " + " and ".join(MODELLED))
    return requirement


def footprint(world, requirement, api):
    """What the block decides: the carrier's shipments and its reviews."""
    carrier = resolve(requirement)["carrier_id"]
    carriers.footprint(world, {**requirement, "schema": carriers.VERSION}, api)
    return SimpleNamespace(writes={("carrier_reviews", "", carrier), ("carrier_shipments", "", carrier)}, reads=set())


def site(world, requirement, api):
    """The carrier's shipments, and everything the producer's `history` reads for them."""
    requirement = resolve(requirement)
    below = carriers.site(world, {**requirement, "schema": carriers.VERSION}, api)
    corpus, producer = world["carrier_evidence"], below.producer
    addresses = sys.modules[producer.address_world.__module__]
    base = producer.address_world(corpus["seed"], corpus["city"]["city_id"])
    if base["world_id"] != corpus["private"]["source_address_world_id"]:
        raise ValueError("The carrier corpus was not drawn from the address world this producer makes")
    experience = json.loads(addresses.PLAN.read_text())["carrier_review_backlog"]["experience_sampling_proposal"]
    carrier = requirement["carrier_id"]
    policy = next(row for row in corpus["public"]["carriers"] if row["carrier_id"] == carrier)
    if len(policy["services"]) != 2:
        raise ValueError("Not modelled: a carrier without exactly two services")
    return SimpleNamespace(
        requirement=requirement, carrier_id=carrier, aspect=requirement["aspect"], seed=corpus["seed"],
        text=corpus["parameters"]["text_probability"], count=corpus["parameters"]["shipments_per_carrier"],
        producer=producer, base=base, policy=policy, rates=experience["success_probabilities_by_aspect_level"],
        levels=next(row["aspect_levels"] for row in corpus["private"]["carrier_parameters"] if row["carrier_id"] == carrier),
        scope=below.native.resolve(carriers.task(world, {**requirement, "schema": carriers.VERSION})), below=below,
        keys=lambda index: [(streams.CARRIER, f"{producer.VERSION}/{part}/{carrier}-shipment-{index:04d}")
                            for part in ("history", "review")])


def in_scope(place, shipping_class, day):
    scope = place.scope
    return (scope["shipping_class"] in ("all", shipping_class) and
            scope.get("date_from", "0001-01-01") <= day <= scope.get("date_to", "9999-12-31"))


@contextmanager
def readings(place):
    """The producer's own `history` and review lines for the carrier's shipments, with streams under a chosen seed.

    Yields `read(index, seed)`: the history of that shipment and the aspects
    its review mentions, as the producer draws them when the shipment's two
    streams open under the seed (the producer's own seed for None).
    """
    natural, chosen = place.producer.rng, [None]
    place.producer.rng = lambda seed, key: natural(seed if chosen[0] is None else chosen[0], key)

    def read(index, seed):
        chosen[0] = seed
        history = place.producer.history(place.base, place.policy, place.levels, index, place.rates)
        shipment = SimpleNamespace(history=history, key=(streams.CARRIER, f"{place.producer.VERSION}/review/{history['shipment_id']}"))
        return history, carriers.drawn(place, shipment, place.seed if seed is None else seed)

    try:
        yield read
    finally:
        place.producer.rng = natural


def said(place, found):
    """What a shipment with this history and review adds to the task's count: positive, negative, or nothing."""
    history, mentioned = found
    day = datetime.fromisoformat(history["receipt_at"]).date().isoformat()
    sign = next((row["sentiment"] for row in history["observations"] if row["aspect"] == place.aspect), None)
    if sign is None or place.aspect not in mentioned or not in_scope(place, history["shipping_class"], day):
        return REST
    return sign


def leads(place, service):
    """Days from the planned handover to a delivered shipment's first attempt, with whether it is on the promised day.

    Maps (days, on time) to probability: the retailer's delay of a day or two,
    the service's transit days, the day chosen where the recipient chooses
    one, and one to three days late when the promise is not kept.
    """
    timely = place.rates["arrival_on_promised_day"][place.levels["punctuality"]]
    source = next(s for s in place.base["services"] if s["service_id"] == service["service_id"])
    transit = max(1, 1 + source["transit_offset_days"]) + (service["shipping_class"] == "bulky")
    offsets = range(3) if service["scheduling"] != "carrier_assigned" else (0,)
    found = Counter()
    for delay, delayed in ((0, 1 - DELAYED), (1, DELAYED / 2), (2, DELAYED / 2)):
        for offset in offsets:
            for late, lateness in ((0, timely), (1, (1 - timely) / 3), (2, (1 - timely) / 3), (3, (1 - timely) / 3)):
                found[delay + transit + offset + late, not late] += delayed * lateness / len(offsets)
    return found


def dated(place, service):
    """When a delivered shipment's first attempt falls, as (days after the quote date, on time) to probability.

    The planned handover is 10 to 90 days back, each day alike.
    """
    found = Counter()
    for (lead, on_time), mass in leads(place, service).items():
        for back in DAYS_BACK:
            found[lead - back, on_time] += mass / len(DAYS_BACK)
    return found


def shares(place):
    """The probability that one shipment yields a positive comment on the aspect in scope, a negative one, or neither.

    Per service: the shipment is not collected and its first attempt does not
    fail (the recipient is at home, or the parcel may be left and the carrier
    gets in); it arrives on the promised day or one to three days late; the
    review is dated by the first attempt, which is the handover day, the
    retailer's delay, the transit days, the day chosen and the lateness after
    a start 10 to 90 days back. On time is the punctuality observation; the
    handover promise is kept or not independently of all that.
    """
    quote = datetime.fromisoformat(place.base["quote_as_of"]).date()
    kept = place.rates["promised_handoff_complied_with"][place.levels["handoff"]]
    points = [p for p in place.base["collection_points"] if p["point_id"] in place.policy["collection_point_ids"]]
    total = {POSITIVE: 0.0, NEGATIVE: 0.0}
    for chance, service in zip((FIRST_SERVICE, 1 - FIRST_SERVICE), place.policy["services"]):
        regular = service["shipping_class"] == "regular"
        delivered = (1 - (COLLECTED if regular and points else 0)) * (
            AT_HOME + (1 - AT_HOME) * (PERMITTED if service["unattended_allowed"] else 0) * (AUTHORISED + CODE * CODE_GIVEN))
        within = {True: 0.0, False: 0.0}
        for (days, on_time), mass in dated(place, service).items():
            if in_scope(place, service["shipping_class"], (quote + timedelta(days=days)).isoformat()):
                within[on_time] += mass
        aspects = ["punctuality"] + ["window"] * (service["scheduling"] == "choose_day_and_window") + [
            "handoff", "handling", "tracking"] + ["notification_" + kind for kind, offered in service["notifications"].items()
                                                   if offered and kind != "failed_attempt"]
        told = chance * delivered * carriers.mention(place.text, aspects, place.aspect)
        if place.aspect == "handoff":
            total[POSITIVE] += told * (within[True] + within[False]) * kept
            total[NEGATIVE] += told * (within[True] + within[False]) * (1 - kept)
        else:
            total[POSITIVE] += told * within[True]
            total[NEGATIVE] += told * within[False]
    return {**total, REST: 1 - total[POSITIVE] - total[NEGATIVE]}


def holds(requirement, positive, negative):
    """As the native task judges it; these aspects have no neutral observation."""
    return carriers.holds(requirement, positive, negative, 0)


def model(world, requirement, api):
    """The counts that satisfy the requirement, with the logarithm of each one's probability."""
    place = site(world, requirement, api)
    share = shares(place)
    found = multinomial(place.count, share, lambda positive, negative: holds(place.requirement, positive, negative))
    if found is None:
        raise ZeroMass("no_outcome", "No counts of this carrier's reviews satisfy the requirement in this world")
    return SimpleNamespace(site=place, shares=share, log_terms=found[0], log_probability=found[1],
                           probability=exp(found[1]))


def written(world, place):
    """What a world records of the carrier's shipments: each history and the aspects its review mentions."""
    corpus = world["carrier_evidence"]["private"]
    reviews = {row["shipment_id"]: row for row in corpus["reviews"]}
    return [(history, [found["aspect"] for found in reviews[history["shipment_id"]]["statements"]])
            for history in corpus["shipments"] if history["carrier_id"] == place.carrier_id]


def counted(place, rows):
    seen = Counter(said(place, row) for row in rows)
    return seen[POSITIVE], seen[NEGATIVE]


def check(world, requirement, api):
    """Read the requirement off a world with the native carrier-review task's reference."""
    place = site(world, requirement, api)
    found = carriers.check(world, {**place.requirement, "schema": carriers.VERSION}, api)
    if (found["counts"][POSITIVE], found["counts"][NEGATIVE]) != counted(place, written(world, place)) or found["counts"]["neutral"]:
        raise AssertionError("The native carrier-review task and the recorded shipments disagree about the counts")
    return found


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    block = model(natural, requirement, api)
    place = block.site
    positive, negative = pick_log(rng, list(block.log_terms), list(block.log_terms.values()))
    order = rng.sample(range(place.count), place.count)
    wanted = {index: POSITIVE if rank < positive else NEGATIVE if rank < positive + negative else REST
              for rank, index in enumerate(order)}
    seeds, tries = {}, 0
    with readings(place) as read:
        for index in range(place.count):
            for _ in range(TRIES):
                seeds[index], tries = rng.getrandbits(64), tries + 1
                if said(place, read(index, seeds[index])) == wanted[index]:
                    break
            else:
                raise NumericalLimit("A shipment's class is too rare to reach by redrawing the shipment")
    script = {key: streams.Reseeded(seeds[index]) for index in range(place.count) for key in place.keys(index)}

    def record(world):
        with readings(place) as read:
            planned = [read(index, seeds[index]) for index in range(place.count)]
        if written(world, place) != planned:
            raise streams.PlanMismatch(f"{place.carrier_id}: producer recorded other shipments than planned")
        return {"method": "exact_counts_then_per_shipment_rejection", "requirement": place.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": block.probability,
                "log_probability_given_upstream": block.log_probability,
                "shipment_class_probabilities": block.shares, "shipments": place.count, "shipment_redraws": tries,
                "natural_counts": dict(zip((POSITIVE, NEGATIVE), counted(place, written(natural, place)))),
                "steered_counts": {POSITIVE: positive, NEGATIVE: negative},
                "distribution_claim": "The history and the review of every shipment of this carrier are sampled from "
                                      "their distribution given the requirement: the counts exactly, then each "
                                      "shipment by redrawing its two streams until it is of its class. The carrier's "
                                      "quality levels, policy and services and every other draw are the seed's own; "
                                      "the requirement depends on no other draw. Use the probability as the "
                                      "importance weight across seeds."}

    return Step(script=script, probability=block.probability, log_probability=block.log_probability,
                **vars(footprint(natural, requirement, api)), record=record,
                check=lambda world: check(world, requirement, api))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def trial(natural, requirement, api):
    """Every shipment of the carrier from the producer's own lines under another seed; independent of the model."""
    place = site(natural, requirement, api)

    def reading(seed):
        with readings(place) as read:
            return [read(index, seed) for index in range(place.count)]

    return SimpleNamespace(
        keys={key for index in range(place.count) for key in place.keys(index)},
        **vars(footprint(natural, requirement, api)), reading=reading,
        counts=lambda seed: counted(place, reading(seed)),
        holds=lambda seed: holds(place.requirement, *counted(place, reading(seed))),
        recorded=lambda world: written(world, place),
        satisfied=lambda world: satisfied(world, requirement, api))


def satisfied(world, requirement, api):
    try:
        return bool(check(world, requirement, api))
    except blocks.Unmet:
        return False


def empirical(natural, requirement, api, trials, first_seed):
    """How often the requirement holds under other seeds, by (positive, negative) counts."""
    found, stated = trial(natural, requirement, api), resolve(requirement)
    seen = (found.counts(seed) for seed in range(first_seed, first_seed + trials))
    return Counter(row for row in seen if holds(stated, *row))
