from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from browser_training.curriculum import FamilySampler, SamplerConfig
from browser_training.outcomes import Ledger, snapshot
from test_outcome_metrics import episode, ledger


def task(family="checkout", template="insurance"):
    return dict(task_id=family, task_family=family, task_template=template, split="rl_train",
                harness_revision="h1", verifier_revision="v1", environment_revision="site1",
                tokenizer_revision="fixture-tokenizer-v1")


def add_group(ledger, group, family, rewards, **changes):
    for i, reward in enumerate(rewards):
        event = episode(i, group_id=group, episode_id=f"{group}-{i}", task_family=family,
                        goal_completed=bool(reward), reward=reward, **changes)
        ledger.append(event)


def test_adaptive_prefers_intermediate_with_nonzero_rehearsal(ledger):
    for family, rewards in (("easy", [1, 1]), ("middle", [1, 0]), ("hard", [0, 0])):
        for i in range(10):
            add_group(ledger, f"{family}-{i}", family, rewards)
    sampler = FamilySampler([task(f) for f in ("easy", "middle", "hard")], SamplerConfig(mode="adaptive"))
    d = sampler.refresh(ledger, policy_version=4, now=150)
    p = d["probabilities"]
    assert p["middle"] > p["easy"] == pytest.approx(p["hard"])
    assert min(p.values()) >= 0.2/3
    assert sum(p.values()) == pytest.approx(1)
    assert d["evidence"]["middle"]["groups"] == 10
    baseline = FamilySampler(sampler.tasks)
    assert set(baseline.refresh(ledger, policy_version=4, now=150)["probabilities"].values()) == {1/3}


def test_sparse_or_unknown_families_stay_exploratory(ledger):
    add_group(ledger, "one", "checkout", [1, 1])
    sampler = FamilySampler([task(), task("unknown")], SamplerConfig(mode="adaptive"))
    assert sampler.refresh(ledger, policy_version=4, now=150)["probabilities"] == {"checkout": 0.5, "unknown": 0.5}


def test_only_recent_verified_train_groups_influence_curriculum(ledger):
    add_group(ledger, "valid", "checkout", [1, 0])
    add_group(ledger, "dev", "checkout", [1, 1], split="model_dev")
    add_group(ledger, "old-policy", "checkout", [1, 1], policy_version=0)
    add_group(ledger, "new-policy", "checkout", [1, 1], policy_version=10)
    add_group(ledger, "other-verifier", "checkout", [1, 1], verifier_revision="unqualified")
    event = episode(0, episode_id="unknown", group_id="unknown", goal_completed=None,
                    constraints_satisfied=None, unauthorized_effect=None, reward=None)
    ledger.append(event)
    broken = episode(0, episode_id="broken", group_id="broken", status="infra_error", goal_completed=None,
                     constraints_satisfied=None, unauthorized_effect=None, reward=None)
    ledger.append(broken)
    sampler = FamilySampler([task()], SamplerConfig(mode="adaptive"))
    d = sampler.refresh(ledger, policy_version=4, now=150)
    assert d["evidence"]["checkout"]["episodes"] == 2
    assert d["excluded"] == {"nontraining_slots": 2, "old_policy_slots": 2, "future_policy_slots": 2,
                             "provenance_mismatch_slots": 2, "unverified_slots": 1, "execution_error_slots": 1}
    assert sampler.refresh(ledger, policy_version=4, now=10000)["evidence"]["checkout"]["episodes"] == 0


