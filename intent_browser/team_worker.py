"""Outbound-only team worker. The existing runner owns each complete episode.

Cloud jobs are a small allowlist; they cannot supply URLs, scripts, paths or grader
inputs. Interrupted jobs are never replayed. Original traces stay on the worker.
"""
import argparse
import base64
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4
import zipfile

import httpx

from .backend import ChatCompletionsBackend, Completion, BackendResponseError
from .demo import ASSETS, ROOT, World, DemoTask, EXAMPLES, RehearsalBackend
from .openrouter import DEFAULT_PROVIDERS, provider_options, completion_token_limit
from .trace import write_json, runtime_provenance


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Broker:
    def __init__(self, url, token):
        parsed = urlparse(url)
        if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1'))
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise ValueError('HARNESS_URL must be an HTTPS origin (or localhost for development)')
        if not token or len(token) < 43:
            raise ValueError('HARNESS_WORKER_TOKEN is missing or too short')
        self.client = httpx.Client(base_url=url.rstrip('/'), headers={'Authorization': 'Bearer ' + token},
                                   timeout=30, trust_env=False, follow_redirects=False)

    def post(self, operation, value):
        response = self.client.post('/api/harness/worker/' + operation, json=value)
        if not response.is_success:
            detail = ''
            if operation == 'reserve' and response.status_code == 429:
                try:
                    message = response.json().get('error', '')
                    if isinstance(message, str) and message.startswith('Demo daily '):
                        detail = ': ' + message[:400]
                except ValueError:
                    pass
            raise RuntimeError(f'Worker API {operation} returned HTTP {response.status_code}{detail}; no automatic replay')
        return response.json()


