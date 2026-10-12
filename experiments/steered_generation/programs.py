"""What a product package's review program says about one topic, read exactly.

Outside the pilot concepts a review comes from the review program of the
product's package: a list of steps, each a draw or a value derived from
earlier ones, run once per review under that review's own seed; then one
statement for every pool of the program's language whose condition holds. A
review reports a topic favourably when a positive pool of that topic holds
for it, unfavourably when a negative one does.

The probability of each, together with each star rating, is a sum over the
outcomes of the rating's draw and of the draws those conditions depend on,
directly or through other steps; no other step is looked at. The program's
own code resolves every draw's parameters and
evaluates every derived value and condition (`resolve`, `_eval`); what is
written here is only the probability of each outcome of a resolved draw: a
weighted or uniform choice, the star rating, the set of topics, and a normal
draw that the program reads through one threshold.

The producer may wrap a package's review program in checks that refuse
anything but a whole sample. The reading here runs on a plain copy made from
the wrapped program's own document, which draws from the same streams; a
world whose recorded reviews that copy does not reproduce is refused, and a
steered pass whose reviews differ from the copy's fails.
"""
from collections import defaultdict
from copy import deepcopy
from importlib import import_module
import json
from math import erfc, exp, fsum, lgamma, log, sqrt
import re
import sys
from types import SimpleNamespace

from . import reviews, streams

# A derived value that reads a normal draw through one threshold.
THRESHOLD = re.compile(r"\s*([A-Za-z_][\w.]*)\s*>=\s*(\d+(?:\.\d+)?)\s*")
# Review programs rebuilt from a world, by the producer module, the world's seed and the product.
BUILT = {}


def unmodelled(what):
    return ValueError("Not modelled: " + what)


def touches(path, other):
    """Whether two dotted paths name the same value or one inside the other."""
    return path == other or path.startswith(other + ".") or other.startswith(path + ".")


def program(world, item, api):
    """The review program the producer ran for a product, as a plain copy, with the product's entities.

    The producer builds a package from the brand and the product, and some
    packages hand out their review program only after manufacturing; so the
    product is manufactured again by the producer's own call, which must
    return the entities the world records.
    """
    export, public = api.package_export, item["public"]
    seed, entities = api.commerce.seed_for(world["seed"], public["product_id"]), item["private"]["sample"]["entities"]
    key = (id(export), world["seed"], public["product_id"])
    if key in BUILT and BUILT[key].entities == entities:
        return BUILT[key]
    brand = next((row for row in world["brands"] if row["brand_id"] == public["brand_id"]), None)
    if brand is None:
        raise ValueError("The product's brand is not in the world")
    caught, real = [], export._package

    def watched(concept_id, inputs):
        caught.append(real(concept_id, inputs))
        return caught[-1]

    export._package = watched
    try:
        again = export.sample(seed, public["concept_id"], brand, public["product_id"], earlier=(), review_count=0)
    finally:
        export._package = real
    if len(caught) != 1 or again["private"]["sample"]["entities"] != entities:
        raise ValueError("The product could not be manufactured again as the world records it")
    stage = caught[0].make_review() if hasattr(caught[0], "make_review") else caught[0].programs["review"]
    while len(BUILT) >= 8:
        del BUILT[next(iter(BUILT))]
    BUILT[key] = SimpleNamespace(
        twin=export.ProductPackage(deepcopy(stage.document)), entities=deepcopy(entities), cells={},
        module=sys.modules[export.ProductPackage.__module__])
    return BUILT[key]


