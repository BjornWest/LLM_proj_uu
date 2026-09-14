"""Read curated tasks without mixing verifier input into policy observations.

Static preflight only: this module does not execute upstream code, navigate to
sites, or treat curation readiness/avoidance fields as observed outcomes.
"""

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .actions import ACTION_NAMES


@dataclass(frozen=True)
class PilotTask:
    _record: dict

    @property
    def id(self):
        return self._record["id"]

    @property
    def policy_input(self):
        # Deliberately project rather than return the whole manifest field.
        return {"goal": self._record["policy_input"]["goal"]}

    @property
    def source_key(self):
        return (self._record["source"], self._record["source_task_id"], self._record["source_revision"])

    @property
    def grader_input(self):
        # Includes original_prompt for legacy checkers that dispatch on text.
        return copy.deepcopy(self._record)


def load_pilot(path):
    raw = Path(path).read_bytes()
    manifest = json.loads(raw)
    if str(manifest.get("schema_version")) != "1.0":
        raise ValueError("Expected curated pilot schema 1.0")
    tasks, seen = [], set()
    for record in manifest["candidates"]:
        for field in ("id", "source", "source_task_id", "source_revision", "original_prompt"):
            if not isinstance(record.get(field), str) or not record[field].strip():
                raise ValueError(f"Candidate requires nonempty {field}")
        if record["id"] in seen:
            raise ValueError(f"Duplicate candidate ID: {record['id']}")
        seen.add(record["id"])
        goal = record.get("policy_input", {}).get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError(f"{record['id']} requires an explicit policy_input.goal")
        conditions = record.get("condition_ids", {})
        if set(conditions) != {"no_added_injection", "one_selected_injection"}:
            raise ValueError(f"{record['id']} requires a matched condition pair")
        if any(not isinstance(value, str) or not value for value in conditions.values()) or len(set(conditions.values())) != 2:
            raise ValueError(f"{record['id']} requires distinct condition IDs")
        tasks.append(PilotTask(copy.deepcopy(record)))
    return tasks, hashlib.sha256(raw).hexdigest()


def preflight(tasks, manifest_sha256, inventory_path):
    inventory_bytes = Path(inventory_path).read_bytes()
    inventory = {row["record_id"]: row for row in
                 (json.loads(line) for line in inventory_bytes.decode().splitlines() if line.strip())}
    supported = {"observations": {"accessibility_tree", "current_url"},
                 "actions": set(ACTION_NAMES),
                 "environment": {"local_site_start", "query_parameter_pattern_selection", "fresh_browser_storage"}}
    records, plan = [], []
    for task in tasks:
        record = task.grader_input
        required = record["required_capabilities"]
        missing = {kind: sorted(set(required.get(kind, [])) - available) for kind, available in supported.items()}
        inventory_record = inventory.get(record.get("source_record"))
        inventory_matches = bool(inventory_record and inventory_record.get("source") == task.source_key[0]
                                 and inventory_record.get("source_revision") == task.source_key[2])
        # Local scripted validation does not promote curated model-evaluation
        # readiness or training eligibility.
        implemented = task.id == 'P07' and task.source_key[:2] == ('trickyarena', 'ShoppingTask.DELL_BUY')
        blockers = (["P07 local fixture requires curation review before model evaluation"] if implemented else
                    ["source task adapter not implemented", "independent grader and regression cases not validated"])
        if record.get("evaluation_ready") is not True:
            blockers.append("curation marks this candidate not evaluation-ready")
        if not inventory_matches:
            blockers.append("source inventory reference missing or revision/source mismatch")
        if any(missing.values()):
            blockers.append("required browser/environment capabilities missing")
        if required.get("unresolved"):
            blockers.append("required capabilities remain unresolved")
        records.append({"id": task.id, "source_key": list(task.source_key),
                        "original_prompt": record["original_prompt"], "inventory_matches": inventory_matches,
                        "missing_capabilities": missing, "unresolved_capabilities": required.get("unresolved", []),
                        "visual_claim_requires": required.get("additional_for_visual_pattern_claim", []),
                        "source_flags": record.get("source_flags", []),
                        "local_adapter_implemented": implemented,
                        "defect_evidence_ids": record.get("proposed_grader", {}).get("defect_evidence_ids", []),
                        "ready": False, "blockers": blockers})
        if record.get("first_four") is True:
            for condition, condition_id in record["condition_ids"].items():
                plan.append({"candidate_id": task.id, "condition": condition, "condition_id": condition_id,
                             "policy_input": task.policy_input, "ready": False, "execution_status": "not_run"})
    return {"schema_version": 1, "kind": "static_pilot_preflight", "manifest_sha256": manifest_sha256,
            "inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
            "scope": "Capability/identity audit only; no browser, checker or model was run.",
            "candidate_count": len(records), "ready_count": 0, "candidates": records,
            "first_four_episode_plan": plan,
            "policy_boundary": "Only PilotTask.policy_input goes to the policy; this report is privileged."}
