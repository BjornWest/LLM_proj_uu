"""Single fresh scripted bridge case; privileged driver, zero model calls."""
import argparse
import importlib
import json
import os
from pathlib import Path
from .bindings import ROOT, digest, load_registry
from .context import RuntimeContext
from .tasks import make_task


def driver_for(task, negative, holder):
    family = task.row['family']
    if family == 'tricky.lookup':
        from data.curation.expansion.tricky.verify_lookups import Driver
        return Driver(task, 'wrong_answer' if negative else 'positive', holder)
    if family == 'tricky.action':
        from data.curation.expansion.tricky.batch02.verify_actions import Driver
        return Driver(task, 'wrong_product' if negative else 'positive', holder)
    if family == 'tricky.remaining':
        from data.curation.expansion.tricky_original_remaining.driver import Driver
        return Driver(task, negative, holder)
    module = importlib.import_module('data.curation.expansion.' + family)
    return module.Driver(task, negative, holder)


def source_hashes():
    # Standalone bridge never imports service dispatcher/client modules.
    paths = [p for p in (ROOT / 'intent_browser').glob('*.py')
             if p.name not in {'team_worker.py', 'worker_sites.py'}]
    paths += list((ROOT / 'data/curation/worker_integration').glob('*.py'))
    paths += list((ROOT / 'data/curation/expansion/tricky').rglob('*.py'))
    paths += list((ROOT / 'data/curation/expansion/tricky_original_remaining').glob('*.py'))
    paths += [ROOT / 'scripts/harness_suite_tasks.py']
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}


def case(task_id, negative, output, registry):
    from intent_browser.actions import make_action_set
    from intent_browser.harness import native_tools_profile
    from intent_browser.runner import run_episode
    from intent_browser.task_finalization import finalize_task_run
    from scripts.harness_suite_tasks import scripted_backend
    output.mkdir(parents=True, exist_ok=False)
    before = source_hashes()
    row = next(r for r in load_registry(registry)['tasks'] if r['id'] == task_id)
    context = RuntimeContext(registry, fixture_root=ROOT / '.local/tricky-full-v1')
    task = make_task(task_id, runtime_context=context, revision=row['revision'])
    holder = {}
    driver = driver_for(task, negative, holder)
    backend = scripted_backend(driver)
    def factory(video):
        holder['env'] = task.make_env(video, make_action_set().to_python_code)
        return holder['env']
    try:
        trace, summary = run_episode(factory, backend,
            {'task': 'expanded-task-shared-bridge', 'task_id': task_id, 'binding_revision': row['revision'],
             'model': None, 'model_calls': 0, 'scripted_negative': negative, 'training_eligible': False},
            output=output / 'traces', max_steps=row['profile']['max_steps'], episode_task=task,
            harness_profile=native_tools_profile(parallel_tool_calls=None, compact_feedback=True, reasoning_replay='preserve'),
            before_observation=lambda: None, observation_text_limit=row['profile']['observation_text_limit'],
            terminal_response_instruction=row['policy_input']['terminal_response_instruction'])
        authoritative = finalize_task_run(task, trace, summary)
        # Other owners may add unrelated modules. Freeze and recheck the selected
        # source set; adding an unimported worker module is not a changed runtime.
        unchanged = before == {name: digest(ROOT / name) for name in before}
        passed = (summary['error'] is None and summary['action_error_count'] == 0 and unchanged
                  and authoritative['evaluation']['task_completed'] is (not negative))
        report = {'schema': 'expanded-task-bridge-case-v1', 'task_id': task_id, 'negative': negative,
            'passed': passed, 'trace': str(trace), 'summary': summary, 'authoritative': authoritative,
            'source_sha256': before, 'source_unchanged': unchanged, 'model_calls': 0, 'training_eligible': False,
            'registry_sha256': digest(registry),
            'artifact_sha256': {str(p.relative_to(trace)): digest(p) for p in trace.rglob('*') if p.is_file()}}
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'task_id': task_id, 'negative': negative, 'passed': passed,
                          'error': summary['error'], 'action_errors': summary['action_error_count']}), flush=True)
        return passed
    finally:
        task.close()
        backend.client.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task', required=True)
    p.add_argument('--negative', action='store_true')
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--registry', type=Path, default=ROOT / '.local/curation-expansion/worker-registry-v2.json')
    args = p.parse_args()
    os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH', '')
    if not case(args.task, args.negative, args.output, args.registry):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
