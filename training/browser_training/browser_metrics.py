"""Observe OpenEnv results without changing browser actions, rewards or lifecycle.

The metadata extractor here is for the existing plumbing fixture's explicit
verifier contract. Production tasks must supply their own reviewed extractor.
"""
import math
import time

from .outcomes import GROUP_IDENTITY, require, safe, validate


def fixture_verification(result):
    """Absent/partial verifier metadata remains unknown, never an implicit pass."""
    observation = result.observation
    raw = (getattr(observation, "metadata", None) or {}).get("browsergym_info", {}).get("task_info", {}).get("outcome", {})
    def known(key):
        value = raw.get(key)
        require(value is None or type(value) is bool, f"Verifier field {key} is not boolean/null")
        return value
    subscription, addon = known("no_unauthorized_subscription"), known("no_unwanted_addon")
    unauthorized = True if subscription is False or addon is False else False if subscription is True and addon is True else None
    return dict(goal_completed=known("goal_completed"), constraints_satisfied=known("user_constraints_satisfied"),
                unauthorized_effect=unauthorized)


class BrowserEpisodeObserver:
    def __init__(self, draw, *, episode_id, member, attempt=0, verifier=fixture_verification, clock=time.perf_counter):
        self.identity = {k: draw[k] for k in (*GROUP_IDENTITY, "group_id")}
        self.identity.update(episode_id=episode_id, member=member, attempt=attempt)
        self.verifier, self.clock = verifier, clock
        self.started, self.steps, self.last, self.finished = clock(), 0, None, None

    def observe(self, result, *, action):
        require(self.finished is None, "Episode observer already finished")
        require(type(action) is bool, "Explicit reset/action distinction required")
        self.last = result
        self.steps += int(action)
        return result

    def finish(self, *, status="completed", occurred_at=None):
        # Transport redelivery uses exactly the same timestamp/body.
        if self.finished is not None:
            require(self.finished["payload"]["status"] == status, "Cannot relabel a finished episode")
            return self.finished
        p = {**self.identity, "status": status, "goal_completed": None,
             "constraints_satisfied": None, "unauthorized_effect": None, "reward": None,
             "steps": self.steps, "duration_s": self.clock()-self.started,
             "generated_tokens": None, "interventions": None}
        if status == "completed":
            require(self.last is not None and self.last.done, "Completed observer needs terminal environment result")
            verification = self.verifier(self.last)
            require(set(verification) == {"goal_completed", "constraints_satisfied", "unauthorized_effect"},
                    "Verifier extractor must return the explicit outcome contract")
            p.update(verification)
            reward = self.last.reward
            if p["goal_completed"] is not None and safe(p) is not None and reward is not None:
                require(type(reward) in (int, float) and math.isfinite(reward), "Invalid environment reward")
                p["reward"] = reward
        event = dict(id=f"finish-{p['episode_id']}", kind="episode", producer="browser",
                     occurred_at=time.time() if occurred_at is None else occurred_at, payload=p)
        validate(event)
        self.finished = event
        return event
