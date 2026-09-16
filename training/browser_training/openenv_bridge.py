"""Interface adapter, not a new rollout engine. Caller supplies the upstream client.

Client creation/transport belongs to the environment service deployment. Follow the
pinned OpenEnv BrowserGym client; attach our deterministic verifier via outcome_fn.
The default outcome is deliberately not inferred from a scalar BrowserGym reward.
"""
from .environment import Outcome


class OpenEnvBackend:
    def __init__(self, client_factory, action_factory, outcome_fn):
        # AsyncGRPO calls reset synchronously from an active asyncio loop. The
        # explicit OpenEnv wrapper prevents reset/step from returning coroutines.
        self.client = client_factory().sync()
        self._action_factory, self._outcome_fn = action_factory, outcome_fn

    def reset(self, *, task, seed):
        result = self.client.reset(task_name=task, seed=seed)
        return self._observation(result)

    def step(self, action):
        result = self.client.step(self._action_factory(action_str=action))
        outcome = self._outcome_fn(result)
        if not isinstance(outcome, Outcome):
            raise TypeError("Verifier callback must return Outcome")
        return self._observation(result), bool(result.done), outcome

    def close(self):
        self.client.close()

    @staticmethod
    def _observation(result):
        observation = result.observation
        # The goal is separate from the accessibility tree in the upstream schema.
        # Dropping it leaves environment-owned datasets without task instructions.
        parts = []
        for label, field in (("Task", "goal"), ("URL", "url")):
            value = getattr(observation, field, "")
            if value:
                parts.append(f"{label}: {value}")
        parts.append(observation.axtree_txt or observation.text)
        if getattr(observation, "error", ""):
            parts.append(f"Action error: {observation.error}")
        elif getattr(observation, "last_action_error", False):
            parts.append("The last browser action failed.")
        return "\n".join(parts)
