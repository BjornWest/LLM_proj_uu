"""Policy reservations for the pinned TRL worker; no model or CUDA dependencies.

The manager is local to the trainer host. vLLM's native named-adapter HTTP API
still owns loading/inference. All state transitions below are serialized, even
when called by the trainer process and multiple harness threads concurrently.
"""
import asyncio
import json
from contextvars import ContextVar, copy_context
from multiprocessing.managers import BaseManager
from pathlib import Path
import shutil
import threading
import time
import uuid


class PolicyCancelled(RuntimeError):
    pass


class PolicyUnsafe(RuntimeError):
    pass


class PolicyRegistry:
    def __init__(self, max_staleness=2):
        self.lock = threading.RLock()
        self.current = 0
        self.max_staleness = max_staleness
        self.versions = {}
        self.groups = {}
        self.episodes = {}
        self.fault = None
        self.events = []
        self.event_number = 0
        self.event_path = None
        self.run_id = uuid.uuid4().hex

    def _event(self, event, **fields):
        self.event_number += 1
        self.events.append(dict(run_id=self.run_id, seq=self.event_number, time=time.time(), event=event, **fields))
        self.events = self.events[-2048:]
        if self.event_path:
            with Path(self.event_path).open("a") as stream:
                stream.write(json.dumps(self.events[-1]) + "\n")

    def assert_healthy(self):
        with self.lock:
            if self.fault:
                raise PolicyUnsafe(self.fault)

    def fail(self, reason):
        with self.lock:
            self.fault = reason
            self._event("unsafe", reason=reason)

    def configure(self, max_staleness, event_path=None):
        with self.lock:
            if self.groups or self.versions:
                raise PolicyUnsafe("Configure reservations before publishing/starting rollouts")
            if max_staleness < 0:
                raise ValueError("max_staleness must be nonnegative")
            self.max_staleness = max_staleness
            self.event_path = event_path
            if event_path:
                Path(event_path).parent.mkdir(parents=True, exist_ok=True)

    def publish(self, version):
        """Only after native vLLM load has succeeded; also atomic with group acquisition."""
        with self.lock:
            self.assert_healthy()
            if version <= self.current:
                raise PolicyUnsafe("Policy versions must increase; restart with a fresh registry/server")
            self.versions[version] = "available"
            self.current = version
            for old in self.versions:
                if version - old > self.max_staleness and self.versions[old] == "available":
                    self.versions[old] = "retired"
            for group_id, group in self.groups.items():
                if version - group["version"] > self.max_staleness:
                    self.cancel_group(group_id, "staleness")
            self._event("publish", version=version)

    def acquire_group(self, group_id):
        with self.lock:
            self.assert_healthy()
            if group_id in self.groups or not self.current:
                raise PolicyUnsafe("Duplicate group or no registered policy")
            self.groups[group_id] = dict(version=self.current, cancelled=None)
            self._event("group_start", group_id=group_id, version=self.current)
            return self.current

    def cancel_group(self, group_id, reason):
        with self.lock:
            group = self.groups[group_id]
            if not group["cancelled"]:
                group["cancelled"] = reason
                self._event("group_cancel", group_id=group_id, version=group["version"], reason=reason)

    def start_episode(self, group_id, episode_id):
        with self.lock:
            self.assert_healthy()
            group = self.groups[group_id]
            if group["cancelled"]:
                raise PolicyCancelled(group["cancelled"])
            if episode_id in self.episodes:
                raise PolicyUnsafe("Duplicate episode ID")
            self.episodes[episode_id] = dict(group_id=group_id, version=group["version"], requests=0)
            self._event("episode_start", episode_id=episode_id, group_id=group_id, version=group["version"])
            return group["version"]

    def begin_request(self, episode_id):
        with self.lock:
            self.assert_healthy()
            episode = self.episodes[episode_id]
            group = self.groups[episode["group_id"]]
            if group["cancelled"]:
                raise PolicyCancelled(group["cancelled"])
            episode["requests"] += 1
            self._event("request_start", episode_id=episode_id, version=episode["version"])
            return episode["version"]

    def end_request(self, episode_id):
        with self.lock:
            episode = self.episodes[episode_id]
            if episode["requests"] <= 0:
                raise PolicyUnsafe("Unbalanced request release")
            episode["requests"] -= 1
            self._event("request_end", episode_id=episode_id, version=episode["version"])

    def finish_episode(self, episode_id):
        with self.lock:
            if self.episodes[episode_id]["requests"]:
                raise PolicyUnsafe("Cannot release an episode with outstanding inference")
            episode = self.episodes.pop(episode_id)
            self._event("episode_end", episode_id=episode_id, **episode)

    def release_group(self, group_id):
        with self.lock:
            if any(e["group_id"] == group_id for e in self.episodes.values()):
                raise PolicyUnsafe("Cannot release a group with active episodes")
            group = self.groups.pop(group_id)
            self._event("group_end", group_id=group_id, **group)
            return group["cancelled"]

    def claim_evictions(self):
        with self.lock:
            self.assert_healthy()
            busy = {g["version"] for g in self.groups.values()}
            ready = [v for v, state in self.versions.items() if state == "retired" and v not in busy]
            for version in ready:
                self.versions[version] = "unloading"
                self._event("eviction_claim", version=version)
            return ready

    def confirm_eviction(self, version):
        with self.lock:
            if self.versions[version] != "unloading":
                raise PolicyUnsafe("Eviction was not claimed")
            del self.versions[version]
            self._event("evicted", version=version)

    def check_capacity(self):
        with self.lock:
            self.assert_healthy()
            if len(self.versions) >= self.max_staleness + 2:
                raise PolicyUnsafe("Adapter capacity exhausted while old episodes drain; stop safely and reduce sync frequency/concurrency")

    def snapshot(self):
        with self.lock:
            import copy
            return copy.deepcopy(dict(current=self.current, versions=self.versions, groups=self.groups,
                                      episodes=self.episodes, fault=self.fault, events=self.events))