class Publisher:
    """Separate readonly projection; reviewer notes are never read by the policy."""
    def __init__(self, broker, job, folder):
        self.broker, self.job, self.folder = broker, job, folder
        self.directory = None
        self.uploaded = set()
        self.stopped = threading.Event()
        self.failure = None
        self.last_snapshot = None
        self.last_heartbeat = 0.0
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def rpc(self, operation, **value):
        return self.broker.post(operation, {'id': self.job['id'], 'lease': self.job['lease'], **value})

    def checkpoint(self):
        if self.failure:
            raise RuntimeError('Trace publication failed; worker stopped before another decision') from self.failure
        return self.rpc('checkpoint')

    def attach(self, trace):
        self.directory = trace.directory

    def upload(self, name, data):
        fingerprint = digest(data)
        if (name, fingerprint) in self.uploaded:
            return
        self.rpc('artifact', name=name, sha256=fingerprint, data=base64.b64encode(data).decode())
        self.uploaded.add((name, fingerprint))

    def project(self):
        directory = self.directory
        if not directory or not (directory / 'metadata.json').is_file():
            return None
        metadata = json.loads((directory / 'metadata.json').read_text())
        rows = []
        if (directory / 'steps.jsonl').exists():
            for line in (directory / 'steps.jsonl').read_text().splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    break  # A flushed complete JSONL record is the publication boundary.
        steps, latest = [], None
        for row in rows:
            observation = row.get('observation') or {}
            artifact = {key: observation[source] for key, source in [('text', 'text'), ('image', 'screenshot')]
                        if observation.get(source)}
            for name in artifact.values():
                self.upload(name, (directory / name).read_bytes())
            next_obs = row.get('next_observation') or {}
            if next_obs.get('screenshot'):
                latest = next_obs['screenshot']
                self.upload(latest, (directory / latest).read_bytes())
            elif artifact.get('image'):
                latest = artifact['image']
            steps.append({'step': row['step'], 'action': row.get('action'),
                          'error': row.get('error') or row.get('action_error'), 'artifact': artifact,
                          'browser_stepped': row.get('browser_stepped', False)})
        family_rows=list(rows)
        for file in sorted(directory.glob('children/*/steps.jsonl')):
            for line in file.read_text().splitlines():
                try:family_rows.append(json.loads(line))
                except json.JSONDecodeError:break
        known, unknown, alerts, previous_providers = [], 0, [], {}
        for row in family_rows:
            response = row.get('model_response') or {}
            usage = response.get('usage') or {}
            cost = usage.get('cost')
            if type(cost) in (int, float) and cost >= 0:
                if len(known) >= 3 and cost > 0.005 and cost > 3 * statistics.median(known):
                    alerts.append('A request cost exceeded three times the earlier median; review its trace.')
                known.append(cost)
            elif row.get('model_request'):
                unknown += 1
            provider = response.get('provider')
            session=(row.get('model_request') or {}).get('session_id')
            previous_provider=previous_providers.get(session)
            if provider and previous_provider and provider != previous_provider:
                alerts.append('Provider changed within this episode; caching continuity is not guaranteed.')
            if provider: previous_providers[session] = provider
        initial_path = directory / 'initial-state.json'
        resolved_goal = json.loads(initial_path.read_text()).get('resolved_goal') if initial_path.exists() else None
        return {'episode': directory.name, 'resolved_goal': resolved_goal, 'cost': {'reported_usd': sum(known) if known else
                    (0 if metadata.get('driver') == 'scripted-rehearsal' else None),
                    'unknown_attempts': unknown, 'alerts': sorted(set(alerts)),
                    'scope':'parent and helpers','model_attempts':sum(bool(r.get('model_request')) for r in family_rows)},
                'runtime': {'worker': 'team-browsergym-v1',
                'driver': metadata.get('driver'), 'model': metadata.get('model'),
                'generation': metadata.get('generation'), **metadata['runtime']},
                'steps': steps, 'image': latest, 'evaluation': None, 'error': None}

    def loop(self):
        while not self.stopped.wait(3):
            try:
                if time.monotonic() - self.last_heartbeat >= 15:
                    self.checkpoint()
                    self.last_heartbeat = time.monotonic()
                snapshot = self.project()
                if snapshot and snapshot != self.last_snapshot:
                    self.rpc('update', snapshot=snapshot)
                    self.last_snapshot = snapshot
            except Exception as exc:
                self.failure = exc
                return

    def finish(self, error=None, *, authoritative_result=None, require_authoritative=False):
        self.stopped.set()
        self.thread.join(timeout=35)
        if self.thread.is_alive():
            raise RuntimeError('Publisher did not stop; retained local trace without replay')
        snapshot = self.project() or {'steps': [], 'runtime': None, 'image': None}
        parts = []
        if self.directory:
            summary_path = self.directory / 'episode.json'
            if summary_path.exists():
                summary = json.loads(summary_path.read_text())
                snapshot['evaluation'] = summary.get('evaluation')
                error = error or summary.get('error')
            if authoritative_result is not None:
                recorded = json.loads((self.directory / 'authoritative-evaluation.json').read_text())
                if recorded != authoritative_result:
                    raise ValueError('Authoritative result differs from retained artifact')
                snapshot['evaluation'] = recorded['evaluation']
                snapshot['grading_phase'] = recorded['grading_phase']
                snapshot['evaluation_source'] = 'authoritative-evaluation.json'
                error = error or recorded['evaluation'].get('technical_error')
            elif require_authoritative:
                snapshot['evaluation'] = None
                error = error or 'Authoritative grading did not complete; no fallback to runtime evaluation'
            # ZIP retains every original file and relative path. No trace conversion.
            archive = self.folder / 'trace.zip'
            with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as zipped:
                for file in sorted(self.directory.rglob('*')):
                    if file.is_symlink():
                        raise ValueError('Refusing symlink in original trace')
                    if file.is_file():
                        zipped.write(file, str(Path(self.directory.name) / file.relative_to(self.directory)))
            with archive.open('rb') as stream:
                for index in range(200):
                    data = stream.read(1024 * 1024)
                    if not data:
                        break
                    name = f'trace-{index:03d}.part'; self.upload(name, data); parts.append(name)
                else:
                    raise ValueError('Trace exceeds 200 MiB development archive limit')
        snapshot.update(status='error' if error or self.failure else 'finished', error=error or
                        ('Live publication was interrupted; inspect the original trace' if self.failure else None), trace_parts=parts)
        self.rpc('update', snapshot=snapshot)
        write_json(self.folder / 'publication.json', {'uploaded': True, 'episode': snapshot.get('episode'),
                                                    'archive_parts': parts, 'status': snapshot['status']})