def site(world, item, api, native, **common):
    """Where one product's review draws sit, and what its review program reads them with."""
    found, topic = program(world, item, api), common["requirement"]["topic"]
    twin, pools = found.twin, {reviews.POSITIVE: [], reviews.NEGATIVE: []}
    for pool in twin.document.get("language", []):
        meaning = pool.get("meaning")
        # The native review task's own test of which statements report the topic.
        if (type(meaning) is dict and meaning.get("kind") == "customer_experience" and
                meaning.get("source") == "first_hand" and meaning.get("aspect") == topic["aspect"] and
                native.context_matches(meaning.get("context"), topic["context"])):
            if meaning.get("polarity") not in pools:
                raise unmodelled("a statement about the topic that is neither for nor against")
            pools[meaning["polarity"]].append(pool)
    read = set().union(*(twin.expression(pool["when"]).references for rows in pools.values() for pool in rows
                         if "when" in pool))
    # The review's stars are the one rating draw's, whatever else reads them.
    rating = [step for step in twin.document.get("steps", []) if step.get("sample") == "rating"]
    if len(rating) != 1 or rating[0]["target"] not in ("review.rating", "review.stars") or "{" in rating[0].get("stream", ""):
        raise unmodelled("a review whose stars are not one rating draw")
    steps, needed = [], read | {rating[0]["target"]}
    for step in reversed(twin.document.get("steps", [])):
        if "for_each" in step or "emit" in step:
            raise unmodelled("a review program with loops")
        if any(touches(step["target"], path) for path in needed):
            steps.append(step)
            needed |= twin._step_refs(step)
    steps.reverse()
    bounds, block, drawn = {}, set(), []
    for step in steps:
        if "derive" in step:
            continue
        name = step.get("stream", step["id"])
        if "{" in name or step["sample"] not in ("weighted_choice", "uniform_choice", "rating", "review_topics", "normal"):
            raise unmodelled("a review step drawn by " + step["sample"])
        drawn.append(step["id"])
        if step["sample"] == "review_topics":
            block |= {name + "/length", name + "/value"} | {
                f"{name}/other/{slot}" for slot in range(max(map(int, step["length_weights"])))}
        else:
            block.add(name)
        if step["sample"] == "normal":
            users = [other for other in steps if other is not step and
                     any(touches(step["target"], path) for path in twin._step_refs(other))]
            match = THRESHOLD.fullmatch(users[0].get("derive", "")) if len(users) == 1 else None
            if (match is None or match[1] != step["target"] or "when" in users[0] or
                    "applicable_when" in twin.fields[users[0]["target"]] or
                    any(touches(step["target"], path) for path in read)):
                raise unmodelled("a continuous draw the statements read other than through one threshold")
            bounds[step["id"]] = (users[0]["target"], float(match[2]))
    return SimpleNamespace(
        **common, reader=sys.modules[__name__], program=found, pools=pools, steps=steps, bounds=bounds,
        block=frozenset(block), drawn=frozenset(drawn), rating=rating[0],
        seeds=[streams.program_review_seed(common["seed"], index) for index in range(common["count"])])


def keys(place, index):
    """The streams of one review that decide its stars and what it says about the topic."""
    return [(streams.PROGRAM, place.seed, index, name) for name in sorted(place.block)]


def rating_key(place, index):
    """The stream of one review that draws its star rating."""
    return (streams.PROGRAM, place.seed, index, place.rating.get("stream", place.rating["id"]))


def stars(execution, concentration):
    """The probability of each star rating: one more than a beta-binomial count of four."""
    mean = .05 + .9 * execution
    a, b = mean * concentration, (1 - mean) * concentration
    beta = lambda x, y: lgamma(x) + lgamma(y) - lgamma(x + y)
    return {1 + hits: exp(log((1, 4, 6, 4, 1)[hits]) + beta(a + hits, b + 4 - hits) - beta(a, b)) for hits in range(5)}


