"""Once-only Luna suite over independently accepted, immutable per-case builds.

The transport is an explicitly pinned external dependency loaded under a private
package name. It never replaces the recipe's native source or frozen grader.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from hashlib import sha256
import argparse
import fcntl
import importlib
import importlib.util
import importlib.machinery
import importlib.abc
import inspect
import json
import os
from pathlib import Path
import runpy
import re
import signal
import subprocess
import sys
import threading
import time
import types
from urllib.request import urlopen
import uuid

CASE_IDS = tuple([f'B{i:02d}' for i in range(1, 17)] + ['B18', 'B20',
    'H01', 'H02', 'H03', 'H05', 'H06', 'H07', 'H10',
    'A01', 'A02', 'A03', 'A04', 'H08', 'B17', 'B19', 'H04', 'H09'])
LIMITS = {'max_steps': 200, 'max_input_tokens': 120000,
          'whole_episode_timeout_seconds': 10800, 'request_timeout_seconds': 180,
          'automatic_retries': 0}
COUNT_SCOPE = 'Qwen local complete-request estimate with usage-backed opaque reasoning; not exact Luna tokenization'


def pin(path):
    path = Path(path).absolute()
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def checked(row):
    path = Path(row['path'])
    if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != row['sha256']:
        raise ValueError('Bound input changed: ' + str(path))
    return path


def load(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def progress(output, stage, **details):
    path = Path(output)/'capacity-state.json'
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex)
    save(temporary, {'stage': stage, 'pid': os.getpid(), 'epoch': time.time(), **details})
    os.replace(temporary, path)


def validate_request(request):
    if (request.get('id') != 'LUNA34-PARALLEL-EVALUATION-20261011-01'
            or request.get('model') != 'gpt-6-luna'
            or request.get('reasoning_effort') != 'medium'
            or tuple(c['case'] for c in request['cases']) != CASE_IDS
            or any(request['limits'].get(k) != v for k, v in LIMITS.items())
            or request['concurrency']['target'] != 34):
        raise ValueError('Require the exact authorized Luna34 suite and limits')


def validate_cases(spec):
    request = load(checked(spec['authorization']))
    validate_request(request)
    if spec['cases'] != case_table(request):
        raise ValueError('Launch cases differ from exact accepted recipe/callable bindings')


def verify_source_export(root, commit, descriptor, required):
    """Explicit reviewed capsule provenance, never an absent-Git fallback."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Export root must be an ordinary directory')
    root = root.resolve()
    index = load(checked(descriptor['index']))
    if index.get('format') != 'private-frozen-source-capsule-v1':
        raise ValueError('Exact frozen source capsule index required')
    row = index['roots'][descriptor['root_id']]
    if row['commit'] != commit:
        raise ValueError('Export committed identity changed')
    for name, digest in required.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Export file escaped indexed root')
        path = root/relative
        if not path.resolve().is_relative_to(root) or any(parent.is_symlink() for parent in [path,*path.parents] if parent.is_relative_to(root)):
            raise ValueError('Export path or ancestor is a symlink')
        record = row['files'][name]
        if record['sha256'] != digest or record['mode'] not in ('100644','100755'):
            raise ValueError('Export pin differs from approved indexed source')
        checked({'path':str(path),'sha256':digest})
        mode = path.stat().st_mode & 0o777
        expected = 0o755 if record['mode']=='100755' else 0o644
        if mode != expected or path.stat().st_size != record['bytes']:
            raise ValueError('Export bytes/mode differ from approved index')
    return row


CODE_PACKAGES = ('scripts', 'intent_browser', 'experiments', 'environments')


def current_binding(case):
    """True when the case runs from the one current checkout, not a frozen root."""
    mode = case.get('source_binding', 'pinned')
    if mode not in ('current', 'pinned'):
        raise ValueError('Unknown case source binding: ' + str(mode))
    return mode == 'current'


def recipe_check(case):
    recipe = Path(case['recipe']).resolve()
    manifest = load(checked(case['recipe_manifest']))
    for name, digest in manifest['files'].items():
        path = recipe/name
        if not path.resolve().is_relative_to(recipe):
            raise ValueError('Recipe path escaped its root')
        checked({'path': str(path), 'sha256': digest})
    root = Path(case['root']).resolve()
    current = current_binding(case)
    if current:
        # One checkout runs every task: verify that exact clean commit, and
        # keep only data-like declared sources exact (code drift is recorded
        # by generation.load as provenance).
        if subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                   text=True).strip() != case['commit']:
            raise ValueError('Single-version checkout is not at the accepted commit')
        if subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no',
                                    '--', *CODE_PACKAGES], text=True).strip():
            raise ValueError('Single-version checkout has uncommitted code changes')
    elif 'source_export' in case:
        verify_source_export(root, case['commit'], case['source_export'], manifest['source_sha256'])
    elif subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                 text=True).strip() != case['commit']:
        raise ValueError('Accepted per-case commit changed')
    for name, digest in manifest['source_sha256'].items():
        path = root/name
        if not path.resolve().is_relative_to(root):
            raise ValueError('Declared source escaped accepted root')
        if current and not (name.startswith('.local/') or '/data/' in name):
            continue
        checked({'path': str(path), 'sha256': digest})
    setup_names = ['saved-answer-setup.private.json', 'simulated-order-setup.private.json',
                   'variant-reset-setup.private.json', 'saved-review-setup.private.json']
    public = [load(recipe/n) for n in setup_names if (recipe/n).is_file()]
    episode = load(recipe/'episode.json')
    public.append(episode.get('manual_task', {}))
    if not any(p.get('user_message') == case['public_request'] for p in public):
        # Configured instances also bind prose in the instance declaration.
        instance = recipe/'task-instance.private.json'
        if not instance.is_file() or load(instance).get('user_message') != case['public_request']:
            raise ValueError('Accepted public request differs from authorization')
    address_only = (case.get('task_id',case['id']) in ('H01', 'H02') and
        case['callable']['module'] == 'environments.website_world.simulated_order_address_runner')
    if not manifest.get('automatic_grader_supported') and not address_only:
        raise ValueError('Recipe lacks native automatic grading support')
    return manifest