class TeamBackend(ChatCompletionsBackend):
    # complete() reserves the full serialized payload, including tool definitions
    # and assistant/tool history, before a single dispatch.
    supports_native_tools = True
    def __init__(self, publisher, env):
        options = provider_options(env.get('OPENROUTER_PROVIDERS') or DEFAULT_PROVIDERS)
        options['provider']['max_price'] = {'prompt': 0.5, 'completion': 4, 'request': 0}
        key = env.get('DAYLIGHT_OPENROUTER_API_KEY')
        if not key:
            raise ValueError('Dedicated DAYLIGHT_OPENROUTER_API_KEY is required for live worker')
        super().__init__('https://openrouter.ai/api/v1', env.get('MODEL_NAME', 'qwen/qwen3.8-27b'), key,
                         max_tokens=completion_token_limit(env.get("OPENROUTER_MAX_TOKENS")), request_options=options, session_routing=True,
                         supports_images=True)
        self.publisher, self.index, self.last_finished = publisher, 0, 0.0
        self.pending_settlement = None
        self.sources = runtime_provenance()['source_sha256']
        self.client.event_hooks['response'] = [self.record_transport]

    def record_transport(self, response):
        response.read()
        row = {'request_body': response.request.content.decode(), 'response_body': response.text,
               'http_status': response.status_code, 'retry_after': response.headers.get('retry-after'),
               'recorded_at_unix': time.time()}
        with (self.publisher.directory / 'model-transport.jsonl').open('a') as file:
            file.write(json.dumps(row) + '\n')
        if self.pending_settlement is not None:
            try:
                result = self.publisher.rpc('settle', **self.pending_settlement, response_text=response.text)
                with (self.publisher.directory / 'team-settlements.jsonl').open('a') as file:
                    file.write(json.dumps({'request': self.pending_settlement, 'result': result}) + '\n')
            except Exception as exc:
                try:
                    raw = response.json()
                except ValueError:
                    raw = {'unparsed_body': response.text}
                raise BackendResponseError('Cost accounting failed; stopped before action delivery',
                                           json.loads(response.request.content), raw) from exc

    def before_observation(self):
        wait = max(0, self.last_finished + 10 - time.monotonic())
        if wait:
            time.sleep(wait)
        self.publisher.checkpoint()
        return {'worker': 'team-browsergym-v1', 'pace_seconds': wait}

    def complete(self, messages):
        self.last_request = None
        if runtime_provenance()['source_sha256'] != self.sources:
            raise RuntimeError('Worker source changed during the episode')
        self.publisher.checkpoint()
        request = {'model': self.model, 'messages': messages, 'temperature': 0,
                   'max_tokens': self.max_tokens, 'stream': False, **self.request_options,
                   'session_id': self.session_id}
        raw = httpx.Request('POST', self.base_url + '/chat/completions', json=request).content
        receipt = self.publisher.rpc('reserve', step=self.index, input_bytes=len(raw), request_sha256=digest(raw), max_tokens=self.max_tokens)
        with (self.publisher.directory / 'team-reservations.jsonl').open('a') as file:
            file.write(json.dumps({'step': self.index, 'request_sha256': digest(raw), 'receipt': receipt}) + '\n')
        self.pending_settlement = {'step': self.index, 'request_sha256': digest(raw)}
        self.index += 1
        if receipt.get('max_tokens') != self.max_tokens:
            raise RuntimeError('Broker did not acknowledge the requested output ceiling; no inference sent')
        try:
            result = super().complete(messages)
            cost = result.raw.get('usage', {}).get('cost')
            if type(cost) not in (int, float) or not 0 <= cost <= receipt['amount_usd']:
                raise BackendResponseError('Unknown or unexpectedly high cost; stopped for review', result.request, result.raw)
            try:
                self.publisher.checkpoint()
            except Exception as exc:
                raise BackendResponseError('Worker connection lost before action delivery', result.request, result.raw) from exc
            return result
        finally:
            self.pending_settlement = None
            self.last_finished = time.monotonic()


