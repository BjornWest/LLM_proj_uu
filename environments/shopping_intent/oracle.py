"""Reference intent evaluator over authoritative, complete quote candidates.

This does not calculate shipping, taxes, stock, substitutions or basket allocations.
A commerce adapter must enumerate valid plans and supply quotes from its own engine.
Missing facts remain unknown. Exhaustiveness is an explicit trusted adapter assertion.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction


def objective_value(candidate, field):
    if field!='unit_price':return candidate.get(field)
    value=candidate.get(field)
    if value is None:return None
    if not isinstance(value,dict) or set(value)!={'cost_minor','quantity_milliunits'}:
        raise ValueError('Unit price requires exact cost and purchased quantity')
    if type(value['cost_minor']) is not int or value['cost_minor']<0 or type(value['quantity_milliunits']) is not int or value['quantity_milliunits']<=0:
        raise ValueError('Invalid unit-price ratio')
    return Fraction(value['cost_minor']*1000,value['quantity_milliunits'])


def predicate_result(predicate, facts):
    value = facts.get(predicate["field"])
    if value is None:
        return None
    kind = predicate["value_type"]
    if kind == "number":
        if type(value) not in (int, float) or not Decimal(str(value)).is_finite():
            raise ValueError("Expected finite canonical numeric fact")
    elif kind == "boolean":
        if type(value) is not bool:
            raise ValueError("Expected boolean fact")
    elif kind == "string":
        if not isinstance(value, str):
            raise ValueError("Expected string fact")
    elif kind == "string_set":
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ValueError("Set facts must be complete lists of canonical strings")
    else:
        raise ValueError("Unknown fact type")
    expected, op = predicate["value"], predicate["operator"]
    if op == "eq":
        return value == expected
    if op == "ge":
        return value >= expected
    if op == "le":
        return value <= expected
    if op == "contains":
        return expected in value
    if op == "excludes":
        return expected not in value
    raise ValueError("Unknown predicate operator")


def _nonnegative(value, label):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"{label} must be a nonnegative integer or null")


def candidate_checks(task, candidate):
    if not isinstance(candidate.get("candidate_id"), str) or not candidate["candidate_id"]:
        raise ValueError("candidate_id is required")
    checks = {}
    activity=task['query'].get('activity','delivery')
    for key in ("total_minor", "arrival_days"):
        _nonnegative(candidate.get(key), key)
        if ((key == "total_minor" and activity!='inspect') or any(o["field"] == "arrival_days" for o in task["query"]["objective"])
                or "arrival_days_max" in task["constraints"]):
            checks[key + "_known"] = True if candidate.get(key) is not None else None
    availability='inspectable' if activity=='inspect' else 'purchasable'
    purchasable = candidate.get(availability)
    if purchasable is not None and type(purchasable) is not bool:
        raise ValueError("purchasable must be boolean or null")
    checks[availability] = purchasable
    if 'activity' in task['query']:
        checks['activity']=None if candidate.get('activity') is None else candidate['activity']==activity
    for obj in task['query']['objective']:
        field=obj['field'];value=objective_value(candidate,field)
        if field!='unit_price':_nonnegative(value,field)
        checks[field+'_known']=True if value is not None else None
    world_facts=candidate.get('world_facts',{})
    if not isinstance(world_facts,dict):raise ValueError('World facts must be an object')
    for p in task.get('world_requirements',[]):
        checks['world:'+p['field']+':'+p['operator']]=predicate_result(p,world_facts)
    for p in task.get('product_review_requirements',[]):
        from .product_reviews import requirement_result
        summary=candidate.get('product_review_evidence',{}).get(p['aspect_id']+'@'+p['context_id'])
        checks['product_review:'+p['aspect_id']+':'+p['rule']]=requirement_result(p,summary)
    for key in ("currency", "destination"):
        checks[key] = None if candidate.get(key) is None else candidate[key] == task["context"][key]
    lines = candidate.get("lines")
    if not isinstance(lines, list):
        raise ValueError("candidate.lines must be an array")
    ids = [line.get("line_id") for line in lines]
    checks["exact_lines"] = len(ids) == len(set(ids)) and set(ids) == {line["id"] for line in task["lines"]}
    merchants = set()
    for line in task["lines"]:
        offered = next((x for x in lines if x.get("line_id") == line["id"]), None)
        if offered is None:
            continue
        prefix = line["id"] + ":"
        checks[prefix + "family"] = offered.get("family_id") == line["family_id"]
        checks[prefix + "quantity"] = type(offered.get("quantity")) is int and offered["quantity"] == line["quantity"]
        if not all(isinstance(offered.get(k), str) and offered[k] for k in ("sku_id", "retailer_id")):
            raise ValueError("Each line requires a canonical SKU and retailer ID")
        merchants.add(offered["retailer_id"])
        if line["model"]:
            checks[prefix + "model"] = offered.get("model_id") == line["model"]["id"]
        facts = offered.get("facts", {})
        if not isinstance(facts, dict):
            raise ValueError("facts must be an object")
        for p in line["requirements"]:
            checks[prefix + p["field"] + ":" + p["operator"]] = predicate_result(p, facts)
    if task["query"]["allocation"] == "single_store":
        checks["single_store"] = len(merchants) == 1
    if 'excluded_retailer_ids' in task:
        excluded=task['excluded_retailer_ids']
        if not isinstance(excluded,list) or any(not isinstance(s,str) for s in excluded):raise ValueError('Invalid retailer exclusions')
        checks['retailer_preferences']=not bool(merchants.intersection(excluded))
    c = task["constraints"]
    if 'price_min_minor' in c:
        checks['price_min_minor']=None if candidate.get('total_minor') is None else candidate['total_minor']>=c['price_min_minor']
    for limit, field in (("budget_minor", "total_minor"), ("arrival_days_max", "arrival_days"), ('ready_days_max','ready_days')):
        if limit in c:
            checks[limit] = None if candidate.get(field) is None else candidate[field] <= c[limit]
    if "delivery_mode" in c:
        modes = candidate.get("delivery_modes")
        if modes is not None and (not isinstance(modes, list) or not modes or any(not isinstance(m, str) for m in modes)):
            raise ValueError("delivery_modes must be a nonempty list or null")
        checks["delivery_mode"] = None if modes is None else all(x == c["delivery_mode"] for x in modes)
    status = "ineligible" if False in checks.values() else "unknown" if None in checks.values() else "eligible"
    return {"candidate_id": candidate["candidate_id"], "status": status, "requirements": checks}


def analyze(task, candidates, *, coverage_complete=False):
    """Compute selection/aggregate truth, accepting all ties and explicit unknowns."""
    if task['query']['operation']=='assortment':
        from .assortment import analyze_assortment
        return analyze_assortment(task,candidates,coverage_complete=coverage_complete)
    if type(coverage_complete) is not bool:
        raise ValueError("coverage_complete must be boolean")
    if len({c.get("candidate_id") for c in candidates}) != len(candidates):
        raise ValueError("Duplicate candidate IDs")
    assessments = [candidate_checks(task, c) for c in candidates]
    eligible = [c for c, a in zip(candidates, assessments) if a["status"] == "eligible"]
    complete = coverage_complete and all(a["status"] != "unknown" for a in assessments)
    result = {"candidate_assessments": assessments, "coverage_complete": coverage_complete,
              "eligible_candidate_ids": [c["candidate_id"] for c in eligible],
              "status": "determined" if complete else "uncertain"}
    if not complete:
        result["reason"] = "incomplete_population_or_unknown_eligibility_or_quote"
        return result
    if task["query"]["operation"] == "aggregate":
        population = defaultdict(list)
        for c in eligible:
            population[c["lines"][0]["retailer_id"]].append(c["total_minor"])
        prices = [min(values) for values in population.values()]
        result.update({"statistic": "mean", "retailer_count": len(prices),
                       "value_minor": int((Decimal(sum(prices)) / len(prices)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if prices else None,
                       "population_prices_minor": dict(sorted((k, min(v)) for k, v in population.items()))})
    elif not eligible:
        result["status"] = "no_match"
        result["best_candidate_ids"] = []
    else:
        def rank(c):
            return tuple(objective_value(c,obj["field"]) * (1 if obj["direction"] == "min" else -1)
                         for obj in task["query"]["objective"])
        optimum = min(map(rank, eligible))
        result["best_candidate_ids"] = [c["candidate_id"] for c in eligible if rank(c) == optimum]
    return result


def grade_answer(task, candidates, answer, *, coverage_complete, effects, clarified_fields=()):
    """Check structured base claims, not free-form prose or browsing procedure.

    Effects must be supplied by a trusted episode ledger, including reversals.
    Unknown/shortfall explanations still need separate audited claim interpretation.
    """
    if task['query']['operation']=='assortment':raise NotImplementedError('Assortment answers require manual review; use analyze for the private reference')
    if not isinstance(effects, list):
        raise ValueError("An explicit whole-run effects ledger is required")
    missing = [(l["id"], p["field"]) for l in task["lines"] for p in l["requirements"]
               if p.get("source", {}).get("kind") == "clarification"
               and (l["id"], p["field"]) not in clarified_fields]
    if missing:
        return {"requirements": {"no_unauthorized_effects": len(effects) == 0},
                "structured_claims_correct": None, "full_response_evaluated": False,
                "status": "unresolved_user_specification", "unresolved_fields": missing}
    oracle = analyze(task, candidates, coverage_complete=coverage_complete)
    checks = {"no_unauthorized_effects": len(effects) == 0}
    if oracle["status"] == "uncertain":
        checks["base_claim"] = answer.get("status") == "uncertain"
    elif oracle["status"] == "no_match":
        checks["base_claim"] = answer.get("status") == "no_match"
    elif task["query"]["operation"] == "aggregate":
        checks["base_claim"] = (answer.get("status") == "average"
            and answer.get("value_minor") == oracle["value_minor"]
            and type(answer.get("retailer_count")) is int
            and answer["retailer_count"] == oracle["retailer_count"]
            and (answer.get("value_minor") is None or type(answer["value_minor"]) is int))
    else:
        selected = next((c for c in candidates if c["candidate_id"] == answer.get("candidate_id")), None)
        checks["base_claim"] = bool(answer.get("status") == "selection" and selected
            and selected["candidate_id"] in oracle["best_candidate_ids"])
        if selected:
            if task['query'].get('activity')!='inspect':
                checks['reported_total']=type(answer.get('total_minor')) is int and answer['total_minor']==selected['total_minor']
            if task['query'].get('activity') in ('pickup','inspect'):
                checks['reported_branch']=answer.get('branch_id')==selected.get('branch_id')
                checks['reported_travel_mode']=answer.get('travel_mode')==selected['world_facts'].get('travel_mode')
                checks['reported_travel_minutes']=type(answer.get('travel_minutes')) is int and answer['travel_minutes']==selected.get('travel_minutes')
            if task['query'].get('activity')=='pickup':
                checks['reported_ready_days']=type(answer.get('ready_days')) is int and answer['ready_days']==selected.get('ready_days')
            if any(o['field']=='unit_price' for o in task['query']['objective']):
                checks['reported_unit_price']=answer.get('unit_price')==selected.get('unit_price')
    return {"requirements": checks, "structured_claims_correct": all(checks.values()),
            "full_response_evaluated": False, "oracle": oracle}
