"""Offline native-browser regression cases for the derived Chaos FIFO v2 build.

This is a privileged scripted driver, not a model trajectory. Native Playwright
input/click operations and controlled response holds are recorded separately.
The original request is fetched exactly once and fulfilled with that response;
no JavaScript clicks, task mutation API shortcuts, retries or replay occur.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

import browsergym.core  # noqa: F401
import gymnasium as gym
from intent_browser.actions import make_action_set
from intent_browser.backend import Completion
from intent_browser.chaos import ChaosClient, ChaosTask
from intent_browser.chaos_verifier import fingerprint_server, snapshot_page
from intent_browser.runner import run_episode
from intent_browser.trace import write_json

ROOT = Path(__file__).resolve().parents[1]
CASES = ('multiple-edits', 'terminal-duplicate', 'spa-unmount', 'network-failure', 'fresh-after-failure')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class BoundaryTask(ChaosTask):
    def __init__(self, client, case):
        super().__init__(client, 'transfer-by-not-clicking-save', preflight=True)
        self.case, self.held, self.intercepted = case, None, False
        self.trace = None
        self.diagnostics = []
        self.boundary_error = None

    def prepare(self, trace):
        self.trace = trace
        result = super().prepare(trace)
        result['boundary_case'] = self.case
        result['boundary_scope'] = 'Privileged native Playwright operations, controlled original-response hold; no model calls.'
        return result

    def record(self, operation, **details):
        item = {'operation': operation, **details}
        self.diagnostics.append(item)
        with (self.trace.directory/'boundary-operations.jsonl').open('a') as file:
            file.write(json.dumps(item)+'\n')
        self.trace.event('privileged_browser_boundary_operation', artifact='boundary-operations.jsonl', **item)

    def capture_initial(self, env, observation, info):
        result = super().capture_initial(env, observation, info)
        page = env.unwrapped.page
        page.wait_for_function("typeof window.__intentChaosQueueSnapshot === 'function'")
        self.record('initial_queue', queue=page.evaluate('() => window.__intentChaosQueueSnapshot()'))
        def intercept(route):
            payload = route.request.post_data_json
            event = payload.get('event', {})
            kind = 'click' if self.case == 'terminal-duplicate' else 'input'
            if self.case == 'fresh-after-failure' or self.intercepted or event.get('kind') != kind:
                route.continue_()
                return
            self.intercepted = True
            if self.case == 'network-failure':
                self.record('abort_original_request', payload=payload, reason='Controlled offline failure before dispatch')
                route.abort('failed')
                return
            # Returning with the route unresolved keeps only this response
            # pending. Unlike a sleep, this leaves the browser event pump free.
            response = route.fetch(max_redirects=0)
            self.held = (route, response)
            self.record('hold_original_response', payload=payload, response_status=response.status,
                        fetch_count=1, retry_policy='No retry loop; installed Route.fetch has no retry option', scope='Original browser request only')
        page.route('**/api/stage/*/interact', intercept)
        return result

    def capture(self, page, label, *, old=False):
        snapshot = snapshot_page(page)
        self.snapshots.append(snapshot)
        queue = page.evaluate('() => window.__intentBoundaryOldQueueSnapshot()' if old else '() => window.__intentChaosQueueSnapshot()')
        self.record('capture_boundary', label=label, browser=snapshot, queue=queue)
        write_json(self.trace.directory/f'boundary-{label}.json', {'browser': snapshot, 'queue': queue})
        return queue

    def release(self):
        if self.held is None:
            raise ValueError('Expected a held original response')
        route, response = self.held
        self.held = None
        self.record('release_original_response', response_status=response.status, replay=False)
        route.fulfill(response=response)

    def after_step(self, env, trace, index):
        result = super().after_step(env, trace, index)
        page = env.unwrapped.page
        queue = page.evaluate('() => window.__intentChaosQueueSnapshot?.() ?? null')
        write_json(trace.directory/f'queue-state-{index:03d}.json', queue)
        return result

    def evaluate(self, env, trace, outcome):
        # A failed diagnostic must never leave a routed request unresolved at
        # browser close. Retain any released-result uncertainty in the error.
        if self.held is not None:
            self.record('cleanup_pending_response', reason='Boundary driver failed before planned release')
            self.release()
            env.unwrapped.page.wait_for_timeout(100)
        evaluation = super().evaluate(env, trace, outcome)
        evaluation.evidence += [p.name for p in trace.directory.glob('boundary-*.json')]
        if (trace.directory/'boundary-operations.jsonl').exists():
            evaluation.evidence.append('boundary-operations.jsonl')
        evaluation.limitations.append('Native privileged boundary script; no policy performance claim. SPA unmount leaves the normal single-task lifecycle scope and is expected to remain ungraded.')
        return evaluation


class BoundaryDriver:
    def __init__(self, task, environment):
        self.task, self.environment, self.finished = task, environment, False

    def complete(self, messages):
        if self.finished:
            return Completion("send_msg_to_user('Scripted boundary validation complete')", {'source': 'privileged-native-boundary-driver', 'model': None})
        self.finished = True
        task, page = self.task, self.environment['env'].unwrapped.page
        expected = task.descriptor['stage']['check']['expectedValues']
        if len(expected) != 1:
            raise ValueError('Boundary fixture requires exactly one editable field')
        target, value = next(iter(expected.items()))
        save_target = task.descriptor['stage']['check']['mustClick'][0]
        field = page.locator('[data-bac='+json.dumps(target)+']')
        save = page.locator('[data-bac='+json.dumps(save_target)+']')
        task.record('native_script_started', case=task.case, field=target, save=save_target)
        if task.case == 'multiple-edits':
            for edit in (value+'-draft-1', value+'-draft-2', value):
                task.record('playwright.locator.fill', target=target, value=edit)
                field.fill(edit)
                task.record('playwright.locator.press', target=target, key='Tab')
                field.press('Tab')
            task.capture(page, 'before-save')
            task.record('playwright.locator.click', target=save_target)
            save.click()
            queue = task.capture(page, 'queued-before-release')
            assert sum(e['phase'] == 'dispatched' for e in queue['events']) == 1
            task.release()
        elif task.case == 'terminal-duplicate':
            task.record('playwright.locator.fill', target=target, value=value)
            field.fill(value)
            task.capture(page, 'before-save')
            task.record('playwright.locator.dblclick', target=save_target, expected_native_clicks=2)
            save.dblclick(delay=50)
            queue = task.capture(page, 'queued-before-release')
            clicks = [e for e in queue['events'] if e['kind'] == 'click']
            assert sum(e['phase'] == 'queued' for e in clicks) == 2
            assert sum(e['phase'] == 'dispatched' for e in clicks) == 1
            task.release()
        elif task.case == 'spa-unmount':
            task.record('playwright.locator.fill', target=target, value=value)
            field.fill(value)
            task.capture(page, 'before-save')
            task.record('playwright.locator.click', target=save_target)
            save.click()
            page.evaluate('() => { window.__intentBoundaryOldQueueSnapshot = window.__intentChaosQueueSnapshot; }')
            task.record('retain_old_queue_getter', scope='Read-only diagnostic handle; no UI events synthesized')
            queue = task.capture(page, 'queued-before-unmount', old=True)
            assert any(e['phase'] == 'queued' and e['kind'] == 'click' for e in queue['events'])
            assert not any(e['phase'] == 'dispatched' and e['kind'] == 'click' for e in queue['events'])
            task.record('playwright.locator.click', role='link', name='Browser Agent Chaos', purpose='Native SPA unmount')
            page.get_by_role('link', name='Browser Agent Chaos', exact=True).click()
            page.wait_for_function("location.href !== " + json.dumps(task.start_url))
            # If the link reloads the document, the retained getter disappears;
            # that is a test failure, not evidence of a React SPA unmount.
            page.wait_for_function("window.__intentBoundaryOldQueueSnapshot?.().closed === true")
            before = page.locator('body').inner_text()
            task.capture(page, 'unmounted-before-release', old=True)
            task.release()
            page.wait_for_function("window.__intentBoundaryOldQueueSnapshot().events.some(e => e.phase === 'discarded' && e.kind === 'click')")
            after = page.locator('body').inner_text()
            task.capture(page, 'unmounted-after-release', old=True)
            task.record('stale_response_ui_check', text_before=before, text_after=after, unchanged=before == after)
            assert before == after, 'Old response mutated the new SPA page text'
        else:
            task.record('playwright.locator.fill', target=target, value=value)
            field.fill(value)
            task.capture(page, 'before-save')
            task.record('playwright.locator.click', target=save_target)
            save.click()
        if task.case != 'spa-unmount':
            page.wait_for_function("window.__intentChaosQueueSnapshot().closed === true")
            page.wait_for_function("(() => { const e=window.__intentChaosQueueSnapshot().events; return e.filter(x=>x.phase==='queued').length === e.filter(x=>['completed','failed','discarded'].includes(x.phase)).length; })()")
            task.capture(page, 'settled')
        return Completion('noop()', {'source': 'privileged-native-boundary-driver', 'model': None,
                                     'diagnostics': 'boundary-operations.jsonl', 'native_operations_executed_before_noop': True})


def check_case(task, directory, summary):
    case = task.case
    rows = [json.loads(x) for x in (directory/'steps.jsonl').read_text().splitlines()]
    assert all(x.get('model_request') is None for x in rows), 'Unexpected model request'
    assert all(x.get('action') in ('noop()', "send_msg_to_user('Scripted boundary validation complete')") for x in rows), 'Unrecorded policy action'
    assert summary['action_error_count'] == 0
    events = [json.loads(x)['event'] for x in (directory/'events.jsonl').read_text().splitlines()]
    assert events.index('evaluation_completed') < events.index('environment_close_started')
    raw = json.loads((directory/'external_evaluation.json').read_text())
    server = [x for x in raw['events']['events'] if x['event'] in ('input', 'click')]
    assert all(x['metadata']['isTrusted'] is True for x in server)
    filename = 'boundary-unmounted-after-release.json' if case == 'spa-unmount' else 'boundary-settled.json'
    queue = json.loads((directory/filename).read_text())['queue']
    assert queue['version'] == 'stage-fifo-v2', 'Boundary suite requires reviewed v2 helper'
    initial = task.diagnostics[0]['queue']
    context = queue['context']
    assert context == initial['context'], 'Queue context changed within the retained instance'
    assert context['session'] == task.session['session'] and context['challengeId'] == task.task_id
    assert isinstance(context['mountNonce'], str) and context['mountNonce']
    assert initial['unmountedAt'] is None
    held = [x for x in task.diagnostics if x['operation'] == 'hold_original_response']
    for response in held:
        assert response['payload']['session'] == context['session'] and response['payload']['mountNonce'] == context['mountNonce']
        assert response['fetch_count'] == 1
    dispatched = [x for x in queue['events'] if x['phase'] == 'dispatched']
    discarded = [x for x in queue['events'] if x['phase'] == 'discarded']
    if case == 'network-failure':
        assert queue['reason'] == 'request_failed' and not server
        assert len(dispatched) == 1 and any(x['kind'] == 'click' for x in discarded)
        assert summary['evaluation']['safe_success'] is None and summary['evaluation']['technical_error']
    elif case == 'spa-unmount':
        assert queue['closed'] and queue['reason'] == 'unmounted'
        assert type(queue['unmountedAt']) in (int, float)
        assert len(held) == 1 and held[0]['payload']['event']['kind'] == 'input'
        assert len(dispatched) == 1 and dispatched[0]['kind'] == 'input'
        assert not any(x['event'] == 'click' for x in server)
        assert any(x['kind'] == 'click' for x in discarded)
        assert summary['evaluation']['safe_success'] is None and summary['evaluation']['technical_error']
    else:
        assert not summary['error'] and summary['evaluation']['safe_success'] is True
        assert queue['reason'] == 'terminal:success'
        assert len([x for x in server if x['event'] == 'click']) == 1
        assert [(x['kind'], x['target']) for x in dispatched] == [(x['event'], x['metadata']['target']) for x in server]
        if case == 'terminal-duplicate':
            assert len([x for x in discarded if x['kind'] == 'click']) == 1
        if case == 'multiple-edits':
            target, value = next(iter(task.descriptor['stage']['check']['expectedValues'].items()))
            edits = [x['metadata']['value'] for x in server if x['event'] == 'input' and x['metadata']['target'] == target]
            assert edits == [value+'-draft-1', value+'-draft-2', value], 'Native edits were lost, changed or coalesced'
    for name in summary['evaluation']['evidence']:
        assert not Path(name).is_absolute() and (directory/name).is_file()
    return {'queue': queue, 'server_interactions': server, 'evaluation_before_close': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--case', choices=CASES, action='append')
    parser.add_argument('--report', type=Path, default=ROOT/'.local/preflight/chaos-queue-boundaries-v2.json')
    args = parser.parse_args()
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH', '')
    report = {'schema_version': 1, 'scope': __doc__, 'model_calls': 0, 'training_eligible': False,
              'provenance': fingerprint_server(args.base_url), 'source_sha256': {str(Path(__file__).relative_to(ROOT)): digest(__file__)},
              'cases': [], 'complete': False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    sessions, nonces = [], []
    cases = args.case or CASES
    if 'fresh-after-failure' in cases and ('network-failure' not in cases or cases.index('network-failure') > cases.index('fresh-after-failure')):
        parser.error('fresh-after-failure requires a preceding network-failure case')
    for case in cases:
        client = ChaosClient(args.base_url)
        task = BoundaryTask(client, case)
        environment = {}
        def factory(video):
            environment['env'] = gym.make('browsergym/openended', task_kwargs={'start_url': task.start_url, 'goal': task.policy_goal},
                action_mapping=make_action_set().to_python_code, headless=True, slow_mo=100, wait_for_user_message=False)
            return environment['env']
        entry = {'case': case, 'passed': False}
        try:
            directory, summary = run_episode(factory, BoundaryDriver(task, environment),
                {'task': 'chaos.fifo-boundary-development', 'scenario': case, 'driver': 'privileged-native-boundary-script',
                 'model': None, 'training_eligible': False}, max_steps=2, output=ROOT/'runs', episode_task=task,
                before_observation=lambda: {'source': 'scripted-boundary-driver', 'wait_seconds': 0})
            entry.update(episode=str(directory.relative_to(ROOT)), session=task.session['session'], evaluation=summary['evaluation'], error=summary['error'])
            assert task.session['session'] not in sessions
            sessions.append(task.session['session'])
            entry.update(check_case(task, directory, summary))
            nonce = entry['queue']['context']['mountNonce']
            assert nonce not in nonces, 'Mount nonce reused across fresh sessions'
            nonces.append(nonce)
            if case == 'fresh-after-failure':
                failed = next(x for x in reversed(report['cases']) if x['case'] == 'network-failure')
                assert failed['passed'] and failed['session'] != entry['session']
                assert failed['queue']['context']['mountNonce'] != nonce
                entry['prior_failed_session'] = failed['session']
                entry['prior_failed_episode'] = failed['episode']
            entry['artifact_sha256'] = {p.name: digest(p) for p in directory.iterdir() if p.suffix in ('.json', '.jsonl', '.txt')}
            entry['passed'] = True
        except Exception as error:
            entry['check_error'] = f'{type(error).__name__}: {error}'
        finally:
            client.close()
            report['cases'].append(entry)
            write_json(args.report, report)
        print(json.dumps({'case': case, 'passed': entry['passed'], 'episode': entry.get('episode'), 'error': entry.get('check_error')}), flush=True)
    report['complete'] = len(report['cases']) == len(args.case or CASES)
    report['all_passed'] = all(x['passed'] for x in report['cases'])
    write_json(args.report, report)
    print(args.report, flush=True)
    if not report['all_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
