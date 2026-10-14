"""Scripted (model-free) latency episodes on a prepared generated-world recipe.

Runs the real ``run_episode`` loop against a real generated world in Chromium.
The "model" is an offline MockTransport that waits a configured inference time
and answers with the next journey step, resolving BIDs/refs by role and name
from tool results already delivered in the request (no browser access from the
model thread). Episodes are tagged ``scripted``; no provider is contacted.

Automatic grading is deliberately not attached (``allow_ungraded`` with a
recorded reason): this measures harness timing, not task outcomes.

Example (run under scripts/run_bounded_job.py, PYTHONPATH=<overlay>:<frozen root>):

    python scripts/generated_world_latency.py --recipe .../B14/recipe \
        --kind catalog_priority --journey journeys/b14.json --config baseline \
        --inference-seconds 2 --output OUT
"""
import argparse
import json
import os
import re
import threading
import time
from pathlib import Path

CONFIGS = {
    # The 2026-10-14 Vast run's capture configuration.
    'baseline': dict(observation_pipeline='native', trace_screenshots=True, async_recording=False,
                     record_facts=True, shared_chromium=True),
    'baseline_nofacts': dict(observation_pipeline='native', trace_screenshots=True, async_recording=False,
                             record_facts=False, shared_chromium=True),
    # Capability-gated generated-world fast capture (agent custody, budgeted decision).
    'fast_nofacts': dict(observation_pipeline='auto', trace_screenshots=None, async_recording=True,
                         record_facts=False, shared_chromium=True, declare_fast_capture=True),
    'fast': dict(observation_pipeline='auto', trace_screenshots=None, async_recording=True,
                 record_facts=True, shared_chromium=True, declare_fast_capture=True),
}


class JourneyPolicy:
    """Deterministic journey; each step is one model turn with one or more calls."""

    def __init__(self, steps, answer):
        self.steps, self.answer, self.index = steps, answer, 0
        self.log = []
        self.lock = threading.Lock()

    @staticmethod
    def _objects(messages):
        """Dict objects delivered since the last assistant turn, newest first.

        Older results may name elements of a page that has since changed.
        """
        recent = []
        for message in reversed(messages):
            if message.get('role') == 'assistant':
                break
            recent.append(message)
        for message in recent:
            content = message.get('content')
            texts = []
            if isinstance(content, str):
                texts = [content]
            elif isinstance(content, list):
                texts = [part.get('text', '') for part in content if isinstance(part, dict)]
            for text in texts:
                # Delivered blocks are a heading line followed by one JSON line.
                for candidate in (line for line in text.splitlines() if line.startswith('{')):
                    try:
                        value = json.loads(candidate)
                    except ValueError:
                        continue
                    stack = [value]
                    found = []
                    while stack:
                        item = stack.pop()
                        if isinstance(item, dict):
                            found.append(item)
                            stack.extend(item.values())
                        elif isinstance(item, list):
                            stack.extend(item)
                    yield from found

    def _find(self, messages, spec, field):
        role = spec.get('role')
        needles = spec.get('name_contains')
        needles = [needles] if isinstance(needles, str) else (needles or [])
        for item in self._objects(messages):
            if field not in item or item.get(field) is None:
                continue
            if role is not None and item.get('role') != role:
                continue
            name = str(item.get('name', ''))
            if needles and not any(n.casefold() in name.casefold() for n in needles):
                continue
            return item[field]
        return None

    def next_calls(self, messages):
        with self.lock:
            if self.index >= len(self.steps):
                calls = [('send_msg_to_user', {'text': self.answer})]
                self.log.append({'turn': self.index, 'final': True})
                self.index += 1
                return calls
            step = self.steps[self.index]
            calls, misses = [], []
            for call in step:
                args = dict(call.get('args', {}))
                for field, key in (('bid', 'find_bid'), ('node_ref', 'find_ref')):
                    if key in call:
                        value = self._find(messages, call[key], 'bid' if field == 'bid' else 'ref')
                        if value is None:
                            misses.append({'tool': call['tool'], key: call[key]})
                            break
                        args[field] = value
                else:
                    calls.append((call['tool'], args))
                    continue
                if call.get('fallback'):
                    calls.append((call['fallback']['tool'], call['fallback'].get('args', {})))
            if not calls:
                calls = [('ax_search', {'query': 'journey fallback', 'limit': 1})]
            self.log.append({'turn': self.index, 'calls': [c[0] for c in calls], 'misses': misses})
            self.index += 1
            return calls


