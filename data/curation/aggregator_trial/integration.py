"""Small deployment-facing facade over the existing Prislyktan runtime and task.

The backend owns session policy and publication. This module only exposes the
fixture's existing lifecycle and task adapter without creating another runner.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from environments.aggregator_trial.server import RETAILER_IDS, Runtime
from .tasks import CONTRACTS, make_task


PREVIEW_MANIFEST = Path(__file__).with_name("preview_manifest.json")
TRUSTED_TASKS = Path(__file__).with_name("trusted_tasks.json")
SITE_IDS = ("aggregator", *RETAILER_IDS)


def trusted_task_catalog() -> dict:
    """Return the exact public goals, excluding private grader requirements."""
    contracts = json.loads(CONTRACTS.read_text())
    published = json.loads(TRUSTED_TASKS.read_text())
    expected = [(row["id"], row["goal"]) for row in contracts["tasks"]]
    if [(row["id"], row["goal"]) for row in published["tasks"]] != expected:
        raise ValueError("Published trusted task catalog differs from contracts")
    tasks = []
    for row in published["tasks"]:
        goal = row["goal"]
        tasks.append({"id": row["id"], "goal": goal,
                      "revision": hashlib.sha256((row["id"] + "\0" + goal).encode()).hexdigest()})
    if len(tasks) != 6 or len({row["id"] for row in tasks}) != 6:
        raise ValueError("Prislyktan deployment requires exactly six unique tasks")
    return {"schema": "prislyktan-trusted-task-catalog-v1",
            "contracts_sha256": hashlib.sha256(CONTRACTS.read_bytes()).hexdigest(),
            "tasks": tasks}


def create_runtime(*, ports: dict[str, int] | None = None) -> Runtime:
    """Create one isolated four-origin state lifetime.

    A manual/Ask owner should retain this object across questions in one session
    and close it only when that session ends. Task adapters create their own
    isolated Runtime during prepare().
    """
    return Runtime(ports=ports)


def runtime_descriptor(runtime: Runtime) -> dict:
    if tuple(runtime.origins) != SITE_IDS:
        raise ValueError("Runtime does not expose the complete four-site origin set")
    origins = deepcopy(runtime.origins)
    return {"homepage_url": origins["aggregator"] + "/", "origins": origins,
            "allowed_origins": [origins[site] for site in SITE_IDS]}


def make_env(task, video=None, *, action_mapping, headless=True):
    """Delegate to the actual EpisodeTask BrowserEnv entrypoint."""
    return task.make_env(video, action_mapping=action_mapping, headless=headless)


def preview_manifest() -> dict:
    return json.loads(PREVIEW_MANIFEST.read_text())


__all__ = ["create_runtime", "make_env", "make_task", "preview_manifest",
           "runtime_descriptor", "trusted_task_catalog"]
