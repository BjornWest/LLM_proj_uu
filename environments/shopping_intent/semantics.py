"""Conservative intent-domain logic, independent of retailer inventory and prices.

Rules describe this authored vocabulary, not a comprehensive physical product model.
An absence of a rule never implies a real-world guarantee of compatibility.
"""
import copy

from .catalog import FAMILIES

# Explicit allowlist: absence of these facts prevents choosing a personal fit or a
# compatible replacement. A field being a selectable variation is NOT sufficient.
BLOCKERS = {
    "footwear": {"size_eu": ("What EU shoe size do you need?", "Personal shoe fit")},
    "trousers": {"waist_in": ("What waist size do you wear, in inches?", "Personal trouser fit"),
                 "inseam_in": ("What inside-leg length do you need, in inches?", "Personal trouser fit")},
    "jackets": {"size_label": ("What jacket size do you need?", "Personal garment fit")},
    "phone_cases": {"compatible_model": ("Which phone model is the case for?", "Device-specific fit")},
    "camera_lenses": {"mount": ("Which lens mount does your camera use?", "Camera/lens compatibility")},
    "foundation": {"shade": ("What foundation shade do you use in this range?", "Personal shade match")},
    "brush_heads": {"compatible_system": ("Which toothbrush handle system do you have?", "Replacement-head compatibility")},
    "printer_ink": {"compatible_model": ("Which printer model do you have?", "Cartridge compatibility")},
    "vacuum_bags": {"compatible_model": ("Which vacuum model do you have?", "Replacement-bag compatibility")},
    "bedding": {"dimensions": ("What size is your duvet?", "Cover/duvet fit")},
}

# Finite relations apply only to coupled fields. Other attributes keep open numeric
# domains and open sets: sampling values are not a universe of all possible facts.
RELATIONS = {
    "footwear": [{"id": "authored-shoe-type-activity", "fields": ["shoe_type", "activity"],
                  "rows": [["walking shoes", "walking"], ["running shoes", "running"],
                           ["hiking shoes", "hiking"], ["dress shoes", "formal"], ["flip-flops", "beach"]]}],
    "beer": [{"id": "beer-production-location", "fields": ["origin_country", "production_region"],
              "rows": [["Sweden", "Uppsala"], ["Sweden", "Skåne"], ["Germany", "Bavaria"],
                       ["Belgium", "Flanders"], ["United Kingdom", "Kent"]]}],
    "ssd": [{"id": "ssd-interface-form", "fields": ["interface", "form_factor"], "rows": [
        ["SATA", "2.5-inch"], ["SATA", "M.2 2280"], ["SATA", "M.2 2230"],
        ["NVMe PCIe 4.0", "M.2 2280"], ["NVMe PCIe 4.0", "M.2 2230"],
        ["NVMe PCIe 5.0", "M.2 2280"], ["NVMe PCIe 5.0", "M.2 2230"]]}],
    "cookware": [{"id": "pan-body-base-induction", "fields": ["material", "base", "induction"], "rows": [
        ["aluminium", "bonded magnetic base", True], ["aluminium", "bare aluminium base", False],
        ["stainless steel", "bonded magnetic base", True], ["stainless steel", "magnetic stainless base", True],
        ["stainless steel", "nonmagnetic stainless base", False], ["cast iron", "cast iron base", True]]}],
}

# Scoped implications. Marketing claims and personal preferences imply nothing.
IMPLICATIONS = {
    "chargers": [("pps-includes-pd", ("protocols", "contains", "USB PD PPS"), ("protocols", "contains", "USB PD"))],
    "dog_food": [("recipe-contains-" + v, ("recipe", "eq", v), ("ingredients", "contains", v)) for v in ("chicken", "salmon", "lamb")],
    "cat_food": [("recipe-contains-" + v, ("recipe", "eq", v), ("ingredients", "contains", v)) for v in ("chicken", "salmon", "turkey")],
}
ORDERED_PAIRS = {"board_games": [("min_players", "max_players")],
                 "pet_harnesses": [("chest_min_cm", "chest_max_cm")]}


def key(p):
    return p["field"], p["operator"], p["value"]


def holds(p, value):
    op, expected = p["operator"], p["value"]
    if op == "eq": return value == expected
    if op == "ge": return value >= expected
    if op == "le": return value <= expected
    if op == "contains": return expected in value
    if op == "excludes": return expected not in value
    raise ValueError("Unknown operator: " + op)


def closure(family_id, predicates):
    result = copy.deepcopy(predicates)
    used = []
    while True:
        known = {key(p) for p in result}
        added = []
        for rule, antecedent, consequent in IMPLICATIONS.get(family_id, []):
            if antecedent in known and consequent not in known:
                field, op, value = consequent
                added.append({"field": field, "operator": op, "value": value})
                used.append(rule)
        if not added:
            return result, sorted(set(used))
        result.extend(added)


def _bounds(predicates, field):
    low, high = float('-inf'), float('inf')
    for p in predicates:
        if p['field'] != field or type(p['value']) not in (int, float): continue
        if p['operator'] in ('eq', 'ge'): low = max(low, p['value'])
        if p['operator'] in ('eq', 'le'): high = min(high, p['value'])
    return low, high


