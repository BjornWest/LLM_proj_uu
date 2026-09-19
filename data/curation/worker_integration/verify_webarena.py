"""One explicitly requested scripted case on the dedicated worker lease service.

Never uses the manual pool/shared benchmark services. No model transport.
Supports representative existing contracts; it is not a solver for all 103 tasks.
"""
import argparse
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import uuid
from .bindings import ROOT, digest, load_registry
from .context import RuntimeContext
from .tasks import make_task
from data.curation.expansion.webarena.browser_batch import Driver
from data.curation.expansion.webarena.extra_driver import ExtraDriver

SUPPORTED = ('webarena:117', 'webarena:28', 'webarena:399', 'webarena:400',
             'webarena:407', 'webarena:516', 'webarena:630', 'webarena:689')


class ScriptedDriver(Driver):
    def __init__(self, task, negative, wait_for_visible_idle=False):
        super().__init__(task.row['source_task_id'])
        self.task, self.negative = task, negative
        self.wait_for_visible_idle = wait_for_visible_idle
        self.targets = []

    def act(self, loc, op='click', value=None):
        action = super().act(loc, op, value)
        self.targets.append({'action': action, 'bid': loc.get_attribute('bid'),
                             'current_AX': self.text, 'url': self.page.url})
        return action

    def complete(self, messages):
        copied = copy.deepcopy(messages)
        copied[-1]['content'] = copied[-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n', 1)[-1]
        return super().complete(copied)

    def finish(self, data=None):
        if self.task.family == 'native_read_only':
            if self.negative:
                data = []
            return super().finish(data)
        self.response = {'task_type': 'mutate', 'status': 'SUCCESS', 'retrieved_data': None}
        return 'send_msg_to_user(' + repr(json.dumps(self.response)) + ')'

    def forum(self, name):
        yield from ExtraDriver.forum(self, name)

    def steps(self):
        page, contract = self.page, self.task.contract
        family = self.task.family
        if family == 'native_read_only':
            if self.task_id == 28:
                from data.curation.expansion.webarena.batch03_driver import Batch03Driver
                yield from Batch03Driver.steps(self)
            else:
                yield from Driver.steps(self)
            return
        if family in ('biography', 'biography_batch02'):
            yield self.act(page.get_by_role('button', name='MarvelsGrantMan136', exact=True))
            yield self.act(page.get_by_role('link', name='Profile', exact=True))
            yield self.act(page.get_by_role('link', name='Edit biography', exact=True))
            value = 'Wrong scripted biography' if self.negative else contract['grader_input']['expected_biography']
            yield self.act(page.locator('textarea'), 'fill', value)
            yield self.act(page.get_by_role('button', name='Save', exact=True))
            yield self.act(page.get_by_role('link', name='/u/MarvelsGrantMan136', exact=True))
        elif family == 'coupon':
            yield self.act(page.get_by_role('link', name='Contact Us', exact=True))
            value = 'Wrong scripted draft' if self.negative else contract['grader_input']['reason']
            yield self.act(page.locator('#comment'), 'fill', value)
        elif family == 'votes':
            yield from ExtraDriver.forum(self, contract['scripted_navigation']['forum_label'])
            yield self.act(page.get_by_role('button', name='Sort by: Hot', exact=True))
            yield self.act(page.get_by_role('link', name='New', exact=True))
            yield self.act(page.locator('.submission').first.get_by_role('button',
                name='Downvote' if self.negative else 'Upvote', exact=True))
        elif family == 'wishlist':
            yield self.act(page.locator('.product-social-links').get_by_role('link', name='Add to Wish List', exact=True))
            if self.negative:
                if self.wait_for_visible_idle:
                    # Explicit policy-visible waits, retained as ordinary native actions.
                    # No hidden warm-up, no click replay and no grader-state inspection.
                    for _ in range(10):
                        if 'busy=1' not in self.text:
                            break
                        yield 'noop(1000)'
                    if 'busy=1' in self.text:
                        raise ValueError('Page stayed visibly busy through bounded native waits')
                yield self.act(page.locator('.products-grid.wishlist li.product-item').first.get_by_role('link', name='Remove item', exact=True))
        elif family == 'posts':
            values = contract['scripted_input_from_user_goal']
            yield self.act(page.get_by_role('link', name='Submit', exact=True).first)
            yield self.act(page.get_by_label('Title', exact=False), 'fill', 'Wrong scripted title' if self.negative else values['title'])
            if values['body'] is not None:
                yield self.act(page.get_by_label('Body', exact=True), 'fill', values['body'])
            options = page.locator('#submission_forum option').evaluate_all('(es)=>es.map(e=>e.textContent.trim())')
            label = values['observed_forum_label']
            if label not in options:
                raise ValueError('Requested original forum unavailable')
            yield self.act(page.get_by_role('combobox').first)
            yield self.act(page.locator('input.select2-search__field'), 'fill', label)
            yield self.act(page.get_by_role('option', name=label, exact=True))
            yield self.act(page.get_by_role('button', name='Create submission', exact=True), 'press', 'Enter')
        else:
            raise ValueError(family)
        yield self.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', choices=SUPPORTED, required=True)
    parser.add_argument('--negative', action='store_true')
    parser.add_argument('--action-timeout-ms', type=int, default=None,
                        help='Explicit new runtime amendment; omitted preserves the shared default')
    parser.add_argument('--wait-for-visible-idle', action='store_true',
                        help='Distinct wishlist negative control: logged native waits while current AX is busy')
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--service-url', required=True)
    parser.add_argument('--token-env', default='WORKER_SITE_SERVICE_TOKEN')
    parser.add_argument('--evaluator-python', type=Path, default=ROOT / '.local/webarena-verified/venv/bin/python')
    args = parser.parse_args()
    if args.wait_for_visible_idle and (args.task != 'webarena:516' or not args.negative):
        parser.error('--wait-for-visible-idle requires --task webarena:516 --negative')
    from intent_browser.expanded_tasks import runner_options
    row = next(r for r in load_registry(args.registry)['tasks'] if r['id'] == args.task)
    options = runner_options(row, action_timeout_ms=args.action_timeout_ms)
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH', '')
    from intent_browser.worker_sites import WorkerSites
    from intent_browser.runner import run_episode
    from intent_browser.actions import make_action_set
    from intent_browser.task_finalization import finalize_task_run
    from scripts.harness_suite_tasks import scripted_backend
    service = WorkerSites(args.service_url, os.environ[args.token_env])
    lease = None
    backend = None
    task = None
    passed = False
    try:
        lease = service.acquire(args.task, row['revision'], str(uuid.uuid4()))
        def native_grade(task_id, response, har_path, origins):
            request = args.output / 'native-input.json'
            result = args.output / 'native-result.json'
            with request.open('x') as stream:
                json.dump({'task_id': task_id, 'response': response, 'har_path': str(har_path.resolve()), 'origins': origins}, stream)
            subprocess.run([str(args.evaluator_python), '-m', 'data.curation.worker_integration.native_grader',
                            '--input', str(request), '--output', str(result)], check=True, timeout=60, cwd=ROOT)
            return json.loads(result.read_text())
        context = RuntimeContext(args.registry, origins={row['site']: lease.origin},
            browser_proxy=lease.browser_proxy, attest=lease.attest, state_read=lease.state_read, native_grade=native_grade)
        task = make_task(args.task, runtime_context=context, revision=row['revision'])
        driver = ScriptedDriver(task, args.negative, args.wait_for_visible_idle)
        backend = scripted_backend(driver)
        def factory(video):
            driver.env = task.make_env(video, make_action_set().to_python_code)
            return driver.env
        trace, summary = run_episode(factory, backend, {'task': 'expanded-task-shared-bridge',
            'task_id': args.task, 'binding_revision': row['revision'], 'model': None, 'model_calls': 0,
            'scripted_negative': args.negative, 'scripted_wait_for_visible_idle': args.wait_for_visible_idle, 'training_eligible': False}, output=args.output / 'traces',
            episode_task=task, before_observation=lambda: None, **options)
        authoritative = finalize_task_run(task, trace, summary)
        (trace / 'scripted-targets.json').write_text(json.dumps(driver.targets, indent=2) + '\n')
        sources = json.loads((trace / 'expanded-runtime-sources.json').read_text())['source_sha256']
        unchanged = all(digest(ROOT / name) == expected for name, expected in sources.items())
        proxy = lease.browser_proxy
        secrets = [os.environ[args.token_env].encode(), proxy['password'].encode(),
                   base64.b64encode((proxy['username'] + ':' + proxy['password']).encode())]
        secret_free = all(not any(secret in p.read_bytes() for secret in secrets)
                          for p in trace.rglob('*') if p.is_file())
        passed = (unchanged and secret_free and summary['error'] is None and summary['action_error_count'] == 0
                  and authoritative['evaluation']['technical_error'] is None
                  and authoritative['evaluation']['task_completed'] is (not args.negative))
        report = {'task_id': args.task, 'negative': args.negative, 'passed': passed, 'trace': str(trace),
                  'summary': summary, 'authoritative': authoritative, 'model_calls': 0, 'training_eligible': False,
                  'scripted_wait_for_visible_idle': args.wait_for_visible_idle,
                  'requested_action_timeout_ms': args.action_timeout_ms,
                  'registry_sha256': digest(args.registry), 'source_unchanged': unchanged,
                  'proxy_and_control_credentials_absent': secret_free,
                  'artifact_sha256': {str(p.relative_to(trace)): digest(p) for p in trace.rglob('*') if p.is_file()}}
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'task': args.task, 'negative': args.negative, 'passed': passed, 'error': summary['error']}))
    finally:
        if task:
            task.close()
        if backend:
            backend.client.close()
        if lease:
            lease.close()
        service.close()
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