class ConfirmRehearsal:
    def __init__(self): self.done = False
    def complete(self, messages):
        if self.done:
            return Completion("send_msg_to_user('Done')", {'source': 'scripted-chaos-rehearsal'})
        # Read only the delivered page text, never the privileged task descriptor.
        matches = re.findall(r"\[([^\]]+)\] button '([^']+)'", messages[-1]['content'])
        decline = next((bid for bid, label in matches if 'no' in label.lower() and 'thank' in label.lower()), None)
        if not decline:
            raise ValueError('Expected newsletter decline control is absent')
        self.done = True
        return Completion(f'click({decline!r})', {'source': 'scripted-chaos-rehearsal'})
    def close(self): pass


class RoomsSite:
    def __init__(self, goal):
        self.world_id = uuid4().hex
        self.world = World()
        self.app = SimpleNamespace(worlds={self.world_id: self.world})
        self.job = {'world': self.world_id, 'area': 'booking', 'goal': goal}
        site = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def send(self, data, mime='application/json', status=200):
                if not isinstance(data, bytes): data = json.dumps(data).encode()
                self.send_response(status);self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(data)));self.end_headers();self.wfile.write(data)
            def do_GET(self):
                path = urlparse(self.path).path
                if path == '/api/world/' + site.world_id: return self.send(site.world.public())
                if path == f'/world/{site.world_id}/booking': return self.send((ASSETS/'site.html').read_bytes(), 'text/html')
                if path in ('/assets/style.css', '/assets/site.js', '/assets/rooms.js'):
                    return self.send((ASSETS/path.split('/')[-1]).read_bytes(), 'text/css' if path.endswith('.css') else 'text/javascript')
                self.send({'error': 'Not found'}, status=404)
            def do_POST(self):
                try:
                    if self.path != '/api/world/' + site.world_id: raise ValueError('Unsupported route')
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size < 24000: raise ValueError('Invalid body size')
                    self.send(site.world.action(json.loads(self.rfile.read(size))))
                except (ValueError, TypeError, KeyError) as exc: self.send({'error': str(exc)}, status=400)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True);self.thread.start()
    def close(self): self.server.shutdown();self.server.server_close();self.thread.join()


