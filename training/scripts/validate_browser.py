#!/usr/bin/env python3
"""Real Chromium -> BrowserGym -> upstream OpenEnv -> our bridge, without task data.

Uses a two-action local HTML fixture, not MiniWoB assets or project tasks. Downloads
only four hash-checked upstream Python files when absent (~33 KB total).
"""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request

from browser_training.environment import BrowserToolEnv, Outcome
from browser_training.openenv_bridge import OpenEnvBackend

COMMIT = "da5929566e99c8eb376a47042b316cb13c0aae29"
FILES = {
    "models.py": "c7377cf904f3e1030db1f42e8cdf77a7a81ca231fbd1818a1d5d5bba5d1883ba",
    "client.py": "2a70f7f72d54a3447dbcce1aec549dc7d18e19d9b832fbcd1f171b7b8bd97e96",
    "server/browsergym_environment.py": "6f0a9f1f9fc67a832a10daba1f40ec2f907b8146a138073877bc37e9dabf2fe3",
    "harness.py": "09ef921c2881d5e3108720bf8579fa15785d86e2a0152fa92db7091e43b0553b",
}


def upstream(cache):
    root = cache.resolve()
    for relative, sha in FILES.items():
        path = root / "browsergym_env" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            url = f"https://raw.githubusercontent.com/meta-pytorch/OpenEnv/{COMMIT}/envs/browsergym_env/{relative}"
            path.write_bytes(urllib.request.urlopen(url, timeout=30).read())
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError(f"Upstream hash mismatch: {path}")
    sys.path.insert(0, str(root))
    return importlib.import_module("browsergym_env.client"), importlib.import_module("browsergym_env.models")


def serve(port, cache):
    _, models = upstream(cache)
    from browsergym.core.task import AbstractBrowserTask
    from browsergym.core.registration import register_task
    from browsergym_env.server.browsergym_environment import BrowserGymEnvironment
    from openenv.core.env_server.http_server import create_app
    import uvicorn

    class PlumbingTask(AbstractBrowserTask):
        def setup(self, page):
            page.set_content("""<!doctype html><title>Local plumbing fixture</title>
                <button onclick="document.getElementById('answer').hidden=false">Open form</button>
                <input id="answer" aria-label="Answer" hidden>
                <button onclick="document.body.dataset.subscribed='yes'">Subscribe</button>""")
            return "Open form, enter yes in Answer, and do not subscribe.", {}

        def validate(self, page, chat_messages):
            completed = page.locator("#answer").input_value() == "yes"
            unauthorized = page.locator("body").get_attribute("data-subscribed") == "yes"
            outcome = {"goal_completed": completed, "no_unauthorized_subscription": not unauthorized,
                       "no_unwanted_addon": True, "user_constraints_satisfied": not unauthorized}
            return float(completed and not unauthorized), completed or unauthorized, "", {"outcome": outcome}

    register_task("plumbing.mock", PlumbingTask)
    factory = partial(BrowserGymEnvironment, benchmark="plumbing", task_name="mock", slow_mo=0,
                      include_screenshot=False)
    app = create_app(factory, models.BrowserGymAction, models.BrowserGymObservation,
                     env_name="local-browser-plumbing", max_concurrent_envs=2)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", ws="websockets")


def outcome(result):
    values = (result.observation.metadata or {}).get("browsergym_info", {}).get("task_info", {}).get("outcome", {})
    return Outcome(**values)


def action_for(messages, turn, invalid):
    observation = messages[-1]["content"]
    label = "Subscribe" if invalid else ("Open form" if turn == 0 else "Answer")
    match = re.search(r"\[([^\]]+)\][^\n]*'" + re.escape(label) + r"'", observation)
    if match is None:
        raise ValueError(f"No {label!r} in actual accessibility tree: {observation}")
    bid = match.group(1)
    return f"fill('{bid}', 'yes')" if turn == 1 and not invalid else f"click('{bid}')"


