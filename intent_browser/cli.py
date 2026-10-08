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
from .retry_policy import DecisionRetryPolicy
from .search import ParallelSearch, run_search, validate_search_query
from .preview import ensure_preview
from .openrouter import completion_token_limit
from .input_budget import DEFAULT_MAX_STEPS, DEFAULT_MAX_INPUT_TOKENS


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
    parser = argparse.ArgumentParser(description="BrowserGym loop; local sites by default, explicit opt-in open internet")
    parser.add_argument("mode", choices=["smoke", "run", "manual", "development", "search"])
    parser.add_argument("--env-file", type=Path, help="Load credentials/settings from an explicit dotenv file")
    parser.add_argument("--search", choices=["disabled", "parallel"], default="disabled")
    parser.add_argument("--max-searches", type=int, default=3, help="HTTP attempts per episode, including failures")
    parser.add_argument("--search-timeout", type=float, default=25)
    parser.add_argument("--query", help="Query for standalone search mode (one HTTP request)")
    parser.add_argument("--task", default="openended", help="openended or miniwob.<task>")
    parser.add_argument("--url")
    parser.add_argument('--open-internet', action='store_true',
                        help='Opt-in current-harness live HTTP(S) browsing with fresh context and tabs; no task grader')
    parser.add_argument('--shoe-search', action='store_true', help='Open internet: original New Balance request plus Sweden comparison context')
    parser.add_argument('--step-through', action='store_true', help='Open internet: pause before each fresh observation for human intervention')
    parser.add_argument('--human-handover', action='store_true',
        help='Open internet: yield tabs to a local human panel while the agent works in other tabs; requires --headful --no-subagents')
    parser.add_argument('--capture-timeout-mode',choices=['diagnostic','bounded'],default=None,
        help='Human-handover capture/guard deadlines: diagnostic logs overruns without aborting (default); bounded enforces deadlines')
    parser.add_argument('--record-har', action='store_true', help='Open internet: save private network archive; may contain sensitive site/session data')
    parser.add_argument('--record-fact-provenance', action='store_true',
        help='Private AX output/delivery sidecars; missing trusted source exports remain unknown')
    parser.add_argument('--grading-factory', help='Trusted MODULE:CALLABLE taking (episode_task,args), returning AutomaticGrading')
    parser.add_argument('--allow-ungraded', action='store_true', help='Explicit diagnostic escape; requires --ungraded-reason')
    parser.add_argument('--ungraded-reason', help='Recorded reason for intentionally ungraded diagnostic')
    parser.add_argument("--chaos-base-url", help="Chaos agent origin; creates a fresh session per episode")
    parser.add_argument("--chaos-task", help="Stable Chaos task ID, e.g. confirmshaming")
    parser.add_argument("--pilot-task", choices=['P07','P10','P11'], help="Local Tricky shopping, privacy or membership fixture")
    parser.add_argument("--condition", choices=['clean','injected','warranty'], default=None, help='Default injected; warranty is the legacy P07 alias')
    parser.add_argument("--goal", default="Click the Finish button.")
    parser.add_argument('--native-tool-choice', choices=['auto','required'], default='auto',
                        help='core-tools profiles only: advertise tools normally or require a tool call')
    parser.add_argument('--retry-policy', choices=['none','bounded-v1'], default=None,
                        help='Opt-in single model recovery within existing episode call/budget caps')
    parser.add_argument('--strict-tools', action='store_true',
                        help='core-tools profiles only: request provider-side strict argument schemas')
    parser.add_argument('--reasoning-replay', choices=['preserve','strip'], default=None,
                        help='core-tools profiles: preserve returned reasoning (default), or strip for an ablation')
    parser.add_argument('--harness-profile', choices=['legacy', 'append-feedback-v1', 'append-events-v1', 'core-feedback-v2', 'core-tools-v1', 'core-tools-v2', 'core-tools-v3', 'core-tools-v4-navigation', 'core-tools-v5-feedback', 'core-tools-v6-ax','core-tools-v7-context','core-tools-v8-vision','core-tools-v9-batch','core-tools-v10-agents','core-tools-v11-data','core-tools-v12-ax-reuse'],
                        default=None, help='Live runs default to the combined current harness; explicit historical profiles remain available')
    parser.add_argument('--no-subagents',action='store_true',help='Current harness ablation: omit helper tools for the whole conversation')
    parser.add_argument('--navigation-origin', action='append', default=[],
                        help='Trusted exact HTTP(S) origin; repeat for multi-site navigation profile')
    parser.add_argument('--image-retention', choices=['retain','agent'], default=None,
                        help='v8 vision: retain images by default, or allow explicit agent release')
    parser.add_argument('--ax-tokenizer-file', help='core-tools-v6-ax: existing local tokenizer.json')
    parser.add_argument('--ax-overview-tokens', type=int, default=2000)
    parser.add_argument('--ax-result-tokens', type=int, default=1500)
    parser.add_argument('--ax-verbose', action='store_true', help='v7: include AX extraction diagnostics by default')
    parser.add_argument('--ax-repeat', action='store_true', help='v7: resend known AX content by default (ablation)')
    parser.add_argument("--action-timeout-ms", type=int, default=None,
                        help="Override project action deadlines (default 5000 ms; 500 reproduces legacy timing)")
    parser.add_argument("--model", default=os.getenv("MODEL_NAME"))
    parser.add_argument("--base-url", default=os.getenv("MODEL_BASE_URL"))
    parser.add_argument("--api-key-env", default="MODEL_API_KEY")
    parser.add_argument("--preset", help="Legacy explicit preset; cannot combine with provider allowlist")
    parser.add_argument("--providers", help="Comma-separated OpenRouter allowlist (or OPENROUTER_PROVIDERS)")
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument('--max-input-tokens', type=int, default=DEFAULT_MAX_INPUT_TOKENS,
                        help='Current AX harness: estimated next input ceiling, checked before inference (default 100000)')
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--max-tokens", type=int, default=None,
                        help="Combined reasoning/answer ceiling; OpenRouter defaults to OPENROUTER_MAX_TOKENS or 16384, local endpoints to 128")
    parser.add_argument("--seed", type=int, default=0)
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--headless", dest="headless", action="store_true", help="Default: browser runs without desktop windows")
    display.add_argument("--headful", dest="headless", action="store_false", help="Open native browser windows (may take desktop focus)")
    parser.set_defaults(headless=True)
    parser.add_argument("--no-preview", action="store_true", help="Do not start/reuse the localhost screenshot viewer")
    parser.add_argument("--preview-port", type=int, default=8877)
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--observation-mode", choices=("auto","native"), default="auto",
                        help="Auto: reviewed live-web preview/overlap when compatible; native: full observations")
    capture_images=parser.add_mutually_exclusive_group()
    capture_images.add_argument("--screenshots", dest="trace_screenshots", action="store_true", default=None,
                        help="Retain automatic screenshots; disables deferred post-action capture")
    capture_images.add_argument("--no-screenshots", dest="trace_screenshots", action="store_false", default=None,
                        help="Skip automatic observation screenshots; explicit screenshot tool and --video remain independent")
    parser.add_argument("--hold-seconds", type=int, default=0)
    parser.add_argument("--output", default="runs")
    parser.add_argument("--collection", help="Viewer folder, e.g. Integration/checkout or RL/experiment-1; independent of --output")
    args = parser.parse_args()
    if args.collection is not None:
        from agent_trace.collections import normalize_collection
        try:args.collection=normalize_collection(args.collection)
        except ValueError as error:parser.error(str(error))
    if args.open_internet:
        if args.mode != 'run' or args.task != 'openended' or args.chaos_task or args.pilot_task or args.navigation_origin:
            parser.error('--open-internet requires run/openended without a fixture or fixed navigation origins')
        if args.harness_profile not in (None, 'core-tools-v10-agents', 'core-tools-v11-data', 'core-tools-v12-ax-reuse'):
            parser.error('--open-internet uses the current harness; historical profiles stay unchanged')
        if args.shoe_search and args.goal != 'Click the Finish button.':
            parser.error('Choose --shoe-search or --goal')
        from .open_internet import SHOE_GOAL
        if args.shoe_search:
            args.goal = SHOE_GOAL
        if not args.url or args.goal == 'Click the Finish button.':
            parser.error('--open-internet requires --url and --goal (or --shoe-search)')
        try:
            from .navigation import origin
            origin(args.url)
        except ValueError as exc:
            parser.error(str(exc))
        if args.step_through and args.headless:
            parser.error('--step-through requires --headful so the human can inspect/intervene')
    else:
        if args.shoe_search or args.step_through or args.record_har:
            parser.error('--shoe-search/--step-through/--record-har require --open-internet')
        if args.url:
            try:
                args.url = local_url(args.url)
            except argparse.ArgumentTypeError as exc:
                parser.error(str(exc))
    if args.human_handover and (not args.open_internet or args.headless or args.step_through or not args.no_subagents):
        parser.error('--human-handover requires --open-internet --headful --no-subagents, without --step-through')
    if args.capture_timeout_mode is not None and not args.human_handover:
        parser.error('--capture-timeout-mode requires --human-handover')
    enable_data=args.harness_profile!='core-tools-v10-agents'
    adaptive_ax=args.harness_profile in (None,'core-tools-v12-ax-reuse')
    current_profile=args.harness_profile in ('core-tools-v10-agents','core-tools-v11-data','core-tools-v12-ax-reuse') or (args.harness_profile is None and args.mode=='run')
    if current_profile:
        from .standard_profile import tokenizer_path
        args.harness_profile='core-tools-v9-batch'
        args.ax_tokenizer_file=args.ax_tokenizer_file or tokenizer_path()
    elif args.harness_profile is None:args.harness_profile='legacy'
    args.retry_policy=args.retry_policy or ('bounded-v1' if current_profile else 'none')
    if args.no_subagents and not current_profile:parser.error('--no-subagents requires the current harness')
    if not 1 <= args.preview_port <= 65535:
        parser.error('--preview-port must be 1..65535')
    if bool(args.chaos_base_url) != bool(args.chaos_task):
        parser.error("--chaos-base-url and --chaos-task must be used together")
    if args.pilot_task and (args.chaos_task or args.url or args.task != 'openended' or args.mode not in ('run','manual','development')):
        parser.error('--pilot-task requires run/manual/development without another environment selector')
    if args.condition == 'warranty' and args.pilot_task != 'P07':
        parser.error('--condition warranty is only an alias for P07; use injected for other fixtures')
    if args.condition and not args.pilot_task:
        parser.error('--condition requires --pilot-task')
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
    if args.max_tokens is None:
        try:
            args.max_tokens = (completion_token_limit(os.getenv('OPENROUTER_MAX_TOKENS'))
                               if urlparse(args.base_url or '').hostname == 'openrouter.ai' else 128)
        except ValueError as exc:
            parser.error(str(exc))
    args.preset = args.preset or os.getenv("OPENROUTER_PRESET")
    args.providers = args.providers or os.getenv('OPENROUTER_PROVIDERS')
    request_options = {}
    session_routing = False
    if args.mode == 'run' and urlparse(args.base_url or '').hostname == 'openrouter.ai':
        from .openrouter import DEFAULT_PROVIDERS, provider_options
        if args.preset and args.providers:
            parser.error('Choose a model slug/provider allowlist or a legacy preset, not both')
        if not args.preset:
            try:
                request_options = provider_options(args.providers or DEFAULT_PROVIDERS)
            except ValueError as exc:
                parser.error(str(exc))
            session_routing = True
    elif args.mode == 'run' and args.providers:
        parser.error('--providers/OPENROUTER_PROVIDERS requires an OpenRouter endpoint')
    if args.preset:
        request_options = {'preset': args.preset, 'reasoning': {'enabled': True}}
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
    if args.allow_ungraded and args.grading_factory:
        parser.error('Choose --grading-factory or --allow-ungraded')
    if not args.grading_factory:
        try:
            from .automatic_grading import validate_options
            validate_options(None,args.allow_ungraded,args.ungraded_reason)
        except ValueError as exc:parser.error(str(exc))
    elif args.ungraded_reason is not None:
        parser.error('--ungraded-reason requires --allow-ungraded')
    if args.mode == "run" and (not args.model or not args.base_url):
        parser.error("run requires --model and --base-url (or MODEL_NAME and MODEL_BASE_URL)")
    if args.max_steps < 1 or args.max_input_tokens < 1 or args.timeout <= 0 or args.max_tokens < 1 or not 0 <= args.hold_seconds <= 60:
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
        condition = 'no_added_injection' if args.condition == 'clean' else 'one_selected_injection'
        if args.pilot_task == 'P07':
            from .tricky import TrickyTask
            episode_task = TrickyTask('P07', condition=condition)
        elif args.pilot_task == 'P11':
            from .tricky_membership import MembershipTask
            episode_task = MembershipTask(condition=condition)
        else:
            from .tricky_privacy import PrivacyTask
            episode_task = PrivacyTask(condition=condition)
    if args.harness_profile not in ('core-tools-v1','core-tools-v2','core-tools-v3','core-tools-v4-navigation','core-tools-v5-feedback','core-tools-v6-ax','core-tools-v7-context','core-tools-v8-vision','core-tools-v9-batch') and (args.strict_tools or args.native_tool_choice != 'auto' or args.reasoning_replay is not None or args.retry_policy != 'none'):
        parser.error('Native tool options require --harness-profile core-tools-v1/v2/v3/v4-navigation/v5-feedback')
    if args.harness_profile not in ('core-tools-v6-ax','core-tools-v7-context','core-tools-v8-vision','core-tools-v9-batch') and bool(args.navigation_origin) != (args.harness_profile in ('core-tools-v4-navigation','core-tools-v5-feedback')):
        parser.error('Navigation profiles require --navigation-origin; other profiles do not accept it')
    if bool(args.ax_tokenizer_file) != (args.harness_profile in ('core-tools-v6-ax','core-tools-v7-context','core-tools-v8-vision','core-tools-v9-batch')):
        parser.error('AX profiles require --ax-tokenizer-file; non-AX profiles do not accept it')
    if (args.ax_verbose or args.ax_repeat) and args.harness_profile not in ('core-tools-v7-context','core-tools-v8-vision','core-tools-v9-batch'):
        parser.error('--ax-verbose/--ax-repeat require core-tools-v7-context')
    if args.image_retention is not None and args.harness_profile not in ("core-tools-v8-vision","core-tools-v9-batch"):
        parser.error("--image-retention requires core-tools-v8-vision")
    ax_config = None
    if args.ax_tokenizer_file:
        from .ax_explorer import AXConfig
        ax_config = AXConfig(args.ax_tokenizer_file, args.ax_overview_tokens, args.ax_result_tokens,
            incremental=args.harness_profile in ('core-tools-v7-context','core-tools-v8-vision','core-tools-v9-batch'), verbose=args.ax_verbose, repeat=args.ax_repeat)
    harness_profile = None
    if args.harness_profile != 'legacy':
        if episode_task is not None:
            if not current_profile:parser.error('Historical development profiles require explicit adapter adoption')
            from .current_task import CurrentPolicyTask
            episode_task=CurrentPolicyTask(episode_task)
        from .harness import HarnessProfile
        if args.harness_profile in ('core-tools-v1','core-tools-v2','core-tools-v3','core-tools-v4-navigation','core-tools-v5-feedback','core-tools-v6-ax','core-tools-v7-context','core-tools-v8-vision','core-tools-v9-batch'):
            if args.mode != 'run':
                parser.error('Native tools require run mode with an API backend')
            from .vision import VisionConfig
            from .harness import native_tools_profile
            harness_profile=native_tools_profile(tool_choice=args.native_tool_choice,strict=args.strict_tools,
                parallel_tool_calls=False if args.harness_profile=='core-tools-v1' else None,
                compact_feedback=args.harness_profile in ('core-tools-v3','core-tools-v4-navigation','core-tools-v5-feedback','core-tools-v6-ax','core-tools-v7-context','core-tools-v8-vision','core-tools-v9-batch'),
                navigation_origins=tuple(args.navigation_origin),
                timeout_feedback=args.harness_profile in ('core-tools-v5-feedback','core-tools-v6-ax','core-tools-v7-context','core-tools-v8-vision','core-tools-v9-batch'),
                ax_config=ax_config,
                vision_config=VisionConfig(args.image_retention or "retain") if args.harness_profile in ("core-tools-v8-vision","core-tools-v9-batch") else None,
                reasoning_replay=args.reasoning_replay or 'preserve',
                batch_size=8 if args.harness_profile=='core-tools-v9-batch' else 1)
            if current_profile:
                from dataclasses import replace
                from .harness import with_subagents
                harness_profile=replace(harness_profile,navigation_from_reset=not bool(args.navigation_origin))
                if not args.no_subagents:harness_profile=with_subagents(harness_profile)
                if enable_data:
                    from .harness import with_data_tools
                    from .data_tools import DataConfig
                    harness_profile=with_data_tools(harness_profile,DataConfig(image=os.getenv('HARNESS_PYTHON_IMAGE','intent-browser-python:stdlib-v1')))
                if adaptive_ax:
                    from .standard_profile import with_adaptive_ax
                    harness_profile=with_adaptive_ax(harness_profile)
        elif args.harness_profile == 'core-feedback-v2':
            from .harness import core_feedback_profile
            harness_profile=core_feedback_profile()
        elif args.harness_profile == 'append-events-v1':
            from .browser_feedback import BrowserEventFeedback
            harness_profile = HarnessProfile(name='append-events-v1', feedback_factory=BrowserEventFeedback)
        else:
            harness_profile = HarnessProfile()
    if args.open_internet:
        from .open_internet import OpenInternetTask, open_profile
        harness_profile = open_profile(harness_profile)
        if args.human_handover:
            from .open_internet import with_human_handover
            harness_profile = with_human_handover(harness_profile,
                compact_tabs=adaptive_ax,stable_frames=adaptive_ax,
                capture_timeout_mode=args.capture_timeout_mode or 'diagnostic')
        episode_task = OpenInternetTask(args.url, args.goal, headless=args.headless, har=args.record_har)
        episode_task.supported_harness_profiles = (harness_profile.name,)
    action_set = make_action_set()

    def env_factory(video_dir):
        if args.open_internet:
            return episode_task.make_env(video_dir, action_mapping=action_set.to_python_code)
        if args.pilot_task:
            return episode_task.make_env(video_dir, action_mapping=action_set.to_python_code, headless=args.headless)
        if episode_task:
            kwargs["start_url"] = episode_task.start_url
            kwargs["goal"] = episode_task.policy_goal or args.goal
        return gym.make("browsergym/" + args.task, task_kwargs=kwargs,
                        headless=args.headless, slow_mo=250,
                        wait_for_user_message=False, record_video_dir=video_dir,
                        action_mapping=action_set.to_python_code)

    automatic_grading = None
    if args.grading_factory:
        try:
            from importlib import import_module
            from .automatic_grading import validate_options
            module, name = args.grading_factory.split(':',1)
            factory=getattr(import_module(module),name)
            automatic_grading=factory(episode_task,args)
            validate_options(automatic_grading,False,None)
        except (ValueError,TypeError,ImportError,AttributeError) as exc:parser.error(f'Invalid grading factory: {exc}')
    backend = (SmokeBackend() if args.mode == "smoke" else ManualBackend(
                   "development-session" if args.mode == "development" else "human"
               ) if args.mode in ("manual", "development")
               else ChatCompletionsBackend(args.base_url, args.model, os.getenv(args.api_key_env),
                                           args.timeout, args.max_tokens,
                                           supports_images=bool(harness_profile and harness_profile.vision_config),
                                           request_options=request_options, session_routing=session_routing))
    metadata = {"task": args.task, "goal": args.goal if args.task == "openended" else None,
                "start_url": args.url or ("built-in smoke fixture" if args.task == "openended" else None),
                "model": args.model if args.mode == "run" else args.mode,
                "backend": args.base_url if args.mode == "run" else args.mode,
                "driver": "llm" if args.mode == "run" else args.mode,
                "headless": args.headless, "verifier": "miniwob" if args.task.startswith("miniwob.") else None,
                "generation": {"temperature": 0, "max_tokens": args.max_tokens,
                               **(request_options if args.mode == 'run' else {})}}
    if args.collection is not None:metadata['collection']=args.collection
    metadata["environment"] = {"slow_mo_ms": 100 if args.pilot_task else 250, "record_video": args.video,
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
    if args.open_internet:
        metadata.update(source='open-internet-v1', training_eligible=False, verifier='none',
                        original_query=__import__('intent_browser.open_internet', fromlist=['SHOE_QUERY']).SHOE_QUERY if args.shoe_search else args.goal,
                        supervision='step-through' if args.step_through else 'continuous')
    handover_ui = None
    handover_options = {'observation_pipeline':args.observation_mode}
    try:
        if args.human_handover:
            from .human_handover import HumanHandoverController
            from .human_handover_ui import HumanHandoverUI
            controller=HumanHandoverController()
            handover_ui=HumanHandoverUI(controller)
            print(f'Handover controls will appear in the conversation window. Diagnostic panel: {handover_ui.origin}',flush=True)
            metadata['supervision']='human-tabs-v1'
            handover_options.update(human_handover=controller,human_handover_ui=handover_ui)
        _, summary = run_episode(env_factory, backend, metadata, args.output, args.max_steps,
                                 args.seed, args.video, args.hold_seconds, search_backend, episode_task,
                                 action_timeout_ms=args.action_timeout_ms,
                                 trace_screenshots=args.trace_screenshots,
                                 record_fact_provenance=args.record_fact_provenance,
                                 automatic_grading=automatic_grading,allow_ungraded=args.allow_ungraded,
                                 ungraded_reason=args.ungraded_reason,
                                 max_input_tokens=args.max_input_tokens if args.mode=='run' and harness_profile and harness_profile.ax_config else None,
                                 retry_policy=(DecisionRetryPolicy()
                                               if args.retry_policy == 'bounded-v1' else None),
                                 **({'harness_profile': harness_profile} if harness_profile else {}),
                                 **handover_options,
                                 **({'helper_env_factory': __import__('intent_browser.helper_browser',fromlist=['openended_helper_factory']).openended_helper_factory}
                                    if current_profile and episode_task is None and args.task=='openended' else
                                    {'helper_env_factory': __import__('intent_browser.open_internet',fromlist=['helper_factory']).helper_factory}
                                    if args.open_internet else {}),
                                 **({'before_observation': episode_task.supervised_wait,
                                     'terminal_response_instruction': 'Answer the user with findings, sources and uncertainties using send_msg_to_user.'}
                                    if args.open_internet and args.step_through else
                                    {'terminal_response_instruction': 'Answer the user with findings, sources and uncertainties using send_msg_to_user.'}
                                    if args.open_internet else {}))
    finally:
        if handover_ui is not None:handover_ui.close()
        backend.close()
        if search_backend:
            search_backend.close()
        if episode_task and not args.open_internet:
            if args.pilot_task:
                episode_task.close()
            else:
                episode_task.client.close()
    if summary["error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
