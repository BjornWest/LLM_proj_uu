#!/usr/bin/env python3
import json
from pathlib import Path
from browser_training.dataset import convert_trajectory

path = Path("data/smoke.jsonl")
path.parent.mkdir(parents=True, exist_ok=True)
rows = []
for i in range(64):
    rows.extend(convert_trajectory({"task": f"Click button {i}.", "success": True,
        "steps": [{"observation": f"Button [{i}]", "action": f"click('{i}')"}]}))
path.write_text("".join(json.dumps(row) + "\n" for row in rows))
print(f"Wrote {len(rows)} synthetic plumbing examples to {path}")
