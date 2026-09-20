"""Complete-site human browsing, separate from benchmark preparation and grading.

Uses the immutable BrowserGym runtime/assets. WebArena origins are supplied only
by the controller's exclusive lease broker; no public arbitrary-URL interface.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from intent_browser.environment_runtime import EnvironmentRuntime
from intent_browser.trace import write_json

TRICKY = {'tricky-shop': 'shop', 'tricky-health': 'health', 'tricky-news': 'news', 'tricky-music': 'spotify'}
SITES = set(TRICKY) | {'webarena-shopping', 'webarena-forum', 'prislyktan'}

class BrowsingSession:
    task = None
    def __init__(self, runtime, task_id):
        self.runtime = runtime
        self.site_id = task_id.removeprefix('browse.')
        if self.site_id not in SITES: raise ValueError('Unsupported browsing site')
        self.server = None
        self.prislyktan = None
        self.requests = []; self.blocked = []
        self.headers = {}
        if self.site_id == 'prislyktan':
            from intent_browser.prislyktan import create_runtime, runtime_descriptor
            self.prislyktan=create_runtime()
            descriptor=runtime_descriptor(self.prislyktan)
            self.origin=descriptor['origins']['aggregator']
            self.start_url=descriptor['homepage_url']
            self.allowed_origins=descriptor['allowed_origins']
        elif self.site_id in TRICKY:
            from intent_browser.tricky import FixtureServer
            self.server = FixtureServer(runtime.package/'fixtures/tricky-full-v1')
            if not self.server.build.get('full_site'): raise ValueError('Complete Tricky assets required')
            self.origin = self.server.origin
            self.start_url = self.origin+'/sites/tricky/'+TRICKY[self.site_id]
        else:
            launch = runtime.launch
            if launch.get('site_id') != self.site_id: raise ValueError('Lease site mismatch')
            self.origin = launch['origin'].rstrip('/')
            u = urlsplit(self.origin)
            if u.scheme != 'http' or not u.hostname or u.path or u.query or u.fragment or u.username: raise ValueError('Invalid private browsing origin')
            self.headers = {'X-Daylight-Lease': launch['lease_token']}
            self.start_url = self.origin+'/'
        if not hasattr(self,'allowed_origins'):self.allowed_origins=[self.origin]

    def prepare(self, trace):
        self.trace = trace
        return {'source': self.site_id, 'interaction_kind':'manual', 'browse_only':True,
                'task_setup_applied':False, 'grader':None, 'training_eligible':False,
                'package_sha256':self.runtime.manifest_hash,
                'site_revision':self.server.build['site_revision'] if self.server else self.runtime.launch.get('image_id'),
                'lease_provenance':{k:self.runtime.launch.get(k) for k in ('image_id','generation','reset_report_sha256','broker_sha256') } if not self.server else None,
                'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    def make_env(self, video=None, *, action_mapping, headless=True):
        from browsergym.core.env import BrowserEnv
        from browsergym.core.task import OpenEndedTask
        session = self
        class BrowseTask(OpenEndedTask):
            def setup(self, page):
                def route(r):
                    url = r.request.url; u = urlsplit(url)
                    origin = u.scheme+'://'+u.netloc
                    cached = session.runtime.resources.get(url)
                    if cached:
                        r.fulfill(body=(session.runtime.package/'resources'/cached['file']).read_bytes(),
                                  content_type=cached['content_type'],headers={'Access-Control-Allow-Origin':'*'})
                    elif origin in session.allowed_origins:
                        session.requests.append({'url':url,'method':r.request.method})
                        r.continue_()
                    elif u.scheme in ('data','blob','about'): r.continue_()
                    else:
                        session.blocked.append({'url':url,'method':r.request.method});r.abort()
                page.context.route('**/*',route)
                # Headers contain only a revocable browsing lease, never model or
                # controller credentials. The proxy supplies fixture account auth.
                page.context.set_extra_http_headers(session.headers)
                if session.site_id=='webarena-shopping':
                    page.goto(session.origin+'/customer/account/',timeout=20000,wait_until='domcontentloaded')
                page.goto(self.start_url, timeout=20000, wait_until='domcontentloaded')
                page.wait_for_load_state('load',timeout=20000)
                return '', {}
        env = BrowserEnv(task_entrypoint=BrowseTask,
            task_kwargs={'start_url':self.start_url,'goal':''},headless=headless,
            wait_for_user_message=False,action_mapping=action_mapping,record_video_dir=video)
        env.pw_context_kwargs={**env.pw_context_kwargs,'service_workers':'block'}
        return env

    def capture_initial(self, env, obs, info):
        return {'scope':'Human exploration without task preparation or grading','url':obs['url']}

    def close(self):
        if getattr(self,'closed',False): return
        self.closed=True
        if hasattr(self,'trace'):
            write_json(self.trace.directory/'browsing-network.json',{'requests':self.requests,'blocked':self.blocked,
                'scope':'Browser requests only; no grading, headers or lease secrets'})
        if self.server:
            self.server.close(); self.server = None
        if self.prislyktan:
            self.prislyktan.close();self.prislyktan=None

class BrowsingRuntime(EnvironmentRuntime):
    def __init__(self, package, state, *, launch=None):
        super().__init__(package,state)
        self.launch = launch or {}
    @contextmanager
    def session(self, task_id):
        session = BrowsingSession(self,task_id)
        try: yield session
        finally: session.close()
