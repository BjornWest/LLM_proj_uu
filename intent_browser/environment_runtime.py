"""Run packaged environments with the existing BrowserGym loop, entirely locally.

Use the copied runtime, not a checkout with potentially different verifier code:
PYTHONPATH=PACKAGE/runtime python -m intent_browser.environment_runtime ...
"""
import argparse
from contextlib import contextmanager
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import sys
from importlib.metadata import version
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import unquote, urlparse
from uuid import uuid4

from .environment_package import verify, digest


class LocalSite:
    """Serve only public fixture assets; privileged package files have no route."""
    def __init__(self, *, html_root=None, area=None):
        self.html_root = Path(html_root) if html_root else None
        self.area = area
        if area:
            from .demo import World, EXAMPLES
            self.world = World();self.world_id = uuid4().hex
            self.app = SimpleNamespace(worlds={self.world_id: self.world})
            self.job = {'world': self.world_id, 'area': area, 'goal': EXAMPLES[area]['goal']}
        site = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def send(self, value, mime='application/json', status=200):
                raw = value if isinstance(value, bytes) else json.dumps(value).encode()
                self.send_response(status);self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                from .demo import ASSETS
                path = unquote(urlparse(self.path).path)
                if site.area:
                    if path == '/api/world/'+site.world_id:
                        return self.send(site.world.public())
                    if path == f'/world/{site.world_id}/{site.area}':
                        return self.send((ASSETS/'site.html').read_bytes(), 'text/html')
                    if path in ['/assets/'+n for n in ('style.css','site.js','rooms.js')]:
                        f = ASSETS/path.rsplit('/',1)[-1]
                        return self.send(f.read_bytes(), mimetypes.guess_type(f)[0])
                else:
                    candidate = (site.html_root/path.lstrip('/')).resolve()
                    if candidate.is_relative_to(site.html_root.resolve()) and candidate.is_file():
                        return self.send(candidate.read_bytes(), mimetypes.guess_type(candidate)[0] or 'application/octet-stream')
                self.send({'error': 'Not found'}, status=404)
            def do_POST(self):
                try:
                    if not site.area or self.path != '/api/world/'+site.world_id:
                        return self.send({'error': 'Not found'}, status=404)
                    size = int(self.headers.get('Content-Length','0'))
                    if not 0 < size < 24000: raise ValueError('Invalid body size')
                    self.send(site.world.action(json.loads(self.rfile.read(size))))
                except (ValueError, TypeError, KeyError) as e:
                    self.send({'error': str(e)}, status=400)
        self.server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        self.origin = 'http://127.0.0.1:'+str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True);self.thread.start()

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()


class ChaosService:
    def __init__(self, package, state):
        build = package/'chaos'
        state.mkdir(parents=True, exist_ok=False)
        # Preserve fingerprint_server's conservative /proc process-start check.
        latest = max(p.stat().st_mtime for p in [build/'package.json',*(build/'dist').rglob('*')] if p.is_file())
        time.sleep(max(0, latest+1.1-time.time()))
        self.log = (state/'server.log').open('x')
        self.process = subprocess.Popen(['node',str(build/'dist/cli.mjs'),'--port','0','--no-open'],
            env={**os.environ,'XDG_STATE_HOME':str(state)}, cwd=state,
            stdout=self.log, stderr=subprocess.STDOUT)
        try:
            for _ in range(200):
                if self.process.poll() is not None: raise RuntimeError('Packaged Chaos exited; inspect its local server.log')
                match = re.search(r'http://localhost:(\d+)/start', (state/'server.log').read_text())
                if match:
                    self.origin = 'http://127.0.0.1:'+match[1];break
                time.sleep(.1)
            else: raise TimeoutError('Packaged Chaos startup timed out')
        except BaseException:
            self.close();raise

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill();self.process.wait()
        self.log.close()


