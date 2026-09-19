"""Portable setup, unchanged existing Tricky snapshot/grading methods.

No historical module globals or fixtures are modified. A fresh adapter/server is
created for every invocation, including when called from a local test suite.
"""
import importlib
import json
from pathlib import Path
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.tricky import FixtureServer
from intent_browser.trace import write_json
from .bindings import digest
from .provenance import record_sources


class AuthoredBrowser(OpenEndedTask):
    def __init__(self, seed, adapter):
        self.adapter = adapter
        super().__init__(seed, adapter.start_url, adapter.policy_goal)

    def setup(self, page):
        task = self.adapter
        setup = task.contract.get('setup', {})
        saved = setup.get('saved_article_ids', [])
        if saved:
            page.context.add_init_script("if (!sessionStorage.getItem('authored03_news_seeded')) {"
                "localStorage.setItem('personalizedArticles'," + json.dumps(json.dumps(saved)) + ");"
                "sessionStorage.setItem('authored03_news_seeded','1');}")
        seed = setup.get('cart_quantities', {})
        if seed:
            catalog = json.loads((task.fixture_root / 'catalog.json').read_text())
            cart = [{**p, 'quantity': seed[str(p['id'])]} for p in catalog if str(p['id']) in seed]
            if len(cart) != len(seed):
                raise ValueError('Seed product missing from pinned catalog')
            page.context.add_init_script("if (!sessionStorage.getItem('authored02_seeded')) {"
                "localStorage.setItem('cart'," + json.dumps(json.dumps(cart)) + ");"
                "sessionStorage.setItem('authored02_seeded','1');}")
        page.context.expose_binding('__authoredCapture', lambda source, event: task.events.append(event))
        page.context.add_init_script('window.__intentEmit=(kind,payload)=>window.__authoredCapture({kind,payload,url:location.href});')
        page.context.route('**/*', task.route)
        result = super().setup(page)
        page.get_by_text('Scratchpad', exact=True).wait_for(timeout=5000)
        return result


class TrickyTask:
    supported_harness_profiles = ('core-tools-v3',)
    grading_phase = 'before_browser_close'

    def __init__(self, row, contract, context):
        self.row, self.context, self.contract = row, context, contract
        self.policy_goal = row['policy_input']['goal']
        self.fixture_root = Path(context.fixture_root) if context.fixture_root else None
        family = row['family']
        if family == 'tricky.lookup':
            module = importlib.import_module('data.curation.expansion.tricky.lookup_tasks')
            cls, self.browser_class, self.contract_filename = module.LookupTask, module.LookupBrowserTask, 'lookup-contract.json'
        elif family in ('tricky.action', 'tricky.remaining'):
            module = importlib.import_module('data.curation.expansion.tricky.batch02.tasks')
            self.browser_class, self.contract_filename = module.BrowserTask, 'action-contract.json'
            cls = module.ActionTask
            if family == 'tricky.remaining':
                cls = importlib.import_module('data.curation.expansion.tricky_original_remaining.tasks').RemainingTask
        else:
            module = importlib.import_module('data.curation.expansion.' + family)
            cls, self.browser_class, self.contract_filename = module.AuthoredTask, AuthoredBrowser, 'authored-contract.json'
        self.adapter = cls(contract['id'])
        if self.adapter.contract != contract or self.adapter.policy_goal != self.policy_goal:
            raise ValueError('Loaded adapter differs from pinned private contract')
        # Portable browser setup only. Retain exact existing evaluation/snapshot methods.
        self.adapter.fixture_root = self.fixture_root
        self.adapter.route = self.route

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    def route(self, route):
        if route.request.url.startswith(self.adapter.server.origin + '/'):
            route.continue_()
        else:
            route.abort()

    def prepare(self, trace):
        if self.fixture_root is None:
            raise ValueError('Complete Tricky fixture required')
        for filename, key in [('build.json', 'complete_site_build'), ('catalog.json', 'catalog')]:
            if digest(self.fixture_root / filename) != self.row['fixture'][key]['sha256']:
                raise ValueError('Fixture pin mismatch: ' + filename)
        adapter = self.adapter
        adapter.trace = trace
        adapter.server = FixtureServer(self.fixture_root)
        path = self.contract.get('start_path', '/sites/tricky/' + self.contract.get('site', 'shop'))
        adapter.start_url = adapter.server.origin + path
        write_json(trace.directory / self.contract_filename, self.contract)
        write_json(trace.directory / 'full-build.json', adapter.server.build)
        write_json(trace.directory / 'expanded-task-binding.json', self.row)
        sources = record_sources(self.row, self.context, trace)
        return {'source': 'expanded-task-shared-bridge', 'task_id': self.row['id'], 'bridge_sources': sources,
                'binding_revision': self.row['revision'], 'grading_phase': self.row['grading_phase'],
                'historical_adapter': self.row['historical_factory'], 'portable_setup_version': 1,
                'training_eligible': False, 'curation_ready': False}

    def make_env(self, video, action_mapping):
        return BrowserEnv(task_entrypoint=self.browser_class, task_kwargs={'adapter': self.adapter},
                          headless=True, slow_mo=self.row['profile']['slow_mo_ms'],
                          wait_for_user_message=False, action_mapping=action_mapping, record_video_dir=video)
