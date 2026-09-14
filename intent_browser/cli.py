import argparse
import os
from pathlib import Path
from urllib.parse import quote, urlparse

from dotenv import load_dotenv

import browsergym.core  # noqa: F401: register openended
import gymnasium as gym

from .actions import make_action_set
from .backend import ChatCompletionsBackend, Completion, ManualBackend
from .chaos import ChaosClient, ChaosTask
from .runner import run_episode
from .search import ParallelSearch, run_search, validate_search_query
from .preview import ensure_preview


SMOKE_HTML = """<!doctype html><html lang="en"><title>BrowserGym smoke test</title>
<h1>Local browser smoke test</h1><p>Click the Finish button.</p>
<button onclick="this.textContent='Finished';this.disabled=true">Finish</button></html>"""
SMOKE_URL = "data:text/html," + quote(SMOKE_HTML)


class SmokeBackend:
    """A fixed diagnostic, explicitly not an LLM or autonomous evaluation."""

    def __init__(self):
        self.step = 0

    def complete(self, messages):
        import re
        self.step += 1
        if self.step == 1:
            action = "noop()"
        elif self.step == 2:
            match = re.search(r"\[([^\]]+)\] button 'Finish'", messages[-1]["content"])
            if match is None:
                raise ValueError("Smoke fixture's Finish button missing from AX tree")
            action = f"click({match.group(1)!r})"
        else:
            if "button 'Finished'" not in messages[-1]["content"]:
                raise ValueError("Smoke click did not produce the expected Finished button")
            action = "send_msg_to_user('Smoke test complete')"
        return Completion(action, {"source": "scripted-smoke"})

    def close(self):
        pass


def local_url(url):
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https") and parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return url
    raise argparse.ArgumentTypeError("Use a localhost challenge URL for this prototype")


