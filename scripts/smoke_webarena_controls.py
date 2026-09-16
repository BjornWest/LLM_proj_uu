"""Exercise complete local WebArena sites through the unchanged BrowserGym runner.

Scripted control tests, not model benchmarks. DOM locators only select controls
for the script; every mutation goes through an ordinary parsed BrowserGym action.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask

from intent_browser.actions import make_action_set
from intent_browser.backend import Completion, ManualBackend
from intent_browser.runner import run_episode
from intent_browser.trace import write_json

ROOT = Path(__file__).resolve().parents[1]
SITES = {
    'reddit': {'url': 'http://localhost:9999', 'task_id': 399,
               'goal': 'Change my bio to "I am a robot" in the discussion forum',
               'headers': {'X-Postmill-Auto-Login': 'MarvelsGrantMan136:test1234'}},
    'shopping': {'url': 'http://localhost:7770', 'task_id': 118,
                 'goal': 'I have a jaw bruxism problem, go to the product page for something that could alleviate the problem.',
                 'headers': {'X-M2-Customer-Auto-Login': 'emma.lopez@gmail.com:Password.123'}},
}


class LocalSiteTask(OpenEndedTask):
    def __init__(self, seed, start_url, goal, diagnostics):
        super().__init__(seed, start_url, goal)
        self.blocked_requests = diagnostics

    def setup(self, page):
        # Prevent navigation/requests to live sites while inspecting seeded data.
        # No page elements are removed; blocked remote requests are recorded.
        allowed = urlsplit(self.start_url).netloc
        def route(request_route):
            parsed = urlsplit(request_route.request.url)
            if parsed.scheme in ('http', 'https') and parsed.netloc != allowed:
                self.blocked_requests.append(request_route.request.url)
                request_route.abort()
            else:
                request_route.continue_()
        page.context.route('**/*', route)
        page.goto(self.start_url, timeout=120000)
        page.wait_for_load_state('load')
        return self.goal, {}


class ControlScript:
    def __init__(self, site):
        self.site, self.index, self.env = site, 0, None
        self.checks = []

    def action(self, text, locator, name='click', value=None):
        locator.wait_for(state='visible', timeout=15000)
        bid = locator.get_attribute('bid')
        if not bid or f'[{bid}]' not in text:
            raise AssertionError('Script target is absent from the delivered AX text')
        args = [bid] + ([] if value is None else [value])
        return f"{name}({', '.join(repr(x) for x in args)})"

    def complete(self, messages):
        text = messages[-1]['content']
        page = self.env.unwrapped.page
        i = self.index
        self.index += 1
        if self.site == 'shopping':
            if i == 0:
                code = self.action(text, page.locator('#search'), 'fill', 'bruxism')
            elif i == 1:
                code = self.action(text, page.locator('#search'), 'press', 'Enter')
            elif i == 2:
                code = self.action(text, page.locator('select[data-role="sorter"]').first, 'select_option', 'price')
            elif i == 3:
                code = self.action(text, page.locator('.product-item-link').filter(has_text=re.compile('grinding|bruxism', re.I)).first)
            else:
                assert '.html' in page.url and page.locator('.product-info-main').is_visible()
                assert re.search('grinding|bruxism', page.locator('h1').inner_text(), re.I)
                self.checks.append({'check': 'Search and product navigation', 'passed': True, 'url': page.url})
                code = "send_msg_to_user('Done')"
        else:
            # Concrete locators are inspected against the complete upstream site.
            if i == 0:
                code = self.action(text, page.get_by_role('button', name='MarvelsGrantMan136'))
            elif i == 1:
                code = self.action(text, page.get_by_role('link', name='Profile', exact=True))
            elif i == 2:
                code = self.action(text, page.get_by_role('link', name='Edit biography', exact=True))
            elif i == 3:
                code = self.action(text, page.locator('textarea'), 'fill', 'I am a robot')
            elif i == 4:
                code = self.action(text, page.get_by_role('button', name='Save', exact=True))
            elif i == 5:
                assert page.get_by_text('The biography was updated.', exact=True).is_visible()
                code = self.action(text, page.get_by_role('link', name='/u/MarvelsGrantMan136', exact=True))
            else:
                assert page.get_by_role('complementary').get_by_text('I am a robot', exact=True).is_visible()
                self.checks.append({'check': 'Saved biography persists on new profile document', 'passed': True, 'url': page.url})
                code = "send_msg_to_user('Done')"
        return Completion(code, {'source': 'scripted-browser-control-test', 'network_model_calls': 0})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', choices=list(SITES), required=True)
    parser.add_argument('--interactive', action='store_true', help='Development actions via stdin; not model inference')
    parser.add_argument('--observation-limit', type=int, default=16000)
    args = parser.parse_args()
    libraries = ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu'
    if libraries.is_dir():
        os.environ['LD_LIBRARY_PATH'] = str(libraries) + ':' + os.getenv('LD_LIBRARY_PATH', '')
    site = SITES[args.site]
    backend = ManualBackend('development-control-test') if args.interactive else ControlScript(args.site)
    held = {'blocked': []}
    with tempfile.TemporaryDirectory(prefix='wav-smoke-') as temp:
        har = Path(temp) / 'network.har'
        def factory(video):
            env = BrowserEnv(task_entrypoint=LocalSiteTask,
                task_kwargs={'start_url': site['url'], 'goal': site['goal'], 'diagnostics': held['blocked']},
                headless=True, slow_mo=100, timeout=10000, pre_observation_delay=1,
                action_mapping=make_action_set().to_python_code,
                pw_context_kwargs={'extra_http_headers': site['headers'],
                    'record_har_path': str(har), 'record_har_content': 'embed', 'service_workers': 'block'},
                wait_for_user_message=False)
            backend.env = env
            held['env'] = env
            return env
        path, summary = run_episode(factory, backend, {
            'task': 'webarena-verified.control-smoke', 'source_task_id': site['task_id'],
            'goal': site['goal'], 'site': args.site, 'model': None,
            'driver': 'external-development-assistant' if args.interactive else 'scripted_validation',
            'training_eligible': False, 'network_model_calls': 0, 'verifier': None,
            'native_evaluation': 'separate offline report after HAR flush',
            'site_distribution': 'full upstream Verified image; off-origin browser requests blocked',
        }, output=ROOT / 'runs', max_steps=20, observation_text_limit=args.observation_limit)
        if har.exists():
            (path / 'network.har').write_bytes(har.read_bytes())
        rows = [json.loads(s) for s in (path / 'steps.jsonl').read_text().splitlines()]
        report = {'scope': 'Scripted controls only, not model performance or full benchmark certification',
            'passed': summary['error'] is None and summary['action_error_count'] == 0 and summary['stop_reason'] == 'agent_finished',
            'trace': str(path.relative_to(ROOT)), 'site': args.site, 'model_calls': 0,
            'checks': getattr(backend, 'checks', []), 'summary': summary,
            'actions': [row.get('action') for row in rows],
            'off_origin_requests_blocked': held['blocked'],
            'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [Path(__file__).resolve(), ROOT / 'deploy/webarena-verified/compose.yaml']}}
        write_json(path / 'control-smoke.json', report)
        print(json.dumps(report, indent=2))
        if not report['passed']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