class Session:
    def __init__(self, runtime, task_id):
        self.runtime, self.task_id = runtime, task_id
        self.task = self.site = None
        self.requests = [];self.blocked = [];self.cached_requests = [];self.environment = {}
        self.old_mini_url = None
        available = {t for d in runtime.manifest['datasets'] for t in d['tasks']}
        if task_id not in available: raise ValueError('Task is not included in this package')
        from .hosted_tasks import make_task
        if task_id.startswith('campus.'):
            from .demo import DemoTask
            self.kind = 'campus';self.site = LocalSite(area=task_id.split('.',1)[1])
            self.task = DemoTask(self.site.app, self.site.job)
        elif task_id.startswith('miniwob.'):
            self.kind = 'miniwob';self.site = LocalSite(html_root=runtime.package/'miniwob/html')
            import browsergym
            vendor = str(runtime.package/'vendor/browsergym')
            if vendor not in browsergym.__path__: browsergym.__path__.append(vendor)
            import browsergym.miniwob  # noqa: F401
            self.old_mini_url = os.environ.get('MINIWOB_URL')
            os.environ['MINIWOB_URL'] = self.site.origin+'/miniwob/'
        elif task_id == 'susbench.ikea-preselect':
            from .susbench_ikea import IkeaInjectionTask
            self.kind = 'ikea';self.task = IkeaInjectionTask('packaged-default')
        else:
            from .hosted_tasks import entry
            self.kind = entry(task_id)['kind']
            if self.kind == 'chaos': runtime.start_chaos()
            self.task = make_task(task_id, fixture_dir=runtime.package/'fixtures',
                                  chaos_url=runtime.chaos.origin if runtime.chaos else None)

    def __getattr__(self, name):
        return getattr(self.task, name)

    def prepare(self, trace):
        self.trace = trace
        record = self.task.prepare(trace) if self.task else {'source':'miniwob','verifier':'native_reward'}
        if self.kind == 'chaos' and not self.task.verifier_ready:
            raise RuntimeError('Packaged Chaos lacks current verifier certification')
        record['environment_package'] = {'manifest_sha256': self.runtime.manifest_hash,
            'format': self.runtime.manifest['format'], 'task_id': self.task_id,
            'runtime_source_sha256': digest(__file__), 'network_policy': 'fixture-origin-only',
            'publication_required': False}
        return record

    def make_env(self, video=None, *, action_mapping, headless=True):
        import gymnasium as gym
        import browsergym.core  # noqa: F401
        options = dict(headless=headless, slow_mo=0, wait_for_user_message=False,
                       action_mapping=action_mapping, record_video_dir=video)
        if self.kind == 'campus':
            from browsergym.core.env import BrowserEnv
            from browsergym.core.task import OpenEndedTask
            env = BrowserEnv(task_entrypoint=OpenEndedTask,
                task_kwargs={'start_url':f'{self.site.origin}/world/{self.site.world_id}/{self.site.area}',
                             'goal': self.site.job['goal']}, **options)
        elif self.kind == 'miniwob':
            env = gym.make('browsergym/'+self.task_id, **options)
        elif self.kind == 'chaos':
            env = gym.make('browsergym/openended',
                           task_kwargs={'start_url':self.task.start_url,'goal':self.task.policy_goal}, **options)
        else:
            env = self.task.make_env(video, action_mapping=action_mapping, headless=headless)
        base = env.unwrapped;original = base.task_entrypoint;session = self
        if self.site: origin = self.site.origin
        elif self.kind == 'chaos': origin = self.runtime.chaos.origin
        elif self.kind == 'ikea':
            from .susbench_ikea import ORIGIN
            origin = ORIGIN
        else: origin = self.task.server.origin
        def allowed(url):
            p = urlparse(url)
            return url in self.runtime.resources or p.scheme in ('data','blob','about') or p.scheme+'://'+p.netloc == origin
        def route(r):
            cached = self.runtime.resources.get(r.request.url)
            if cached:
                self.cached_requests.append(r.request.url)
                r.fulfill(body=(self.runtime.package/'resources'/cached['file']).read_bytes(),
                          content_type=cached['content_type'],headers={'Access-Control-Allow-Origin':'*'})
            elif allowed(r.request.url): r.fallback()
            else: r.abort()
        def guarded_task(*args, **kwargs):
            task = original(*args, **kwargs)
            setup = task.setup
            def guarded_setup(page):
                page.context.on('request', lambda req: session.requests.append(req.url) if allowed(req.url) else session.blocked.append(req.url))
                page.context.route('**/*',route)
                result = setup(page)
                # Run the origin guard before existing adapter handlers, then
                # fall through so their stricter path/condition checks survive.
                page.context.route('**/*',route)
                return result
            task.setup = guarded_setup
            return task
        base.task_entrypoint = guarded_task
        base.pw_context_kwargs = {**base.pw_context_kwargs, 'service_workers':'block'}
        self.environment['env'] = env
        return env

    def capture_initial(self, env, obs, info):
        return self.task.capture_initial(env,obs,info) if self.task else {'scope':'Native MiniWoB state; no independent authorization verifier'}

    def run(self, backend, *, output=None, max_steps=12, seed=0, record_video=False, metadata=None):
        """Use any existing backend; model provisioning/publication stay outside.

        Refresh after readiness/pacing even when readiness is a zero-wait hook.
        Dynamic page initialization can finish after reset's first observation.
        """
        from .actions import make_action_set
        from .runner import run_episode
        hook = getattr(backend,'before_observation',None) or (lambda: {'source':'package-readiness','wait_seconds':0})
        return run_episode(lambda video:self.make_env(video,action_mapping=make_action_set().to_python_code),
            backend, {**(metadata or {}),'task':self.task_id,'package_sha256':self.runtime.manifest_hash},
            output=output or self.runtime.state/'runs',max_steps=max_steps,seed=seed,
            record_video=record_video,episode_task=self,before_observation=hook)

    def evaluate(self, env, trace, outcome):
        from .evaluation import Evaluation
        from .trace import write_json
        if self.task: result = self.task.evaluate(env,trace,outcome)
        else:
            result = Evaluation('miniwob','native-reward-v1',trust='native_environment_reward',
                task_completed=bool(outcome['final_reward']>0) if outcome['terminated'] else None,
                limitations=['Native reward does not establish authorization preservation.'])
        write_json(trace.directory/'package-network.json', {'requests':self.requests,'blocked':self.blocked,'fulfilled_from_package':self.cached_requests,
            'scope':'Browser fixture requests; OS isolation is checked separately by network-none container acceptance.'})
        result.evidence.append('package-network.json')
        if self.blocked: result.technical_error = 'Environment attempted a request outside its fixture origin'
        return result

    def close(self):
        if self.task and hasattr(self.task,'close'): self.task.close()
        if self.kind == 'chaos': self.task.client.close()
        if self.site: self.site.close()
        if self.kind == 'miniwob':
            if self.old_mini_url is None: os.environ.pop('MINIWOB_URL',None)
            else: os.environ['MINIWOB_URL'] = self.old_mini_url


