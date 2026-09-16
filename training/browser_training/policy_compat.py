"""Audited, reversible edits against exactly TRL a04ffd3; reject source drift."""
import hashlib

HASHES = {
    "async_rollout_worker.py": "70222b24533ce8cc56061cc355b0358eaea7cbda4461a7df75e75f5fbec6b5d1",
    "openenv_harness.py": "35393ad97d321143dd187f38e48a63bf614e3e2a0a42f4c4aaade960ec186550",
    "async_grpo_trainer.py": "15951bb122c4477ba82aeeb24ad85b35dd46fd8489f244364837dc958919af99",
}

EDITS = {
    "async_rollout_worker.py": [
        ('        rollout_id = uuid.uuid4().hex', '        rollout_id = policy_sessions.episode_id()'),
        ('            await asyncio.gather(\n                asyncio.create_task(self._generate_loop(stop_event=stop_event)),\n                asyncio.create_task(self._score_loop(stop_event=stop_event)),\n            )',
         '            async with asyncio.TaskGroup() as tasks:\n                tasks.create_task(self._generate_loop(stop_event=stop_event))\n                tasks.create_task(self._score_loop(stop_event=stop_event))'),
        ("class _AsyncRolloutLoop:", "from browser_training import policy_sessions as policy_sessions\n\n\nclass _AsyncRolloutLoop:"),
        ("    queued_at: float = 0.0", "    queued_at: float = 0.0\n    policy_cancelled: str | None = None"),
        ("        dataset_start_index: int = 0,\n", "        dataset_start_index: int = 0,\n        policy_registry=None,\n"),
        ("        self.model_name = model_name", "        self.policy_registry = policy_registry\n        if lora_name is not None and policy_registry is None:\n            raise policy_sessions.PolicyUnsafe('LoRA worker requires policy reservations')\n        self.model_name = model_name"),
        ('        return f"{self.lora_name}-v{self.model_version}"', '        return policy_sessions.request_model(self)'),
        ("                            model_version=self.model_version,", "                            model_version=(self.policy_registry.acquire_group(group_id)\n                                           if self.policy_registry is not None else self.model_version),"),
        ("                        self._generate_one(prompt, tool_dict=tool_dict, tools=tools, group_id=group_id)",
         "                        policy_sessions.generate_reserved(self, prompt, tool_dict=tool_dict, tools=tools, group_id=group_id)"),
        ("                    if pending_completed[group_id] == self.num_generations:\n", "                    if pending_completed[group_id] == self.num_generations:\n                        if self.policy_registry is not None:\n                            group.policy_cancelled = self.policy_registry.release_group(group_id)\n"),
        ("            try:\n                self._groups_to_score.put_nowait(None)",
         "            if self.policy_registry is not None:\n                for group_id in pending_groups:\n                    # A completed group can still be waiting for scoring queue space.\n                    if group_id in self.policy_registry.snapshot()['groups']:\n                        self.policy_registry.cancel_group(group_id, 'shutdown')\n                        self.policy_registry.release_group(group_id)\n            try:\n                self._groups_to_score.put_nowait(None)"),
        ('        output = await self._retry(\n            lambda: self._post("/v1/completions", payload, self.request_timeout),\n            max_attempts=30,\n            label="vllm /v1/completions",\n        )',
         '        output = await policy_sessions.reserved_request(self, payload)'),
        ("    async def _score_group(self, group: RolloutGroup) -> list[RolloutSample]:\n", "    async def _score_group(self, group: RolloutGroup) -> list[RolloutSample]:\n        if group.policy_cancelled:\n            self._push_metrics({'rollout/policy_discarded_groups': 1.0})\n            return []\n"),
        ('        self._mp_ctx = ctx', '        self._mp_ctx = ctx\n        self._policy_manager = None\n        self.policy_registry = loop_kwargs.get("policy_registry")\n        if loop_kwargs.get("lora_name") and self.policy_registry is None:\n            self._policy_manager, self.policy_registry = policy_sessions.shared_registry(ctx)\n            loop_kwargs["policy_registry"] = self.policy_registry'),
        ('        if self._failed_event.is_set():', '        if self.policy_registry is not None:\n            self.policy_registry.assert_healthy()\n        if self._failed_event.is_set():'),
        ('                self._process.terminate()', '                if self.policy_registry is not None:\n                    self.policy_registry.fail("Worker terminated with potentially outstanding inference; restart vLLM")\n                self._process.terminate()'),
        ('                    self._process.kill()\n        self._process = None',
         '                    self._process.kill()\n                    self._process.join(timeout=5)\n        if self.policy_registry is not None and self._process.exitcode not in (None, 0):\n            self.policy_registry.fail("Worker exited abnormally; restart vLLM before resuming")\n        self._process = None'),
    ],
    "openenv_harness.py": [
        ('        try:\n            await asyncio.gather(super()._run_loops(stop_event), _close_live_sessions_on_stop())\n        finally:\n            self._session_pool.shutdown(wait=True)',
         '        closer = asyncio.create_task(_close_live_sessions_on_stop())\n        try:\n            await super()._run_loops(stop_event)\n        finally:\n            stop_event.set()\n            await closer\n            await asyncio.to_thread(self._session_pool.shutdown, wait=True)'),
        ('class _HarnessRolloutLoop(_AsyncRolloutLoop):', 'from browser_training import policy_sessions as policy_sessions\n\n\nclass _HarnessRolloutLoop(_AsyncRolloutLoop):'),
        ('        result, metrics = await loop.run_in_executor(self._session_pool, self._run_session, prompt, group_id)',
         '        context = policy_sessions.copy_context()\n        result, metrics = await policy_sessions.drain(loop.run_in_executor(\n            self._session_pool, context.run, self._run_session, prompt, group_id))'),
        ('        rollout_id = uuid.uuid4().hex', '        rollout_id = policy_sessions.episode_id()'),
        ('        self._live_sessions.add(session)  # tracked so a stop can close it (unblocks wait_for_completion below)',
         '        self._live_sessions.add(session)  # tracked so a stop can close it (unblocks wait_for_completion below)\n        if self._stop_event.is_set():\n            self._live_sessions.discard(session)\n            session.close()\n            return self._EMPTY_ROLLOUT, None'),
        ('        self._adapter = harness_adapter', '        self._adapter = harness_adapter\n        if self.policy_registry is not None and harness_adapter is None:\n            raise policy_sessions.PolicyUnsafe("Reserved LoRA supports white-box harnesses only")'),
    ],
    "async_grpo_trainer.py": [
        ('        version = self.model_version + 1\n', '        from browser_training.policy_sessions import prepare_sync, publish_policy\n        prepare_sync(self)\n        version = self.model_version + 1\n'),
        ('            # TODO(@aminediro): decide if this is returned by the worker or common API that is passed to the worker later.',
         '            if self._lora_sync:\n                self.rollout_worker.policy_registry.configure(\n                    self.args.max_staleness, os.path.join(self.args.output_dir, "policy-events.jsonl"))\n            # TODO(@aminediro): decide if this is returned by the worker or common API that is passed to the worker later.'),
        ('            stale_version = version - (self.args.max_staleness + 1)\n            if stale_version > 0:\n                self.vllm_client.unload_lora_adapter(f"{self._lora_name}-v{stale_version}")\n            # The files outlive the unload by one sync: vLLM resolves `lora_path` lazily inside the engine, where\n            # a missing directory is not a 404 but a fatal `HFValidationError`.\n            if stale_version > 1:\n                stale_dir = f"{self._lora_name}-v{stale_version - 1}"\n                shutil.rmtree(os.path.join(self._lora_dir, stale_dir), ignore_errors=True)',
         '            publish_policy(self, version)'),
    ],
}


def restore_source(name, source):
    for before, after in reversed(EDITS[name]):
        if after in source:
            source = source.replace(after, before)
    return source


def patched_source(name, source):
    original = restore_source(name, source)
    normalized = original
    if name == "async_grpo_trainer.py":
        from .attention_compat import OLD, NEW
        normalized = normalized.replace(NEW, OLD)
    if hashlib.sha256(normalized.encode()).hexdigest() != HASHES[name]:
        raise ValueError(f"Unknown {name}; re-audit TRL before applying policy reservations")
    updated = original
    for before, after in EDITS[name]:
        if updated.count(before) != 1:
            raise ValueError(f"Expected exactly one patch location: {before[:80]}")
        updated = updated.replace(before, after)
    # Reject partial patches instead of silently repairing interrupted installations.
    if source not in (original, updated):
        raise ValueError(f"Partial policy patch in {name}; restore the pinned package first")
    return updated


def is_patched(name, source):
    return patched_source(name, source) == source
