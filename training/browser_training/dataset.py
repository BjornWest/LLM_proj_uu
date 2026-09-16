"""Minimal, deliberately strict conversion of normalized teacher trajectories."""
import json
from pathlib import Path

SYSTEM = "Complete the browser task while respecting the user's constraints. Return one browser action per turn."


def convert_trajectory(trajectory, *, target="action", layout="trajectory", successful_only=True):
    if target not in {"action", "reasoning-action"} or layout not in {"trajectory", "state-action"}:
        raise ValueError("Unknown target/layout")
    # Unknown and truthy strings are NOT verified successes.
    if successful_only and trajectory.get("success") is not True:
        return []
    task = trajectory.get("task")
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be nonempty text")
    steps = trajectory.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a nonempty list")
    initial = [{"role": "system", "content": SYSTEM}]
    messages = list(initial)
    rows = []
    for i, step in enumerate(steps):
        observation, action = step.get("observation"), step.get("action")
        if not isinstance(observation, str) or not isinstance(action, str) or not action.strip():
            raise ValueError(f"step {i}: observation and nonempty action must be text")
        reasoning = step.get("reasoning", "")
        if not isinstance(reasoning, str):
            raise ValueError(f"step {i}: reasoning must be text")
        assistant = {"role": "assistant", "content": action}
        if target == "reasoning-action" and reasoning.strip():
            assistant["reasoning_content"] = reasoning.strip()
        prompt = f"Task: {task}\n\nObservation:\n{observation}" if i == 0 or layout == "state-action" else observation
        pair = [{"role": "user", "content": prompt}, assistant]
        if layout == "state-action":
            rows.append({"messages": initial + pair})
        else:
            messages.extend(pair)
    return rows if layout == "state-action" else [{"messages": messages}]


def convert_file(source, destination, **kwargs):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("Input and output must differ")
    rows, inputs = [], 0
    with source.open() as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            inputs += 1
            try:
                rows.extend(convert_trajectory(json.loads(line), **kwargs))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"{source}:{line_no}: {exc}") from exc
    if not rows:
        raise ValueError("No eligible examples; no output written")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    temporary.replace(destination)
    return {"trajectories_read": inputs, "examples_written": len(rows), **kwargs}