def case_table(request):
    result = []
    for requested in request['cases']:
        source = load(checked(requested['manifest']))
        row = next(c for c in source['cases'] if c.get('id', c.get('case')) == requested['case'])
        if 'prepared' in row:
            release = load(checked(row['source_receipt']))
            root = release.get('source_root', release.get('root', release.get('worktree')))
            commit = release.get('source_head', release.get('frozen_composed_commit'))
            if commit is None:
                # Navigation's accepted runtime report carries the exact frozen
                # commit separately from the source-only owned commit list.
                commit = release['dependencies']['exact_local_tip']
            prepared = checked(row['prepared'])
            recipe = prepared.parent/'recipe'
            call = {'module': 'environments.website_world.task_instances', 'symbol': 'run'}
            argument = str(prepared.parent)
            manifest = row['recipe_manifest']
        else:
            root, commit = row['source_root'], row['source_commit']
            recipe = Path(row['recipe'])
            call = row['callable']
            if isinstance(call, str):
                module, symbol = call.rsplit('.', 1)
                call = {'module': module, 'symbol': symbol}
            argument = str(recipe)
            manifest = row.get('recipe_manifest', row.get('manifest'))
        result.append({'id': requested['case'], 'root': root, 'commit': commit,
            'recipe': str(recipe), 'recipe_manifest': manifest,
            'callable': call, 'argument': argument, 'public_request': requested['public_request'],
            'acceptance_manifest': requested['manifest'], 'whole_run_effects': 'unknown'})
    return result


class RawSourceLoader(importlib.machinery.SourceFileLoader):
    """Execute the pinned source, never read a historical bytecode cache."""
    def get_code(self, fullname):
        return self.source_to_code(self.get_data(self.path), self.path)


class FrozenSourceFinder(importlib.abc.MetaPathFinder):
    def __init__(self, roots):
        self.roots = roots

    def find_spec(self, fullname, path=None, target=None):
        prefix = fullname.split('.')[0]
        if prefix not in self.roots:
            return None
        found = importlib.machinery.PathFinder.find_spec(fullname, path)
        root = self.roots[prefix]
        if found is not None and found.origin is None:
            locations = [p for p in found.submodule_search_locations or []
                         if Path(p).resolve().is_relative_to(root)]
            if locations:
                found.submodule_search_locations = locations
                return found
        if (found is None or found.origin is None or not found.origin.endswith('.py')
                or not Path(found.origin).resolve().is_relative_to(root)):
            raise ModuleNotFoundError('Module absent from its accepted frozen source root: '+fullname)
        found.loader = RawSourceLoader(fullname, found.origin)
        return found


def configure_case(spec, case):
    """Pin source bytes and isolate imports before any task/harness import."""
    recipe_check(case)
    for row in spec['case_dependencies'][case['id']] + spec['shared_inputs']:
        checked(row)
    assets = load(checked(spec['external_assets']))
    external = Path(assets['source_root']).resolve()
    for name, row in assets['files'].items():
        checked({'path': str(external/name), 'sha256': row['sha256']})
    root = Path(case['root']).resolve()
    # -I omits mutable cwd/PYTHONPATH; prepend only these accepted roots.
    excluded = {Path(spec['project_root']).resolve(), Path(spec['original_external_root']).resolve()}
    sys.path[:] = [str(root), str(external)] + [p for p in sys.path
        if Path(p or '.').resolve() not in excluded | {root, external}]
    sys.meta_path.insert(0, FrozenSourceFinder({**{p: root for p in
        ('scripts', 'intent_browser', 'experiments', 'environments')}, 'agent_trace': external}))
    os.environ['HARNESS_AX_TOKENIZER'] = str(checked(spec['tokenizer']))
    # Website-world loaders follow the case binding; historical frozen roots
    # keep exact source pins.
    os.environ['WEBSITE_WORLD_SOURCE_BINDING'] = 'current' if current_binding(case) else 'pinned'
    sys.dont_write_bytecode = True
    module = importlib.import_module(case['callable']['module'])
    function = getattr(module, case['callable'].get('symbol', 'run'))
    if not Path(module.__file__).resolve().is_relative_to(root):
        raise ValueError('Task callable imported outside its accepted source root')
    if 'source' in case['callable'] and not current_binding(case):
        checked(case['callable']['source'])
    return function


