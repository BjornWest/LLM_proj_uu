"""Local scripted verifier preflight. No model API or search requests.

The driver intentionally uses privileged fixture targets to test the verifier;
these episodes are NOT policy demonstrations or training trajectories.
"""

import argparse
import json
import os
from pathlib import Path

import browsergym.core  # noqa: F401
import gymnasium as gym

from intent_browser.actions import make_action_set
from intent_browser.backend import Completion
from intent_browser.chaos import ChaosClient, ChaosTask
from intent_browser.chaos_verifier import SUPPORTED, fingerprint_server
from intent_browser.runner import run_episode
from intent_browser.trace import write_json


class FixtureDriver:
    def __init__(self, task, scenario, environment):
        self.task, self.scenario, self.environment = task, scenario, environment
        self.actions = None
        self.index = 0

    def plan(self):
        descriptor = self.task.descriptor
        stage = descriptor.get('stage')
        actions = []
        if stage:
            spec = stage['check']
            # This UI emits text on blur. Blur can make its request gate busy
            # and swallow a simultaneous button click; Tab flushes it first.
            edits = [action for target, value in spec.get('expectedValues', {}).items()
                     for action in [('fill', target, value), ('press', target, 'Tab')]]
            edits += [('check' if value else 'uncheck', target, None) for target, value in spec.get('expectedChecked', {}).items()]
            # Tab from the name field focuses the read-only owner field in
            # the transfer fixture. Its blur emits too, so flush that event.
            if self.task.task_id == 'transfer-by-not-clicking-save' and self.scenario == 'positive':
                edits += [('press', stage['data']['fields'][-1]['id'], 'Tab')]
            commit = ('click', spec['mustClick'][0], None)
            if self.scenario == 'positive':
                actions = edits + [commit]
            elif self.scenario == 'negative' and self.task.task_id == 'force-push':
                actions = [commit]
            elif self.scenario == 'negative' and spec.get('expectedValues'):
                actions = [commit] + edits
            else:
                target = (spec.get('mustNotClick') or spec['hardDangerClick'])[0]
                actions = [('click', target, None)]
        else:
            spec = descriptor['task']['actionSpec']
            if self.scenario == 'positive':
                actions = [('label', spec['correct']['label'], None)]
            elif self.scenario == 'email-then-decline':
                actions = [('email', 'synthetic@example.test', None), ('label', spec['correct']['label'], None)]
            elif self.scenario == 'skip':
                actions = [('label', 'Skip challenge', None)]
            else:
                actions = [('label', spec['others'][0]['label'], None)]
        return actions

    def complete(self, messages):
        if self.actions is None:
            self.actions = self.plan()
        if self.index >= len(self.actions):
            return Completion("send_msg_to_user('Scripted verifier preflight complete')", {'source': 'privileged-verifier-test'})
        kind, target, value = self.actions[self.index]
        self.index += 1
        page = self.environment['env'].unwrapped.page
        if kind == 'label':
            element = page.get_by_role('button', name=target, exact=True)
            kind = 'click'
        elif kind == 'email':
            element = page.locator('input[type=email]')
            kind, value = 'fill', target
        else:
            element = page.locator('[data-bac=' + json.dumps(target) + ']')
        bid = element.get_attribute('bid', timeout=5000)
        if not bid:
            raise ValueError('Fixture target has no BrowserGym ID')
        action = f'{kind}({bid!r}' + (f', {value!r}' if value is not None else '') + ')'
        return Completion(action, {'source': 'privileged-verifier-test'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--task', choices=SUPPORTED, action='append')
    parser.add_argument('--headful', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    libraries = root / '.local/system-libs/usr/lib/x86_64-linux-gnu'
    if libraries.is_dir():
        os.environ['LD_LIBRARY_PATH'] = str(libraries) + ':' + os.getenv('LD_LIBRARY_PATH', '')
    tasks = args.task or SUPPORTED
    provenance = fingerprint_server(args.base_url)
    results = []
    for task_id in tasks:
        scenarios = ['positive', 'negative']
        if task_id == 'confirmshaming':
            scenarios += ['email-then-decline', 'skip']
        for scenario in scenarios:
            client = ChaosClient(args.base_url)
            task = ChaosTask(client, task_id, preflight=True)
            environment = {}
            action_set = make_action_set()
            def factory(video):
                env = gym.make('browsergym/openended', task_kwargs={'start_url': task.start_url, 'goal': task.policy_goal},
                               action_mapping=action_set.to_python_code, headless=not args.headful, slow_mo=100,
                               wait_for_user_message=False, record_video_dir=video)
                environment['env'] = env
                return env
            try:
                directory, summary = run_episode(factory, FixtureDriver(task, scenario, environment), {
                    'task': 'openended', 'source_task_id': task_id, 'scenario': scenario,
                    'driver': 'privileged-scripted-verifier-preflight', 'model': None,
                    'training_eligible': False, 'verifier': None,
                }, output=root / 'runs', max_steps=6, record_video=args.headful, episode_task=task)
                raw_path = directory / 'external_evaluation.json'
                raw = json.loads(raw_path.read_text()) if raw_path.exists() else {}
                upstream = (raw.get('selected_results') or [{}])[0]
                expected = scenario in ('positive', 'email-then-decline')
                step_rows = [json.loads(line) for line in (directory / 'steps.jsonl').read_text().splitlines()]
                action_errors = sum(bool(row.get('action_error')) for row in step_rows)
                expected_action_errors = 1 if scenario == 'email-then-decline' else 0
                result = {'task': task_id, 'scenario': scenario, 'episode': str(directory.relative_to(root)),
                          'session': task.session['session'] if task.session else None,
                          'expected_safe_success': expected, 'evaluation': summary['evaluation'],
                          'upstream_success': upstream.get('success'), 'error': summary['error'],
                          'browser_action_errors': action_errors,
                          'expected_browser_action_errors': expected_action_errors,
                          'case_note': 'Read-only email blocks entry; failed attempt is not an actual unauthorized effect.' if scenario == 'email-then-decline' else None,
                          'passed': summary['evaluation']['safe_success'] is expected and not summary['error'] and action_errors == expected_action_errors}
                results.append(result)
                if not result['passed']:
                    raise RuntimeError('Verifier preflight case failed: ' + json.dumps(result))
            finally:
                client.close()
                if results:
                    write_json(root / results[0]['episode'] / 'chaos-preflight-suite.json',
                               {'provenance': provenance, 'cases': results, 'complete': False})
    assert len({r['session'] for r in results}) == len(results), 'Sessions were reused'
    report = root / results[0]['episode'] / 'chaos-preflight-suite.json'
    write_json(report, {'provenance': provenance, 'cases': results, 'complete': True})
    print(f'Passed {len(results)} cases; unique sessions. Report: {report}')


if __name__ == '__main__':
    main()
