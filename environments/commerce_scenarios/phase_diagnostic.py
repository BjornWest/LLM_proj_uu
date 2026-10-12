"""One freshly bound quantity control using the existing publication lifecycle.

No replay, provider, manufacture, action override, timeout change or retry. The
caller supplies a source-reviewed saved-world binding and an outer180s cap.
"""
import json
from pathlib import Path

from . import matrix, publication


def run(world, instance, output):
    from intent_browser.step_telemetry import resolve_step_telemetry
    if resolve_step_telemetry():
        raise ValueError('Direct phase diagnostics require HARNESS_ENV_STEP_TELEMETRY unset or 0; '
                         'the runner and direct recorders cannot be enabled together')
    output = Path(output).resolve()
    instance = Path(instance).resolve(strict=True)
    packet = publication._json(instance)
    if packet.get('family') != 'pricing_promotions' or packet.get('mechanism') != 'quantity_condition':
        raise ValueError('This finite diagnostic is only quantity_condition-wrong')
    output.mkdir(parents=True, exist_ok=False)
    prepared = publication.prepare_episode(world, instance, 'wrong',
        origin_diagnostics_path=output/'origin-phases.jsonl')
    try:
        return _run_prepared(prepared, world, instance, output)
    finally:
        prepared.close()


def _run_prepared(prepared, world, instance, output):
    # The exact released direct API keeps the older accepted runner unchanged.
    # Expose the original step while observe installs its instance-local clone;
    # call that clone on the existing Playwright owner thread.
    from intent_browser.step_telemetry import EnvStepTelemetry
    from intent_browser.trace import write_json
    native_make_env, native_policy = prepared.episode.task.make_env, prepared.policy
    prepared.config['metadata']['tags'].append('phase-diagnostic')
    holder, decision = {}, {'index': -1, 'tool': None}
    missing = object()

    def restore_step(env, previous):
        if previous is missing:
            del env.step
        else:
            env.step = previous

    def policy(page):
        action = native_policy(page)
        decision.update(index=decision['index'] + 1, tool=action[0])
        return action

    def make_env(video=None):
        env = native_make_env(video)
        previous_step = vars(env).get('step', missing)

        def step(action):
            if 'recorder' not in holder:
                trace = prepared.episode.task.trace
                holder['recorder'] = EnvStepTelemetry(trace.directory)
                trace.metadata['env_step_telemetry'] = holder['recorder'].describe()
                write_json(trace.directory/'metadata.json', trace.metadata)
            restore_step(env, previous_step)
            try:
                with holder['recorder'].observe(env.unwrapped, step=decision['index'], tool=decision['tool']):
                    return env.step(action)
            finally:
                env.step = step

        env.step = step
        holder.update(env=env, previous_step=previous_step)
        return env

    terminal = {'status': 'infrastructure_incomplete', 'effects': 'unknown'}
    # An external hard timeout may bypass finally. Keep a pessimistic record;
    # the bounded launcher remains authoritative for process termination.
    write_json(output/'diagnostic-terminal.json', terminal)
    publication.checked_files(prepared.source_files)
    binding = {'case': 'quantity_condition-wrong', 'instance': str(instance),
               'instance_sha256': prepared.instance_sha256,
               'world': str(Path(world).resolve()), 'max_steps': 40, 'max_input_tokens': 500000,
               'tags': list(prepared.config['metadata']['tags']),
               'source_files': prepared.source_files, 'provider_requests': 0, 'world_draws': 0,
               'retries': 0, 'prior_trace_replayed': False,
               'origin_diagnostics': str(prepared.episode.runtime.origin_diagnostics_path)}
    publication_path = output/'diagnostic-binding.private.json'
    with publication_path.open('x', encoding='utf-8') as stream:
        json.dump(binding, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    prepared.episode.task.make_env, prepared.policy = make_env, policy
    try:
        result = publication.run_saved(prepared, output/'episode', max_steps=40, max_input_tokens=500000)
        terminal.update(status='completed' if matrix._control_completed(result) else 'driver_incomplete',
                        native_status=result['publication']['status'], trace=result['trace'],
                        control_matches_expectation=result['publication']['control_matches_expectation'])
        with (output/'result.private.json').open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
        return terminal
    except BaseException as error:
        terminal['error_type'] = type(error).__name__
        raise
    finally:
        recorder = holder.get('recorder')
        if recorder is not None:
            recorder.close()
            terminal['step_telemetry'] = recorder.describe()
        if 'env' in holder:
            restore_step(holder['env'], holder['previous_step'])
        prepared.episode.task.make_env, prepared.policy = native_make_env, native_policy
        terminal['origin_diagnostics_errors'] = [bridge.diagnostics_error
            for _, bridge in prepared.episode.runtime._browser_bridges]
        write_json(output/'diagnostic-terminal.json', terminal)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--world', required=True)
    parser.add_argument('--instance', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.world, args.instance, args.output)), flush=True)


if __name__ == '__main__':
    main()
