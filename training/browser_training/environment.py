"""TRL's environment_factory contract. No trainer, browser or GPU import required."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Outcome:
    goal_completed: bool = False
    no_unauthorized_subscription: bool = False
    no_unwanted_addon: bool = False
    user_constraints_satisfied: bool = False


def deterministic_reward(outcome: Outcome) -> float:
    return float(all(value is True for value in vars(outcome).values()))


class BrowserBackend(Protocol):
    def reset(self, *, task: str, seed: int) -> str: ...
    def step(self, action: str) -> tuple[str, bool, Outcome]: ...
    def close(self) -> None: ...


class MockBackend:
    """Two tool turns, deterministic state reward, no browser or network."""
    def reset(self, *, task, seed):
        self.stage = 0
        return "Button [1] opens the form. Click it, then fill [2] with 'yes'."

    def step(self, action):
        if self.stage == 0 and action == "click('1')":
            self.stage = 1
            return "Input [2] is ready.", False, Outcome()
        if self.stage == 1 and action == "fill('2', 'yes')":
            self.stage = 2
            return "Task complete. Stop.", True, Outcome(True, True, True, True)
        return "Invalid action. Stop.", True, Outcome()

    def close(self):
        pass


class BrowserToolEnv:
    """Picklable factory with one backend per episode; private lifecycle methods aren't tools.

    Replace backend_factory with a module-level factory implementing BrowserBackend.
    In pinned AsyncGRPO, get_reward is the supported state-based reward hook.
    """
    def __init__(self, backend_factory=MockBackend, reward_callback=deterministic_reward, max_steps=8):
        self._backend_factory = backend_factory
        self._reward_callback = reward_callback
        self._max_steps = max_steps
        self._backend = None

    def reset(self, task="mock", seed=42, **kwargs):
        self._close()
        self._backend = self._backend_factory()
        self._outcome, self._done, self._steps = Outcome(), False, 0
        try:
            return self._backend.reset(task=task, seed=seed)
        except Exception:
            self._close()
            raise

    def browser_action(self, action: str) -> str:
        """Execute one browser action and return the next observation.

        Args:
            action: A single BrowserGym action, for example click('1').
        """
        if self._done:
            raise ValueError("Episode ended; stop calling tools")
        observation, done, self._outcome = self._backend.step(action)
        self._steps += 1
        self._done = done or self._steps >= self._max_steps
        return observation + ("\nEpisode ended." if self._done else "")

    def get_reward(self) -> float:
        try:
            return self._reward_callback(self._outcome) if self._done else 0.0
        finally:
            self._close()

    def _close(self):
        if self._backend is not None:
            self._backend.close()
            self._backend = None


class OneTurnMockEnv:
    """Environment lifecycle plumbing ONLY; no tools, so the upstream version bug is avoided.

    The seed selects a deterministic outcome independently of model text. Rewards within
    a group are identical: this tests GRPO/sync/checkpoints, NOT learning improvement.
    """
    def reset(self, seed=42, **kwargs):
        self._outcome = Outcome(seed % 2 == 0, True, True, True)
        return "Mock browser episode ended. Reply 'done'."

    def get_reward(self):
        return deterministic_reward(self._outcome)