class PolicyManager(BaseManager):
    pass


PolicyManager.register("PolicyRegistry", PolicyRegistry)


def shared_registry(ctx):
    manager = PolicyManager(ctx=ctx)
    manager.start()
    return manager, manager.PolicyRegistry()


_episode = ContextVar("trl_reserved_episode", default=None)
EMPTY = ([], [], [], 0, 0, None)


async def drain(awaitable, on_cancel=None):
    """Cancellation cannot release a lease while its thread/HTTP request still runs."""
    future = asyncio.ensure_future(awaitable)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(future)
            break
        except asyncio.CancelledError:
            if future.cancelled():
                raise
            cancelled = True
            if on_cancel:
                on_cancel()
    if cancelled:
        raise asyncio.CancelledError
    return result


async def generate_reserved(loop, prompt, *, tool_dict, tools, group_id):
    registry = loop.policy_registry
    if registry is None:
        return await loop._generate_one(prompt, tool_dict=tool_dict, tools=tools, group_id=group_id)
    episode_id = uuid.uuid4().hex
    try:
        version = registry.start_episode(group_id, episode_id)
    except PolicyCancelled:
        return EMPTY
    token = _episode.set((registry, group_id, episode_id, version))
    try:
        result = await drain(loop._generate_one(prompt, tool_dict=tool_dict, tools=tools, group_id=group_id),
                             lambda: registry.cancel_group(group_id, "cancelled"))
        registry.assert_healthy()  # The OpenEnv harness catches model callback exceptions.
        if not result[2]:
            registry.cancel_group(group_id, "empty_or_failed_episode")
        return result
    except PolicyCancelled:
        return EMPTY
    except BaseException:
        registry.cancel_group(group_id, "episode_error_or_shutdown")
        raise
    finally:
        _episode.reset(token)
        registry.finish_episode(episode_id)


def episode_id():
    value = _episode.get()
    return value[2] if value else uuid.uuid4().hex


def current_episode():
    """Read-only identity for observers running inside a reserved harness session."""
    value = _episode.get()
    return None if value is None else dict(group_id=value[1], episode_id=value[2], policy_version=value[3])


def fail_current_episode(reason):
    """Stop safely if a trusted observer cannot persist its reserved episode."""
    value = _episode.get()
    if value is not None:
        value[0].fail(reason)


def request_model(loop):
    value = _episode.get()
    if loop.policy_registry is not None:
        if value is None:
            raise PolicyUnsafe("LoRA inference outside a reserved episode")
        return f"{loop.lora_name}-v{value[3]}"
    return loop.model_name if loop.lora_name is None else f"{loop.lora_name}-v{loop.model_version}"


async def reserved_request(loop, payload):
    value = _episode.get()
    if loop.policy_registry is None:
        return await loop._retry(lambda: loop._post("/v1/completions", payload, loop.request_timeout),
                                 max_attempts=30, label="vllm /v1/completions")
    registry, group_id, session_id, version = value
    assert registry.begin_request(session_id) == version
    try:
        # No automatic retries after an ambiguous timeout: an earlier request may
        # still be executing remotely. Halt the run and preserve its adapter.
        return await drain(loop._post("/v1/completions", payload, loop.request_timeout, max_retries=1),
                           lambda: registry.cancel_group(group_id, "request_cancelled"))
    except asyncio.CancelledError:
        raise  # drain completed the HTTP future before propagating cancellation
    except Exception as exc:
        registry.fail(f"Inference outcome uncertain for v{version}: {type(exc).__name__}: {exc}; restart vLLM before resuming")
        raise PolicyUnsafe("Inference failed; adapter eviction is disabled") from exc
    finally:
        registry.end_request(session_id)


def evict_idle(trainer):
    registry = trainer.rollout_worker.policy_registry
    for version in registry.claim_evictions():
        name = f"{trainer._lora_name}-v{version}"
        try:
            trainer.vllm_client.unload_lora_adapter(name)
            # No episode or HTTP request can still lazily resolve this path.
            shutil.rmtree(Path(trainer._lora_dir) / name, ignore_errors=False)
            registry.confirm_eviction(version)
        except Exception as exc:
            registry.fail(f"Adapter eviction failed for {name}: {exc}")
            raise


def prepare_sync(trainer):
    if getattr(trainer.accelerator, "num_processes", 1) != 1:
        raise PolicyUnsafe("Policy reservations currently qualify one trainer process only")
    if trainer.accelerator.is_main_process:
        registry = trainer.rollout_worker.policy_registry
        if registry is None:
            raise PolicyUnsafe("LoRA synchronization requires the patched reservation worker")
        child = getattr(trainer.rollout_worker, "_process", None)
        if child is not None and child.exitcode is not None:
            registry.fail("Rollout worker exited; restart vLLM before resuming")
        registry.assert_healthy()
        evict_idle(trainer)
        registry.check_capacity()


def publish_policy(trainer, version):
    trainer.rollout_worker.policy_registry.publish(version)
    evict_idle(trainer)
