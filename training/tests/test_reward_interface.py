import pickle
import pytest
from types import SimpleNamespace
from browser_training.environment import BrowserToolEnv, Outcome, deterministic_reward
from browser_training.openenv_bridge import OpenEnvBackend


def test_mock_episode_and_reset():
    env = pickle.loads(pickle.dumps(BrowserToolEnv()))
    env.reset()
    assert "[2]" in env.browser_action("click('1')")
    env.browser_action("fill('2', 'yes')")
    assert env.get_reward() == 1.0
    env.reset()
    env.browser_action("subscribe()")
    assert env.get_reward() == 0.0


@pytest.mark.parametrize("field", list(Outcome.__dataclass_fields__))
def test_constraint_failure_cannot_earn_reward(field):
    fields = dict.fromkeys(Outcome.__dataclass_fields__, True)
    fields[field] = False
    assert deterministic_reward(Outcome(**fields)) == 0.0


def test_incomplete_episode_has_no_reward():
    env = BrowserToolEnv()
    env.reset()
    assert env.get_reward() == 0


def test_openenv_client_contract():
    result = SimpleNamespace(observation=SimpleNamespace(axtree_txt="[1] Button", text=""), done=True)
    class Client:
        def sync(self): return self
        def reset(self, *, task_name, seed):
            assert task_name == "click-test" and seed == 42
            return result
        def step(self, action):
            assert action.action_str == "click('1')"
            return result
        def close(self): self.closed = True
    backend = OpenEnvBackend(Client, SimpleNamespace, lambda result: Outcome(True, True, True, True))
    assert backend.reset(task="click-test", seed=42) == "[1] Button"
    assert backend.step("click('1')")[1] is True
    backend.close()
    assert backend.client.closed


def test_openenv_preserves_task_goal_and_error():
    obs = SimpleNamespace(goal="Buy only the requested item", url="http://local/cart",
                          axtree_txt="[2] Buy", text="fallback", error="Element not found")
    rendered = OpenEnvBackend._observation(SimpleNamespace(observation=obs))
    assert obs.goal in rendered and obs.url in rendered and obs.error in rendered
    assert "[2] Buy" in rendered and "fallback" not in rendered


def test_failed_reset_releases_backend():
    class FailingBackend:
        closed = False
        def reset(self, **kwargs): raise RuntimeError("reset transport failed")
        def close(self): self.closed = True
    backend = FailingBackend()
    env = BrowserToolEnv(backend_factory=lambda: backend)
    with pytest.raises(RuntimeError, match="transport failed"):
        env.reset()
    assert backend.closed and env._backend is None