def topic_sets(policy, eligible, lengths):
    """The probability of each set of topics a comment can be about.

    The comment's length is a weighted choice; in a comment, value comes
    first with its own probability where it is eligible, and the remaining
    places are weighted draws without replacement among the other topics.
    """
    others = {name: weight for name, weight in policy["effective_weights"].items() if name != "value"}
    value = min(1.0, max(0.0, policy["value_probability_given_comment"])) if "value" in eligible else 0.0
    total, found = fsum(lengths.values()), defaultdict(list)

    def fill(chosen, left, slots, mass):
        if not slots:
            found[tuple(sorted(chosen))].append(mass)
            return
        weight = fsum(left.values())
        for name, own in left.items():
            if own > 0:
                fill([*chosen, name], {k: v for k, v in left.items() if k != name}, slots - 1, mass * own / weight)

    for slots, weight in lengths.items():
        if weight <= 0:
            continue
        if not int(slots):
            found[()].append(weight / total)
            continue
        if value > 0:
            fill(["value"], others, int(slots) - 1, weight / total * value)
        if value < 1:
            fill([], others, int(slots), weight / total * (1 - value))
    return {topics: fsum(parts) for topics, parts in found.items()}


def tails(params, bound):
    """The probabilities that a resolved normal draw ends at or above a bound, and below it.

    The program clips the draw to its range and rounds it to a grid before
    anything reads it, so the draw's own bound is the smallest number whose
    rounding reaches the stated one; bisection finds it among the floats.
    """
    low, high, step = params["min"], params["max"], params.get("round_to")
    if params.get("bounds_mode") != "clip" or params["sd"] <= 0 or not low < high:
        raise unmodelled("a normal draw that is not clipped to a range")
    ended = (lambda x: round(x / step) * step) if step is not None else (lambda x: x)
    if ended(low) >= bound:
        return 1.0, 0.0
    if ended(high) < bound:
        return 0.0, 1.0
    while True:
        middle = (low + high) / 2
        if not low < middle < high:
            break
        low, high = (low, middle) if ended(middle) >= bound else (middle, high)
    distance = (high - params["mean"]) / (params["sd"] * sqrt(2))
    return erfc(distance) / 2, erfc(-distance) / 2


def outcomes(place, step, context):
    """The values a resolved draw can take, with the probability of each."""
    twin = place.program.twin
    params = twin.resolve(step, context)
    if step["sample"] == "weighted_choice":
        for name, share in params["probabilities"].items():
            if share > 0:
                yield (twin._eval(params["values_expr"][name], context) if "values_expr" in params
                       else deepcopy(params.get("values", {}).get(name, name))), share
    elif step["sample"] == "uniform_choice":
        options = params["resolved_values"]
        if type(options) is not list or not options:
            raise unmodelled("a uniform choice among nothing")
        for option in options:
            yield deepcopy(option), 1 / len(options)
    elif step["sample"] == "rating":
        yield from stars(params["execution"], params["concentration"]).items()
    else:
        eligible = twin._eval(params["eligible_from"], context)
        sampling = import_module(place.program.module.__package__ + ".review_topic_sampling")
        policy = sampling.topic_policy(
            positioning=twin._eval(params["positioning_from"], context), execution=params["execution"],
            eligible=eligible, length_weights=params["length_weights"], config=params.get("topic_config"),
            topic_multipliers=params.get("topic_multipliers"))
        for topics, share in topic_sets(policy, eligible, params["length_weights"]).items():
            yield list(topics), share


def told(place, entities):
    """What a review with these entities says about the topic, by the pools that hold for it."""
    twin = place.program.twin
    sides = {side: any("when" not in pool or twin._eval(pool["when"], entities) for pool in rows)
             for side, rows in place.pools.items()}
    if all(sides.values()):
        raise unmodelled("a comment both for and against the topic")
    return next((side for side, holds in sides.items() if holds), reviews.REST)


