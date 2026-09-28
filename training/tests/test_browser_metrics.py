from types import SimpleNamespace

import pytest

from browser_training.browser_metrics import BrowserEpisodeObserver, fixture_verification
from browser_training.outcomes import snapshot
from test_outcome_metrics import episode, ledger


def result(raw=None, *, done=True, reward=1):
    return SimpleNamespace(done=done, reward=reward,
                           observation=SimpleNamespace(metadata={"browsergym_info": {"task_info": {"outcome": raw or {}}}}))


def test_missing_verification_not_inferred_from_positive_reward(ledger):
    observer = BrowserEpisodeObserver(episode()["payload"], episode_id="real", member=0)
    observer.observe(result(), action=True)
    event = observer.finish(occurred_at=100)
    assert event["payload"]["goal_completed"] is None
    assert event["payload"]["unauthorized_effect"] is None
    assert event["payload"]["reward"] is None
    ledger.append(event)
    assert snapshot(ledger, now=200)["cohorts"]["rl_train"]["all"]["metrics"]["safe_completion"]["value"] is None


def test_browser_state_maps_exactly_without_token_invention(ledger):
    clock = iter([10, 13])
    observer = BrowserEpisodeObserver(episode()["payload"], episode_id="real", member=0, clock=lambda: next(clock))
    observer.observe(result(done=False), action=False)
    observer.observe(result(dict(goal_completed=True, user_constraints_satisfied=True,
                                 no_unauthorized_subscription=True, no_unwanted_addon=True)), action=True)
    e = observer.finish(occurred_at=100)
    assert e["payload"]["duration_s"] == 3
    assert e["payload"]["steps"] == 1
    assert e["payload"]["generated_tokens"] is None
    assert e["payload"]["reward"] == 1
    assert observer.finish() == e
    assert ledger.append(e) == ledger.append(observer.finish())
    with pytest.raises(ValueError, match="already finished"):
        observer.observe(result(), action=True)


def test_error_and_cancel_do_not_claim_task_failure():
    for status in ("infra_error", "cancelled"):
        observer = BrowserEpisodeObserver(episode()["payload"], episode_id="error", member=0)
        e = observer.finish(status=status)
        assert e["payload"]["reward"] is None and e["payload"]["goal_completed"] is None


def test_partial_verifier_and_nonterminal_rejected():
    assert fixture_verification(result(dict(no_unauthorized_subscription=True)))["unauthorized_effect"] is None
    assert fixture_verification(result(dict(no_unauthorized_subscription=False)))["unauthorized_effect"] is True
    observer = BrowserEpisodeObserver(episode()["payload"], episode_id="early", member=0)
    observer.observe(result(done=False), action=True)
    with pytest.raises(ValueError, match="terminal"):
        observer.finish()
