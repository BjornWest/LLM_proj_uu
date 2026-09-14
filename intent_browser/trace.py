"""Portable, append-only transitions plus compressed raw browser observations."""

import gzip
import json
import hashlib
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image


def json_default(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(f"Cannot serialize {type(value)}")


def write_json(path, value):
    path = Path(path)
    text = json.dumps(value, indent=2, default=json_default)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def runtime_provenance():
    from importlib.metadata import version

    package = Path(__file__).resolve().parent
    return {"python": platform.python_version(),
            "packages": {name: version(name) for name in ("browsergym-core", "playwright", "httpx")},
            "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(package.glob("*.py"))},
            "observation_adapter": "axtree-text-v1", "action_parser": "literal-call-v2"}


class Trace:
    def __init__(self, root, metadata):
        self.episode_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        self.directory = Path(root) / self.episode_id
        self.directory.mkdir(parents=True)
        self.metadata = {**metadata, "schema_version": 3, "episode_id": self.episode_id,
                         "runtime": runtime_provenance()}
        write_json(self.directory / "metadata.json", self.metadata)
        self.events = (self.directory / "steps.jsonl").open("w", encoding="utf-8")
        self.lifecycle = (self.directory / "events.jsonl").open("w", encoding="utf-8")
        self.event("episode_started")

    def event(self, kind, **data):
        self.lifecycle.write(json.dumps({"event": kind,
            "timestamp": datetime.now(timezone.utc).isoformat(), **data}, default=json_default) + "\n")
        self.lifecycle.flush()

    def observation(self, index, obs, text):
        stem = f"observation-{index:03d}"
        Image.fromarray(obs["screenshot"]).save(self.directory / f"{stem}.png")
        with gzip.open(self.directory / f"{stem}.json.gz", "wt", encoding="utf-8") as f:
            json.dump({k: v for k, v in obs.items() if k != "screenshot"}, f, default=json_default)
        (self.directory / f"{stem}.txt").write_text(text, encoding="utf-8")
        return {"raw": f"{stem}.json.gz", "screenshot": f"{stem}.png", "text": f"{stem}.txt"}

    def append(self, step):
        self.events.write(json.dumps(step, default=json_default) + "\n")
        self.events.flush()

    def finish(self, summary):
        self.event("episode_finished", stop_reason=summary.get("stop_reason"), error=summary.get("error"))
        self.events.close()
        self.lifecycle.close()
        write_json(self.directory / "episode.json", {
            **self.metadata, **summary, "steps_file": "steps.jsonl", "events_file": "events.jsonl",
            "videos": [str(p.relative_to(self.directory)) for p in self.directory.rglob("*.webm")],
        })