def make_backend(policy, inference_seconds, record):
    import httpx
    from intent_browser.backend import ChatCompletionsBackend
    backend = ChatCompletionsBackend('http://offline.invalid/v1', 'scripted', supports_images=True)
    backend.client.close()
    counter = {'n': 0}

    def handle(request):
        body = json.loads(request.content)
        started = time.monotonic()
        calls = policy.next_calls(body['messages'])
        # Simulated inference: real decode/prefill would happen here.
        remaining = inference_seconds - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)
        counter['n'] += 1
        record.append({'request': counter['n'], 'thread': threading.current_thread().name,
                       'started': started, 'finished': time.monotonic(), 'calls': [c[0] for c in calls]})
        tool_calls = [{'id': f'call-{counter["n"]}-{i}', 'type': 'function',
                       'function': {'name': name, 'arguments': json.dumps(args)}}
                      for i, (name, args) in enumerate(calls)]
        return httpx.Response(200, json={'id': f'scripted-{counter["n"]}', 'model': 'scripted',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls',
                         'message': {'role': 'assistant', 'content': None, 'tool_calls': tool_calls}}],
            'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}})

    backend.client = httpx.Client(transport=httpx.MockTransport(handle))
    return backend


def policy_profile(original):
    """Same reduction as comparison_suite_helpers.policy_profile(discovery=False)."""
    from intent_browser.standard_profile import standard_profile
    fresh = standard_profile(navigation_origins=original.tools.navigation_origins,
                             helpers=False, data_tools=False)
    if getattr(original.tools, 'site_discovery_tools', False):
        from intent_browser.harness import with_site_discovery
        fresh = with_site_discovery(fresh)
    return fresh


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--recipe', required=True)
    parser.add_argument('--kind', required=True)
    parser.add_argument('--journey', required=True)
    parser.add_argument('--config', required=True, choices=sorted(CONFIGS))
    parser.add_argument('--inference-seconds', type=float, default=2.0)
    parser.add_argument('--output', required=True)
    parser.add_argument('--tokenizer', default=os.environ.get('HARNESS_AX_TOKENIZER'))
    args = parser.parse_args()
    config = dict(CONFIGS[args.config])
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    journey = json.loads(Path(args.journey).read_text())

    from environments.website_world.saved_answer_registry import saved_episode
    from intent_browser.runner import run_episode
    from intent_browser.input_budget import QwenInputCounter
    episode_class = saved_episode(args.kind)
    calls = []
    policy = JourneyPolicy(journey['steps'], journey['answer'])
    backend = make_backend(policy, args.inference_seconds, calls)
    summary = {'config_name': args.config, 'config': config, 'inference_seconds': args.inference_seconds,
               'recipe': args.recipe, 'kind': args.kind, 'journey': args.journey}
    supervisor = None
    started = time.monotonic()
    try:
        with episode_class(Path(args.recipe)) as episode:
            factory = episode.task.make_env
            if config.get('declare_fast_capture'):
                # The frozen recipe adapter predates the declaration; graders of
                # this family read chat answers and world state, not transition
                # observations. Recorded in the driver summary.
                for flag in ('supports_agent_fast_capture', 'supports_dynamic_preview',
                             'supports_targeted_observations'):
                    setattr(episode.task, flag, True)
                summary['adapter_capabilities_declared_by_driver'] = True
            pool_episode = None
            if config['shared_chromium']:
                from intent_browser.chromium_pool import PoolSupervisor
                supervisor = PoolSupervisor(out / 'chromium-pool', max_leases=4, per_server=4)
                supervisor.start()
                pool_episode = supervisor.client.episode('latency/' + out.name)
                factory = pool_episode.wrap(factory)
            runner = run_episode
            if config['record_facts']:
                from training.browser_training.native_suite_recording import recording_runner, package_pins
                runner = recording_runner(run_episode, enabled=True, expected_sources=package_pins(),
                                          report=out / 'recording-status.json',
                                          capture='pipeline' if config['observation_pipeline'] == 'auto' else 'native')
            options = dict(output=str(out / 'runs'), episode_task=episode.task,
                harness_profile=policy_profile(episode.profile), site_discovery=episode.site_discovery,
                max_steps=len(journey['steps']) + 2, max_input_tokens=150000,
                input_counter=QwenInputCounter(args.tokenizer), retry_policy=None,
                trace_screenshots=config['trace_screenshots'], async_recording=config['async_recording'],
                observation_pipeline=config['observation_pipeline'], debug_timings=True,
                env_step_telemetry=True, allow_ungraded=True,
                ungraded_reason='scripted latency benchmark; task outcome is not under test')
            metadata = {'suite': 'generated-world-latency', 'case': Path(args.recipe).parent.name,
                        'model': 'scripted', 'tags': ['scripted', 'latency-benchmark'],
                        'training_eligible': False, 'latency_config': args.config}
            trace, result = runner(factory, backend, metadata, **options)
            summary.update(trace=str(trace), result={k: result.get(k) for k in ('steps', 'stop_reason', 'error')
                                                     if isinstance(result, dict)})
    except BaseException as error:
        summary['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if supervisor is not None:
            supervisor.close()
        summary['wall_seconds'] = time.monotonic() - started
        summary['model_calls'] = calls
        summary['journey_log'] = policy.log
        (out / 'driver-summary.json').write_text(json.dumps(summary, indent=1, default=str))


if __name__ == '__main__':
    main()
