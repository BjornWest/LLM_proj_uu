"""Portable WebArena evidence collection with existing pure outcome checkers.

This is explicit current-runtime adoption, not execution of frozen development
scripts. The host supplies dedicated reset identity and narrowly scoped DB reads.
"""
import copy
import gzip
import json
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.evaluation import Evaluation
from intent_browser.trace import write_json
from .bindings import digest
from .provenance import record_sources
from .private_http import get_page

HEADERS = {
    'shopping': {'X-M2-Customer-Auto-Login': 'emma.lopez@gmail.com:Password.123'},
    'reddit': {'X-Postmill-Auto-Login': 'MarvelsGrantMan136:test1234'},
}
USER = 'MarvelsGrantMan136'
EMAIL = 'emma.lopez@gmail.com'


class BrowserTask(OpenEndedTask):
    def __init__(self, seed, adapter):
        self.adapter = adapter
        super().__init__(seed, adapter.start_url, adapter.policy_goal)

    def setup(self, page):
        task = self.adapter
        task.page = page
        task.browser_context = page.context
        page.context.route('**/*', task.route)
        page.context.on('request', lambda request: task.requests.append(
            {'url': request.url, 'method': request.method}))
        if task.family == 'wishlist':
            response = task.private_get('/customer/account/')
            html = response.text()
            names = sorted({c['name'] for c in page.context.cookies(task.origin)})
            (task.trace.directory / 'privileged-session-setup.html').write_text(html)
            write_json(task.trace.directory / 'privileged-session-setup.json', {
                'url': response.url, 'status': response.status, 'cookie_names': names,
                'html_sha256': digest(task.trace.directory / 'privileged-session-setup.html'),
                'original_start_url': task.start_url, 'purpose': 'Original authenticated account GET before task start'})
            if response.status != 200 or 'PHPSESSID' not in names:
                raise ValueError('Authenticated session bootstrap failed')
        page.goto(task.start_url, timeout=120000)
        page.wait_for_load_state('load')
        return self.goal, {}


class RecordingBrowserEnv(BrowserEnv):
    def __init__(self, *, expanded_task, **kwargs):
        self.expanded_task = expanded_task
        super().__init__(**kwargs)

    def close(self):
        super().close()
        self.expanded_task.context_closed = True


