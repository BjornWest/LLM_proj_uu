"""Two-turn synthetic environment for infrastructure acceptance, never a benchmark.

The model makes both choices. The environment rewards the final exact B answer.
Native TRL records every sampling call and builds masks/logprobs/advantages.
"""
from .choice_probe import PROMPT


class ChoiceSession:
    def initial_messages(self):
        return [dict(message) for message in PROMPT]

    def verify(self, transcript):
        from openenv.core.harness import VerifyResult
        replies = [m.get("content") or "" for m in transcript if m["role"] == "assistant"]
        assert len(replies) == 2
        self.success = replies[-1].strip() == "B"
        return VerifyResult(env_reward=float(self.success), done=True, metrics={"step_count": 2})

    def close(self):
        pass


class ChoiceFactory:
    def create(self, task, seed=None, episode_id=None):
        assert task == "two-choice"
        return ChoiceSession()


def choice_outcome(session, result):
    return dict(status="completed", goal_completed=session.success, constraints_satisfied=True,
                unauthorized_effect=False, reward=result.env_reward)


class TwoTurnAdapter:
    def run_white_box(self, model_step, session, limits):
        from openenv.core.harness import HarnessRolloutResult
        messages = session.initial_messages()
        for turn in range(2):
            result = model_step(messages, [], dict(limits.sampling))
            messages.append(result.response.to_message_dict())
            if turn == 0:
                messages.append(dict(role="user", content="Now choose again independently. Reply with just A or B."))
        return HarnessRolloutResult(messages=messages, done=True, metrics={"turns": 2, "tool_calls": 0})


def task_pool():
    return [dict(task_id="two-choice", task_family="synthetic-choice", task_template="two-turn-choice-v1",
                 split="rl_train", harness_revision="acceptance-two-turn-v1", verifier_revision="exact-B-v1",
                 environment_revision="synthetic-choice-v1", tokenizer_revision="Qwen3.8-1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0")]


def tensor_digest(values):
    """Fingerprint named tensors with exact dtype/shape/bytes, including BF16."""
    import hashlib
    import torch
    digest = hashlib.sha256()
    for name, value in sorted(values.items(), key=lambda item: str(item[0])):
        if not isinstance(value, torch.Tensor):
            raise TypeError("Tensor fingerprint requires tensors")
        value = value.detach().cpu().contiguous()
        digest.update(str((name, str(value.dtype), tuple(value.shape))).encode())
        digest.update(value.reshape(-1).view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


def optimizer_digest(optimizer_state):
    """Compare moments AND integer update counters across serialization."""
    import hashlib
    import json
    import torch
    def tree(value):
        if isinstance(value, torch.Tensor):
            return ["tensor", tensor_digest({"value": value})]
        if isinstance(value, dict):
            return ["dict", [[tree(key), tree(item)] for key, item in sorted(value.items(), key=lambda kv: repr(kv[0]))]]
        if isinstance(value, (list, tuple)):
            return [type(value).__name__, [tree(item) for item in value]]
        if value is None or type(value) in (str, int, float, bool):
            return [type(value).__name__, value]
        raise TypeError(f"Unhandled optimizer state type: {type(value).__name__}")
    return hashlib.sha256(json.dumps(tree(optimizer_state["state"]), sort_keys=True).encode()).hexdigest()


def audit_policy_events(events):
    """Offline independent check: requests keep identity, no live-group eviction."""
    groups, episodes, published, evicted = {}, {}, [], []
    multi_turn = 0
    for event in events:
        kind = event["event"]
        if kind == "publish":
            published.append(event["version"])
        elif kind == "group_start":
            groups[event["group_id"]] = event["version"]
        elif kind == "episode_start":
            assert groups[event["group_id"]] == event["version"]
            episodes[event["episode_id"]] = [event["version"], 0, 0]
        elif kind in ("request_start", "request_end"):
            record = episodes[event["episode_id"]]
            assert record[0] == event["version"] and record[0] not in evicted
            record[1] += 1 if kind == "request_start" else -1
            record[2] += kind == "request_start"
            assert record[1] >= 0
        elif kind == "episode_end":
            record = episodes.pop(event["episode_id"])
            assert record[1] == 0
            multi_turn += record[2] >= 2
        elif kind == "group_end":
            groups.pop(event["group_id"])
        elif kind in ("eviction_claim", "evicted"):
            assert event["version"] not in groups.values(), "Evicted a reserved policy"
            if kind == "evicted":
                evicted.append(event["version"])
        elif kind == "unsafe":
            raise AssertionError(event)
    assert not groups and not episodes, "Reservations leaked after worker exit"
    assert multi_turn > 0 and len(published) >= 2
    return dict(published=published, evicted=evicted, completed_multiturn_episodes=multi_turn,
                no_premature_evictions=True, no_remaining_reservations=True)
