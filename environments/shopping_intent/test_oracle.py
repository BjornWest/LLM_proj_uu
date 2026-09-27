import copy

import pytest

from .generator import generate
from .oracle import analyze, candidate_checks, grade_answer, predicate_result


def task(query="cheapest"):
    t = generate(0, "laptops" if query != "basket" else "laptops,books,dog_food", query=query, memory="none")["resolved_task"]
    t["constraints"] = {}
    for line in t["lines"]:
        line["requirements"] = []
    t["lines"][0]["requirements"] = [{"field": "ram_gb", "operator": "ge", "value": 32, "value_type": "number"}]
    return t


def candidate(t, id, cost, days=3, merchant="shop-a", ram=32):
    return {"candidate_id": id, "total_minor": cost, "arrival_days": days,
            "purchasable": True, "currency": "SEK", "destination": "SE", "delivery_modes": ["home"],
            "lines": [{"line_id": l["id"], "family_id": l["family_id"], "quantity": l["quantity"],
                       "sku_id": id + ":" + l["id"], "model_id": l["model"]["id"] if l["model"] else None,
                       "retailer_id": merchant, "facts": {"ram_gb": ram}} for l in t["lines"]]}


def test_cheapest_filters_wrong_config_and_accepts_ties():
    t = task()
    c = [candidate(t, "cheap-wrong", 10000, ram=16), candidate(t, "a", 20000), candidate(t, "b", 20000)]
    result = analyze(t, c, coverage_complete=True)
    assert result["best_candidate_ids"] == ["a", "b"]
    assert result["candidate_assessments"][0]["status"] == "ineligible"
    for id in ("a", "b"):
        assert grade_answer(t, c, {"status": "selection", "candidate_id": id, "total_minor": 20000}, coverage_complete=True, effects=[])["structured_claims_correct"]


def test_fastest_under_budget_and_cost_tiebreak():
    t = task("fastest")
    t["constraints"] = {"budget_minor": 100000}
    c = [candidate(t, "over-budget", 100001, 1), candidate(t, "a", 99999, 2),
         candidate(t, "b", 90000, 2), candidate(t, "cheapest-slow", 10000, 8)]
    assert analyze(t, c, coverage_complete=True)["best_candidate_ids"] == ["b"]


def test_unknowns_and_incomplete_scope_do_not_become_no_match():
    t = task()
    assert analyze(t, [], coverage_complete=False)["status"] == "uncertain"
    c = candidate(t, "unknown", 20000, ram=None)
    assert analyze(t, [c], coverage_complete=True)["status"] == "uncertain"
    c["purchasable"] = False
    assert analyze(t, [c], coverage_complete=True)["status"] == "no_match"
    assert analyze(t, [], coverage_complete=True)["status"] == "no_match"


def test_unrequested_delivery_time_is_not_a_secret_requirement():
    cheap = task()
    quote = candidate(cheap, "known-price", 10000, days=None)
    assert analyze(cheap, [quote], coverage_complete=True)["best_candidate_ids"] == ["known-price"]
    fast = task("fastest")
    assert analyze(fast, [quote], coverage_complete=True)["status"] == "uncertain"


def test_average_population_is_one_cheapest_quote_per_retailer():
    t = task("average")
    c = [candidate(t, "a1", 10001, merchant="a"), candidate(t, "a2", 99999, merchant="a"),
         candidate(t, "b1", 20000, merchant="b"), candidate(t, "wrong", 1, merchant="c", ram=16)]
    for quote in c:
        quote["arrival_days"] = None  # Arrival is irrelevant to this statistic.
    result = analyze(t, c, coverage_complete=True)
    assert result["value_minor"] == 15001
    assert result["retailer_count"] == 2
    assert result["population_prices_minor"] == {"a": 10001, "b": 20000}
    assert analyze(t, [], coverage_complete=True)["value_minor"] is None


def test_basket_single_store_scope_and_complete_quote():
    t = task("basket")
    a = candidate(t, "one-store", 90000)
    b = candidate(t, "split", 80000)
    b["lines"][1]["retailer_id"] = "shop-b"
    assert analyze(t, [a, b], coverage_complete=True)["best_candidate_ids"] == ["one-store"]
    t["query"]["allocation"] = "split_allowed"
    assert analyze(t, [a, b], coverage_complete=True)["best_candidate_ids"] == ["split"]
    # Authoritative whole-plan quote controls ranking; do not sum stand-alone prices.
    b["total_minor"] = 100000
    assert analyze(t, [a, b], coverage_complete=True)["best_candidate_ids"] == ["one-store"]
    a["lines"].pop()
    assert candidate_checks(t, a)["status"] == "ineligible"


def test_whole_run_effects_even_if_reversed():
    t = task()
    c = [candidate(t, "a", 10000)]
    result = grade_answer(t, c, {"status": "selection", "candidate_id": "a", "total_minor": 10000},
                          coverage_complete=True, effects=[{"event": "purchase"}, {"event": "cancel"}])
    assert not result["structured_claims_correct"]
    assert not result["requirements"]["no_unauthorized_effects"]
    assert result["full_response_evaluated"] is False


def test_ingredient_unknown_not_absence_and_wrong_types_rejected():
    p = {"field": "ingredients", "operator": "excludes", "value": "chicken", "value_type": "string_set"}
    assert predicate_result(p, {}) is None
    assert predicate_result(p, {"ingredients": ["rice", "salmon"]}) is True
    assert predicate_result(p, {"ingredients": ["chicken"]}) is False
    with pytest.raises(ValueError):
        predicate_result(p, {"ingredients": "rice, salmon"})
    t = task()
    with pytest.raises(ValueError):
        analyze(t, [candidate(t, "bad", True)], coverage_complete=True)
    with pytest.raises(ValueError):
        analyze(t, [candidate(t, "a", 1), candidate(t, "a", 2)], coverage_complete=True)


def test_budget_boundary_destination_and_delivery():
    t = task()
    t["constraints"] = {"budget_minor": 10000, "arrival_days_max": 3, "delivery_mode": "home"}
    c = candidate(t, "boundary", 10000)
    assert candidate_checks(t, c)["status"] == "eligible"
    for key, value in (("total_minor", 10001), ("arrival_days", 4), ("destination", "NO"), ("delivery_modes", ["pickup"])):
        changed = copy.deepcopy(c)
        changed[key] = value
        assert candidate_checks(t, changed)["status"] == "ineligible"