class PublishedTask:
    def __init__(self, task, publisher, origin, expanded=None):
        self.task, self.publisher, self.origin, self.expanded = task, publisher, origin, expanded
    def __getattr__(self, name): return getattr(self.task, name)
    def prepare(self, trace):
        self.publisher.attach(trace)
        record = self.task.prepare(trace)
        if self.publisher.job['task'].startswith('chaos-') and not self.task.verifier_ready:
            raise RuntimeError('Chaos build lacks current contract certification')
        if self.expanded:
            row = self.expanded.row
            if self.task.policy_goal != row['policy_input']['goal'] or self.publisher.job['goal'] != self.task.policy_goal:
                raise ValueError('Expanded task goal differs from pinned registry')
            record['team_task'] = {'id': row['id'], 'revision': row['revision'],
                                   'registry_sha256': self.expanded.registry_sha256}
        elif self.publisher.job['task'].startswith('prislyktan:'):
            from .prislyktan import entry
            registered=entry(self.publisher.job['task'])
            if self.task.policy_goal!=registered['goal']:raise ValueError('Prislyktan goal differs from registry')
            record['team_task']={'id':registered['id'],'revision':registered['revision']}
        elif self.publisher.job['task'] != 'rooms':
            from .hosted_tasks import entry, digest, REGISTRY
            registered = entry(self.publisher.job['task'])
            if registered['goal'] is not None and self.task.policy_goal != registered['goal']:
                raise ValueError('Resolved task goal differs from fixed registry goal')
            record['team_task'] = {'id': registered['id'], 'revision': registered['revision'],
                                   'catalog_id': registered['catalog_id'], 'registry_sha256': digest(REGISTRY)}
        return record
    def capture_initial(self, env, obs, info):
        # The allowlisted synthetic site is the only browser network destination.
        # Reviewed Tricky adapters install their own stricter origin/query
        # routes during environment setup. Do not shadow those routes here.
        if hasattr(self.task, 'route'):
            return self.task.capture_initial(env, obs, info)
        origin = self.origin or self.task.client.base_url
        def route(request):
            url = request.request.url
            if url.startswith(origin + '/') or url.startswith(('data:', 'blob:')): request.continue_()
            else: request.abort()
        env.unwrapped.page.context.route('**/*', route)
        return self.task.capture_initial(env, obs, info)