def cells(place):
    """The probability that one review has each star rating and is positive, negative or neither about the topic.

    Walks the steps the rating and the topic's statements depend on in the
    program's order, branching on every outcome of a draw, as `sample` runs
    them for one.
    """
    name = json.dumps(place.requirement["topic"], sort_keys=True)
    if name in place.program.cells:
        return dict(place.program.cells[name])
    twin, module = place.program.twin, place.program.module
    context, found = deepcopy(place.program.entities), defaultdict(list)
    for path, definition in twin.fields.items():
        if "constant" in definition:
            module.set_path(context, path, deepcopy(definition["constant"]))

    def walk(position, mass, decided):
        if position == len(place.steps):
            found[module.get_path(context, place.rating["target"]), told(place, context)].append(mass)
            return
        step = place.steps[position]
        target, ahead = step["target"], position + 1
        conditions = [text for text in (twin.fields[target].get("applicable_when"), step.get("when")) if text is not None]
        if conditions and not all(twin._eval(text, context) for text in conditions):
            module.set_path(context, target, module.NOT_APPLICABLE)
            walk(ahead, mass, decided)
        elif "derive" in step:
            module.set_path(context, target, decided[target] if target in decided
                            else twin._eval(step["derive"], context))
            walk(ahead, mass, decided)
        elif step["sample"] == "normal":
            # The draw itself is never set: only its threshold's side is read.
            later, bound = place.bounds[step["id"]]
            for side, share in zip((True, False), tails(twin.resolve(step, context), bound)):
                if share > 0:
                    walk(ahead, mass * share, {**decided, later: side})
        else:
            for value, share in outcomes(place, step, context):
                module.set_path(context, target, value)
                walk(ahead, mass * share, decided)

    walk(0, 1.0, {})
    if not set(rating for rating, _ in found) <= set(range(1, 6)):
        raise unmodelled("a review without a star rating from one to five")
    place.program.cells[name] = {(rating, side): fsum(found.get((rating, side), [])) for rating in range(1, 6)
                                 for side in (reviews.POSITIVE, reviews.NEGATIVE, reviews.REST)}
    return dict(place.program.cells[name])


def shares(place):
    """The probability that one review is positive, negative or neither about the topic."""
    return reviews.marginal(cells(place))


def draws(place, trace):
    """A review's block draws as its trace records them."""
    return tuple((row["id"], json.dumps(row.get("outcome"), sort_keys=True)) for row in trace
                 if row["id"] in place.drawn)


def redrawn(place, index, fresh=None, stars=None):
    """One review as the program draws it with its block streams opened under a fresh seed, or as the seed draws it.

    The rating's stream opens under `stars` where that is given. Returns the
    block's draws, what the review says about the topic and its star rating.
    """
    twin, own = place.program.twin, place.seeds[index]
    natural, rating = type(twin).rng, rating_key(place, index)[-1]

    def rng(seed, key):
        planned = fresh is not None and seed == own and key in place.block
        return natural(twin, streams.program_seed(fresh if stars is None or key != rating else stars, seed)
                       if planned else seed, key)

    twin.rng = rng
    try:
        review = twin.sample(own, inputs=deepcopy(place.program.entities))
    finally:
        del twin.rng
    return (draws(place, json.loads(json.dumps(review["trace"]))), told(place, review["entities"]),
            place.program.module.get_path(review["entities"], place.rating["target"]))


def said(place, found):
    return found[1]


def rated(place, found):
    return found[2]


def written(world, place):
    """What a world records of each review's block draws and of what it says, in `redrawn`'s shape."""
    item = next(p for p in world["products"] if p["public"]["product_id"] == place.product_id)
    names = {side: {pool["id"] for pool in rows} for side, rows in place.pools.items()}
    rows = []
    for row in item["reviews"]:
        stated = {statement["meaning_id"] for statement in row["statements"]}
        rows.append((draws(place, row["private_trace"]),
                     next((side for side, own in names.items() if own & stated), reviews.REST), row["rating"]))
    return rows


def reads(world, place):
    """Refuse a natural world whose reviews are not what this reading draws under the world's seed."""
    if written(world, place) != [redrawn(place, index) for index in range(place.count)]:
        raise ValueError("The product's recorded reviews are not what its review program draws under the world's seed")
