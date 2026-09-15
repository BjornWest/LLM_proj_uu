"""Fresh local browser bug/control pairs. No model backend, paid calls or repairs.

Run from the repo root with .venv/bin/python data/curation/reproduce_browser_issues.py.
A passing suite confirms CURRENT known behavior, including expected failures;
it does not certify a repaired harness. All episodes are privileged, synthetic,
training-ineligible, and preserve the original environment implementations.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import browsergym.core  # noqa: E402,F401
import gymnasium as gym  # noqa: E402
from intent_browser.actions import make_action_set  # noqa: E402
from intent_browser.backend import Completion  # noqa: E402
from intent_browser.chaos import ChaosClient, ChaosTask  # noqa: E402
from intent_browser.runner import run_episode  # noqa: E402
from intent_browser.trace import write_json  # noqa: E402
from intent_browser.tricky_authorized import AuthorizedWarrantyTask  # noqa: E402
from scripts.verify_authorized_warranty import replay  # noqa: E402
from scripts.verify_chaos import FixtureDriver as ChaosDriver  # noqa: E402
from scripts.verify_tricky import FixtureDriver as ShoppingDriver  # noqa: E402

CASES = ('stale-close', 'refresh-after-wait', 'blur-and-save', 'separate-blur-save')
CLOSE = re.compile(r"^\s*\[([^\]]+)\] link 'Close'\s*$", re.MULTILINE)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def now():
    return datetime.now(timezone.utc).isoformat()


class NotificationDriver(ShoppingDriver):
    def plan(self):
        return [('search', 'Dell Inspiron'), ('add', 24), ('delay',)] + (
            [('cart',), ('checkout',)] if self.case == 'refresh-after-wait' else [])

    def complete(self, messages):
        if self.actions and self.actions[0][0] == 'delay':
            self.actions.pop(0)
            # Select from exactly the delivered observation, never a post-wait DOM query.
            ids = CLOSE.findall(messages[-1]['content'])
            if not ids:
                raise AssertionError('Precondition failed: delivered AX has no notification Close')
            self.close_bid = ids[0]
            page = self.environment['env'].unwrapped.page
            present_before = page.locator('[bid=' + json.dumps(self.close_bid) + ']').count()
            start_wall, start = now(), time.monotonic()
            self.task.trace.event('reproduction_wait_started', seconds=10,
                                  selected_bid=self.close_bid, scope='after supplied observation')
            # Pump browser events while the page's original two-second timer expires.
            page.wait_for_timeout(10000)
            end_wall, elapsed = now(), time.monotonic() - start
            present_after = page.locator('[bid=' + json.dumps(self.close_bid) + ']').count()
            self.task.trace.event('reproduction_wait_completed', elapsed_seconds=elapsed,
                                  selected_bid=self.close_bid, present_after=present_after)
            self.wait_evidence = {
                'delivered_close_ids': ids, 'selected_bid': self.close_bid,
                'present_before': present_before, 'present_after': present_after,
                'started_at': start_wall, 'finished_at': end_wall, 'elapsed_seconds': elapsed,
                'wait_method': 'page.wait_for_timeout', 'scope': 'scripted delay after supplied observation',
            }
            action = f'click({self.close_bid!r})' if self.case == 'stale-close' else 'noop()'
            return Completion(action, {'source': 'privileged-browser-reproduction', **self.wait_evidence})
        if self.case == 'refresh-after-wait' and self.actions and self.actions[0][0] == 'cart':
            # noop causes the unchanged runner to capture a NEW observation.
            self.refreshed_close_ids = CLOSE.findall(messages[-1]['content'])
            if self.refreshed_close_ids:
                raise AssertionError('Control did not receive a refreshed, notification-free AX')
        completion = super().complete(messages)
        completion.raw['source'] = 'privileged-browser-reproduction'
        return completion


class ObservedChaosTask(ChaosTask):
    def after_step(self, env, trace, index):
        result = super().after_step(env, trace, index)
        # Read-only snapshots; no stage interaction/mount API calls in the driver.
        write_json(trace.directory / f'reproduction-server-events-{index:03d}.json',
                   self.client.get('/api/events/' + self.session['session']))
        return result


class BlurDriver(ChaosDriver):
    def plan(self):
        stage = self.task.descriptor['stage']
        edits = [('fill', key, value) for key, value in stage['check']['expectedValues'].items()]
        if self.scenario == 'separate-blur-save':
            # Existing privileged validation workaround: flush BOTH editable and readonly blur.
            edits = [step for kind, key, value in edits
                     for step in [(kind, key, value), ('press', key, 'Tab')]]
            edits += [('press', stage['data']['fields'][-1]['id'], 'Tab')]
        return edits + [('click', stage['check']['mustClick'][0], None)]


def check_case(case, directory, summary, driver, task):
    steps = rows(directory / 'steps.jsonl')
    lifecycle = rows(directory / 'events.jsonl')
    names = [r['event'] for r in lifecycle]
    errors = [s['action_error'] for s in steps if s.get('action_error')]
    checks = {
        'no_fatal_error': summary['error'] is None,
        'no_model_http_requests': bool(steps) and all(s.get('model_request') is None for s in steps),
        'evaluation_before_close': names.index('evaluation_completed') < names.index('environment_close_started'),
        'explicit_terminal_action': steps[-1]['action'].startswith('send_msg_to_user('),
    }
    evidence = {'actions': [s['action'] for s in steps], 'action_errors': errors}
    if case in CASES[:2]:
        evidence['wait'] = getattr(driver, 'wait_evidence', {})
        wait = evidence['wait']
        checks.update({
            'target_delivered_and_present_before_wait': wait.get('present_before') == 1,
            'target_expired_after_ten_seconds': wait.get('present_after') == 0 and wait.get('elapsed_seconds', 0) >= 10,
        })
        evidence['replay'] = replay(directory, task.server.catalog)
        final = json.loads((directory / 'tricky-final-state.json').read_text())
        if case == 'stale-close':
            checks.update({
                'exactly_one_missing_target_error': len(errors) == 1 and driver.close_bid in errors[0],
                'single_add_no_checkout': len(final['orders']) == 0 and
                    {str(p['id']): p['quantity'] for p in final['browser']['cart']} == {'24': 1, '24-warranty': 1},
                'incomplete_without_unauthorized_effect': summary['evaluation']['task_completed'] is False
                    and summary['evaluation']['authorization_satisfied'] is True,
            })
        else:
            checks.update({
                'fresh_observation_excludes_expired_close': driver.refreshed_close_ids == [],
                'no_browser_action_errors': not errors,
                'single_authorized_checkout': len(final['orders']) == 1 and summary['evaluation']['safe_success'] is True,
            })
    else:
        raw = json.loads((directory / 'external_evaluation.json').read_text())
        events = raw['events']['events']
        interactions = [e for e in events if e['event'] in ('input', 'click', 'task:success')]
        evidence['server_interactions'] = interactions
        commit_id = task.descriptor['stage']['check']['mustClick'][0]
        commits = [e for e in events if e['event'] == 'click' and e['metadata'].get('target') == commit_id]
        name_id, expected = next(iter(task.descriptor['stage']['check']['expectedValues'].items()))
        inputs = [e for e in events if e['event'] == 'input' and e['metadata'].get('target') == name_id
                  and e['metadata'].get('value') == expected]
        checks.update({'no_browser_action_errors': not errors,
                       'one_correct_input_reached_server': len(inputs) == 1,
                       'fresh_single_mount': raw['selected_results'][0]['mountCount'] == 1})
        if case == 'blur-and-save':
            checks.update({'same_gesture_commit_missing': len(commits) == 0,
                           'task_remains_incomplete': summary['evaluation']['task_completed'] is False})
        else:
            checks.update({'exactly_one_commit_after_input': len(commits) == 1 and len(inputs) == 1
                           and events.index(inputs[0]) < events.index(commits[0]),
                           'authorized_completion': summary['evaluation']['safe_success'] is True})
    return checks, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chaos-base-url', default='http://localhost:45379')
    parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--case', choices=CASES, action='append')
    args = parser.parse_args()
    if not 1 <= args.repeat <= 5:
        parser.error('--repeat must be 1..5')
    os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH', '')
    suite = ROOT / 'data/curation/browser-reproductions' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    suite.mkdir(parents=True)
    pinned = [Path(__file__), *(ROOT / 'intent_browser').glob('*.py'),
              ROOT / 'scripts/verify_tricky.py', ROOT / 'scripts/verify_chaos.py',
              ROOT / 'scripts/verify_authorized_warranty.py', ROOT / 'config/chaos_verifier.json',
              ROOT / 'config/authorized_warranty_contract.json']
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sorted(pinned)}
    report = {'schema_version': 1, 'protocol': 'scripted-browser-reproductions-v1',
              'expectation': 'Known bug reproduced and scripted control succeeds; NOT a repair certificate.',
              'training_eligible': False, 'model_http_calls': 0, 'source_sha256': hashes,
              'started_at': now(), 'cases': [], 'complete': False}
    write_json(suite / 'report.json', report)
    for repeat in range(args.repeat):
        for case in args.case or CASES:
            print(f'Start {case} repeat {repeat + 1}', flush=True)
            task = (AuthorizedWarrantyTask(preflight=True) if case in CASES[:2] else
                    ObservedChaosTask(ChaosClient(args.chaos_base_url), 'transfer-by-not-clicking-save', preflight=True))
            environment = {}
            def factory(video):
                if case in CASES[:2]:
                    env = task.make_env(video, action_mapping=make_action_set().to_python_code, headless=True)
                else:
                    env = gym.make('browsergym/openended', task_kwargs={'start_url': task.start_url, 'goal': task.policy_goal},
                                   action_mapping=make_action_set().to_python_code, headless=True, slow_mo=250,
                                   wait_for_user_message=False, record_video_dir=video)
                environment['env'] = env
                return env
            driver = (NotificationDriver(task, case, environment) if case in CASES[:2]
                      else BlurDriver(task, case, environment))
            result = {'case': case, 'repeat': repeat + 1, 'passed': False}
            report['cases'].append(result)
            try:
                if any(digest(ROOT / p) != h for p, h in hashes.items()):
                    raise RuntimeError('Source changed during suite; stop and stage a new suite')
                directory, summary = run_episode(factory, driver, {
                    'task': 'synthetic.browser-reproduction', 'scenario': case,
                    'driver': 'privileged-scripted-no-model', 'model': None, 'training_eligible': False,
                    'curation_readiness': False, 'suite': str(suite.relative_to(ROOT)), 'repeat': repeat + 1,
                }, output=ROOT / 'runs', max_steps=8, record_video=True, episode_task=task)
                result.update(episode=str(directory.relative_to(ROOT)), evaluation=summary['evaluation'])
                checks, evidence = check_case(case, directory, summary, driver, task)
                result.update(checks=checks, evidence=evidence, passed=all(checks.values()),
                              session=task.session['session'] if case in CASES[2:] else None)
                # Include every saved artifact except video in the review index.
                result['artifact_sha256'] = {str(p.relative_to(directory)): digest(p)
                                             for p in sorted(directory.rglob('*')) if p.is_file() and p.suffix != '.webm'}
            except Exception as exc:
                result['review_error'] = f'{type(exc).__name__}: {exc}'
            finally:
                if case in CASES[:2]:
                    task.close()
                else:
                    task.client.close()
                write_json(suite / 'report.json', report)
            print(json.dumps({k: v for k, v in result.items() if k in ('case', 'repeat', 'episode', 'passed', 'checks', 'review_error')}), flush=True)
            if result.get('review_error'):
                print(f'Incomplete suite retained: {suite}', flush=True)
                return 1
    sessions = [r['session'] for r in report['cases'] if r.get('session')]
    report.update(complete=True, finished_at=now(), unique_chaos_sessions=len(sessions) == len(set(sessions)),
                  sources_unchanged=all(digest(ROOT / p) == h for p, h in hashes.items()))
    report['passed'] = all(c['passed'] for c in report['cases']) and report['unique_chaos_sessions'] and report['sources_unchanged']
    write_json(suite / 'report.json', report)
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {suite / 'report.json'}", flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
