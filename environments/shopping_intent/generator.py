"""Sample intent before any realized offers, stock, shipping quotes or oracle answer."""
import copy
import hashlib
import json
import random

from .catalog import FAMILIES, attribute_for
from .semantics import BLOCKERS, conflicts, entails, sample_requirements

VERSION = "shopping-intent-v2"
QUERY_PRESETS = {
    "cheapest": {"operation": "select", "line_count": 1, "allocation": "single_store",
                 "objective": [{"field": "total_minor", "direction": "min"}]},
    "fastest": {"operation": "select", "line_count": 1, "allocation": "single_store",
                "objective": [{"field": "arrival_days", "direction": "min"},
                              {"field": "total_minor", "direction": "min"}]},
    "basket": {"operation": "select", "line_count": 3, "allocation": "single_store",
               "objective": [{"field": "total_minor", "direction": "min"}]},
    "split_basket": {"operation": "select", "line_count": 3, "allocation": "split_allowed",
                     "objective": [{"field": "total_minor", "direction": "min"}]},
    "average": {"operation": "aggregate", "line_count": 1, "allocation": "single_store",
                "objective": [], "statistic": {"operation": "mean", "measure": "total_minor",
                    "population": "cheapest_eligible_quote_per_retailer",
                    "rounding": "nearest_minor_unit_half_up", "empty": "undefined"}},
}
MEMORY_MODES = ("auto", "none", "profile", "episodic", "mixed", "override")


def stream(seed, namespace):
    digest = hashlib.sha256(f"{VERSION}:{seed}:{namespace}".encode()).digest()
    return random.Random(int.from_bytes(digest, "big"))


def atom(attr, value):
    return {"field": attr.key, "operator": attr.operator, "value": value,
            "unit": attr.unit, "value_type": attr.value_type,
            "label": attr.label, "surface": attr.surface}


def semantic_key(predicate):
    return predicate["field"], predicate["operator"]


def resolve(request, memory_facts):
    """Resolve family/subject-scoped memories, then explicit same-field overrides.

    A prose memory's binding is private authoring truth; no NLP extraction happens here.
    Different operators remain separate conjuncts (e.g. include X and exclude Y).
    """
    result = copy.deepcopy(request)
    for line in result["lines"]:
        resolved = {}
        for fact in memory_facts:
            if fact["subject"] == line["subject"] and fact["family_id"] == line["family_id"]:
                p = copy.deepcopy(fact["predicate"])
                p["source"] = {"kind": "memory", "id": fact["id"], "channel": fact["channel"]}
                resolved[semantic_key(p)] = p
        for p in line.pop("explicit_requirements"):
            p = copy.deepcopy(p)
            p["source"] = {"kind": "request"}
            resolved[semantic_key(p)] = p
        line["requirements"] = sorted(resolved.values(), key=semantic_key)
    return result


