import pickle
import pytest
from browser_training.choice_probe import choice_reward, choose_target, summarize, compare, render_prompt_ids


def test_reward_is_response_dependent_and_spawn_safe():
    reward = pickle.loads(pickle.dumps(choice_reward))
    assert reward([[{"role": "assistant", "content": "A"}], "B", "A or B", " A\n"],
                  ["A"] * 4) == [1, 0, 0, 1]
    assert reward(["A", "B"], ["B", "B"]) == [0, 1]
    with pytest.raises(ValueError):
        reward(["A"], [])


def test_no_advantage_task_is_rejected():
    for samples in ([], ["A"] * 32, ["invalid"] * 32, ["A"] * 31 + ["B"]):
        with pytest.raises(ValueError):
            choose_target(samples)
    assert choose_target(["A"] * 24 + ["B"] * 8) == "B"


def test_learning_evidence_requires_change_beyond_sampling_uncertainty():
    before = summarize(["A"] * 32 + ["B"] * 32, "A")
    assert not compare(before, before)["clear_improvement"]
    assert compare(before, summarize(["A"] * 62 + ["B"] * 2, "A"))["clear_improvement"]
    assert not compare(before, summarize(["A"] * 36 + ["B"] * 28, "A"))["clear_improvement"]


def test_tokenizer_api_change_is_not_allowed_into_http_payload():
    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            return [10, 20] if kwargs.get('return_dict') is False else {'input_ids': [10, 20]}
    assert render_prompt_ids(Tokenizer()) == [10, 20]
    class BrokenTokenizer:
        def apply_chat_template(self, *args, **kwargs):
            return {'input_ids': [10, 20]}
    with pytest.raises(TypeError):
        render_prompt_ids(BrokenTokenizer())