def test_durable_group_draw_and_checkpoint_resume(ledger, tmp_path):
    sampler = FamilySampler([task(), task("other")])
    sampler.refresh(ledger, policy_version=4, now=150)
    first = sampler.draw(ledger, group_id="g0", group_size=2, policy_version=4, now=160)
    state = json.loads(json.dumps(sampler.state_dict()))
    next_draw = sampler.draw(ledger, group_id="g1", group_size=2, policy_version=4, now=161)
    restored = FamilySampler(sampler.tasks)
    restored.load_state_dict(state)
    assert restored.draw(ledger, group_id="g0", group_size=2, policy_version=4, now=200) == first
    assert restored.draw(ledger, group_id="g1", group_size=2, policy_version=4, now=200) == next_draw
    # Checkpoint restores probability state; keyed randomness yields the same NEW draw.
    ledger.backup(tmp_path / "restored.sqlite")
    independent = Ledger(tmp_path / "restored.sqlite", run_id="test", synthetic=True, expected_producers=["browser", "trainer"])
    assert restored.draw(independent, group_id="g2", group_size=2, policy_version=4, now=200) == sampler.draw(
        ledger, group_id="g2", group_size=2, policy_version=4, now=200)
    assert snapshot(ledger, now=200)["curriculum"]["all"]["draws"] == 3
    with pytest.raises(ValueError, match="intent"):
        restored.draw(ledger, group_id="g0", group_size=2, policy_version=5, now=200)


def test_concurrent_same_group_draw_does_not_allocate_twice(ledger):
    sampler = FamilySampler([task()])
    sampler.refresh(ledger, policy_version=4, now=150)
    def draw(i):
        return sampler.draw(ledger, group_id="same", group_size=2, policy_version=4, now=160+i)
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(draw, range(4)))
    assert all(p == result[0] for p in result)
    assert len(ledger.records()) == 1


def test_observation_cannot_change_committed_group_identity(ledger):
    sampler = FamilySampler([task()])
    sampler.refresh(ledger, policy_version=4, now=150)
    draw = sampler.draw(ledger, group_id="g0", group_size=2, policy_version=4, now=160)
    with pytest.raises(ValueError, match="committed"):
        ledger.append(episode())  # Wrong seed/instance for the actual draw.
    e = episode(seed=draw["seed"], task_instance=draw["task_instance"])
    e["occurred_at"] = 170
    ledger.append(e)
    assert len(ledger.records()) == 2


def test_bad_pool_or_checkpoint_rejected(ledger):
    with pytest.raises(ValueError, match="Dev/test"):
        FamilySampler([{**task(), "split": "final_test"}])
    with pytest.raises(ValueError):
        SamplerConfig(exploration=0)
    sampler = FamilySampler([task()])
    sampler.refresh(ledger, policy_version=4, now=150)
    state = sampler.state_dict()
    state["distribution"]["probabilities"]["checkout"] = 0
    with pytest.raises(ValueError, match="checksum"):
        sampler.load_state_dict(state)
    with pytest.raises(ValueError, match="expired"):
        sampler.draw(ledger, group_id="late", group_size=2, policy_version=4, now=10000)


def test_requested_and_realized_allocation_are_separate(ledger):
    from browser_training.monitoring_io import curriculum_rows, scalar_metrics, agent_summary
    sampler = FamilySampler([task(), task("other")])
    sampler.refresh(ledger, policy_version=4, now=150)
    p = sampler.draw(ledger, group_id="one", group_size=2, policy_version=4, now=160)
    value = snapshot(ledger, now=200)
    data = value["curriculum"]["all"]
    assert data["latest"]["probabilities"] == {"checkout": 0.5, "other": 0.5}
    assert data["realized_fractions"] == {p["task_family"]: 1}
    assert scalar_metrics(value)["curriculum/all/draws"] == 1
    assert len(curriculum_rows(value)[1]) == 4
    assert agent_summary(value)["curriculum"] == value["curriculum"]


def test_checkpoint_cannot_silently_reference_lost_ledger_events(ledger, tmp_path):
    add_group(ledger, "valid", "checkout", [1, 0])
    sampler = FamilySampler([task()])
    sampler.refresh(ledger, policy_version=4, now=150)
    empty = Ledger(tmp_path / "older.sqlite", run_id="test", synthetic=True, expected_producers=["browser", "trainer"])
    with pytest.raises(ValueError, match="ahead"):
        sampler.draw(empty, group_id="new", group_size=2, policy_version=4, now=160)