def load_transport(spec):
    dependency = spec['transport']
    for row in dependency['files']:
        checked(row)
    package = types.ModuleType('_luna_transport')
    package.__path__ = [dependency['directory']]
    sys.modules[package.__name__] = package
    sys.meta_path.insert(0, FrozenSourceFinder({'_luna_transport': Path(dependency['directory']).resolve()}))
    backend = importlib.import_module('_luna_transport.backend')
    server = importlib.import_module('_luna_transport.server')
    admission = importlib.import_module('_luna_transport.episode_admission')
    quota = importlib.import_module('_luna_transport.subscription_quota')
    transport_origins(spec)
    return (backend.ExternalAgentBackend, server.BridgeServer, admission.EpisodeConcurrency,
            admission.SuiteEpisode, quota.SubscriptionQuotaGuard, quota._read, quota.snapshot)


def transport_origins(spec):
    dependency = spec['transport']
    directory = Path(dependency['directory']).resolve()
    declared = {checked(row).resolve(): row for row in dependency['files']}
    canonical = Path(spec['project_root'])/'.local/external-agent/subscription.lock'
    if Path(dependency['subscription_lock']).absolute() != canonical.absolute():
        raise ValueError('Require the canonical shared subscription lock')
    for name, module in list(sys.modules.items()):
        if name.startswith('_luna_transport.'):
            path = Path(module.__file__).resolve()
            if not path.is_relative_to(directory) or path not in declared:
                raise ValueError('Unbound transport module: '+name)


def module_origins(spec, case):
    root = Path(case['root']).resolve()
    external = Path(load(checked(spec['external_assets']))['source_root']).resolve()
    for name, module in list(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path is None:
            continue
        prefix = name.split('.')[0]
        allowed = external if prefix == 'agent_trace' else root
        if prefix in ('scripts', 'environments', 'experiments', 'intent_browser', 'agent_trace'):
            if not Path(path).resolve().is_relative_to(allowed):
                raise ValueError('Mutable source entered accepted case: '+name)


def policy_profile(original, *, discovery):
    """Disable optional compute/helpers while retaining task-required channels."""
    from dataclasses import replace
    from intent_browser.standard_profile import standard_profile
    fresh = standard_profile(navigation_origins=original.tools.navigation_origins,
                             helpers=False, data_tools=False)
    if discovery or getattr(original.tools, 'site_discovery_tools', False):
        from intent_browser.harness import with_site_discovery
        fresh = with_site_discovery(fresh)
    if getattr(original.tools, 'clarification_tools', False):
        from intent_browser.harness import with_clarification
        fresh = with_clarification(fresh)
    # Keep consumer-owned observation/conversation/capture configuration. Reject
    # any unhandled required tool instead of silently removing its channel.
    optional = {'spawn_agent', 'get_agent', 'wait_agent', 'cancel_agent',
                'extract_page', 'run_python', 'script_file'}
    if set(original.describe()['tools']) - optional != set(fresh.describe()['tools']):
        raise ValueError('Cannot preserve task-required channels in Luna profile')
    return replace(original, name=fresh.name, tools=fresh.tools, data_config=None,
                   agent_limits=None, instructions=fresh.instructions)


def require_quota_windows(result, normalizer):
    """Use the reviewed transport's complete nullable-window contract."""
    normalizer(result, require_complete_windows=True)
    return result


def client_timeout(admission):
    wait = admission['admission_wait_seconds']
    if type(wait) is not int or not 0 < wait < LIMITS['whole_episode_timeout_seconds'] - 190:
        raise ValueError('Missing or invalid reviewed admission-wait bound')
    cleanup = admission.get('admission_lock_wait_seconds', wait - 50)
    if type(cleanup) is not int or cleanup < 0 or wait + 190 + cleanup >= 10800:
        raise ValueError('Invalid admission cleanup allowance')
    return wait + 190 + cleanup  # Include failed-request phase cleanup, separately from provider180.


def case_options(case, extraction):
    options = dict(case['callable'].get('required_kwargs', {}))
    if case['id'] not in ('H01', 'H02', 'B17', 'B19'):
        options['extraction_backend_factory'] = extraction
    return options


def interface_check(spec, case, run):
    from intent_browser.backend import ChatCompletionsBackend
    from intent_browser.input_budget import OpaqueReasoningInputCounter, QwenInputCounter
    from intent_browser.standard_profile import standard_profile
    from intent_browser.runner import run_episode
    options = dict(policy_session=lambda **k: None, metadata={},
        runner_options={}, viewer_projection=lambda **k: None,
        quota_guard=lambda: None, runner=lambda **k: None,
        **case_options(case, lambda path: None))
    inspect.signature(run).bind(case['argument'], '/source-check/no-execution', **options)
    if case['id'] in ('B17', 'B19'):
        delegated = importlib.import_module('environments.website_world.task_instance_cart')
        inspect.signature(delegated.run).bind(case['recipe'], '/source-check/no-execution', **options)
    base = standard_profile(helpers=False, data_tools=False)
    if case['id'] == 'B08':
        from intent_browser.harness import with_clarification
        base = with_clarification(base)
    policy_profile(base, discovery=False)
    OpaqueReasoningInputCounter(QwenInputCounter(checked(spec['tokenizer'])))
    if 'transport' in spec:
        *_, normalize = load_transport(spec)
        inspect.signature(normalize).bind({}, require_complete_windows=True)
    module_origins(spec, case)


def suite_preflight(spec):
    """Validate every real interface in isolated processes before once-only claims."""
    def check(case):
        result = subprocess.run([spec['python'], '-I', '-B', spec['driver']['path'],
            'check', spec['spec_path'], case['id']], capture_output=True, text=True, timeout=180,
            env={**os.environ, 'LD_LIBRARY_PATH':spec['library_path'], 'PYTHONDONTWRITEBYTECODE':'1'})
        return {'case':case['id'], 'exit_code':result.returncode,
                'stdout':result.stdout, 'stderr':result.stderr}
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(check, spec['cases']))
    save(Path(spec['output'])/'interface-preflight.json', {'driver':spec['driver'], 'cases':rows})
    if any(row['exit_code'] for row in rows):
        raise ValueError('Suite interface preflight failed; no episode has been claimed')


