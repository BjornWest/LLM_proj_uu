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
written here is the order of the steps, as `sample` runs them, and the
probability of each outcome of a resolved draw: a weighted or uniform choice,
a whole number from a range, the star rating, the set of topics, and a normal
draw that the program reads only through `>=` thresholds (found on the
expressions as the program parses them). A loop is followed where it only
derives and collects values.

The producer may wrap a package's review program in checks that refuse
anything but a whole sample. The reading here runs on a plain copy made from
the wrapped program's own document, which draws from the same streams; a
world whose recorded reviews that copy does not reproduce is refused, and a
steered pass whose reviews differ from the copy's fails. So is a world where
following the steps here from a review's recorded draws gives another rating
or says another thing than the review does.
"""
import ast
from collections import defaultdict
from copy import deepcopy
from importlib import import_module
import json
from math import erfc, fsum, prod, sqrt
import sys
from types import SimpleNamespace

from . import reviews, streams

# The sizes of number the arithmetic here is written for. A normal draw's range, mean, spread, grid and thresholds
# within these never overflow a product, quotient or midpoint below, and neither do the products of four factors
# that a rating's concentration within its own enters. Anything outside is refused, not approximated.
SMALL, LARGE, CONCENTRATIONS = 1e-150, 1e150, (1e-60, 1e60)
# Review programs rebuilt from a world, by the producer module, the world's seed and the product.
BUILT = {}


def unmodelled(what):
    return ValueError("Not modelled: " + what)


def touches(path, other):
    """Whether two dotted paths name the same value or one inside the other."""
    return path == other or path.startswith(other + ".") or other.startswith(path + ".")


def inner(step):
    """The steps a loop runs for each of its values; none for a step that is not a loop."""
    return step["steps"] if "for_each" in step else []


def written_by(step):
    """The paths a step, or a loop with its steps, writes."""
    return [row["target"] for row in inner(step)] + [step["for_each"]["binding"]] if inner(step) else [step["target"]]


def expressions(twin, step):
    """Every expression a step, or a loop with its steps, evaluates, with the conditions of the fields it writes."""
    texts = []

    def one(row):
        texts.extend(row[key] for key in ("derive", "when", "weights_from", "values_from", "eligible_from",
                                          "count_from", "positioning_from") if key in row)
        texts.extend(row[key] for key in ("min", "max", "mean", "sd", "round_to", "execution", "concentration")
                     if isinstance(row.get(key), str))
        texts.extend(adjustment["when"] for adjustment in row.get("adjustments", []))
        for case in row.get("cases", []):
            one(case)
        texts.extend([*row.get("values_expr", {}).values(), *row.get("emit", {}).values()])
        if row.get("target") and "applicable_when" in twin.fields[row["target"]]:
            texts.append(twin.fields[row["target"]]["applicable_when"])

    for row in [step, *inner(step)]:
        one(row)
    return texts + [step["for_each"]["from"]] if "for_each" in step else texts


def read_by(twin, step):
    """The paths a step, or a loop with its steps, reads: the program's own account, which `expressions` must match.

    The match is a guard against an expression this module does not list, not
    a proof that it lists them all: one that reads only paths another
    already reads would not show.
    """
    found = set().union(twin._step_refs(step), *(twin._step_refs(row) for row in inner(step)))
    found = found | twin.expression(step["for_each"]["from"]).references if "for_each" in step else found
    if found != set().union(*(twin.expression(text).references for text in expressions(twin, step))):
        raise unmodelled("a step that reads in a way this reading does not look at")
    return found


def thresholds(twin, text, target):
    """The numbers an expression compares a path with by `>=`; None where it mentions the path in any other way.

    Read on the expression as the program parses it: the path alone on the
    left, one `>=`, a number written out on the right. The numbers are the
    program's own values, whole or not.
    """
    found = []

    def path(node):
        names = []
        while isinstance(node, ast.Attribute):
            names.append(node.attr)
            node = node.value
        return ".".join(reversed([*names, node.id])) if isinstance(node, ast.Name) else None

    def plain(node):
        if isinstance(node, (ast.Name, ast.Attribute)) and path(node) is not None:
            return not touches(path(node), target)
        if (isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.GtE) and
                path(node.left) == target and isinstance(node.comparators[0], ast.Constant) and
                type(node.comparators[0].value) in (int, float)):
            # The number as the program has it: a whole number is compared exactly, and a float of it may differ.
            found.append(node.comparators[0].value)
            return True
        return all([plain(child) for child in ast.iter_child_nodes(node)])

    return found if plain(twin.expression(text).tree) else None


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
        if any(touches(target, path) for target in written_by(step) for path in needed):
            if any("for_each" in row or "sample" in row for row in inner(step)):
                raise unmodelled("a loop that draws, or holds another loop")
            if any("emit" in row and ("when" in row or "applicable_when" in twin.fields[row["target"]])
                   for row in (inner(step) or [step])):
                raise unmodelled("a collected value under a condition of its own")
            steps.append(step)
            needed |= read_by(twin, step)
    steps.reverse()
    bounds, block, drawn = {}, set(), []
    for step in steps:
        if "sample" not in step:
            continue
        name = step.get("stream", step["id"])
        if "{" in name or step["sample"] not in ("weighted_choice", "uniform_choice", "uniform_int", "rating",
                                                 "review_topics", "normal"):
            raise unmodelled("a review step drawn by " + step["sample"])
        drawn.append(step["id"])
        if step["sample"] == "review_topics":
            block |= {name + "/length", name + "/value"} | {
                f"{name}/other/{slot}" for slot in range(max(map(int, step["length_weights"])))}
        else:
            block.add(name)
        if step["sample"] == "normal":
            # Every mention of the draw, in what the other steps and the statements evaluate, is a threshold.
            texts = [text for other in steps if other is not step for text in expressions(twin, other)] + [
                pool["when"] for rows in pools.values() for pool in rows if "when" in pool]
            cuts = [thresholds(twin, text, step["target"]) for text in texts]
            if None in cuts or not any(cuts):
                raise unmodelled("a continuous draw read other than through thresholds it must reach")
            # One value stands for all that reach the same thresholds: none of them may read differently.
            if twin.fields[step["target"]].get("unknown_values"):
                raise unmodelled("a continuous draw some of whose values count as unknown")
            bounds[step["id"]] = sorted({cut for found in cuts for cut in found})
    # Whether the rating can be redrawn on its own: no other draw sets its parameters.
    above, staged = read_by(twin, rating[0]), True
    for step in reversed(steps[:steps.index(rating[0])]):
        if any(touches(target, path) for target in written_by(step) for path in above):
            above, staged = above | read_by(twin, step), staged and "sample" not in step
    return SimpleNamespace(
        **common, reader=sys.modules[__name__], program=found, pools=pools, steps=steps, bounds=bounds,
        block=frozenset(block), drawn=frozenset(drawn), rating=rating[0], staged=staged,
        emits=sorted({row["target"] for step in steps for row in (inner(step) or [step]) if "emit" in row}),
        seeds=[streams.program_review_seed(common["seed"], index) for index in range(common["count"])])


def keys(place, index):
    """The streams of one review that decide its stars and what it says about the topic."""
    return [(streams.PROGRAM, place.seed, index, name) for name in sorted(place.block)]


def rating_key(place, index):
    """The stream of one review that draws its star rating."""
    return (streams.PROGRAM, place.seed, index, place.rating.get("stream", place.rating["id"]))


def stars(execution, concentration):
    """The probability of each star rating: one more than a beta-binomial count of four."""
    if not (type(concentration) in (int, float) and CONCENTRATIONS[0] <= concentration <= CONCENTRATIONS[1] and
            type(execution) in (int, float) and 0 <= execution <= 1):
        raise unmodelled("a rating whose concentration or execution is beyond ordinary size")
    mean = .05 + .9 * execution
    a, b = mean * concentration, (1 - mean) * concentration
    # Ratios of beta functions as rising products: no difference of large logarithms.
    rising = lambda start, count: prod(start + more for more in range(count))
    return {1 + hits: (1, 4, 6, 4, 1)[hits] * rising(a, hits) * rising(b, 4 - hits) / rising(a + b, 4)
            for hits in range(5)}


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


def bands(params, cuts):
    """A resolved normal draw by the thresholds it reaches: a value for each case, with its probability.

    The value stands for every draw that reaches the same thresholds: the
    range's lower end where it reaches none, otherwise the highest it reaches.
    That is sound where the expressions tell values apart by those thresholds
    alone, which `site` requires: only `>=` comparisons mention the draw, and
    its field marks no value as unknown.
    """
    ends = [tails(params, cut) for cut in cuts]
    for index in range(len(cuts) + 1):
        above, below = ends[index - 1] if index else (1.0, 0.0), ends[index] if index < len(cuts) else (0.0, 1.0)
        # The band between two thresholds, by whichever pair of tails is the smaller.
        share = above[0] - below[0] if above[0] <= .5 else below[1] - above[1]
        if share > 0:
            yield (cuts[index - 1] if index else params["min"]), share


def tails(params, bound):
    """The probabilities that a resolved normal draw ends at or above a bound, and below it.

    The program clips the draw to its range and rounds it to a grid before
    anything reads it, so the draw's own bound is the smallest number whose
    rounding reaches the stated one; bisection finds it among the floats.
    """
    low, high, step = params["min"], params["max"], params.get("round_to")
    if params.get("bounds_mode") != "clip" or params["sd"] <= 0 or not low < high:
        raise unmodelled("a normal draw that is not clipped to a range")
    sizes = [low, high, params["mean"], params["sd"], bound, *([] if step is None else [step])]
    if (not all(type(size) in (int, float) and abs(size) <= LARGE for size in sizes) or params["sd"] < SMALL or
            step is not None and not step >= SMALL):
        raise unmodelled("a normal draw with a range, mean, spread, grid or threshold beyond ordinary size")
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
    elif step["sample"] == "uniform_int":
        low, high, grid = params["min"], params["max"], params.get("round_to")
        if type(low) is not int or type(high) is not int or not low <= high <= low + 10000:
            raise unmodelled("a whole-number draw without a short range")
        for value in range(low, high + 1):
            yield (value if grid is None else round(value / grid) * grid), 1 / (high - low + 1)
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


def follow(place, choose, visit):
    """Run the steps the reading needs from the product's entities, once for every way the draws can fall.

    `choose` gives a draw's outcomes with their probabilities; `visit` gets
    the entities and the probability at the end of each way. The order and the handling of a step
    are `sample`'s: a step whose condition fails is not applicable, a loop
    runs its steps for each value under the group's bindings, and collected
    rows add to their list. A package gives every path one producing step, so
    a list's rows all come from one step, which starts it afresh on each way.
    """
    twin, module = place.program.twin, place.program.module
    context = deepcopy(place.program.entities)
    for path, definition in twin.fields.items():
        if "constant" in definition:
            module.set_path(context, path, deepcopy(definition["constant"]))
    start = {target: deepcopy(module.get_path(context, target)) for target in place.emits}

    def settle(step):
        """A step that draws nothing: not applicable, collected or derived."""
        target = step["target"]
        conditions = [text for text in (twin.fields[target].get("applicable_when"), step.get("when")) if text is not None]
        if conditions and not all(twin._eval(text, context) for text in conditions):
            module.set_path(context, target, module.NOT_APPLICABLE)
        elif "emit" in step:
            row, rows = {name: twin._eval(text, context) for name, text in step["emit"].items()}, module.get_path(context, target)
            if module.unresolved(rows):
                rows = []
                module.set_path(context, target, rows)
            rows.append(row)
        else:
            module.set_path(context, target, twin._eval(step["derive"], context))

    def renew(step):
        """Before a collecting step runs: its list as the entities had it, not as another way left it."""
        for row in (inner(step) or [step]):
            if "emit" in row:
                holder, names = context, row["target"].split(".")
                for name in names[:-1]:
                    holder = holder.setdefault(name, {})
                if module.unresolved(start[row["target"]]):
                    holder.pop(names[-1], None)
                else:
                    holder[names[-1]] = deepcopy(start[row["target"]])

    def walk(position, mass):
        if position == len(place.steps):
            visit(context, mass)
            return
        step, ahead = place.steps[position], position + 1
        if "for_each" in step:
            renew(step)
            if "when" not in step or twin._eval(step["when"], context):
                values = twin._eval(step["for_each"]["from"], context)
                if not isinstance(values, (list, set)):
                    raise unmodelled("a loop over something that is not a collection")
                saved = deepcopy(context.get("group", {}))
                for value in sorted(values) if isinstance(values, set) else list(values):
                    context["group"] = deepcopy(saved)
                    module.set_path(context, step["for_each"]["binding"], value)
                    for row in step["steps"]:
                        settle(row)
                context["group"] = saved
            walk(ahead, mass)
        elif "sample" not in step:
            renew(step)
            settle(step)
            walk(ahead, mass)
        else:
            target, definition = step["target"], twin.fields[step["target"]]
            conditions = [text for text in (definition.get("applicable_when"), step.get("when")) if text is not None]
            if conditions and not all(twin._eval(text, context) for text in conditions):
                module.set_path(context, target, module.NOT_APPLICABLE)
                walk(ahead, mass)
                return
            for value, share in choose(step, context):
                module.set_path(context, target, value)
                walk(ahead, mass * share)

    walk(0, 1.0)


def cells(place):
    """The probability that one review has each star rating and is positive, negative or neither about the topic.

    Follows the steps the rating and the topic's statements depend on,
    branching on every outcome of a draw.
    """
    name = json.dumps(place.requirement["topic"], sort_keys=True)
    if name in place.program.cells:
        return dict(place.program.cells[name])
    twin, module, found = place.program.twin, place.program.module, defaultdict(list)

    def choose(step, context):
        if step["sample"] != "normal":
            return outcomes(place, step, context)
        return bands(twin.resolve(step, context), place.bounds[step["id"]])

    follow(place, choose, lambda context, mass: found[
        module.get_path(context, place.rating["target"]), told(place, context)].append(mass))
    if not set(rating for rating, _ in found) <= set(range(1, 6)):
        raise unmodelled("a review without a star rating from one to five")
    place.program.cells[name] = reviews.whole({
        (rating, side): fsum(found.get((rating, side), [])) for rating in range(1, 6)
        for side in (reviews.POSITIVE, reviews.NEGATIVE, reviews.REST)})
    return dict(place.program.cells[name])


def replayed(place, found):
    """What following the steps from a review's recorded block draws says of it: the topic's class and the rating."""
    recorded, module, seen = {name: json.loads(outcome) for name, outcome in found[0]}, place.program.module, []

    follow(place, lambda step, context: [(recorded[step["id"]], 1.0)], lambda context, mass: seen.append(
        (told(place, context), module.get_path(context, place.rating["target"]))))
    return seen[0]


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
    """Refuse a natural world whose reviews are not what this reading draws under the world's seed, or follows."""
    rows = written(world, place)
    if rows != [redrawn(place, index) for index in range(place.count)]:
        raise ValueError("The product's recorded reviews are not what its review program draws under the world's seed")
    if any(replayed(place, row) != row[1:] for row in rows):
        raise ValueError("Following the review program's steps from a review's recorded draws gives another review")
