import json
import pytest
from browser_training.dataset import convert_trajectory, convert_file


@pytest.fixture
def trajectory():
    return {"task": "Accept only the required option", "success": True, "steps": [
        {"observation": "Button [1]", "reasoning": "This opens the form", "action": "click('1')"},
        {"observation": "Input [2]", "reasoning": "Enter the requested value", "action": "fill('2', 'yes')"}]}


@pytest.mark.parametrize("target", ["action", "reasoning-action"])
@pytest.mark.parametrize("layout", ["trajectory", "state-action"])
def test_conversion_modes(trajectory, target, layout):
    rows = convert_trajectory(trajectory, target=target, layout=layout)
    assert len(rows) == (2 if layout == "state-action" else 1)
    assistants = [m for row in rows for m in row["messages"] if m["role"] == "assistant"]
    assert len(assistants) == 2
    assert all(("reasoning_content" in m) == (target == "reasoning-action") for m in assistants)
    assert all("<think>" not in m["content"] for m in assistants)
    assert all("Accept only" in row["messages"][1]["content"] for row in rows)


@pytest.mark.parametrize("success", [None, False, "true", 1])
def test_requires_verified_boolean_success(trajectory, success):
    trajectory["success"] = success
    assert convert_trajectory(trajectory) == []


def test_invalid_input_does_not_overwrite_output(tmp_path, trajectory):
    src, dst = tmp_path / "input.jsonl", tmp_path / "output.jsonl"
    dst.write_text("existing")
    src.write_text(json.dumps(trajectory) + "\n{broken\n")
    with pytest.raises(ValueError, match=":2:"):
        convert_file(src, dst)
    assert dst.read_text() == "existing"


def test_reject_empty_action(trajectory):
    trajectory["steps"][0]["action"] = ""
    with pytest.raises(ValueError):
        convert_trajectory(trajectory)