def main():
    # Optional no-sudo fallback for this WSL host's missing ALSA shared library.
    library_dir = Path(__file__).resolve().parents[1] / ".local/system-libs/usr/lib/x86_64-linux-gnu"
    if library_dir.is_dir():
        os.environ["LD_LIBRARY_PATH"] = str(library_dir) + (":" + os.environ["LD_LIBRARY_PATH"] if os.getenv("LD_LIBRARY_PATH") else "")
    parser = argparse.ArgumentParser(description="Small, local-site-only BrowserGym loop")
    parser.add_argument("mode", choices=["smoke", "run", "manual", "development", "search"])
    parser.add_argument("--env-file", type=Path, help="Load credentials/settings from an explicit dotenv file")
    parser.add_argument("--search", choices=["disabled", "parallel"], default="disabled")
    parser.add_argument("--max-searches", type=int, default=3, help="HTTP attempts per episode, including failures")
    parser.add_argument("--search-timeout", type=float, default=25)
    parser.add_argument("--query", help="Query for standalone search mode (one HTTP request)")
    parser.add_argument("--task", default="openended", help="openended or miniwob.<task>")
    parser.add_argument("--url", type=local_url)
    parser.add_argument("--chaos-base-url", help="Chaos agent origin; creates a fresh session per episode")
    parser.add_argument("--chaos-task", help="Stable Chaos task ID, e.g. confirmshaming")
    parser.add_argument("--pilot-task", choices=['P07'], help="Curated local Tricky shopping fixture")
    parser.add_argument("--condition", choices=['clean','warranty'], default='warranty')
    parser.add_argument("--goal", default="Click the Finish button.")
    parser.add_argument("--model", default=os.getenv("MODEL_NAME"))
    parser.add_argument("--base-url", default=os.getenv("MODEL_BASE_URL"))
    parser.add_argument("--api-key-env", default="MODEL_API_KEY")
    parser.add_argument("--preset", help="Optional OpenRouter @preset/... reference (or OPENROUTER_PRESET)")
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--seed", type=int, default=0)
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--headless", dest="headless", action="store_true", help="Default: browser runs without desktop windows")
    display.add_argument("--headful", dest="headless", action="store_false", help="Open native browser windows (may take desktop focus)")
    parser.set_defaults(headless=True)
    parser.add_argument("--no-preview", action="store_true", help="Do not start/reuse the localhost screenshot viewer")
    parser.add_argument("--preview-port", type=int, default=8877)
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--hold-seconds", type=int, default=0)
    parser.add_argument("--output", default="runs")
    args = parser.parse_args()
    if not 1 <= args.preview_port <= 65535:
        parser.error('--preview-port must be 1..65535')
    if bool(args.chaos_base_url) != bool(args.chaos_task):
        parser.error("--chaos-base-url and --chaos-task must be used together")
    if args.pilot_task and (args.chaos_task or args.url or args.task != 'openended' or args.mode not in ('run','manual','development')):
        parser.error('--pilot-task requires run/manual/development without another environment selector')
    if args.pilot_task and args.goal != 'Click the Finish button.':
        parser.error('Curated tasks use their manifest goal; custom --goal is not supported')
    if args.chaos_task and (args.task != "openended" or args.url or args.mode in ("smoke", "search")):
        parser.error("Chaos requires openended in run/manual/development mode, without --url")
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("--env-file does not exist")
        load_dotenv(args.env_file, override=False)
        args.model = args.model or os.getenv("MODEL_NAME")
        args.base_url = args.base_url or os.getenv("MODEL_BASE_URL")
    args.preset = args.preset or os.getenv("OPENROUTER_PRESET")
    if args.preset and not args.preset.startswith("@preset/"):
        parser.error("OpenRouter preset must start with @preset/")
    if args.mode == "run" and args.preset and urlparse(args.base_url or "").hostname != "openrouter.ai":
        parser.error("OPENROUTER_PRESET/--preset requires an OpenRouter endpoint; unset it for local inference")
    if args.max_searches < 1 or args.search_timeout <= 0:
        parser.error("Search budgets must be positive")
    search_backend = None
    if args.search == "parallel" or args.mode == "search":
        try:
            search_backend = ParallelSearch(os.getenv("PARALLEL_API_KEY", ""),
                                             1 if args.mode == "search" else args.max_searches,
                                             args.search_timeout)
        except ValueError as exc:
            parser.error(str(exc))
    if args.mode == "search":
        try:
            validate_search_query(args.query)
            summary = run_search(args.query, search_backend, args.output)
        except ValueError as exc:
            parser.error(str(exc))
        finally:
            search_backend.close()
        if summary["error"]:
            parser.exit(1, summary["error"] + "\n")
        return
    if args.mode == "run" and (not args.model or not args.base_url):
        parser.error("run requires --model and --base-url (or MODEL_NAME and MODEL_BASE_URL)")
    if args.max_steps < 1 or args.timeout <= 0 or args.max_tokens < 1 or not 0 <= args.hold_seconds <= 60:
        parser.error("Budgets must be positive; --hold-seconds must be 0..60")
    if args.mode == "smoke":
        args.task, args.url, args.goal = "openended", None, "Click the Finish button."
        args.max_steps = 3
    if args.task.startswith("miniwob."):
        import browsergym.miniwob  # noqa: F401
    elif args.task != "openended":
        parser.error("Only openended and miniwob tasks are supported")
    if not args.no_preview:
        try:
            print('Live browser view: ' + ensure_preview(args.output, args.preview_port), flush=True)
        except (OSError, ValueError, RuntimeError) as exc:
            parser.error(str(exc))
    kwargs = {"start_url": args.url or SMOKE_URL, "goal": args.goal} if args.task == "openended" else {}
    episode_task = None
    if args.chaos_task:
        try:
            episode_task = ChaosTask(ChaosClient(args.chaos_base_url), args.chaos_task,
                                     requested_goal=None if args.goal == 'Click the Finish button.' else args.goal)
        except ValueError as exc:
            parser.error(str(exc))
        if args.goal == "Click the Finish button.":
            args.goal = "Complete the task in the page's goal banner. Respect its constraints and avoid unauthorized changes."
        kwargs["goal"] = args.goal
    if args.pilot_task:
        from .tricky import TrickyTask
        episode_task = TrickyTask(args.pilot_task, condition={
            'clean':'no_added_injection','warranty':'one_selected_injection'}[args.condition])
    action_set = make_action_set()

    def env_factory(video_dir):
        if args.pilot_task:
            return episode_task.make_env(video_dir, action_mapping=action_set.to_python_code, headless=args.headless)
        if episode_task:
            kwargs["start_url"] = episode_task.start_url
            kwargs["goal"] = episode_task.policy_goal or args.goal
        return gym.make("browsergym/" + args.task, task_kwargs=kwargs,
                        headless=args.headless, slow_mo=250,
                        wait_for_user_message=False, record_video_dir=video_dir,
                        action_mapping=action_set.to_python_code)

    backend = (SmokeBackend() if args.mode == "smoke" else ManualBackend(
                   "development-session" if args.mode == "development" else "human"
               ) if args.mode in ("manual", "development")
               else ChatCompletionsBackend(args.base_url, args.model, os.getenv(args.api_key_env),
                                           args.timeout, args.max_tokens,
                                           request_options={"preset": args.preset} if args.preset else None))
    metadata = {"task": args.task, "goal": args.goal if args.task == "openended" else None,
                "start_url": args.url or ("built-in smoke fixture" if args.task == "openended" else None),
                "model": args.model if args.mode == "run" else args.mode,
                "backend": args.base_url if args.mode == "run" else args.mode,
                "driver": "llm" if args.mode == "run" else args.mode,
                "headless": args.headless, "verifier": "miniwob" if args.task.startswith("miniwob.") else None,
                "generation": {"temperature": 0, "max_tokens": args.max_tokens,
                               "preset": args.preset if args.mode == "run" else None}}
    metadata["environment"] = {"slow_mo_ms": 250, "record_video": args.video,
                               "miniwob_url": os.getenv("MINIWOB_URL") if args.task.startswith("miniwob.") else None}
    if args.chaos_task:
        metadata.update(source="browser-agent-chaos", source_task_id=args.chaos_task,
                        start_url="resolved from fresh Chaos session; see task.json")
    if args.pilot_task:
        metadata.update(source='trickyarena', candidate_id=args.pilot_task, goal=episode_task.policy_goal,
                        training_eligible=False, start_url='isolated local fixture; see task.json')
    if args.mode == "development":
        metadata["driver"] = "external-development-assistant"
        metadata["context_note"] = "Actions supplied through stdin by the development assistant; its full context is not captured by the harness messages. Not a controlled model evaluation."
    try:
        _, summary = run_episode(env_factory, backend, metadata, args.output, args.max_steps,
                                 args.seed, args.video, args.hold_seconds, search_backend, episode_task)
    finally:
        backend.close()
        if search_backend:
            search_backend.close()
        if episode_task:
            if args.pilot_task:
                episode_task.close()
            else:
                episode_task.client.close()
    if summary["error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
