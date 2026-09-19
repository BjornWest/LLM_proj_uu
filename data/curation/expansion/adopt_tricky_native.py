"""New scripted core-tools-v3 adoption; original task/legacy evidence stays frozen.

Uses the real native request/parser path with httpx.MockTransport, never an
inference provider. Each case runs in a bounded child process. No exposure claim.
"""
import argparse
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import signal
import sys

from intent_browser.actions import make_action_set
from intent_browser.harness import native_tools_profile
from intent_browser.runner import run_episode
from scripts.harness_suite_tasks import scripted_backend
from data.curation.expansion.tricky.lookup_tasks import LookupTask
from data.curation.expansion.tricky.verify_lookups import Driver as LookupDriver
from data.curation.expansion.tricky.batch02.tasks import ActionTask
from data.curation.expansion.tricky.batch02.verify_actions import Driver as ActionDriver
from data.curation.expansion.webarena.run_bounded import execute_case

ROOT = Path(__file__).resolve().parents[3]
TASKS = [f'TX{i:02}' for i in range(1, 11)] + [f'TA{i}' for i in range(11, 15)]


class NativeLookup(LookupTask):
    supported_harness_profiles = ('core-tools-v3',)


class NativeAction(ActionTask):
    supported_harness_profiles = ('core-tools-v3',)


def hashes():
    paths = list((ROOT/'intent_browser').glob('*.py')) + [Path(__file__), ROOT/'scripts/harness_suite_tasks.py',
              ROOT/'data/curation/expansion/webarena/run_bounded.py',
              ROOT/'data/curation/expansion/tricky/lookup_tasks.py', ROOT/'data/curation/expansion/tricky/verify_lookups.py',
              ROOT/'data/curation/expansion/tricky/contracts.json', ROOT/'data/curation/expansion/tricky/batch02/tasks.py',
              ROOT/'data/curation/expansion/tricky/batch02/verify_actions.py', ROOT/'data/curation/expansion/tricky/batch02/contracts.json']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def case(task_id, negative, output):
    before = hashes()
    output.mkdir(parents=True, exist_ok=False)
    (output/'source-before.json').write_text(json.dumps(before, indent=2)+'\n')
    lookup = task_id.startswith('TX')
    task = NativeLookup(task_id) if lookup else NativeAction(task_id)
    holder = {}
    which = 'wrong_answer' if lookup and negative else 'wrong_product' if negative else 'positive'
    driver = (LookupDriver if lookup else ActionDriver)(task, which, holder)
    backend = scripted_backend(driver)
    def factory(video):
        holder['env'] = task.make_env(video, make_action_set().to_python_code)
        return holder['env']
    try:
        trace, summary = run_episode(factory, backend,
            {'task': 'tricky-expansion-native-adoption', 'task_id': task_id, 'case': which, 'model': None,
             'model_calls': 0, 'transport': 'httpx.MockTransport', 'training_eligible': False},
            output=output/'traces', max_steps=16, episode_task=task,
            harness_profile=native_tools_profile(parallel_tool_calls=None, compact_feedback=True, reasoning_replay='preserve'),
            before_observation=lambda: None,
            terminal_response_instruction=task.contract.get('policy_terminal_instruction'), observation_text_limit=48000)
        unchanged = before == hashes()
        ev = summary['evaluation']
        passed = unchanged and summary['error'] is None and summary['action_error_count'] == 0 and ev['task_completed'] is (not negative)
        report = {'task_id': task_id, 'case': which, 'passed': passed, 'trace': str(trace.resolve().relative_to(ROOT)),
                  'summary': summary, 'source_unchanged': unchanged, 'source_sha256': before, 'profile': 'core-tools-v3',
                  'model_calls': 0, 'training_eligible': False,
                  'files_sha256': {str(p.relative_to(trace)): hashlib.sha256(p.read_bytes()).hexdigest() for p in trace.rglob('*') if p.is_file()}}
        (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps({'id': task_id, 'case': which, 'passed': passed, 'error': summary['error'], 'action_errors': summary['action_error_count']}), flush=True)
        return passed
    finally:
        task.close()
        backend.client.close()


def main():
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--task', choices=TASKS)
    p.add_argument('--negative', action='store_true')
    p.add_argument('--child', action='store_true')
    args = p.parse_args()
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH', '')
    if args.child:
        if not args.task: p.error('Child requires task')
        if not case(args.task, args.negative, args.output): raise SystemExit(1)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    reports = []
    for tid in [args.task] if args.task else TASKS:
        for negative in (False, True):
            name = tid + ('-negative' if negative else '-positive')
            target = args.output/name
            command = [sys.executable, '-m', 'data.curation.expansion.adopt_tricky_native', '--child', '--task', tid, '--output', str(target)]
            if negative: command += ['--negative']
            execution = execute_case(command, args.output/(name+'.log'), 120)
            path = target/'report.json'
            report = json.loads(path.read_text()) if path.exists() else {'passed': False, 'incomplete': True}
            reports.append({'task_id': tid, 'negative': negative, 'execution': execution,
                            'report': str(path), 'passed': report['passed'] and execution['returncode'] == 0})
            (args.output/'report.json').write_text(json.dumps({'schema_version': 1, 'profile': 'core-tools-v3',
                'model_calls': 0, 'cases': reports, 'passed': all(r['passed'] for r in reports)}, indent=2)+'\n')
            print(json.dumps(reports[-1]), flush=True)
            if not reports[-1]['passed']:
                raise SystemExit('Paused on first failure; inspect retained evidence')


if __name__ == '__main__': main()