def generate(seed=0, family="random", query="cheapest", memory="auto", requirements=3,
             target="category", prose_seed=None, budget_sek=None, hidden="auto"):
    """Return a private authoring bundle; only `public` is policy-facing.

    The family argument may contain three comma-separated families for basket queries.
    Fixed family domains are recipe priors, not feasibility guarantees.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if prose_seed is None:
        prose_seed = seed
    if isinstance(prose_seed, bool) or not isinstance(prose_seed, int):
        raise ValueError("prose_seed must be an integer")
    if hidden not in ("auto", "none", "blocker"):
        raise ValueError("hidden must be auto, none or blocker")
    requested_query = query
    if query == "random":
        query = stream(seed, "query").choice(sorted(QUERY_PRESETS))
    if query not in QUERY_PRESETS or memory not in MEMORY_MODES:
        raise ValueError("Unknown query or memory mode")
    if isinstance(requirements, bool) or not isinstance(requirements, int) or not 1 <= requirements <= 6:
        raise ValueError("requirements must be an integer from 1 through 6")
    if target not in ("category", "model"):
        raise ValueError("target must be category or model")
    if budget_sek is not None and (type(budget_sek) is not int or budget_sek <= 0):
        raise ValueError("budget_sek must be a positive integer")
    query_spec = copy.deepcopy(QUERY_PRESETS[query])
    count = query_spec.pop("line_count")
    available = sorted(FAMILIES)
    if family == "random":
        selected = stream(seed, "families").sample(available, count)
    else:
        selected = [x.strip() for x in family.split(",")]
        if any(x not in FAMILIES for x in selected) or len(set(selected)) != len(selected):
            raise ValueError("Use known, distinct family IDs")
        if len(selected) == 1 and count > 1:
            selected += stream(seed, "families").sample([x for x in available if x not in selected], count - 1)
        if len(selected) != count:
            raise ValueError(f"This query needs {count} family/families")

    mode = memory if memory != "auto" else stream(seed, "memory-mode").choice(MEMORY_MODES[1:])
    request = {"schema_version": VERSION, "query": query_spec, "lines": [],
               "context": {"currency": "SEK", "destination": "SE", "quantity_basis": "sellable_units",
                           "price_basis": "total_including_delivery_and_all_mandatory_charges",
                           "arrival_basis": "latest_promised_calendar_day_after_order",
                           "scope": "all_retailers_in_supplied_environment", "world_time": "frozen_snapshot"},
               "constraints": {}, "authorization": {"purchase": False, "signup": False,
                           "persistent_memory_changes": False, "cart_changes": False},
               "unknown_policy": "report_uncertainty", "no_match_policy": "report_shortfall_no_substitution"}
    facts, hidden_specs, audits = [], [], []
    for index, family_id in enumerate(selected):
        f = FAMILIES[family_id]
        rng = stream(seed, f"requirements:{family_id}")
        predicates, audit = sample_requirements(f, requirements, rng, atom)
        audit["line_id"] = f"line-{index + 1}"
        audits.append(audit)
        line = {"id": f"line-{index + 1}", "family_id": f.id, "subject": f.subject,
                "quantity": 1 if count == 1 else stream(seed, f"quantity:{f.id}").choice((1, 1, 2)),
                "model": None, "explicit_requirements": []}
        if target == "model" or query == "average":
            model_index = stream(seed, f"model:{f.id}").randrange(1, 4)
            line["model"] = {"id": f"{f.id}-model-{model_index}",
                             "name": f"{('Aster', 'Boreal', 'Cedar')[model_index - 1]} {f.label} {model_index}"}
        for j, p in enumerate(predicates):
            channel_rng = stream(seed, f"placement:{f.id}:{j}")
            use_memory = mode != "none" and (j == 0 or (mode == "mixed" and j == 1) or channel_rng.random() < .55)
            if use_memory:
                channel = mode if mode in ("profile", "episodic") else ("profile" if j % 2 == 0 else "episodic")
                facts.append({"id": f"memory-{len(facts) + 1}", "subject": f.subject, "family_id": f.id,
                              "channel": channel, "scope": "durable_family_requirement",
                              "predicate": copy.deepcopy(p), "provenance": "synthetic_prior_user_statement"})
            else:
                line["explicit_requirements"].append(copy.deepcopy(p))
        # Older durable facts must be internally consistent too. A current override
        # is explicit; it does not silently repair a contradictory profile.
        if mode == "override":
            for p in predicates:
                if hidden != "none" and p["field"] in BLOCKERS.get(f.id, {}):
                    continue
                a = attribute_for(f.id, p["field"], p["operator"])
                alternatives = [v for v in a.values if v != p["value"] and not conflicts(f.id,
                    [x for x in predicates if x is not p] + [atom(a, v)])]
                if not alternatives: continue
                k = semantic_key(p)
                fact = next((x for x in facts if x["family_id"] == f.id and semantic_key(x["predicate"]) == k), None)
                if fact is None:
                    fact = {"id": f"memory-{len(facts) + 1}", "subject": f.subject, "family_id": f.id,
                            "channel": "profile", "scope": "durable_family_requirement",
                            "predicate": copy.deepcopy(p), "provenance": "synthetic_prior_user_statement"}
                    facts.append(fact)
                fact["predicate"]["value"] = stream(seed, f"override:{f.id}").choice(alternatives)
                line["explicit_requirements"] = [x for x in line["explicit_requirements"] if semantic_key(x) != k]
                line["explicit_requirements"].append({**copy.deepcopy(p), "temporary_override": True})
                break
        wants_hidden = hidden == "blocker" or (hidden == "auto" and stream(seed, f"hidden:{f.id}").random() < .35)
        if wants_hidden:
            eligible = [p for p in predicates if p["field"] in BLOCKERS.get(f.id, {})
                        and not entails(f.id, [x for x in predicates if x is not p], p)]
            if eligible:
                p = stream(seed, f"hidden-field:{f.id}").choice(eligible)
                k = semantic_key(p)
                line["explicit_requirements"] = [x for x in line["explicit_requirements"] if semantic_key(x) != k]
                facts[:] = [x for x in facts if not (x["family_id"] == f.id and semantic_key(x["predicate"]) == k)]
                question, reason = BLOCKERS[f.id][p["field"]]
                hidden_specs.append({"id": f"hidden-{len(hidden_specs) + 1}", "line_id": line["id"],
                    "subject": f.subject, "family_id": f.id, "predicate": copy.deepcopy(p),
                    "reason": reason, "example_question": question})
        request["lines"].append(line)

    if hidden == "blocker" and not hidden_specs:
        raise ValueError("This family has no authored blocking fit/compatibility specification; choose another family or hidden=none")
    # Reindex after withholding so authoring IDs remain unique when adding basket memories.
    for i, fact in enumerate(facts):
        fact["id"] = f"memory-{i + 1}"
    context_rng = stream(seed, "commercial-requirements")
    reference = sum(FAMILIES[l["family_id"]].reference_sek * l["quantity"] for l in request["lines"])
    if budget_sek is not None or query == "fastest" or (query != "average" and context_rng.random() < .45):
        request["constraints"]["budget_minor"] = (budget_sek if budget_sek is not None else
            max(100, round(reference * context_rng.choice((.65, .9, 1.1, 1.5)) / 50) * 50)) * 100
    if query not in ("average", "fastest") and context_rng.random() < .4:
        request["constraints"]["arrival_days_max"] = context_rng.choice((3, 5, 7, 14))
    if query != "average" and context_rng.random() < .3:
        request["constraints"]["delivery_mode"] = "home"
    accessible = resolve(request, facts)
    resolved = copy.deepcopy(accessible)
    for spec in hidden_specs:
        line = next(x for x in resolved["lines"] if x["id"] == spec["line_id"])
        line["requirements"].append({**copy.deepcopy(spec["predicate"]),
                                     "source": {"kind": "clarification", "id": spec["id"]}})
        line["requirements"].sort(key=semantic_key)
    for line in resolved["lines"]:
        if conflicts(line["family_id"], line["requirements"]):
            raise ValueError("Internal inconsistent intent")
    from .render import render
    public, annotations = render(request, facts, prose_seed)
    from .render import phrase
    for spec in hidden_specs:
        reply = phrase(spec["predicate"], stream(prose_seed, "reply:" + spec["id"]))
        spec["reply"] = reply[0].upper() + reply[1:] + "."
    semantic = {"request": request, "memory_facts": facts, "resolved_task": resolved,
                "hidden_user_specifications": [{k: v for k, v in h.items() if k != "reply"} for h in hidden_specs]}
    fingerprint = hashlib.sha256(json.dumps(semantic, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"schema_version": VERSION, "seed": seed, "prose_seed": prose_seed,
            "settings": {"family": family, "query": requested_query, "resolved_query": query,
                         "memory": memory, "resolved_memory_mode": mode,
                         "requirements": requirements, "target": target, "budget_sek": budget_sek, "hidden": hidden},
            "semantic_sha256": fingerprint, "public": public, **semantic,
            "hidden_user_specifications": hidden_specs, "initial_accessible_task": accessible,
            "authoring": {"message_segments": annotations, "semantic_audit": audits},
            "expected_memory_delta": {"create": [], "update": [], "delete": []},
            "limitations": ["Authoring prototype; no generated websites, real memory retrieval or commerce adapter.",
                            "Synthetic model references and requirements are sampled without offer/stock knowledge.",
                            "No guarantee that any offer or even any valid configuration satisfies the request.",
                            "Effect/suitability labels are attributed claims, not guaranteed real-world outcomes."]}