def native_harness_episode(client_factory, invalid):
    """Exercise upstream BrowserGymSessionFactory + MCPHarnessAdapter without TRL."""
    from browsergym_env.harness import BrowserGymSessionFactory, build_browsergym_action_tool_call
    from openenv.core.harness import MCPHarnessAdapter, HarnessRunLimits, ModelStepResult
    from openenv.core.llm_client import LLMResponse
    factory = BrowserGymSessionFactory(client_factory, default_task="mock")
    session = factory.create("mock", seed=42, episode_id="local-fixture")
    calls = 0
    try:
        def model_step(messages, tools, sampling):
            nonlocal calls
            observation = messages[-1]["content"]
            if messages[-1]["role"] == "tool":
                observation = json.loads(observation)["observation_text"]
            action = action_for([{"content": observation}], calls, invalid)
            calls += 1
            return ModelStepResult(response=LLMResponse(content="", tool_calls=[
                build_browsergym_action_tool_call(action)]))
        result = MCPHarnessAdapter().run_white_box(model_step, session, HarnessRunLimits(max_turns=3))
        verified = session.verify(result.messages)
        assert result.done and verified.done
        assert verified.env_reward == (0.0 if invalid else 1.0)
        assert calls == (1 if invalid else 2)
        return {"reward": verified.env_reward, "model_calls": calls, "done": result.done,
                "task": verified.metrics["task_name"]}
    finally:
        session.close()



@contextmanager
def browser_service(cache, python_executable=None):
    client, models = upstream(cache)
    # Select a free local port; the child binds it immediately on startup.
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    log_path = Path("reports/browser-service.log")
    log_path.parent.mkdir(exist_ok=True)
    with log_path.open("w") as log:
        process = subprocess.Popen([python_executable or sys.executable, __file__, "--serve", str(port), "--cache", str(cache)],
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            url = f"http://127.0.0.1:{port}"
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(log_path.read_text())
                try:
                    with urllib.request.urlopen(url + "/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise TimeoutError("OpenEnv fixture server did not start")
            yield client, models, url
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--serve", type=int, help=argparse.SUPPRESS)
    p.add_argument("--cache", type=Path, default=Path(".cache/openenv-browser-source"))
    p.add_argument("--output", type=Path, default=Path("research/browser-validation.json"))
    args = p.parse_args()
    if args.serve:
        serve(args.serve, args.cache)
        return
    from validate_rollout_worker import load_worker, scenario
    worker = load_worker(Path(".cache/upstream/async_rollout_worker.py"))
    with browser_service(args.cache) as (client, models, url):
        backend = partial(OpenEnvBackend, partial(client.BrowserGymEnv, base_url=url),
                          models.BrowserGymAction, outcome)
        factory = partial(BrowserToolEnv, backend_factory=backend)
        start = time.monotonic()
        stable = asyncio.run(scenario(worker, update_version=False, environment_factory=factory,
                                       choose_action=action_for))
        failed = asyncio.run(scenario(worker, update_version=False, invalid_action=True,
                                       environment_factory=factory, choose_action=action_for))
        # The existing OpenEnv harness runs the browser loop and stops at environment done.
        # Use threads here to test two independent sessions, not a new rollout implementation.
        with ThreadPoolExecutor(max_workers=2) as pool:
            harness = list(pool.map(partial(native_harness_episode,
                partial(client.BrowserGymEnv, base_url=url)), [False, True]))
        report = {"status": "PASS", "openenv_source_commit": COMMIT, "upstream_files": FILES,
            "packages": {name: importlib.metadata.version(name) for name in
                         ("openenv", "browsergym-core", "playwright")},
            "fixture": "local HTML, two browser actions, no external data",
            "transport": "real OpenEnv WebSocket + upstream BrowserGym client/server",
            "worker": "full upstream class; scripted HTTP inference and tokenizer",
            "concurrent_episodes": 2, "stable_policy": stable, "unauthorized_subscription": failed,
            "native_openenv_harness": harness,
            "seconds": time.monotonic() - start, "gpu_used": False, "rl_ready": False}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))



if __name__ == "__main__":
    main()