def launch_configuration_sha256(spec):
    # Review evidence is attached after the configuration is reviewed; excluding
    # only these proof pointers avoids a circular hash while binding all launch inputs.
    configuration = {key:value for key,value in spec.items() if key not in ('review','review_acceptance')}
    return sha256(json.dumps(configuration,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_review(spec):
    if checked(spec['driver']).resolve() != Path(__file__).resolve():
        raise ValueError('Require the exact reviewed execution driver')
    approval = load(checked(spec['review_acceptance']))
    if (approval.get('status') != 'reviewed_ready' or approval.get('driver') != spec['driver']
            or approval.get('review') != spec['review'] or approval.get('commit') != spec['caller_commit']
            or approval.get('launch_configuration_sha256') != launch_configuration_sha256(spec)):
        raise ValueError('Independent review is not bound to the exact executed driver and launch configuration')
    checked(spec['review']); checked(spec['launcher_python'])
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != spec['caller_commit']:
        raise ValueError('Execution root differs from the reviewed caller commit')
    committed = subprocess.check_output(['git','-C',str(root),'show',commit+':scripts/luna_suite.py'])
    if sha256(committed).hexdigest() != spec['driver']['sha256']:
        raise ValueError('Executed driver differs from its committed blob')


def process_identity(pid):
    text = Path('/proc', str(pid), 'stat').read_text()
    # Process comm can contain spaces and parentheses; fields after the final )
    # begin at field3. Start time is field22, state at field3.
    tail = text.rsplit(')',1)[1].split()
    if tail[0] == 'Z':
        raise ProcessLookupError('Supervisor is a zombie')
    return tail[19]


def dispatch_authority(spec):
    authority = load(Path(spec['output'])/'supervisor-start.json')
    if (process_identity(authority['pid']) != authority['process_start']
            or time.monotonic() >= authority['deadline_monotonic']):
        raise RuntimeError('Supervisor lost or authorized lifetime exhausted; no dispatch')
    return authority


def own_scope():
    line = next(line for line in Path('/proc/self/cgroup').read_text().splitlines()
                if line.startswith('0::'))
    group = Path('/sys/fs/cgroup')/line[3:].lstrip('/')
    if group.parent.name != 'llmjobs.slice' or not re.fullmatch(r'llmjob-[0-9a-f]+\.scope', group.name):
        raise RuntimeError('Refuse cleanup outside the case-owned bounded scope')
    return group


def kill_own_scope():
    group = own_scope()
    try:
        try:
            (group/'cgroup.kill').write_text('1')
        except OSError:
            subprocess.run(['systemctl','--user','kill','--kill-who=all','--signal=SIGKILL',group.name],
                           check=True, timeout=10)
    finally:
        # Even a failed manager fallback must end the root process so that its
        # bounded launcher performs process-tree cleanup, not leave a dead watchdog.
        os._exit(124)


def start_watchdog(spec, output):
    own_scope()  # Fail before any dispatch if cleanup cannot identify the bounded case tree.
    authority = load(Path(spec['output'])/'supervisor-start.json')
    stop = threading.Event()
    def watch():
        while not stop.wait(1):
            try:
                alive = process_identity(authority['pid']) == authority['process_start']
            except OSError:
                alive = False
            reason = ('supervisor_lost' if not alive else 'episode_lifetime' if
                time.monotonic() >= authority['deadline_monotonic'] else None)
            if reason:
                try:
                    save(output/'watchdog-stop.json', {'reason':reason, 'automatic_retries':0,
                        'epoch':time.time(), 'task_verdict':None})
                finally:
                    kill_own_scope()
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return stop, thread


def register_roots(spec):
    registry = Path(spec['registry'])
    with registry.with_suffix('.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        data = load(registry)
        for case in spec['cases']:
            root = str(Path(spec['output'])/case['id']/'live/runs')
            if root not in data['roots']:
                data['roots'].append(root)
        temporary = registry.with_name(registry.name+'.'+uuid.uuid4().hex+'.tmp')
        save(temporary, data)
        os.replace(temporary, registry)


def verify_projection(spec, trace):
    """Read canonical/native/HTTP evidence without rewriting saved recordings."""
    trace = Path(trace).resolve()
    canonical = load(trace/'evaluation.json')
    declaration = load(trace/'automatic-grading.json')
    if declaration['status'] != 'graded' or canonical.get('technical_error') is not None:
        raise ValueError('Automatic canonical grade is incomplete')
    from scripts.trace_grades import read_grade
    derived = read_grade(trace)
    if (not derived or derived.get('binding_status') != 'verified'
            or derived.get('structured_claims_correct') is not canonical['task_completed']):
        raise ValueError('Native/canonical/sidecar grade disagreement')
    ident = sha256(('browsergym:' + trace.name).encode()).hexdigest()[:20]
    with urlopen(spec['viewer_url']+'/api/sessions', timeout=30) as response:
        response.read()
    with urlopen(spec['viewer_url']+'/api/sessions/'+ident, timeout=30) as response:
        body = json.loads(response.read())
    if body.get('id') != ident or body.get('derived_evaluation') != derived:
        raise ValueError('Current HTTP viewer omits or changes the native grade')
    return {'status': 'verified', 'url': spec['viewer_url']+'/#'+ident,
        'trace_id': ident, 'task_completed': canonical['task_completed'],
        'automatic': pin(trace/'automatic-grading.json'), 'canonical': pin(trace/'evaluation.json')}


def project(spec, output, case, *, trace, grade):
    trace = Path(trace).resolve()
    run_root = (output/'live/runs').resolve()
    if trace == run_root or not trace.is_relative_to(run_root):
        raise ValueError('Returned trace escaped registered run root')
    if case['id'] in ('H01', 'H02'):
        from scripts.simulated_order_address_trace_grades import publish
        return publish(trace=trace, grade=grade, registry=spec['registry'],
            viewer_url=spec['viewer_url'], expected_run_root=run_root)
    result = verify_projection(spec, trace)
    save(output/'grade-viewer-acceptance.json', result)
    return result


def close_session(raw, server, thread, backend):
    errors = []
    for fn in (lambda: backend.close() if backend else None,
               lambda: server.shutdown() if thread and thread.ident is not None else None,
               lambda: server.server_close() if server else None,
               lambda: thread.join(timeout=10) if thread and thread.ident is not None else None,
               lambda: raw.close() if raw else None):
        try:
            fn()
        except BaseException as error:
            errors.append(error)
    if thread and thread.is_alive():
        errors.append(RuntimeError('Bridge thread cleanup incomplete'))
    if errors:
        original = sys.exception()
        raise BaseExceptionGroup('Policy/transport cleanup failures',
            ([original] if original else []) + errors)


def execute_case(spec, case, *, check_only=False):
    run = configure_case(spec, case)
    interface_check(spec, case, run)
    if check_only:
        return {'case': case['id'], 'status': 'accepted_sources_imported',
                'callable': case['callable']['module'], 'model_dispatches': 0}
    output = Path(spec['output'])/case['id']
    from intent_browser.backend import ChatCompletionsBackend
    from intent_browser.input_budget import OpaqueReasoningInputCounter, QwenInputCounter
    (ExternalAgentBackend, BridgeServer, EpisodeConcurrency, SuiteEpisode,
     SubscriptionQuotaGuard, _read, normalize_quota) = load_transport(spec)
    def read_quota():
        import asyncio
        with ThreadPoolExecutor(max_workers=1) as pool:
            return require_quota_windows(pool.submit(lambda: asyncio.run(_read())).result(), normalize_quota)
    quota = SubscriptionQuotaGuard(output/'subscription-quota', remaining_floor=1, reader=read_quota)
    def source_guard():
        dispatch_authority(spec)
        checked(spec['authorization'])
        checked(spec['driver']); checked(spec['bridge_worker']); checked(spec['pi'])
        module_origins(spec, case)
        transport_origins(spec)
        for row in spec['transport']['files']:
            checked(row)
        for row in spec['case_dependencies'][case['id']] + spec['shared_inputs']:
            checked(row)
    lease = SuiteEpisode(EpisodeConcurrency(spec['suite_id'], 34, 34),
        Path(spec['transport']['subscription_lock']), quota, model='gpt-6-luna',
        reasoning_effort='medium', formatter_reasoning_effort='low', provider_output_limit=True)
    http_timeout = None
    def external(path, effort, before_dispatch):
        return ExternalAgentBackend('gpt-6-luna', path, reasoning_effort=effort,
            timeout=180, max_tokens=16384, provider_output_limit=True,
            command=[str(checked(spec['node'])), str(checked(spec['bridge_worker']))],
            pi_cli=str(checked(spec['pi'])), before_dispatch=before_dispatch,
            suite_episode=lease, episode_phase='policy' if effort == 'medium' else 'formatter')
    @contextmanager
    def session(*, before_dispatch):
        raw = server = thread = backend = None
        def guard():
            before_dispatch()
            progress(output, 'environment_live', role='policy')
        try:
            raw = external(output/'policy-transport', 'medium', guard)
            raw.begin_episode(spec['suite_id']+'/'+case['id']+'/'+uuid.uuid4().hex)
            token = uuid.uuid4().hex + uuid.uuid4().hex
            server = BridgeServer(raw, token, max_requests=200)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            backend = ChatCompletionsBackend('http://127.0.0.1:'+str(server.server_port)+'/v1',
                'gpt-6-luna', token, timeout=http_timeout, max_tokens=16384, supports_images=True)
            yield backend
        finally:
            close_session(raw, server, thread, backend)
            progress(output, 'policy_closed')
    def extraction(path):
        source_guard()
        raw = external(path, 'low', source_guard)
        try:
            raw.begin_episode(spec['suite_id']+'/'+case['id']+'/formatter/'+uuid.uuid4().hex)
        except BaseException:
            raw.close()
            raise
        return raw
    def runner(*args, **kwargs):
        from intent_browser.runner import run_episode
        if kwargs.get('automatic_grading') is None:
            raise ValueError('No model dispatch without attached automatic grading')
        task = kwargs['episode_task']
        for row in [spec['driver'], spec['authorization'], spec['bridge_worker'], spec['node'],
                    spec['pi'], *spec['transport']['files']]:
            task.files[str(checked(row))] = row['sha256']
        public = task.public
        if public['user_message'] != case['public_request']:
            raise ValueError('Actual rendered public request differs from authorized prose')
        kwargs['harness_profile'] = policy_profile(kwargs['harness_profile'],
            discovery=kwargs.get('site_discovery') is not None)
        if 'site_discovery' not in inspect.signature(run_episode).parameters:
            if kwargs.pop('site_discovery', None) is not None:
                raise ValueError('Accepted runner lacks required discovery support')
        kwargs['input_counter'] = OpaqueReasoningInputCounter(QwenInputCounter(checked(spec['tokenizer'])))
        kwargs['retry_policy'] = None
        progress(output, 'runner_starting')
        return run_episode(*args, **kwargs)
    options = case_options(case, extraction)
    try:
        admission = lease.begin_episode(case['id'])
        if admission['subscription_lock'] != spec['transport']['subscription_lock']:
            raise ValueError('Case admission returned a different subscription lock')
        http_timeout = client_timeout(admission)
        save(output/'admission.json', {**admission, 'provider_timeout_seconds': 180,
                                      'http_timeout_seconds': http_timeout})
        result = run(case['argument'], output/'live', policy_session=session,
            metadata={'trace_title': 'Luna — '+case['id'], 'source': spec['suite_id'],
                'model': 'gpt-6-luna', 'driver': 'llm', 'training_eligible': False,
                'tags': ['luna34', 'model', case['id']]},
            runner_options={'max_steps': 200, 'max_input_tokens': 120000,
                            'trace_screenshots': True, 'async_recording': True},
            viewer_projection=lambda **values: project(spec, output, case, **values),
            quota_guard=source_guard, runner=runner, **options)
        result.update(automatic_grading=result.get('status') == 'graded_and_projected',
            billing='subscription_only', paid_fallback=False, input_measurement=COUNT_SCOPE,
            automatic_retries=0, training_eligible=False,
            tools_qualification={'helpers':False,'data_tools':False,
                'clarification':'retained_when_task_required','reason':'No qualified Python sandbox for this suite'})
        if result.get('status') != 'graded_and_projected':
            save(output/'result.json', result)
            raise RuntimeError('Automatic grading/HTTP incomplete: '+result.get('reason', ''))
        canonical = load(Path(result['trace'])/'evaluation.json')
        result['task_verdict'] = {True:'pass', False:'fail', None:'inconclusive'}[canonical['task_completed']]
        save(output/'result.json', result)
        progress(output, 'graded_and_projected', task_verdict=result['task_verdict'])
        return result
    except BaseException as error:
        save(output/'failure.json', {'type': type(error).__name__, 'reason': str(error),
            'automatic_retries': 0, 'task_verdict': None, 'world_draws': 0})
        progress(output, 'infrastructure_failure')
        raise
    finally:
        lease.close()


def resource_sample(spec):
    states, groups = {}, []
    for case in spec['cases']:
        output = Path(spec['output'])/case['id']
        try:
            states[case['id']] = load(output/'capacity-state.json')['stage']
        except (OSError, ValueError, KeyError):
            states[case['id']] = 'not_observed'
        try:
            group = Path(load(output/'bounded/entry.json')['cgroup'])
            row = {'case': case['id']}
            for name in ('memory.current', 'memory.events', 'pids.current', 'pids.events', 'cpu.stat'):
                row[name] = (group/name).read_text().strip()
            processes = (group/'cgroup.procs').read_text().split()
            row['process_count'] = len(processes)
            rss = 0
            for pid in processes:
                try:
                    status = Path('/proc', pid, 'status').read_text().splitlines()
                    rss += sum(int(line.split()[1])*1024 for line in status if line.startswith('VmRSS:'))
                except (OSError, ValueError):
                    pass  # Processes can exit between cgroup and /proc reads.
            row['summed_rss_bytes_including_shared_pages'] = rss
            groups.append(row)
        except (OSError, ValueError, KeyError):
            pass
    live = {r['case'] for r in groups if r['process_count'] > 0}
    return {'epoch': time.time(), 'states': states, 'live_environment_count':
            sum(s == 'environment_live' and c in live for c,s in states.items()), 'groups': groups}


def shared_memory_events():
    try:
        counters = {k:int(v) for k,v in (line.split() for line in
            (own_scope().parent/'memory.events').read_text().splitlines())}
        return {**counters, '_available': True}
    except (OSError, ValueError, RuntimeError, StopIteration) as error:
        return {'_available': False, '_error': str(error)}


def stop_classification(code, bounded, watchdog, *, interrupted, timeout, baseline, current):
    """A sampled-zero cgroup counter is not evidence of no OOM kill."""
    result = {'capacity_failure':None, 'kill_reason':None}
    if code == 0:
        return result  # A later suite signal cannot undo a completed graded case.
    if watchdog:
        result['kill_reason'] = watchdog['reason']
    elif timeout:
        result['kill_reason'] = 'episode_lifetime'
    elif interrupted:
        result['kill_reason'] = 'suite_interrupt'
    elif code == 125:
        result['capacity_failure'] = 'launcher_refusal'
    elif bounded.get('last_observed',{}).get('job',{}).get('memory.events',{}).get('oom_kill',0):
        result.update(capacity_failure='memory_oom',kill_reason='observed_job_oom')
    elif code in (-9,137) or bounded.get('returncode') == -9:
        delta = max(0,current.get('oom_kill',0)-baseline.get('oom_kill',0))
        result.update(kill_reason='sigkill', shared_oom_kill_delta=delta,
            shared_oom_counters_available=baseline.get('_available',True) and current.get('_available',True),
            capacity_failure='possible_memory_oom' if delta else None,
            attribution='Shared OOM delta corroborates a capacity problem but cannot uniquely attribute this kill.'
                if delta else 'SIGKILL cause is unknown; sampled zero does not exclude OOM.')
    return result


def supervise(spec, *, popen=subprocess.Popen, deliver=None):
    """Thirty-four independent bounded trees, once each; no implicit retry."""
    own_scope()  # Enforce bounded execution before registration or once-only claims.
    authorization = load(checked(spec['authorization']))
    validate_request(authorization)
    validate_cases(spec)
    if tuple(c['id'] for c in spec['cases']) != CASE_IDS or spec.get('status') != 'ready':
        raise ValueError('Exact reviewed ready34 launch required')
    validate_review(spec)
    suite_preflight(spec)
    api = runpy.run_path(str(checked(spec['events_helper'])))
    events = api['Events'](Path(spec['output'])/'completion.sqlite')
    events.register(spec['suite_id'], list(CASE_IDS))
    recipient = 'codex:'+spec['thread_id']
    for case in CASE_IDS:
        events.subscribe('evaluation-'+case, spec['suite_id'], recipient, episode=case, final=False)
    events.subscribe('evaluation-suite', spec['suite_id'], recipient,
                     milestones=[10, 20, 30, 34], final=True)
    register_roots(spec)
    with urlopen(spec['viewer_url']+'/', timeout=15) as response:
        if response.status != 200:
            raise ValueError('Current viewer unavailable before dispatch')
    save(Path(spec['output'])/'supervisor-start.json', {'epoch': time.time(), 'target_concurrency': 34,
        'automatic_retries': 0, 'authorization': spec['authorization'], 'driver': spec['driver'],
        'spec': pin(spec['spec_path']), 'pid':os.getpid(), 'process_start':process_identity(os.getpid()),
        'deadline_monotonic':time.monotonic()+LIMITS['whole_episode_timeout_seconds']})
    stop = threading.Event()
    children, lock, prior = {}, threading.RLock(), {}
    def interrupt(signum, _):
        if stop.is_set():
            return
        stop.set()
        with lock:
            for child in children.values():
                if child.poll() is None:
                    child.send_signal(signal.SIGTERM)
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        prior[signum] = signal.signal(signum, interrupt)
    def sample():
        with (Path(spec['output'])/'capacity.jsonl').open('x') as stream:
            while not stop.is_set():
                stream.write(json.dumps(resource_sample(spec))+'\n'); stream.flush()
                stop.wait(2)
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    deliver = deliver or api['flush']
    def job(case):
        output = Path(spec['output'])/case['id']
        output.mkdir(exist_ok=False)
        events.start(spec['suite_id'], case['id'])
        child = None
        error, code = None, -1
        timed_out = False
        baseline = shared_memory_events()
        command = [spec['launcher_python']['path'], checked(spec['launcher']).as_posix(), '--memory-mib', '2048',
            '--tasks', '512', '--receipt', str(output/'bounded'), '--',
            spec['python'], '-I', '-B', spec['driver']['path'], 'case', spec['spec_path'], case['id']]
        try:
            with (output/'supervisor.log').open('x') as stream:
                with lock:
                    if stop.is_set():
                        raise InterruptedError('Suite interrupted before process creation')
                    child = popen(command, cwd=spec['project_root'], stdout=stream, stderr=subprocess.STDOUT,
                        env={**os.environ, 'LD_LIBRARY_PATH': spec['library_path'],
                             'PYTHONDONTWRITEBYTECODE': '1'})
                    children[case['id']] = child
                try:
                    code = child.wait(timeout=10800)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    error = 'Authorized whole-episode10800-second timeout'
                    child.send_signal(signal.SIGTERM)
                    code = child.wait(timeout=30)
        except Exception as exc:
            error = str(exc)
            if child is not None and child.poll() is None:
                child.send_signal(signal.SIGTERM)
                child.wait(timeout=30)  # Never report terminal while launcher cleanup is unresolved.
        finally:
            with lock:
                children.pop(case['id'], None)
        evidence = {'exit_code': code, 'error': error, 'automatic_retries': 0,
                    'task_verdict': None, 'recipe_manifest': case['recipe_manifest']}
        for name in ('result.json', 'failure.json', 'bounded/result.json', 'watchdog-stop.json'):
            if (output/name).is_file():
                evidence[name] = pin(output/name)
        if (output/'result.json').is_file():
            result = load(output/'result.json')
            evidence.update(trace=result.get('trace'), task_verdict=result.get('task_verdict'))
            if code == 0 and (result.get('status') != 'graded_and_projected'
                              or result.get('automatic_grading') is not True):
                error = 'System failure: no automatic native/canonical/HTTP grade'
        elif code == 0:
            error = 'System failure: missing graded result'
        if (output/'failure.json').is_file():
            failure = load(output/'failure.json')
            evidence['failure'] = failure
            error = error or failure.get('reason')
        bounded = load(output/'bounded/result.json') if (output/'bounded/result.json').is_file() else {}
        watchdog = load(output/'watchdog-stop.json') if (output/'watchdog-stop.json').is_file() else None
        evidence.update(stop_classification(code, bounded, watchdog, interrupted=stop.is_set(),
            timeout=timed_out, baseline=baseline, current=shared_memory_events()))
        if evidence['capacity_failure'] or evidence['kill_reason']:
            error = error or 'Infrastructure stop: '+str(evidence['kill_reason'] or evidence['capacity_failure'])
            evidence['task_verdict'] = None
        evidence['error'] = error
        state = 'succeeded' if code == 0 and not error else 'interrupted' if stop.is_set() else 'failed'
        events.finish(spec['suite_id'], case['id'], state, evidence)
        deliver(events)
        return evidence
    unresolved = []
    try:
        with ThreadPoolExecutor(max_workers=34) as pool:
            futures = {pool.submit(job, c): c['id'] for c in spec['cases']}
            for future in as_completed(futures):
                try:
                    future.result()
                except BaseException as error:
                    unresolved.append({'case': futures[future], 'error': str(error)})
        stop.set(); sampler.join(timeout=10)
        if sampler.is_alive():
            raise RuntimeError('Capacity sampler did not stop')
        samples = [json.loads(line) for line in (Path(spec['output'])/'capacity.jsonl').read_text().splitlines()]
        save(Path(spec['output'])/'supervisor-terminal.json', {
            'status': 'unresolved_cleanup' if unresolved else 'terminal', 'unresolved': unresolved,
            'episodes': events.snapshot()['episodes'], 'target_concurrency': 34,
            'observed_peak_live_environments':max((s['live_environment_count'] for s in samples),default=0),
            'capacity_stops_total':sum(bool(r.get('payload',{}).get('capacity_failure'))
                for r in events.snapshot()['episodes']),
            'capacity_stop_counts':{kind:sum(r.get('payload',{}).get('capacity_failure') == kind
                for r in events.snapshot()['episodes'])
                for kind in ('memory_oom','possible_memory_oom','launcher_refusal')},
            'unattributed_sigkills':sum(r.get('payload',{}).get('kill_reason')=='sigkill' and
                not r.get('payload',{}).get('capacity_failure') for r in events.snapshot()['episodes']),
            'measurement':'Observed policy-ready processes at2s intervals; lower bound, startup excluded'})
        if unresolved:
            raise RuntimeError('Unresolved cleanup retained; no automatic retry')
    finally:
        stop.set(); sampler.join(timeout=10)
        for signum, previous in prior.items():
            signal.signal(signum, previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['check', 'case', 'launch'])
    parser.add_argument('spec', type=Path)
    parser.add_argument('case', nargs='?')
    args = parser.parse_args()
    spec = load(args.spec)
    validate_request(load(checked(spec['authorization'])))
    if args.mode == 'launch':
        supervise(spec)
    else:
        case = next(c for c in spec['cases'] if c['id'] == args.case)
        if args.mode == 'case':
            validate_cases(spec)
            if spec.get('status') != 'ready' or checked(spec['driver']) != Path(__file__):
                raise ValueError('Exact reviewed ready caller required')
            validate_review(spec)
            original = load(Path(spec['output'])/'supervisor-start.json')['spec']
            if original != pin(args.spec):
                raise ValueError('Launch specification changed after supervisor admission')
            helper = runpy.run_path(str(checked(spec['events_helper'])))
            snapshot = helper['Events'](Path(spec['output'])/'completion.sqlite').snapshot()
            if next(r['state'] for r in snapshot['episodes']
                    if r['suite'] == spec['suite_id'] and r['id'] == case['id']) != 'running':
                raise ValueError('Require supervisor once-only claim before model dispatch')
            stop, watcher = start_watchdog(spec, Path(spec['output'])/case['id'])
        try:
            result = execute_case(spec, case, check_only=args.mode == 'check')
        finally:
            if args.mode == 'case':
                stop.set(); watcher.join(timeout=5)
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