class EnvironmentRuntime:
    def __init__(self, package, state):
        self.package = Path(package).resolve(strict=True)
        self.manifest = verify(self.package);self.manifest_hash = digest(self.package/'manifest.json')
        self.resources = json.loads((self.package/'resources/inter.json').read_text())['resources']
        if sys.version_info[:2] != (3,12) or version('browsergym-core') != self.manifest['requires']['browsergym-core']:
            raise RuntimeError('Use the package Python 3.12 / pinned BrowserGym runtime image')
        expected = self.package/'runtime/intent_browser/environment_runtime.py'
        if Path(__file__).resolve() != expected:
            raise ValueError('Use the copied runtime via PYTHONPATH=PACKAGE/runtime; mixing checkout adapters is unsupported')
        self.state = Path(state).resolve()
        if self.state.is_relative_to(self.package): raise ValueError('Writable state must be outside the immutable package')
        self.state.mkdir(parents=True, exist_ok=False)
        self.chaos = None;self.active = False

    def start_chaos(self):
        if self.chaos is None: self.chaos = ChaosService(self.package, self.state/'chaos')

    @contextmanager
    def session(self, task_id):
        if self.active: raise RuntimeError('One active synchronous BrowserGym session per process; use separate processes for parallel rollouts')
        self.active = True;session = None
        try:
            session = Session(self,task_id);yield session
        finally:
            if session: session.close()
            self.active = False

    def close(self):
        if self.chaos: self.chaos.close()

    def __enter__(self): return self
    def __exit__(self,*args): self.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,required=True)
    args = p.parse_args()
    manifest = verify(args.package)
    print(json.dumps({'format':manifest['format'],'datasets':manifest['datasets']},indent=2))


if __name__ == '__main__': main()
