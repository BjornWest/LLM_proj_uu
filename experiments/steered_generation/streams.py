"""Run the real producer with chosen random draws replaced by planned results.

The commerce producer gives every decision its own named stream
(`population.stream(seed, key)`), so replacing one stream leaves every other
draw exactly as the seed makes it. A plan maps stream keys to the results the
producer's calls on that stream should return. Nothing in the producer is
copied or edited; a few module and class attributes are swapped for the
duration of a call. That is an experiment seam, not thread-safe and not a
released API.
"""
from collections import Counter
from contextlib import ExitStack, contextmanager
from hashlib import sha256
import json
from math import isfinite
import pickle
import sys


class OutOfSupport(ValueError):
    """A planned result is one the real draw could not have returned."""


class PlanMismatch(RuntimeError):
    """The producer did not make the calls the plan was written for."""


STATUS = "steered_conditional_sample"


class Reseeded:
    """Plan entry that opens a stream under another seed: a natural redraw of that draw.

    Unlike a script it makes no claim about which calls the producer makes,
    and a reseeded key the producer never opens is not an error.
    """

    def __init__(self, seed):
        self.seed = seed


class Scripted:
    """Stands in for one named stream and replays its planned results in order."""

    def __init__(self, key, script):
        self.key, self.script, self.used = key, list(script), 0

    def _next(self, method):
        if self.used >= len(self.script) or self.script[self.used][0] != method:
            planned = self.script[self.used][0] if self.used < len(self.script) else "nothing further"
            raise PlanMismatch(f"{self.key}: producer called {method}, plan has {planned}")
        value = self.script[self.used][1]
        self.used += 1
        return value

    def _require(self, condition, value):
        if not condition:
            raise OutOfSupport(f"{self.key}: {value!r} is outside the draw's support")
        return value

    def random(self):
        value = self._next("random")
        return self._require(type(value) is float and 0 <= value < 1, value)

    def gauss(self, mu, sigma):
        value = self._next("gauss")
        return self._require(type(value) is float and isfinite(value) and (sigma > 0 or value == mu), value)

    def randint(self, low, high):
        value = self._next("randint")
        return self._require(type(value) is int and low <= value <= high, value)

    def choice(self, options):
        value = self._next("choice")
        return self._require(value in options, value)

    def choices(self, population, weights=None, *, k=1):
        value = self._next("choices")
        allowed = [item for item, weight in zip(population, weights or [1] * len(population)) if weight > 0]
        return [self._require(k == 1 and value in allowed, value)]

    def __getattr__(self, name):
        raise PlanMismatch(f"{self.key}: producer called unplanned method {name}")


@contextmanager
def steered(population, plan, opened=None):
    """Within the block, planned stream keys replay their script.

    A key can be opened several times (the producer reopens the price stream
    for each SKU); every opening replays the whole script. Leaving the block
    fails if a planned key was never opened or a script was not fully used,
    since the plan then described draws the producer did not make.
    """
    natural, instances = population.stream, []

    def stream(seed, key):
        if opened is not None:
            opened.append(key)
        if key not in plan:
            return natural(seed, key)
        if isinstance(plan[key], Reseeded):
            return natural(plan[key].seed, key)
        instances.append(Scripted(key, plan[key]))
        return instances[-1]

    population.stream = stream
    try:
        yield
    finally:
        population.stream = natural
    unused = {key for key, entry in plan.items() if not isinstance(entry, Reseeded)} - {s.key for s in instances}
    partial = {s.key for s in instances if s.used != len(s.script)}
    if unused or partial:
        raise PlanMismatch(f"planned draws not made: {sorted(unused)[:3]}; partly used: {sorted(partial)[:3]}")


# A plan key (REVIEW, product seed, stream key) names one stream of a pilot product's review sampler.
REVIEW = "review"


def review_seed(seed, product_seed):
    """The seed a product's review stream opens under when a plan reseeds it.

    The review sampler's stream keys do not name the product, so the product's
    own seed stays part of it: two products reseeded alike still draw apart.
    """
    return f"{seed}/{product_seed}"