def execute_job(broker, job, data_dir, env, chaos_url=None, *, backend_factory=None):
    if env.get('HARNESS_EXPANDED_EXECUTION_ROOT') and job['task'].startswith(('tricky:', 'webarena:')) and backend_factory is None:
        from .expanded_tasks import isolated_runtime
        return isolated_runtime(env, 'execute', {'job': job, 'data_dir': str(data_dir)})
    from .runner import run_episode
    from .actions import make_action_set
    import browsergym.core  # noqa: F401
    import gymnasium as gym
    folder = data_dir / 'jobs' / job['id'];folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / 'job.json', {k: v for k, v in job.items() if k != 'lease'})
    publisher = Publisher(broker, job, folder);publisher.thread.start()
    site = backend = task = expanded = None
    authoritative_result = None
    expanded_requested = job['task'].startswith(('tricky:', 'webarena:'))
    runner_options = {'max_steps': 12}
    environment = {}
    error = None
    try:
        actions = make_action_set()
        if job['task'] == 'rooms':
            site = RoomsSite(job['goal']);task = DemoTask(site.app, site.job)
            wrapped = PublishedTask(task, publisher, site.origin)
            from browsergym.core.env import BrowserEnv
            from browsergym.core.task import OpenEndedTask
            class BookingTask(OpenEndedTask):
                def __init__(self, seed): super().__init__(seed, f'{site.origin}/world/{site.world_id}/booking', job['goal'])
                def validate(self, page, chat_messages):
                    return 0, bool(site.world.snapshot()['bookings']), '', {'episode_boundary': 'first_accepted_reservation'}
            def factory(video):
                return BrowserEnv(task_entrypoint=BookingTask, headless=True, action_mapping=actions.to_python_code,
                    viewport={'width': 1000, 'height': 850}, wait_for_user_message=False)
            if job['mode'] == 'rehearsal' and job['goal'] != EXAMPLES['booking']['goal']:
                raise ValueError('Rehearsal only supports the exact study-room example; use Live for custom goals')
            default_backend = lambda: TeamBackend(publisher, env) if job['mode'] == 'live' else RehearsalBackend('booking')
        elif job['task'].startswith('prislyktan:'):
            from .prislyktan import PrislyktanTask
            if backend_factory is None:
                from .prislyktan import certified_catalog
                if job['task'] not in [r['id'] for r in certified_catalog(env)]:raise ValueError('Prislyktan task lacks current acceptance')
            task=PrislyktanTask(job['task'],job.get('task_revision'))
            if job['goal']!=task.policy_goal:raise ValueError('Prislyktan goal differs from trusted task')
            wrapped=PublishedTask(task,publisher,None)
            runner_options={'max_steps':20,'terminal_response_instruction':'Complete the requested goal and deliver the requested answer using send_msg_to_user.'}
            def factory(video):return task.make_env(video,action_mapping=actions.to_python_code)
            def default_backend():
                if job['mode']=='live':return TeamBackend(publisher,env)
                raise ValueError('Prislyktan tasks require live or explicit scripted acceptance')
        elif expanded_requested:
            from .expanded_tasks import ExpandedTaskSession
            expanded = ExpandedTaskSession(job['task'], job.get('task_revision'), job['id'], env,
                                           require_certificate=backend_factory is None)
            task = expanded.task
            runner_options = expanded.runner_options()
            wrapped = PublishedTask(task, publisher, None, expanded=expanded)
            def factory(video):
                return task.make_env(video, action_mapping=actions.to_python_code)
            def default_backend():
                if job['mode'] == 'live': return TeamBackend(publisher, env)
                raise ValueError('Expanded tasks need a live worker or trusted local scripted backend')
        elif job['task'] != 'rooms':
            from .hosted_tasks import make_task, entry
            registered = entry(job['task'])
            task = make_task(job['task'], fixture_dir=env.get('HARNESS_FIXTURES_DIR'), chaos_url=chaos_url,
                             revision=job.get('task_revision'))
            wrapped = PublishedTask(task, publisher, None)
            def factory(video):
                if hasattr(task, 'make_env'):
                    return task.make_env(video, action_mapping=actions.to_python_code, headless=True)
                return gym.make('browsergym/openended', task_kwargs={'start_url': task.start_url, 'goal': task.policy_goal},
                    headless=True, action_mapping=actions.to_python_code, viewport={'width': 1000, 'height': 850}, wait_for_user_message=False,
                    record_video_dir=video)
            def default_backend():
                if job['mode'] == 'live': return TeamBackend(publisher, env)
                if job['task'] == 'chaos-confirmshaming': return ConfirmRehearsal()
                raise ValueError('This task needs a live worker; no general scripted policy is installed')
        # A callable test backend can only be supplied by trusted local Python,
        # never by the queue, browser, env vars or another serialized request.
        backend = backend_factory(task, environment) if backend_factory else default_backend()
        if job['mode']=='live' or env.get('HARNESS_VALIDATE_CURRENT_PROFILE')=='1':
            from dataclasses import replace
            from .standard_profile import standard_profile
            from .delegation import AgentLimits
            from .current_task import CurrentPolicyTask
            from .retry_policy import DecisionRetryPolicy
            selected=standard_profile()
            runner_options.update(harness_profile=replace(selected,
                agent_limits=AgentLimits(total_model_calls=runner_options['max_steps'])),
                retry_policy=DecisionRetryPolicy())
            wrapped=CurrentPolicyTask(wrapped)
            if job['task']=='rooms':
                from .helper_browser import openended_helper_factory
                runner_options['helper_env_factory']=openended_helper_factory
        original_factory = factory
        def factory(video):
            instance = original_factory(video)
            environment['env'] = instance
            return instance
        original_hook = backend.before_observation if isinstance(backend, TeamBackend) else publisher.checkpoint
        def hook():
            value = original_hook()
            if expanded: expanded.checkpoint()
            return value
        trace_directory, summary = run_episode(factory, backend, {'task': job['task'], 'goal': job['goal'], 'team_job': job['id'],
                    'episode_boundary': 'first_accepted_reservation' if job['task'] == 'rooms' else 'agent_finished',
                    'driver': 'scripted-validation' if backend_factory is not None else 'llm' if job['mode'] == 'live' else 'scripted-rehearsal',
                    'model': getattr(backend, 'model', 'scripted-rehearsal'), 'training_eligible': False,
                    'task_revision': job.get('task_revision'),
                    **(expanded.activity_metadata() if expanded else {}),
                    'generation': {'max_tokens': backend.max_tokens, **backend.request_options} if isinstance(backend, TeamBackend) else None},
                    output=data_dir / 'runs', before_observation=hook, episode_task=wrapped,
                    record_video=True, **runner_options)
        if expanded:
            from .task_finalization import finalize_task_run
            authoritative_result = finalize_task_run(task, trace_directory, summary)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        write_json(folder / 'worker-error.json', {'error': error})
    finally:
        for resource in (backend, expanded if expanded else task, site):
            try:
                if resource and hasattr(resource, 'close'): resource.close()
                elif resource and hasattr(resource, 'client'): resource.client.close()
            except Exception as exc:
                error = error or f'{type(exc).__name__}: Resource cleanup failed'
                write_json(folder / 'cleanup-error.json', {'error': type(exc).__name__, 'replay_allowed': False})
        try: publisher.finish(error, authoritative_result=authoritative_result, require_authoritative=expanded_requested)
        except Exception as exc:
            write_json(folder / 'publication-error.json', {'error': f'{type(exc).__name__}: {exc}',
                       'replay_allowed': False, 'original_trace': str(publisher.directory) if publisher.directory else None})


