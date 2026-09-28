"""Local orchestrator service: sampled tasks, outcomes and checkpoint evidence.

One multiprocessing manager owns the sampler/ledger on the trainer host. This
is not a network service or a distributed database. Callers pass its picklable
proxy through TRL's existing spawned-worker/session-factory interface.
"""
import json
from multiprocessing.managers import BaseManager
from pathlib import Path
import shutil
import threading
import time
import uuid

from .curriculum import FamilySampler, SamplerConfig, digest
from .outcomes import Ledger, canonical, require, snapshot, write_snapshot
from .trainer_metrics import trainer_event
from .publication import publication_run_id


class RuntimeMetrics:
    def __init__(self, directory, *, run_id, synthetic, tasks=(), sampler_config=None,
                 resume=None, expected_producers=("browser", "orchestrator", "trainer"),
                 evaluation_suites=(), evaluation_interval_episodes=1000):
        self.lock = threading.RLock()
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.generation = uuid.uuid4().hex  # Native TRL integer group IDs restart on resume.
        self.active, self.members = {}, {}
        self.log_row = 0
        from .evaluation import EvaluationSchedule
        self.evaluation_schedule = EvaluationSchedule(evaluation_suites, evaluation_interval_episodes) if evaluation_suites else None
        self.sampler = FamilySampler(tasks, SamplerConfig(**(sampler_config or {}))) if tasks else None
        db = self.directory / "events.sqlite"
        require(not db.exists(), "Use a fresh monitoring directory; restore explicitly from a checkpoint")
        restored = None
        publication = None
        if resume:
            resume = Path(resume)
            restored = json.loads((resume / "monitoring/state.json").read_text())
            require(restored.get("state_sha256") == digest({k: v for k, v in restored.items() if k != "state_sha256"}),
                    "Monitoring checkpoint state checksum mismatch")
            require(restored["run_id"] == run_id and restored["synthetic"] is synthetic,
                    "Checkpoint run/classification mismatch")
            require(restored["expected_producers"] == sorted(expected_producers), "Producer contract changed")
            native = json.loads((resume / "rollout_state.json").read_text())
            require(native == restored["rollout_state"], "Native rollout checkpoint differs from monitoring checkpoint")
            require((self.sampler is None) == (restored["sampler"] is None), "Sampler presence changed")
            require((self.evaluation_schedule is None) == (restored.get("evaluation_schedule") is None),
                    "Evaluation schedule presence changed")
            if self.evaluation_schedule:
                self.evaluation_schedule.restore(restored["evaluation_schedule"])
            if self.sampler:
                self.sampler.load_state_dict(restored["sampler"])
            # Use SQLite backup, never copy a live WAL database.
            backup = Ledger(resume / "monitoring/events.sqlite", run_id=run_id, synthetic=synthetic,
                            expected_producers=expected_producers, publication=restored.get("publication"))
            actual = snapshot(backup, now=restored["snapshot_at"])
            require(actual["snapshot_id"] == restored["snapshot_id"], "Checkpoint ledger checksum mismatch")
            publication = dict(run_id="resume-" + uuid.uuid4().hex, parent_run_id=publication_run_id(actual),
                checkpoint_name=resume.name, checkpoint_snapshot_id=actual["snapshot_id"],
                checkpoint_state_sha256=restored["state_sha256"], inherited_watermark=actual["watermark"],
                checkpoint_policy_version=native["model_version"], resumed_at=time.time())
            backup.backup(db, publication=publication)
        self.ledger = Ledger(db, run_id=run_id, synthetic=synthetic, expected_producers=expected_producers,
                             publication=publication)
        if restored:
            # Browser/session state cannot survive process restart. Do not resume its leases.
            for episode_id, record in restored["active"].items():
                self.active[episode_id] = record
                self.finish(episode_id, dict(status="cancelled", goal_completed=None,
                            constraints_satisfied=None, unauthorized_effect=None, reward=None))
            # Restoring a checkpoint does not restore queue lookahead or accumulated
            # gradients. Completed optimizer events in its backup remain durable.
            records = [r["event"] for r in self.ledger.records()]
            manifests = [e["payload"] for e in records if e["kind"] == "row_manifest"]
            decisions = {e["payload"]["row_id"]: e["payload"] for e in records if e["kind"] == "row_decision"}
            terminal = {e["payload"]["row_id"] for e in records if e["kind"] == "row_use"
                        and e["payload"]["stage"] in {"applied", "skipped", "abandoned"}}
            for manifest in manifests:
                for row in manifest["rows"]:
                    identity = dict(episode_id=manifest["episode_id"], row_id=row["row_id"])
                    decision = decisions.get(row["row_id"])
                    if decision is None:
                        self.decide_row(identity, "discarded", "checkpoint_resume_queue_not_restored",
                                        max(native["model_version"], manifest["policy_version"]))
                    elif decision["decision"] == "admitted" and row["row_id"] not in terminal:
                        self.use_rows([identity], "abandoned", 0)
        self.emit_snapshot()

    def begin(self, *, native_group_id, episode_id, policy_version, group_size):
        with self.lock:
            require(self.sampler is not None, "A reviewed task pool is required")
            require(episode_id not in self.active and self.ledger.event(f"finish-{episode_id}") is None,
                    "Duplicate episode start")
            group_id = f"{self.generation}:{native_group_id}"
            # Refresh for each new group. Existing committed draws remain authoritative.
            if group_id not in self.members:
                require(self.ledger.event("draw-" + digest([self.ledger.metadata["run_id"], group_id])) is None,
                        "Native group ID reused within one worker generation")
                self.sampler.refresh(self.ledger, policy_version=policy_version, now=time.time())
                self.members[group_id] = 0
            draw = self.sampler.draw(self.ledger, group_id=group_id, group_size=group_size,
                                     policy_version=policy_version, now=time.time())
            member = self.members[group_id]
            require(member < group_size, "Too many episodes for a native GRPO group")
            self.members[group_id] += 1
            self.active[episode_id] = dict(draw=draw, member=member, started_at=time.time())
            return draw

    def finish(self, episode_id, outcome, *, generated_tokens=None, steps=None, duration_s=None):
        from .outcomes import GROUP_IDENTITY
        with self.lock:
            require(episode_id in self.active, "Unknown/already finished episode")
            record = self.active[episode_id]
            draw = record["draw"]
            payload = {k: draw[k] for k in (*GROUP_IDENTITY, "group_id")}
            payload.update(episode_id=episode_id, member=record["member"], attempt=0,
                           **outcome, generated_tokens=generated_tokens, steps=steps,
                           duration_s=duration_s, interventions=None)
            event = dict(id=f"finish-{episode_id}", kind="episode", occurred_at=time.time(),
                         producer="browser", payload=payload)
            self.ledger.append(event)
            del self.active[episode_id]
            if (self.members.get(draw["group_id"]) == draw["group_size"] and
                    not any(r["draw"]["group_id"] == draw["group_id"] for r in self.active.values())):
                del self.members[draw["group_id"]]
            return event

    def log(self, row, *, policy_version=None):
        with self.lock:
            event = trainer_event(row, kind="rl", source_id=self.generation, row_number=self.log_row,
                                  context="live AsyncGRPO callback; admission/optimizer consumption are separate",
                                  policy_version=policy_version)
            self.log_row += 1
            if event:
                self.ledger.append(event)

    def _row_event(self, kind, payload, identity, producer):
        previous = self.ledger.event(identity)
        if previous:
            require(previous["payload"] == payload, "Row event redelivered with different content")
            return
        self.ledger.append(dict(id=identity, kind=kind, payload=payload, producer=producer, occurred_at=time.time()))

    def register_group_rows(self, native_group_id, policy_version, by_episode, cancelled=False):
        with self.lock:
            group_id = f"{self.generation}:{native_group_id}"
            episodes = [r["event"]["payload"] for r in self.ledger.records()
                        if r["event"]["kind"] == "episode" and r["event"]["payload"]["group_id"] == group_id]
            require(cancelled or (episodes and len(episodes) == episodes[0]["group_size"]),
                    "Scoring requires all persisted group outcomes")
            require(set(by_episode) <= {p["episode_id"] for p in episodes}, "Unknown episode in scored rows")
            for episode in episodes:
                episode_id = episode["episode_id"]
                rows = by_episode.get(episode_id, [])
                self._row_event("row_manifest", dict(episode_id=episode_id, policy_version=policy_version, rows=rows),
                                f"rows-{episode_id}", "rollout")

    def decide_row(self, identity, decision, reason, policy_version):
        with self.lock:
            self._row_event("row_decision", dict(**identity, decision=decision, reason=reason,
                            trainer_policy_version=policy_version), f"decision-{identity['row_id']}", "trainer")

    def use_rows(self, identities, stage, optimizer_step):
        with self.lock:
            for identity in identities:
                self._row_event("row_use", dict(**identity, stage=stage, optimizer_step=optimizer_step,
                                generation=self.generation), f"use-{identity['row_id']}-{stage}", "trainer")

    def applied_native_groups(self):
        """Conservative resume frontier: every expected episode/row reached an update."""
        from collections import defaultdict
        with self.lock:
            events = [r["event"] for r in self.ledger.records()]
            manifests = {e["payload"]["episode_id"]: e["payload"]["rows"] for e in events if e["kind"] == "row_manifest"}
            applied = {e["payload"]["row_id"] for e in events if e["kind"] == "row_use" and e["payload"]["stage"] == "applied"}
            groups = defaultdict(list)
            for event in events:
                p = event["payload"]
                if event["kind"] == "episode" and p["group_id"].startswith(self.generation + ":"):
                    groups[p["group_id"]].append(p)
            return sorted(int(g.split(":", 1)[1]) for g, episodes in groups.items()
                if len(episodes) == episodes[0]["group_size"] and all(
                    manifests.get(p["episode_id"]) and all(r["row_id"] in applied for r in manifests[p["episode_id"]])
                    for p in episodes))

    def _import_resources(self):
        # Latest-sample mailboxes: bounded three files, no network in trainer callbacks.
        # Raw sampler history belongs in a profiler if needed; this is dashboard sampling.
        from .monitoring_files import atomic_json
        from .resource_monitor import ingest_sample
        for role in ("browser", "trainer", "rollout"):
            path = self.directory / "resources" / f"{role}.json"
            if not path.exists():
                continue
            try:
                ingest_sample(self.ledger, json.loads(path.read_text()), role=role)
                status = dict(status="ok", checked_at=time.time())
            except (OSError, ValueError, KeyError, TypeError) as exc:
                status = dict(status="rejected", checked_at=time.time(), error_type=type(exc).__name__)
            # Failure status must not turn optional resource collection into a training failure.
            try:
                atomic_json(self.directory / "resources" / f"{role}-import-status.json", status)
            except OSError:
                pass

    def evaluation_enabled(self):
        return self.evaluation_schedule is not None

    def import_evaluation(self, delivery):
        from .evaluation import validate_report
        from .outcomes import validate
        with self.lock:
            require(set(delivery) == {"episodes", "report"}, "Invalid evaluation delivery")
            report, episodes = delivery["report"], delivery["episodes"]
            validate(report)
            require(report["kind"] == "evaluation", "Expected fixed-suite report")
            for event in episodes:
                validate(event)
                require(event["kind"] == "episode", "Expected evaluation episodes")
            validate_report(report["payload"], episodes)
            require(len(episodes) == len(report["payload"]["episode_ids"]) and
                    {e["id"] for e in episodes} == set(report["payload"]["episode_ids"]),
                    "Evaluation delivery includes extra or duplicate events")
            require(all(e["occurred_at"] <= report["occurred_at"] for e in episodes),
                    "Evaluation report predates its episodes")
            require(report["payload"]["request"]["publication_run_id"] == publication_run_id(self.ledger.metadata),
                    "Evaluation belongs to another execution")
            if self.evaluation_schedule:
                from .evaluation import digest
                require(report["payload"]["request"]["suite_revision"] in
                        {digest(suite) for suite in self.evaluation_schedule.suites},
                        "Evaluation is not from a configured fixed suite")
            for event in episodes:
                self.ledger.append(event)
            self.ledger.append(report)

    def _import_evaluations(self):
        from .monitoring_files import atomic_json
        for path in sorted((self.directory / "evaluation-inbox").glob("*.json"))[:4]:
            try:
                self.import_evaluation(json.loads(path.read_text()))
                status = {"status": "imported", "checked_at": time.time()}
            except (ValueError, KeyError, TypeError, OSError) as exc:
                status = {"status": "rejected", "error_type": type(exc).__name__, "checked_at": time.time()}
            archive = self.directory / "evaluation-deliveries"
            archive.mkdir(exist_ok=True)
            atomic_json(archive / (path.stem + "-status.json"), status)
            path.replace(archive / path.name)

    def emit_snapshot(self):
        with self.lock:
            self._import_resources()
            self._import_evaluations()
            value = snapshot(self.ledger)
            write_snapshot(value, self.directory / "snapshot.json")
            return value

    def checkpoint(self, checkpoint_dir):
        with self.lock:
            checkpoint_dir = Path(checkpoint_dir)
            native = json.loads((checkpoint_dir / "rollout_state.json").read_text())
            require(type(native["model_version"]) is int and native["model_version"] >= 0,
                    "Checkpoint needs native policy version")
            target = checkpoint_dir / "monitoring"
            require(not target.exists(), "Monitoring checkpoint already exists")
            temporary = checkpoint_dir / (".monitoring-" + uuid.uuid4().hex)
            temporary.mkdir()
            previous_schedule = None if self.evaluation_schedule is None else self.evaluation_schedule.state_dict()
            try:
                # All service writes/draws stop during this small consistent backup.
                value = snapshot(self.ledger)
                self.ledger.backup(temporary / "events.sqlite")
                state = dict(schema_version=1, run_id=self.ledger.metadata["run_id"],
                    synthetic=self.ledger.metadata["synthetic"],
                    expected_producers=self.ledger.metadata["expected_producers"],
                    snapshot_id=value["snapshot_id"], snapshot_at=value["snapshot_at"],
                    rollout_state=native, sampler=None if self.sampler is None else self.sampler.state_dict(),
                    active=self.active, generation=self.generation,
                    note="In-flight episodes cancel on resume. Queue admission and optimizer use are not inferred.")
                if self.evaluation_schedule:
                    from .monitoring_files import atomic_json
                    jobs = self.evaluation_schedule.at_checkpoint([r["event"] for r in self.ledger.records()],
                        checkpoint_id=f"{checkpoint_dir.name}:{value['snapshot_id']}",
                        policy_version=native["model_version"], publication_run_id=publication_run_id(value))
                    state["evaluation_schedule"] = self.evaluation_schedule.state_dict()
                    for job in jobs:
                        atomic_json(temporary / "evaluation-requests" / (job["evaluation_id"] + ".json"), job)
                if self.ledger.metadata.get("publication"):
                    state["publication"] = self.ledger.metadata["publication"]
                state["state_sha256"] = digest(state)
                (temporary / "state.json").write_text(canonical(state) + "\n")
                write_snapshot(value, temporary / "snapshot.json")
                temporary.rename(target)
            except BaseException:
                if previous_schedule is not None:
                    self.evaluation_schedule.restore(previous_schedule)
                raise
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            return state


class MetricsManager(BaseManager):
    pass


MetricsManager.register("RuntimeMetrics", RuntimeMetrics)


def start_metrics(ctx, directory, **kwargs):
    manager = MetricsManager(ctx=ctx)
    manager.start()
    try:
        return manager, manager.RuntimeMetrics(str(directory), **kwargs)
    except BaseException:
        manager.shutdown()
        raise