@contextmanager
def reviewed(footwear, plan):
    """Within the block, planned review streams of pilot products open under another seed.

    `plan` maps (product seed, stream key) to a `Reseeded` entry. The review
    sampler looks its `stream` up at each call, so every draw of a review goes
    through here; streams the plan does not name are the product's own.
    """
    if not all(isinstance(entry, Reseeded) for entry in plan.values()):
        raise PlanMismatch("A product's review streams can be reseeded, not scripted")
    natural = footwear.stream

    def stream(seed, key):
        entry = plan.get((seed, key))
        return natural(seed, key) if entry is None else natural(review_seed(entry.seed, seed), key)

    footwear.stream = stream
    try:
        yield
    finally:
        footwear.stream = natural


# A plan key (PROGRAM, product seed, review index, stream key) names one stream of one review that a
# product package's review program draws.
PROGRAM = "program"


def program_review_seed(product_seed, index):
    """The seed the producer runs a package's review program under for one review of a product."""
    return int.from_bytes(sha256(f"accepted-catalog-review/{product_seed}/{index}".encode()).digest()[:4], "big")


def program_seed(seed, review_seed):
    """The seed a review program's stream opens under when a plan reseeds it; the review's own seed stays part of it."""
    return f"{seed}/{review_seed}"


@contextmanager
def programmed(package_class, plan):
    """Within the block, planned streams of package review programs open under another seed.

    `plan` maps (product seed, review index, stream key) to a `Reseeded`
    entry. A package opens every stream through its class's `rng`, which
    knows the review's seed and the stream's key and nothing else, and both
    are short: a planned pair that some other draw of the pass also opens is
    reseeded with it. No planned stream is opened twice by the review it
    belongs to, so a pass in which one was fails.
    """
    if not all(isinstance(entry, Reseeded) for entry in plan.values()):
        raise PlanMismatch("A review program's streams can be reseeded, not scripted")
    planned = {}
    for (product_seed, index, key), entry in plan.items():
        if planned.setdefault((program_review_seed(product_seed, index), key), entry) is not entry:
            raise PlanMismatch("Two planned reviews run under one seed")
    natural, opened = package_class.rng, Counter()

    def rng(self, seed, key):
        entry = planned.get((seed, key))
        if entry is None:
            return natural(self, seed, key)
        opened[seed, key] += 1
        return natural(self, program_seed(entry.seed, seed), key)

    package_class.rng = rng
    try:
        yield
    finally:
        package_class.rng = natural
    if any(count > 1 for count in opened.values()):
        raise PlanMismatch("A planned review stream was opened by more than one draw of the pass")


# A plan key (CARRIER, stream key) names one stream of the carrier-evidence producer.
CARRIER = "carrier"


@contextmanager
def carried(producer, plan):
    """Within the block, planned streams of the carrier-evidence producer open under another seed.

    `plan` maps stream keys to `Reseeded` entries. The producer looks its
    `rng` up at each call; a shipment's review stream names the shipment, so
    reseeded streams of different shipments draw apart.
    """
    if not all(isinstance(entry, Reseeded) for entry in plan.values()):
        raise PlanMismatch("A carrier's review streams can be reseeded, not scripted")
    natural = producer.rng

    def rng(seed, key):
        entry = plan.get(key)
        return natural(seed, key) if entry is None else natural(entry.seed, key)

    producer.rng = rng
    try:
        yield
    finally:
        producer.rng = natural


def relabel(world, record, api):
    """Mark a world from a steered pass: its seed alone no longer reproduces it."""
    world["provenance"]["steered_generation"] = record
    world["status"] = STATUS
    # The producer's own statements (such as "no winner or seed repair")
    # describe the natural draw, not this world.
    world["limitations"] = ["Natural-draw declaration: " + note for note in world["limitations"]] + [
        "Steered conditional sample: the seed alone does not reproduce this world; see provenance.steered_generation."]
    world.pop("world_id")
    world["world_id"] = api.native.digest(world)