def start_chaos(build):
    record = build / 'server.json'
    if record.exists():
        candidate = json.loads(record.read_text())
        try:
            from .chaos_verifier import fingerprint_server, certification
            if certification(fingerprint_server(candidate['agent_url']), 'confirmshaming'): return candidate['agent_url']
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError): pass
    result = subprocess.run(['python3', str(ROOT/'scripts/start_chaos_repair.py'), '--build', str(build), '--human-port', '3147'],
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)['agent_url']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--once', action='store_true', help='Poll once and execute at most one new job')
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    libraries = ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu'
    if libraries.is_dir(): os.environ['LD_LIBRARY_PATH'] = str(libraries) + ':' + os.getenv('LD_LIBRARY_PATH', '')
    env = dict(os.environ);mode = env.get('HARNESS_MODE', 'rehearsal')
    if mode not in ('live', 'rehearsal'): raise ValueError('HARNESS_MODE must be rehearsal or live')
    data_dir = Path(env.get('HARNESS_DATA_DIR', str(ROOT/'.local/team-worker/data'))).resolve();data_dir.mkdir(parents=True, exist_ok=True)
    # Refuse two processes sharing the same worker state, including container restarts.
    import fcntl
    lock = (data_dir/'worker.lock').open('a');fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    broker = Broker(env.get('HARNESS_URL', ''), env.get('HARNESS_WORKER_TOKEN'))
    identity = str(uuid4());chaos_url = start_chaos(Path(env['HARNESS_CHAOS_BUILD']).resolve()) if env.get('HARNESS_CHAOS_BUILD') else None
    from .hosted_tasks import capabilities, registry
    tasks = ['rooms'] + capabilities(mode, env.get('HARNESS_FIXTURES_DIR'), chaos_url)
    while True:
        try:
            from .expanded_tasks import certified_tasks, isolated_runtime
            from .prislyktan import certified_catalog
            prislyktan=certified_catalog(env) if mode=='live' else []
            extra = (isolated_runtime(env, 'capabilities') if env.get('HARNESS_EXPANDED_EXECUTION_ROOT')
                     else certified_tasks(env)[0]) if mode == 'live' else []
            result = broker.post('poll', {'worker_id': identity, 'mode': mode, 'tasks': tasks+[t['id'] for t in extra+prislyktan],
                                'task_revisions': {t['id']:t['revision'] for t in registry()['tasks']+extra+prislyktan}})
            if result.get('job'):
                print('Starting team job', result['job']['id'], flush=True)
                execute_job(broker, result['job'], data_dir, env, chaos_url)
                print('Finished team job', result['job']['id'], flush=True)
        except Exception as exc:
            print('Worker connection unavailable:', type(exc).__name__, flush=True)
        if args.once: break
        time.sleep(max(2, float(env.get('HARNESS_POLL_SECONDS', '5'))))


if __name__ == '__main__': main()