def conflicts(family_id, predicates):
    expanded, _ = closure(family_id, predicates)
    errors = []
    for field in sorted({p['field'] for p in expanded}):
        ps = [p for p in expanded if p['field'] == field]
        eqs = [p['value'] for p in ps if p['operator'] == 'eq']
        if eqs and any(not holds(p, eqs[0]) for p in ps):
            errors.append('incompatible predicates: ' + field)
        if _bounds(ps, field)[0] > _bounds(ps, field)[1]:
            errors.append('empty numeric interval: ' + field)
        inc = {p['value'] for p in ps if p['operator'] == 'contains'}
        exc = {p['value'] for p in ps if p['operator'] == 'excludes'}
        if inc & exc: errors.append('included and excluded: ' + field)
    for relation in RELATIONS.get(family_id, []):
        ps = [p for p in expanded if p['field'] in relation['fields']]
        if not any(all(holds(p, dict(zip(relation['fields'], row))[p['field']]) for p in ps)
                   for row in relation['rows']):
            errors.append(relation['id'])
    for low, high in ORDERED_PAIRS.get(family_id, []):
        if _bounds(expanded, low)[0] > _bounds(expanded, high)[1]:
            errors.append('reversed endpoints: ' + low + '/' + high)
    return sorted(set(errors))


def entails(family_id, predicates, candidate):
    if conflicts(family_id, predicates): return False
    expanded, _ = closure(family_id, predicates)
    if key(candidate) in {key(p) for p in expanded}: return True
    field, op, value = key(candidate)
    same = [p for p in expanded if p['field'] == field]
    if any(p['operator'] == 'eq' and holds(candidate, p['value']) for p in same): return True
    lo, hi = _bounds(same, field)
    if op == 'ge' and lo >= value: return True
    if op == 'le' and hi <= value: return True
    for relation in RELATIONS.get(family_id, []):
        if field not in relation['fields']: continue
        rows = [dict(zip(relation['fields'], row)) for row in relation['rows']]
        rows = [r for r in rows if all(holds(p, r[p['field']]) for p in expanded if p['field'] in r)]
        if rows and all(holds(candidate, row[field]) for row in rows): return True
    return False


def minimize(family_id, predicates):
    """Drop redundancies only when entailed by what remains, preserving equivalence."""
    if conflicts(family_id, predicates): raise ValueError('Contradictory intent')
    kept = copy.deepcopy(predicates)
    removed = []
    for p in reversed(list(kept)):
        rest = kept.copy()
        rest.remove(p)
        if entails(family_id, rest, p):
            kept.remove(p)
            removed.append({"predicate": p, "reason": "entailed_by_remaining_requirements"})
    return kept, removed


def sample_requirements(family, count, rng, atom):
    """Sample coherent intent incrementally, never inspect offers or winning SKUs."""
    essentials = BLOCKERS.get(family.id, {})
    attrs = list(family.attributes)
    rng.shuffle(attrs)
    attrs.sort(key=lambda a: a.key not in essentials)
    selected = []
    skipped = []
    for attr in attrs:
        if len(selected) >= max(count, len(essentials)): break
        values = list(attr.values)
        rng.shuffle(values)
        for value in values:
            p = atom(attr, value)
            if not conflicts(family.id, selected + [p]):
                selected.append(p)
                break
        else:
            skipped.append({"field": attr.key, "reason": "no_consistent_value_in_authored_domain"})
    minimal, redundant = minimize(family.id, selected)
    return minimal, {"redundant": redundant, "skipped": skipped}


def review_catalog():
    """Every family has an explicit review entry; independent does not mean feasible."""
    notes = {
        'cookware': 'Body material alone does not determine induction suitability; base construction does.',
        'ssd': 'NVMe requires an M.2 form in this authored vocabulary; 2.5-inch implies SATA.',
        'chargers': 'PPS extends USB PD; wattage does not guarantee a particular device charging speed.',
        'dog_food': 'Recipe denotes presence of the named protein, not absence of other proteins.',
        'cat_food': 'Recipe denotes presence of the named protein, not absence of other proteins.',
        'pet_harnesses': 'Fit interval endpoints must be ordered; no inferred universal species-to-size mapping.',
        'board_games': 'Player-count endpoints must be ordered; language and play time are independent.',
        'trousers': 'Material blends can include several fibres; a fibre cannot simultaneously be required and excluded. Waist and inseam are independent personal fit dimensions.',
        'beer': 'Production region must match country. Locality requires a user location/scope. Bitterness is a producer-described tasting attribute, not guaranteed taste or an inference from style. Pack volume and cart quantity differ.',
        'wine': 'Colour and sparkling status are separate. Grape variety alone does not determine colour, sweetness, vintage or origin; no such implication is inferred. Volume is per bottle.',
    }
    return {id: {"blockers": list(BLOCKERS.get(id, {})),
                 "relations": RELATIONS.get(id, []), "implications": IMPLICATIONS.get(id, []),
                 "ordered_pairs": ORDERED_PAIRS.get(id, []),
                 "review": notes.get(id, 'No additional hard cross-field rule in the current vocabulary. Fit, dimensions and composition use generic consistency checks; no correlation is promoted to an implication.')}
            for id in FAMILIES}