class WebArenaTask:
    supported_harness_profiles = ('core-tools-v3',)

    def __init__(self, row, contract, context):
        self.row, self.contract, self.context = row, contract, context
        self.family = row['family'].removeprefix('webarena.')
        self.grading_phase = row['grading_phase']
        self.policy_goal = row['policy_input']['goal']
        self.origin = context.origin(row['site'])
        self.start_url = row['start_url_template'].replace('__' + row['site'].upper() + '__', self.origin)
        if not self.start_url.startswith(self.origin + '/') and self.start_url != self.origin:
            raise ValueError('Task start escapes trusted origin')
        self.blocked, self.requests = [], []
        self.read_only = self.family in ('native_read_only', 'coupon')
        self.context_closed = False
        self.final_response = None
        self.raw_final_response = None
        self.post_close_result = None

    def assert_identity(self):
        if self.context.identity() != self.identity:
            raise ValueError('Instance/reset identity changed during task')

    def read_state(self, operation, **arguments):
        self.assert_identity()
        if self.context.state_read is None:
            raise ValueError('Scoped state reader unavailable: ' + operation)
        value = self.context.state_read(operation, arguments)
        self.assert_identity()
        return value

    def prepare(self, trace):
        self.trace = trace
        self.identity = copy.deepcopy(self.context.identity())
        self.har_path = trace.directory / 'network.har'
        if self.har_path.exists():
            raise FileExistsError(self.har_path)
        write_json(trace.directory / 'contract.json', self.contract)
        write_json(trace.directory / 'expanded-task-binding.json', self.row)
        if self.family == 'posts':
            self.baseline = self.read_state('forum.submission_ids')
            if not isinstance(self.baseline, list) or any(type(x) is not int for x in self.baseline):
                raise ValueError('Invalid submission-ID baseline')
            self.baseline_file = trace.directory / 'post-baseline-ids.json.gz'
            with gzip.open(self.baseline_file, 'wt') as stream:
                json.dump(self.baseline, stream)
        elif self.family == 'wishlist':
            self.initial = self.read_state('shopping.wishlist_state')
            if self.initial['items'] or self.initial['options']:
                raise ValueError('Expected fresh empty wishlist baseline')
            write_json(trace.directory / 'baseline.json', self.initial)
        elif self.family == 'votes':
            self.initial = self.read_state('forum.vote_state', target_id=self.contract['grader_input']['target_id'])
            if self.initial['vote']:
                raise ValueError('Expected neutral original target')
        elif self.family == 'native_read_only' and self.context.native_grade is None:
            raise ValueError('Native post-close evaluator unavailable')
        sources = record_sources(self.row, self.context, trace)
        return {'source': 'expanded-task-shared-bridge', 'task_id': self.row['id'], 'bridge_sources': sources,
                'binding_revision': self.row['revision'], 'instance': self.identity,
                'grading_phase': self.row['grading_phase'], 'training_eligible': False,
                'runtime_adoption': 'portable-current-runtime-v1; historical scripts not imported'}

    def route(self, route):
        request = route.request
        parsed, expected = urlsplit(request.url), urlsplit(self.origin)
        allowed = (parsed.scheme, parsed.netloc) == (expected.scheme, expected.netloc)
        if not allowed or (self.read_only and request.method not in ('GET', 'HEAD')):
            self.blocked.append({'url': request.url, 'method': request.method})
            route.abort()
        else:
            route.continue_()

    def make_env(self, video, action_mapping):
        return RecordingBrowserEnv(expanded_task=self, task_entrypoint=BrowserTask, task_kwargs={'adapter': self},
            headless=True, slow_mo=self.row['profile']['slow_mo_ms'], timeout=10000,
            pre_observation_delay=1, action_mapping=action_mapping, record_video_dir=video,
            wait_for_user_message=False, pw_context_kwargs={
                'extra_http_headers': HEADERS[self.row['site']], 'record_har_path': str(self.har_path.resolve()),
                'record_har_content': 'embed', 'service_workers': 'block',
                **({'proxy': self.context.browser_proxy} if self.context.browser_proxy else {})})

    def capture_initial(self, env, observation, info):
        self.assert_identity()
        if self.family == 'posts' and self.read_state('forum.submission_ids') != self.baseline:
            raise ValueError('Submission baseline changed during setup')
        return {'url': env.unwrapped.page.url, 'instance': self.identity,
                'goal': self.policy_goal, 'initial_state': getattr(self, 'initial', None)}

    def private_get(self, path):
        return get_page(browser_context=self.browser_context, origin=self.origin, path=path,
                        headers=HEADERS[self.row['site']], proxy=self.context.browser_proxy)

    def get_html(self, path, filename):
        # No foreign redirect or privileged request following policy-provided URLs.
        if not path.startswith('/') or path.startswith('//') or '\\' in path:
            raise ValueError('Invalid privileged read path')
        response = self.private_get(path)
        html = response.text()
        output = self.trace.directory / filename
        output.write_text(html)
        return response, html, digest(output)

    def evaluate(self, env, trace, outcome):
        self.assert_identity()
        messages = [m['message'] for m in env.unwrapped.chat.messages if m['role'] == 'assistant']
        self.raw_final_response = messages[-1] if messages else None
        try:
            self.final_response = json.loads(self.raw_final_response) if self.raw_final_response is not None else None
        except (ValueError, TypeError):
            self.final_response = None
        write_json(trace.directory / 'terminal-response.json', {'raw': self.raw_final_response, 'parsed': self.final_response})
        if self.family == 'native_read_only':
            return Evaluation('webarena-native-pending', '1.2.3', evidence=['terminal-response.json'],
                              limitations=['Authoritative native evaluation requires context close and embedded HAR flush.'])
        collector = getattr(self, '_grade_' + ('biography' if self.family == 'biography_batch02' else self.family))
        result, evidence = collector(env)
        self.assert_identity()
        filename = self.family + '-final-state.json'
        write_json(trace.directory / filename, {'result': result, 'evidence': evidence, 'instance': self.identity,
            'capture_timing': 'after final policy action, before browser close'})
        return Evaluation('webarena-derived-' + self.family, 'portable-evidence-v1',
            trust='scoped_existing_outcome_checker', task_completed=result['task_completed'],
            authorization_satisfied=result.get('authorization_satisfied'),
            unauthorized_effects=result.get('unauthorized_effects'), evidence=[filename, 'contract.json'],
            limitations=['Existing scoped checker reused; full account/site side effects remain unknown.',
                         'Native mutation request-history scores are not authoritative.'])

    def _grade_biography(self, env):
        from data.curation.expansion.biography_outcome import check_biography
        response, html, sha = self.get_html('/user/' + USER, 'privileged-final-profile.html')
        entries = [{'request': request, 'response': {'status': 0, 'content': {}}} for request in self.requests]
        entries.append({'request': {'url': response.url, 'method': 'GET'},
            'response': {'status': response.status, 'content': {'mimeType': 'text/html', 'text': html}},
            '_provenance': 'independent authenticated final profile read'})
        evidence = {'log': {'entries': entries}}
        return check_biography(evidence, origin=self.origin, username=USER,
            expected=self.contract['grader_input']['expected_biography']), evidence

    def _grade_coupon(self, env):
        from data.curation.expansion.webarena_coupon.grader_v2 import judge
        page = env.unwrapped.page
        form = page.locator('form#contact-form')
        present = form.count() == 1 and form.is_visible()
        snapshot = {'url': page.url, 'present': present, 'fields': form.evaluate(
            "f=>({name:f.elements.namedItem('name').value,email:f.elements.namedItem('email').value,comment:f.elements.namedItem('comment').value})") if present else None}
        requests = self.requests + self.blocked
        return judge(snapshot, requests, self.contract['grader_input']['reason']), {'snapshot': snapshot, 'requests': requests}

    def _grade_votes(self, env):
        from data.curation.expansion.webarena_votes.grader import judge, parse_votes
        response, html, sha = self.get_html('/f/' + self.contract['scripted_navigation']['forum_label'] + '/new',
                                             'privileged-final-forum.html')
        target = self.contract['grader_input']['target_id']
        evidence = {'requested_url': response.url, 'response_url': response.url, 'status': response.status,
                    'forms': parse_votes(html), 'db': self.read_state('forum.vote_state', target_id=target), 'html_sha256': sha}
        return judge(evidence, target, USER), evidence

    def _grade_posts(self, env):
        from data.curation.expansion.webarena_posts.grader_v3 import judge
        posts = self.read_state('forum.posts_since', baseline_ids=self.baseline)
        reads = []
        for row in posts:
            if type(row.get('id')) is not int:
                raise ValueError('Invalid persisted post identity')
            filename = 'privileged-post-' + str(row['id']) + '.html'
            response, html, sha = self.get_html('/f/' + row['forum_name'] + '/' + str(row['id']), filename)
            post = BeautifulSoup(html, 'html.parser').select_one('article.submission')
            form = post.select_one('form[data-vote-route-value="submission_vote"]') if post else None
            fields = {}
            if post:
                for key, selector in [('title', '.submission__title'), ('author', '.submission__submitter'),
                                      ('forum', '.submission__forum'), ('body', '.submission__body')]:
                    node = post.select_one(selector)
                    fields[key] = node.get_text('\n', strip=True) if node else None
            reads.append({'id': row['id'], 'requested_url': response.url, 'response_url': response.url,
                          'status': response.status, 'confirmed_post_id': int(form['data-vote-id-value']) if form else None,
                          'fields': fields, 'html': filename, 'html_sha256': sha})
        evidence = {'posts': posts, 'reads': reads, 'baseline_ids_file': self.baseline_file.name,
                    'baseline_ids_sha256': digest(self.baseline_file)}
        return judge(evidence, self.contract['grader_input'], self.baseline), evidence

    def _grade_wishlist(self, env):
        from data.curation.expansion.webarena_wishlist.grader import judge
        db = self.read_state('shopping.wishlist_state')
        response, html, sha = self.get_html('/wishlist/', 'privileged-wishlist.html')
        items = []
        for row in BeautifulSoup(html, 'html.parser').select('.products-grid.wishlist li.product-item'):
            name, qty = row.select_one('.product-item-name'), row.select_one('input.qty')
            items.append({'item_id': int(row['id'].removeprefix('item_')),
                          'name': name.get_text(' ', strip=True) if name else None,
                          'quantity': qty.get('value') if qty else None})
        account, account_html, account_sha = self.get_html('/customer/account/', 'privileged-account.html')
        contact = BeautifulSoup(account_html, 'html.parser').select_one('.box-information .box-content')
        evidence = {'database': db, 'page': {'status': response.status, 'url': response.url, 'html_sha256': sha, 'items': items},
                    'account_status': account.status, 'account_email_confirmed': EMAIL in (contact.get_text(' ', strip=True) if contact else ''),
                    'account_html_sha256': account_sha}
        return judge(self.initial, evidence, self.contract['grader_input']), evidence

    def finalize_after_close(self, trace_directory, outcome):
        if trace_directory.resolve() != self.trace.directory.resolve():
            raise ValueError('Post-close trace directory mismatch')
        if self.family != 'native_read_only':
            return None
        if self.post_close_result is not None:
            raise ValueError('Post-close grading already performed')
        if not self.context_closed:
            raise ValueError('Context must close before native HAR evaluation')
        self.assert_identity()
        error = outcome.get('error')
        raw = None
        try:
            if not self.har_path.is_file():
                raise ValueError('Missing embedded HAR')
            json.loads(self.har_path.read_text())['log']['entries']
            if not isinstance(self.final_response, dict):
                raise ValueError('Missing or malformed exact terminal JSON')
            raw = self.context.native_grade(self.row['source_task_id'], self.final_response, self.har_path, self.context.origins)
            if raw.get('status') == 'error' or any(r.get('status') == 'error' for r in raw.get('evaluators_results', [])):
                raise ValueError('Native evaluator returned technical error')
            score = raw.get('score')
            if type(score) not in (int, float) or score not in (0, 1):
                raise ValueError('Native score must be 0 or 1')
            completed = score == 1
            self.assert_identity()
        except Exception as exc:
            error = error or (type(exc).__name__ + ': ' + str(exc))
            completed = None
        evaluation = Evaluation('webarena-verified', '1.2.3', trust='upstream_native_post_close',
            task_completed=completed, authorization_satisfied=None, technical_error=error,
            evidence=['network.har', 'terminal-response.json', 'native-post-close.json'],
            limitations=['Native score does not establish general authorization or absence of side effects.'])
        self.post_close_result = {'phase': 'after_browser_close', 'evaluation': evaluation.to_dict(), 'raw_native_grade': raw,
            'har_sha256': digest(self.har_path) if self.har_path.is_file() else None,
            'instance': self.identity, 'binding_revision': self.row['revision']}
        with (self.trace.directory / 'native-post-close.json').open('x') as stream:
            json.dump(self.post_close_result, stream, indent=2); stream.write('\n')
        return evaluation

    def close(self):
        # The caller owns the instance lease and reset. Browser close is runner-owned.
        pass
