"""Native scripted original post tasks; final DB + authenticated-page checker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from data.curation.expansion.runtime_snapshot import activate, fingerprints
FROZEN = activate()
assert FROZEN, 'Copied runtime required before adapter import'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def closure():
    files = list(HERE.glob('*.py')) + [HERE / 'contracts.json', HERE / 'source-forums.json',
        ROOT / '.local/webarena-verified/dataset.json', ROOT / 'scripts/harness_suite_tasks.py',
        ROOT / 'data/curation/expansion/runtime_snapshot.py',
        ROOT / 'data/curation/expansion/webarena/browser_batch.py',
        ROOT / 'data/curation/expansion/webarena/inventory.py']
    files += list((ROOT / '.local/webarena-verified/venv/lib').glob('python*/site-packages/webarena_verified/**/*.py'))
    return {**fingerprints(FROZEN, ROOT), **{str(p.relative_to(ROOT)): sha(p) for p in files}}


BEFORE = closure()
from bs4 import BeautifulSoup
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.evaluation import Evaluation
from intent_browser.harness import native_tools_profile
from intent_browser.runner import run_episode
from scripts.harness_suite_tasks import scripted_backend
from data.curation.expansion.webarena.browser_batch import Driver, HEADERS
from data.curation.expansion.webarena_posts.common import ORIGIN, USER, inspect, latest_id, posts_after
from data.curation.expansion.webarena_posts.grader import judge
assert closure() == BEFORE
CONTRACT = json.loads((HERE / 'contracts.json').read_text())


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


class BrowserTask(OpenEndedTask):
    def __init__(self, seed, adapter):
        self.adapter = adapter
        super().__init__(seed, ORIGIN, adapter.goal)

    def setup(self, page):
        page.context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(ORIGIN + '/') else route.abort())
        return super().setup(page)


class PostTask:
    supported_harness_profiles = ('core-tools-v3',)

    def __init__(self, task, variant):
        self.task = task
        self.variant = variant
        self.goal = task['policy_input']['goal']
        self.result = None

    def prepare(self, trace):
        self.baseline = latest_id()
        self.container = inspect()
        dump(trace.directory / 'contract.json', self.task)
        return {'source_task_id': self.task['source_task_id'], 'baseline_submission_id': self.baseline,
                'container': self.container, 'verifier': 'derived_final_persisted_post', 'training_eligible': False}

    def capture_initial(self, env, observation, info):
        assert latest_id() == self.baseline
        return {'url': env.unwrapped.page.url, 'baseline_submission_id': self.baseline}

    def evaluate(self, env, trace, outcome):
        evidence = None
        if self.variant != 'missing-evidence':
            posts = posts_after(self.baseline)
            reads = []
            for row in posts:
                url = ORIGIN + '/f/' + row['forum_name'] + '/' + str(row['id'])
                response = env.unwrapped.page.context.request.get(url, timeout=45000)
                html = response.text()
                filename = 'privileged-post-' + str(row['id']) + '.html'
                (trace.directory / filename).write_text(html)
                soup = BeautifulSoup(html, 'html.parser')
                post = soup.select_one('article.submission')
                form = post.select_one('form[data-vote-route-value="submission_vote"]') if post else None
                fields = {}
                if post:
                    for key, selector in [('title', '.submission__title'), ('author', '.submission__submitter'), ('forum', '.submission__forum'), ('body', '.submission__body')]:
                        element = post.select_one(selector)
                        fields[key] = element.get_text('\n', strip=True) if element else None
                reads.append({'id': row['id'], 'requested_url': url, 'response_url': response.url,
                              'status': response.status, 'confirmed_post_id': int(form['data-vote-id-value']) if form else None,
                              'fields': fields, 'html': filename, 'html_sha256': sha(trace.directory / filename)})
            assert inspect() == self.container
            evidence = {'baseline_id': self.baseline, 'posts': posts, 'reads': reads,
                        'capture_timing': 'Independent owned database and authenticated GET after final policy action, before browser close'}
        self.result = judge(evidence, self.task['grader_input'])
        dump(trace.directory / 'post-final-state.json', {'evidence': evidence, 'result': self.result,
             'fault_injection': self.variant if self.variant == 'missing-evidence' else None})
        return Evaluation('webarena-posts-derived', 'final-persisted-post-v1',
            trust='scoped_authenticated_server_and_database', task_completed=self.result['task_completed'],
            authorization_satisfied=self.result['authorization_satisfied'],
            unauthorized_effects=self.result.get('unauthorized_effects', []),
            evidence=['post-final-state.json', 'contract.json'], limitations=[
                'Original native historical-request grade remains separate.',
                'Full account and site side effects remain unknown.',
                'Title-only tasks leave body content unspecified; exact author/forum/title and singular new post are checked.',
                'Visible persisted post is a local simulation, not a public external publication.'])


class PostDriver(Driver):
    def __init__(self, task, variant):
        super().__init__(task['source_task_id'])
        self.task, self.variant, self.targets = task, variant, []

    def act(self, locator, op='click', value=None):
        code = super().act(locator, op, value)
        self.targets.append({'code': code, 'bid': locator.get_attribute('bid'), 'current_ax': self.text, 'url': self.page.url})
        return code

    def finish(self, data=None):
        self.response = {'task_type': 'mutate', 'status': 'SUCCESS', 'retrieved_data': None}
        return 'send_msg_to_user(' + repr(json.dumps(self.response)) + ')'

    def create(self, wrong=False):
        page = self.page
        values = self.task['scripted_input_from_user_goal']
        yield self.act(page.get_by_role('link', name='Submit', exact=True).first)
        yield self.act(page.get_by_label('Title', exact=False), 'fill', 'Wrong title for negative validation' if wrong else values['title'])
        if values['body'] is not None:
            yield self.act(page.get_by_label('Body', exact=True), 'fill', values['body'])
        select = page.locator('#submission_forum')
        options = select.locator('option').evaluate_all('(es)=>es.map(e=>({label:e.textContent.trim(),value:e.value}))')
        option = next(row for row in options if row['label'] == values['observed_forum_label'])
        self.record('browser_forum_options', {'options': options, 'selected': option,
                    'scripted_alias_assistance': values['forum_wording'] != option['label']})
        yield self.act(select, 'select_option', option['value'])
        self.record('browser_draft_before_submit', page.locator('form[name=submission]').inner_text())
        if self.variant != 'abandon':
            yield self.act(page.get_by_role('button', name='Create submission', exact=True))
            self.record('browser_after_submit', {'url': page.url, 'body': page.locator('body').inner_text()})

    def steps(self):
        yield from self.create(wrong=self.variant == 'wrong')
        if self.variant == 'overwrite':
            yield self.act(self.page.get_by_role('link', name='Edit', exact=True).first)
            yield self.act(self.page.get_by_label('Title', exact=False), 'fill', 'Changed after the initially correct publication')
            yield self.act(self.page.get_by_role('button', name='Save changes', exact=True))
        elif self.variant == 'duplicate':
            yield from self.create()
        yield self.finish()

    def complete(self, messages):
        from copy import deepcopy
        copied = deepcopy(messages)
        copied[-1]['content'] = copied[-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n', 1)[-1]
        return super().complete(copied)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=int, choices=[t['source_task_id'] for t in CONTRACT['tasks']], required=True)
    parser.add_argument('--variant', choices=['positive', 'wrong', 'overwrite', 'duplicate', 'abandon', 'missing-evidence'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH', '')
    before = closure()
    assert before == BEFORE
    dump(args.output / 'source-before.json', before)
    owned = inspect()
    task = next(task for task in CONTRACT['tasks'] if task['source_task_id'] == args.task)
    adapter = PostTask(task, args.variant)
    driver = PostDriver(task, args.variant)
    backend = scripted_backend(driver)
    profile = native_tools_profile(parallel_tool_calls=None, compact_feedback=True, reasoning_replay='preserve')
    har = args.output / 'network.har'

    def factory(video):
        env = BrowserEnv(task_entrypoint=BrowserTask, task_kwargs={'adapter': adapter}, headless=True,
            slow_mo=0, timeout=10000, pre_observation_delay=1, action_mapping=make_action_set().to_python_code,
            wait_for_user_message=False, pw_context_kwargs={'extra_http_headers': HEADERS['reddit'],
                'record_har_path': str(har.resolve()), 'record_har_content': 'embed', 'service_workers': 'block'})
        driver.env = env
        return env

    try:
        trace, summary = run_episode(factory, backend, {'task': 'webarena-posts-derived', 'source_task_id': args.task,
            'goal': adapter.goal, 'variant': args.variant, 'model': None, 'model_calls': 0, 'training_eligible': False,
            'slow_mo_ms': 0}, output=args.output / 'traces', max_steps=24, episode_task=adapter,
            harness_profile=profile, before_observation=lambda: None, observation_text_limit=48000,
            terminal_response_instruction=CONTRACT['terminal_response_instruction'])
    finally:
        backend.client.close()
    dump(trace / 'scripted-targets.json', driver.targets)
    dump(trace / 'driver-evidence.json', driver.evidence)
    dump(args.output / 'response.json', driver.response)
    subprocess.run([str(ROOT / '.local/webarena-verified/venv/bin/python'), str(HERE / 'grade_native.py'),
                    str(har), str(args.output / 'response.json'), str(args.output / 'native-grade.json'), str(args.task)],
                   check=True, timeout=45)
    native = json.loads((args.output / 'native-grade.json').read_text())
    after = closure()
    dump(args.output / 'source-after.json', after)
    expected = None if args.variant == 'missing-evidence' else args.variant == 'positive'
    passed = (summary['error'] is None and summary['action_error_count'] == 0 and before == after
              and owned == inspect() and adapter.result['task_completed'] is expected)
    report = {'schema': 'webarena-post-case-v1', 'task_id': args.task, 'variant': args.variant, 'passed': passed,
        'trace': str(trace), 'summary': summary, 'derived_result': adapter.result, 'native_grade': native,
        'source_unchanged': before == after, 'source_sha256': before, 'model_calls': 0, 'training_eligible': False,
        'authorization_satisfied': adapter.result['authorization_satisfied'], 'profile': profile.describe(),
        'container': owned, 'artifact_sha256': {str(p.relative_to(args.output)): sha(p) for p in args.output.rglob('*') if p.is_file()}}
    dump(args.output / 'report.json', report)
    print(json.dumps({'task': args.task, 'variant': args.variant, 'passed': passed, 'error': summary['error'],
                     'action_errors': summary['action_error_count'], 'result': adapter.result, 'native_score': native['score']}))
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
