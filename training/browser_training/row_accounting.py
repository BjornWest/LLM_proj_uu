"""Immutable row lifecycle accounting; never implements a training decision."""
from collections import Counter

KINDS = {"row_manifest", "row_decision", "row_use"}


def validate_event(event):
    from .outcomes import fields, number, require
    p, kind = event["payload"], event["kind"]
    require(isinstance(p.get("episode_id"), str) and p["episode_id"], "Row event needs episode identity")
    if kind == "row_manifest":
        fields(p, {"episode_id", "policy_version", "rows"})
        require(event["producer"] == "rollout", "Row manifests come from rollout scoring")
        number(p["policy_version"], "policy_version", integer=True)
        require(isinstance(p["rows"], list), "Rows must be a list")
        for index, row in enumerate(p["rows"]):
            fields(row, {"row_id", "content_sha256", "loss_tokens"})
            require(row["row_id"] == f"{p['episode_id']}:{index}", "Row IDs must be episode:index")
            require(isinstance(row["content_sha256"], str) and len(row["content_sha256"]) == 64
                    and all(c in "0123456789abcdef" for c in row["content_sha256"]), "Invalid row content hash")
            number(row["loss_tokens"], "loss_tokens", integer=True)
    else:
        common = {"episode_id", "row_id"}
        require(event["producer"] in {"trainer", "orchestrator"}, "Only trainer/orchestrator records row decisions/use")
        require(isinstance(p.get("row_id"), str) and p["row_id"], "Row ID required")
        if kind == "row_decision":
            fields(p, common | {"decision", "reason", "trainer_policy_version"})
            require(p["decision"] in {"admitted", "discarded"}, "Unknown row decision")
            require(isinstance(p["reason"], str) and p["reason"], "Decision reason required")
            number(p["trainer_policy_version"], "trainer_policy_version", integer=True)
        else:
            fields(p, common | {"stage", "optimizer_step", "generation"})
            require(p["stage"] in {"backward", "applied", "skipped", "abandoned"}, "Unknown row-use stage")
            number(p["optimizer_step"], "optimizer_step", integer=True)
            require(isinstance(p["generation"], str) and p["generation"], "Trainer generation required")


def validate_relations(events):
    from .outcomes import require, safe
    episodes, manifests, decisions, uses, legacy = {}, {}, {}, {}, set()
    order = {}
    for index, event in enumerate(events):
        p, kind = event["payload"], event["kind"]
        if kind == "episode": episodes[p["episode_id"]] = p
        elif kind == "admission": legacy.add(p["episode_id"])
        elif kind == "row_manifest":
            require(p["episode_id"] not in manifests, "Duplicate row manifest")
            manifests[p["episode_id"]] = p
        elif kind == "row_decision":
            require(p["row_id"] not in decisions, "Row admission is final")
            decisions[p["row_id"]] = p
        elif kind == "row_use":
            key = p["row_id"], p["stage"]
            require(key not in uses, "Duplicate row-use stage")
            uses[key] = p
            order[key] = index
    for episode_id, manifest in manifests.items():
        require(episode_id in episodes, "Row manifest requires persisted episode outcome")
        require(episode_id not in legacy, "Do not mix legacy admission with row-derived admission")
        episode = episodes[episode_id]
        require(episode["split"] == "rl_train" and episode["policy_version"] == manifest["policy_version"],
                "Row manifest split/policy mismatch")
    rows = {r["row_id"]: episode_id for episode_id, m in manifests.items() for r in m["rows"]}
    for row_id, decision in decisions.items():
        require(rows.get(row_id) == decision["episode_id"], "Unknown/misidentified row decision")
        episode = episodes[decision["episode_id"]]
        require(decision["trainer_policy_version"] >= episode["policy_version"], "Negative row policy age")
        if decision["decision"] == "admitted":
            require(episode["status"] == "completed" and safe(episode) is not None and episode["reward"] is not None,
                    "Cannot admit an unverified episode row")
    for (row_id, stage), use in uses.items():
        require(rows.get(row_id) == use["episode_id"], "Unknown/misidentified row use")
        if stage != "abandoned":
            require(decisions.get(row_id, {}).get("decision") == "admitted", "Backward/update requires admitted row")
        if stage in {"applied", "skipped"}:
            backward = uses.get((row_id, "backward"))
            require(backward is not None and all(use[k] == backward[k] for k in ("optimizer_step", "generation")),
                    "Optimizer event requires matching completed backward")
        require(sum((row_id, s) in uses for s in ("applied", "skipped", "abandoned")) <= 1,
                "Conflicting terminal row-use stages")
        if stage == "backward":
            require(all(order[(row_id, "backward")] < order[(row_id, s)]
                        for s in ("applied", "skipped", "abandoned") if (row_id, s) in uses),
                    "Backward cannot follow a terminal row-use stage")


def summarize(events):
    manifests = {e["payload"]["episode_id"]: e["payload"] for e in events if e["kind"] == "row_manifest"}
    if not manifests:
        return None, {}
    decisions = {e["payload"]["row_id"]: e["payload"] for e in events if e["kind"] == "row_decision"}
    uses = {(e["payload"]["row_id"], e["payload"]["stage"]): e["payload"] for e in events if e["kind"] == "row_use"}
    totals, per_episode, derived = Counter(), {}, {}
    for episode_id, manifest in manifests.items():
        ids = [r["row_id"] for r in manifest["rows"]]
        selected = [decisions[r] for r in ids if r in decisions]
        counts = Counter(d["decision"] for d in selected)
        state = ("no_rows" if not ids else "pending" if len(selected) != len(ids) else
                 "mixed" if len(counts) == 2 else next(iter(counts)))
        per_episode[episode_id] = dict(rows=len(ids), admitted=counts["admitted"], discarded=counts["discarded"],
            pending=len(ids)-len(selected), admission=state,
            **{stage: sum((row, stage) in uses for row in ids) for stage in ("backward", "applied", "skipped", "abandoned")})
        totals.update({k: v for k, v in per_episode[episode_id].items() if type(v) is int})
        if state != "pending":
            derived[episode_id] = dict(episode_id=episode_id, decision="discarded" if state == "no_rows" else state,
                reason="no_training_rows" if not ids else "mixed_row_decisions" if state == "mixed" else
                       ",".join(sorted({d["reason"] for d in selected})),
                trainer_policy_version=max((d["trainer_policy_version"] for d in selected), default=manifest["policy_version"]))
    return dict(schema_version=1, totals=dict(totals), episodes=per_episode,
        episode_states=dict(Counter(p["admission"] for p in per_episode.values())),
        scope="All recorded rows, cumulative; applied means optimizer step completed, not nonzero weight change or checkpoint durability."), derived
