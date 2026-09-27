import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from .catalog import FAMILIES
from .generator import MEMORY_MODES, QUERY_PRESETS, generate, resolve, semantic_key
from .semantics import conflicts, entails, BLOCKERS


def test_deterministic_and_prose_independent():
    a = generate(21, "laptops", memory="mixed")
    assert a == generate(21, "laptops", memory="mixed")
    b = generate(21, "laptops", memory="mixed", prose_seed=98)
    assert a["resolved_task"] == b["resolved_task"]
    assert a["semantic_sha256"] == b["semantic_sha256"]


def test_no_memory_is_explicit_and_no_fillers():
    b = generate(3, "dog_food", memory="none", requirements=6, hidden="none")
    assert b["public"]["memories"] == {"profile": [], "episodes": []}
    assert b["memory_facts"] == []
    assert all(p["source"]["kind"] == "request" for p in b["resolved_task"]["lines"][0]["requirements"])


def test_mixed_has_both_channels():
    b = generate(4, "foundation", memory="mixed", requirements=3, hidden="none")
    assert b["public"]["memories"]["profile"]
    assert b["public"]["memories"]["episodes"]


def test_temporary_override_changes_current_not_durable():
    b = generate(13, "footwear", memory="override", requirements=5, hidden="none")
    before = copy.deepcopy(b["memory_facts"])
    line = b["request"]["lines"][0]
    p = next(p for p in line["explicit_requirements"] if p.get("temporary_override"))
    old = next(m for m in before if semantic_key(m["predicate"]) == semantic_key(p))
    assert old["predicate"]["value"] != p["value"]
    resolved = resolve(b["request"], b["memory_facts"])
    assert next(x for x in resolved["lines"][0]["requirements"] if semantic_key(x) == semantic_key(p))["value"] == p["value"]
    assert b["memory_facts"] == before
    assert b["expected_memory_delta"] == {"create": [], "update": [], "delete": []}
    assert any(s["stage"] == "override" for s in b["authoring"]["message_segments"])


def test_irrelevant_subject_and_family_do_not_apply():
    b = generate(15, "footwear", memory="none", hidden="none")
    foreign = generate(16, "dog_food", memory="profile")["memory_facts"]
    wrong_person = generate(15, "footwear", memory="profile")["memory_facts"]
    for fact in wrong_person:
        fact["subject"] = "my brother"
    assert resolve(b["request"], foreign + wrong_person) == b["resolved_task"]


def test_explicit_memory_placement_preserves_intent():
    a = generate(8, "laptops", memory="none")["resolved_task"]
    b = generate(8, "laptops", memory="profile")["resolved_task"]
    for task in (a, b):
        for p in task["lines"][0]["requirements"]:
            p.pop("source")
    assert a == b


def test_query_composition_and_custom_budget():
    b = generate(3, "dog_food,drills,books", query="split_basket", budget_sek=1000)
    assert len(b["resolved_task"]["lines"]) == 3
    assert b["resolved_task"]["constraints"]["budget_minor"] == 100000
    assert b["resolved_task"]["query"]["allocation"] == "split_allowed"
    fast = generate(3, "laptops", query="fastest", budget_sek=1000)
    assert fast["resolved_task"]["query"]["objective"][0]["field"] == "arrival_days"
    assert fast["resolved_task"]["constraints"]["budget_minor"] == 100000
    avg = generate(3, "books", query="average")
    assert avg["resolved_task"]["lines"][0]["model"] is not None
    assert "shop" in avg["public"]["user_message"]
    assert {generate(seed, query="random")["settings"]["resolved_query"] for seed in range(100)} == set(QUERY_PRESETS)


def _audit_family(family_id):
    for query in QUERY_PRESETS:
        for memory in MEMORY_MODES:
            for seed in range(8):
                b = generate(seed, family_id, query, memory, requirements=6)
                assert resolve(b["request"], b["memory_facts"]) == b["initial_accessible_task"]
                # Every effective requirement has an accessible or targeted-answer source.
                pub = b["public"]
                for line in b["resolved_task"]["lines"]:
                    assert not conflicts(line["family_id"], line["requirements"])
                    durable = [f["predicate"] for f in b["memory_facts"] if f["family_id"] == line["family_id"]]
                    assert not conflicts(line["family_id"], durable)
                    keys = [semantic_key(p) for p in line["requirements"]]
                    assert len(keys) == len(set(keys))
                    for p in line["requirements"]:
                        src = p["source"]
                        if src["kind"] == "request":
                            assert any(line["id"] + ":" + p["field"] + ":" + p["operator"] in s["sources"] for s in b["authoring"]["message_segments"])
                        elif src["kind"] == "clarification":
                            h = next(h for h in b["hidden_user_specifications"] if h["id"] == src["id"])
                            assert h["predicate"]["value"] == p["value"]
                            assert p["field"] in BLOCKERS[line["family_id"]]
                        elif src["channel"] == "episodic":
                            entry = next(x for x in pub["memories"]["episodes"] if x["id"] == src["id"])
                            assert entry["text"]
                            if p["value_type"] != "boolean":
                                spelling = {"puppy": "puppies", "kitten": "kittens"}.get(p["value"], str(p["value"]).lower())
                                assert spelling in entry["text"].lower()
                        else:
                            entry = next(x for x in pub["memories"]["profile"] if x["id"] == src["id"])
                            assert (entry["value"], entry["operator"], entry["unit"]) == (p["value"], p["operator"], p["unit"])
                    recipe = next((p["value"] for p in line["requirements"] if p["field"] == "recipe"), None)
                    excluded = {p["value"] for p in line["requirements"] if p["operator"] == "excludes"}
                    assert recipe is None or recipe not in excluded
                # Private semantics and provenance do not accidentally enter projection.
                serialized = json.dumps(pub)
                for key in ("semantic_sha256", "reference_sek", "resolved_task", "temporary_override", "candidate_id", "hidden_user_specifications"):
                    assert key not in serialized
                assert not b["resolved_task"]["authorization"]["purchase"]
                assert "\n" not in pub["user_message"]
                assert "Research and report only" not in pub["user_message"]
                assert "".join(s["text"] for s in b["authoring"]["message_segments"]) == pub["user_message"]
    return family_id


def test_bounded_cross_family_contract_audit():
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert set(pool.map(_audit_family, FAMILIES)) == set(FAMILIES)


@pytest.mark.parametrize("kwargs", [dict(seed=True), dict(family="unicorns"), dict(query="invented"),
    dict(memory="fake"), dict(requirements=0), dict(requirements=2.5), dict(budget_sek=-3),
    dict(family="books,books", query="basket"), dict(prose_seed=True)])
def test_invalid_inputs_fail(kwargs):
    with pytest.raises(ValueError):
        generate(**kwargs)