class Manufacture:
    """Remembers manufactured products so later passes skip that cost.

    Product manufacture is most of a world's generation time. A product is
    reused only when every manufacture call so far in the pass had the same
    arguments as when it was stored, so a plan that changes anything upstream
    of manufacture simply misses the cache from that point on. Results are
    stored pickled; each pass gets its own copy to mutate as the producer does.

    A product whose seed is in `fresh` is manufactured again and not stored:
    its plan changes draws inside its manufacture. Later products are still
    reused, which holds as long as manufacture reads nothing of an earlier
    product that such a plan changes; a pass's comparison with the natural
    world outside the plan's resources would show a product that did.
    """

    def __init__(self):
        self.products = {}

    @contextmanager
    def reused(self, package_export, fresh=()):
        real = package_export.sample
        # `earlier` is the pass's running product list. Chaining the call
        # arguments stands in for hashing its growing contents.
        state = {"chain": b"", "calls": 0}

        def sample(seed, concept_id, brand, product_id, *, earlier, **options):
            if state["chain"] is not None and len(earlier) == state["calls"]:
                own = pickle.dumps((seed, concept_id, product_id, brand, sorted(options.items())))
                state["chain"] = sha256(state["chain"] + own).digest()
            else:
                state["chain"] = None
            state["calls"] += 1
            key = state["chain"]
            if key is None or seed in fresh:
                return real(seed, concept_id, brand, product_id, earlier=earlier, **options)
            if key not in self.products:
                self.products[key] = pickle.dumps(
                    real(seed, concept_id, brand, product_id, earlier=earlier, **options))
            return pickle.loads(self.products[key])

        package_export.sample = sample
        try:
            yield
        finally:
            package_export.sample = real


class Defaults:
    """Reads the sampling defaults once for all of a session's passes.

    The experiment's original producer called `population.load()` for every
    retailer/product entry, re-reading and re-validating the same files. The
    current central producer reads once per world; this session still shares
    its first defaults snapshot across repeated worlds. With manufacture
    cached that is most of a pass, and it grows with the world. Passes here
    get the first call's result instead. The pinned producer only reads it.
    As a check on that, a pass that completes with the configuration changed
    fails; the registry object and a failing pass are not checked.
    """

    def __init__(self):
        self.loaded = self.text = None

    def _text(self):
        return json.dumps(self.loaded[0], sort_keys=True, ensure_ascii=False)

    @contextmanager
    def shared(self, population):
        real = population.load

        def load():
            if self.loaded is None:
                self.loaded = real()
                self.text = self._text()
            return self.loaded

        population.load = load
        try:
            yield
        finally:
            population.load = real
        if self.loaded is not None and self._text() != self.text:
            raise AssertionError("A pass changed the shared sampling defaults")


class Session:
    """One set of generation inputs; repeated passes through the real producer."""

    def __init__(self, native, inputs, share_defaults=True):
        self.native, self.manufacture = native, Manufacture()
        self.defaults = Defaults() if share_defaults else None
        self.inputs = {"seed": inputs["seed"], "concept_ids": inputs["concept_ids"],
                       "tasks": tuple(inputs["tasks"]), "controls": inputs["controls"],
                       "city_id": inputs["city_id"], "review_count": inputs["review_count"]}

    def generate(self, plan=None):
        """Returns the world and the stream keys the producer opened."""
        options = {k: v for k, v in self.inputs.items() if k != "seed"}
        opened, plan = [], plan or {}
        # A key is a commerce stream's name, (REVIEW, product seed, stream name),
        # (PROGRAM, product seed, review index, stream name) or (CARRIER, stream name).
        named = lambda key, kind, length: (type(key) is tuple and len(key) == length and key[0] == kind and
                                           type(key[-1]) is str and bool(key[-1]) and
                                           all(type(part) is int for part in key[1:-1]))
        reviews = {key[1:]: entry for key, entry in plan.items() if named(key, REVIEW, 3)}
        programs = {key[1:]: entry for key, entry in plan.items() if named(key, PROGRAM, 4)}
        carriers = {key[1]: entry for key, entry in plan.items() if named(key, CARRIER, 2)}
        commerce = {key: entry for key, entry in plan.items() if type(key) is str}
        if len(reviews) + len(programs) + len(carriers) + len(commerce) != len(plan):
            raise PlanMismatch("A plan names commerce streams, product review streams and carrier review streams")
        with ExitStack() as stack:
            stack.enter_context(self.manufacture.reused(self.native.package_export,
                                                        {key[0] for key in (*reviews, *programs)}))
            if reviews:
                stack.enter_context(reviewed(self.native.package_export.footwear, reviews))
            if programs:
                stack.enter_context(programmed(self.native.package_export.ProductPackage, programs))
            if carriers:
                stack.enter_context(carried(sys.modules[self.native.commerce.carrier_reviews.__module__], carriers))
            if self.defaults:
                stack.enter_context(self.defaults.shared(self.native.population))
            stack.enter_context(steered(self.native.population, commerce, opened))
            world = self.native.commerce.generate(self.inputs["seed"], **options)
        return world, opened
