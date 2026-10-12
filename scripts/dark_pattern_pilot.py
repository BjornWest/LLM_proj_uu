"""Once-only newsletter model pilot with native grading and completion subscriptions."""
from pathlib import Path
from hashlib import sha256
import argparse
import fcntl
import json
import os
import runpy
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor

PROJECT = Path('/home/bjorn/code/LLM_proj_uu')
ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return json.loads(Path(path).read_bytes())

def pin(path):
    path = Path(path).resolve(strict=True)
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}

def checked(row):
    if pin(row['path']) != row:
        raise ValueError('Changed input: ' + row['path'])
    return Path(row['path'])

def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic publication, retaining exclusive-create semantics.
    finally:
        temporary.unlink(missing_ok=True)

def guard(config):
    if (config['model'] != 'gpt-6.1-sol' or config['max_steps'] != 40
            or config['max_input_tokens'] != 100000 or config['subscription_floor'] != 1
            or config['automatic_retries'] != 0 or config['helpers'] is not False
            or config['reasoning_effort'] != 'high' or config['provider_output_limit'] is not True
            or Path(config['root']).resolve() != ROOT):
        raise ValueError('Only the authorized single pilot is allowed')
    candidate = read(checked(config['candidate']))
    for name, row in candidate['inventory'].items():
        checked({'path': str(ROOT / name), 'sha256': row['sha256']})
    if subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).decode().strip() != candidate['commit']:
        raise ValueError('Evaluation HEAD changed')
    for name in ('instance', 'events', 'tokenizer', 'node', 'pi'):
        checked(config[name])
    for row in config['external_sources']:
        checked(row)
    return candidate

def require_review(config):
    release = read(config['review_release_path'])
    if (release.get('status') != 'approved'
            or release.get('commit') != read(checked(config['candidate']))['commit']
            or release.get('config') != pin(config['_path'])):
        raise ValueError('Exact independent reviewed composition required')
    checked(release['report'])
    return release

def configure(config):
    guard(config)
    sys.dont_write_bytecode = True
    external = Path(config['external_root']).resolve()
    sys.path[:] = [str(ROOT), str(external)] + [p for p in sys.path
        if Path(p or '.').resolve() not in {PROJECT, ROOT, external}]
    os.environ['HARNESS_AX_TOKENIZER'] = str(checked(config['tokenizer']))
    os.environ['LD_LIBRARY_PATH'] = config['library_path']
    # This standalone caller uses the native task's capture, not a second recorder.
    os.environ['HARNESS_ENV_STEP_TELEMETRY'] = '0'

def imported_sources(config):
    external = Path(config['external_root']).resolve()
    for name, module in list(sys.modules.items()):
        if name.split('.')[0] in {'intent_browser', 'environments', 'experiments', 'scripts'}:
            location = getattr(module, '__file__', None)
            if location and not Path(location).resolve().is_relative_to(ROOT):
                raise ValueError('Mutable project import: ' + name)
        if name.split('.')[0] == 'agent_trace':
            location = getattr(module, '__file__', None)
            if location and not Path(location).resolve().is_relative_to(external):
                raise ValueError('Unqualified trace import: ' + name)

def prepared(config, case):
    from environments.commerce_scenarios.publication import prepare_episode
    value = prepare_episode(config['world'], checked(config['instance']), case,
                            offer_id=config['offer_id'], headless=True, lazy_publication=True)
    # Helpers and executable data tools are outside this finite pilot profile.
    from intent_browser.standard_profile import standard_profile
    value.episode.profile = standard_profile(navigation_origins=value.episode.runtime.navigation_origins,
                                             helpers=False, data_tools=False)
    if value.episode.site_discovery is not None:
        from intent_browser.harness import with_site_discovery
        value.episode.profile = with_site_discovery(value.episode.profile)
    imported_sources(config)
    return value

def http_json(url):
    with urlopen(url, timeout=30) as response:
        if response.status != 200:
            raise ValueError('Viewer HTTP unavailable')
        return json.load(response)

def register_root(config, root):
    registry = Path(config['viewer_registry'])
    with registry.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read(registry)
        root = str(Path(root).resolve())
        if root not in data['roots']:
            data['roots'].append(root)
            temporary = registry.with_name(registry.name + '.' + uuid.uuid4().hex + '.tmp')
            save(temporary, data)
            os.replace(temporary, registry)

def publish(config, trace):
    from scripts.trace_grades import read_grade
    trace = Path(trace).resolve(strict=True)
    grade = read_grade(trace)
    declaration = read(trace / 'automatic-grading.json')
    if (grade is None or grade.get('binding_status') != 'verified'
            or declaration.get('status') != 'graded'):
        raise ValueError('Missing automatic grade/viewer projection')
    register_root(config, trace.parent)
    trace_id = sha256(('browsergym:' + trace.name).encode()).hexdigest()[:20]
    detail = http_json(config['viewer_url'] + '/api/sessions/' + trace_id)
    if detail.get('derived_evaluation') != grade:
        raise ValueError('Live HTTP grade disagrees with native reader')
    return {'url': config['viewer_url'] + '/#' + trace_id, 'grade': grade,
            'task_verdict': read(trace / 'automatic-grade.json')['raw_grade']['status']}

def control(config, case):
    configure(config)
    output = Path(config['output']) / ('control-' + case)
    output.mkdir(exist_ok=False)
    from environments.commerce_scenarios.publication import run_saved
    value = prepared(config, case)
    result = run_saved(value, output / 'runs', max_steps=40, max_input_tokens=100000)
    projection = publish(config, result['trace'])
    if not result['publication']['control_matches_expectation']:
        raise ValueError('Control outcome mismatch')
    guard(config)
    save(output / 'result.json', {'result': result, 'http_projection': projection,
                                 'provider_requests': 0, 'world_draws': 0})

def readiness(config):
    output = Path(config['output'])
    output.mkdir(exist_ok=False)
    def run_control(case):
        # Three simultaneous Chromium startups reached the measured 512-PID cap.
        # Keep independent sessions, with two controls active at a time.
        with (output / (case + '.log')).open('x') as log:
            command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                       '--config', config['_path'], '--mode', 'control', '--case', case]
            job = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            try:
                return case, job.wait(timeout=180)
            finally:
                if job.poll() is None:
                    job.terminate()
                    try:
                        job.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        job.kill()
                        job.wait()
    with ThreadPoolExecutor(max_workers=2) as pool:
        failures = [case for case, code in pool.map(run_control, ('positive', 'wrong', 'incomplete')) if code != 0]
    if failures:
        raise ValueError('Readiness control failures: ' + str(failures))
    guard(config)
    configure(config)
    from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
    quota = SubscriptionQuotaGuard(output / 'readiness-quota', remaining_floor=1)
    quota(require_complete_windows=True)
    worker = ROOT / 'experiments/external_agent/worker.mjs'
    envelope = {'version': 1, 'id': 'newsletter-model-readiness', 'payload': None,
                'artifact_dir': str(output), 'pi_cli': str(checked(config['pi'])), 'timeout_ms': 5000}
    inspected = subprocess.run([str(checked(config['node'])), str(worker)],
        input=json.dumps(envelope), text=True, capture_output=True, timeout=15, check=True)
    catalog = json.loads(inspected.stdout)
    if config['model'] not in catalog['models']:
        raise ValueError('Requested model descriptor unavailable')
    save(output / 'readiness.json', {'status': 'passed', 'config': pin(config['_path']),
         'candidate': config['candidate'], 'controls': [pin(output / ('control-' + c) / 'result.json')
         for c in ('positive', 'wrong', 'incomplete')], 'model_catalog': catalog,
         'provider_requests': 0, 'world_draws': 0})

def model(config):
    configure(config)
    output = Path(config['output']) / 'model'
    ready = read(Path(config['output']) / 'readiness.json')
    if ready['status'] != 'passed' or ready['config'] != pin(config['_path']):
        raise ValueError('Actual reviewed readiness required')
    require_review(config)
    with sqlite3.connect('file:' + str(Path(config['output']) / 'completion.sqlite') + '?mode=ro', uri=True) as db:
        if db.execute('SELECT state FROM episodes WHERE suite=? AND id=?',
                      (config['suite_id'], 'newsletter-prechecked')).fetchone() != ('running',):
            raise ValueError('Episode must be claimed by subscribed supervisor')
    for row in ready['controls']:
        checked(row)
    output.mkdir(exist_ok=False)
    register_root(config, output / 'runs')
    from experiments.external_agent.backend import ExternalAgentBackend
    from experiments.external_agent.server import BridgeServer
    from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
    from intent_browser.backend import ChatCompletionsBackend
    from intent_browser.runner import run_episode
    quota = SubscriptionQuotaGuard(output / 'subscription-quota', remaining_floor=1)
    def admission():
        guard(config)
        imported_sources(config)
        return quota(require_complete_windows=True)
    value = prepared(config, 'positive')
    external = bridge = backend = thread = None
    trace = None
    try:
        # Native contract exists before any provider request. No formatter phase.
        contract = value.adapter.contract()
        contract.validate()
        admission()
        external = ExternalAgentBackend(config['model'], output / 'transport',
            reasoning_effort=config['reasoning_effort'], max_tokens=16384, timeout=180,
            provider_output_limit=config['provider_output_limit'], before_dispatch=admission,
            command=[str(checked(config['node'])), str(ROOT / 'experiments/external_agent/worker.mjs')],
            pi_cli=str(checked(config['pi'])), lock_path=config['subscription_lock'])
        admission_record = external.begin_episode(config['suite_id'] + '-newsletter-prechecked')
        save(output / 'admission.json', admission_record)
        token = secrets.token_urlsafe(32)
        bridge = BridgeServer(external, token, max_requests=40)
        thread = threading.Thread(target=bridge.serve_forever, daemon=True)
        thread.start()
        backend = ChatCompletionsBackend('http://127.0.0.1:' + str(bridge.server_port) + '/v1',
            config['model'], token, timeout=260, max_tokens=16384, supports_images=True)
        with value.episode:
            trace, summary = run_episode(value.episode.task.make_env, backend,
                {'tags': ['model', 'commerce-dark-patterns', 'newsletter-prechecked', config['suite_id']],
                 'driver': 'Sol bridge live policy', 'training_eligible': False},
                output=output / 'runs', episode_task=value.episode.task,
                harness_profile=value.episode.profile, site_discovery=value.episode.site_discovery,
                observation_pipeline='native', automatic_grading=contract,
                retry_policy=None, max_steps=40, max_input_tokens=100000, trace_screenshots=False)
    finally:
        if backend:
            backend.close()
        if bridge:
            bridge.shutdown()
            bridge.server_close()
        if thread:
            thread.join(timeout=15)
        if external:
            external.close()
        value.close()
    finalized = value.adapter.finalize(trace)
    projection = publish(config, trace)
    guard(config)
    imported_sources(config)
    save(output / 'result.json', {'trace': str(trace), 'summary': finalized['summary'],
         'native_grade': finalized['viewer_grade'], 'http_projection': projection,
         'task_verdict': projection['task_verdict'], 'admission': admission_record,
         'automatic_retries': 0, 'world_draws': 0})

def preflight(config):
    configure(config)
    if Path(sys.executable).resolve() != checked(config['python']):
        raise ValueError('Use the accepted virtual-environment interpreter')
    import httpx
    from experiments.external_agent.episode_admission import EpisodeLease
    from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
    http_json(config['viewer_url'] + '/api/suites')
    quota = SubscriptionQuotaGuard(Path(config['output']) / ('preflight-quota-' + uuid.uuid4().hex),
                                   remaining_floor=1)
    quota(require_complete_windows=True)
    lease = EpisodeLease(Path(config['subscription_lock']))
    try:
        lease.begin('newsletter-preflight-' + uuid.uuid4().hex)
    finally:
        lease.close()
    imported_sources(config)

def terminal_evidence(output, code, error=None):
    evidence = {'exit_code': code, 'automatic_retries': 0}
    log = output / 'model.log'
    if log.is_file():
        evidence['log'] = pin(log)
    if error is not None:
        evidence['supervisor_error'] = type(error).__name__ + ': ' + str(error)
    result = output / 'model/result.json'
    valid = False
    if result.is_file():
        evidence['result'] = pin(result)
        try:
            value = read(result)
            trace, verdict = value['trace'], value['task_verdict']
            if not isinstance(trace, str) or verdict not in ('pass', 'fail', 'inconclusive'):
                raise ValueError('Invalid terminal trace/verdict')
            evidence.update(trace=trace, task_verdict=verdict)
            valid = True
        except Exception as parse_error:
            evidence['result_parse_error'] = type(parse_error).__name__ + ': ' + str(parse_error)
    traces = sorted((output / 'model/runs').glob('*/metadata.json'))
    evidence['retained_trace_directories'] = [str(path.parent) for path in traces]
    state = ('interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else
             'succeeded' if code == 0 and valid and error is None else 'failed')
    return state, evidence

def supervise(config):
    guard(config)
    ready = read(Path(config['output']) / 'readiness.json')
    if ready['status'] != 'passed' or ready['config'] != pin(config['_path']):
        raise ValueError('Readiness binding missing')
    require_review(config)
    output = Path(config['output'])
    if (output / 'supervisor-start.json').exists():
        raise ValueError('Supervisor attempt already exists; preserve it')
    preflight(config)  # All non-generating admissions precede the once-only claim.
    save(output / 'supervisor-start.json', {'pid': os.getpid(), 'config': pin(config['_path']),
                                          'automatic_retries': 0})
    events_api = runpy.run_path(str(checked(config['events'])))
    events = events_api['Events'](output / 'completion.sqlite')
    events.register(config['suite_id'], ['newsletter-prechecked'])
    events.subscribe('evaluation-dark-episode', config['suite_id'], 'codex:' + config['thread_id'],
                     episode='newsletter-prechecked', final=False)
    events.subscribe('evaluation-dark-suite', config['suite_id'], 'codex:' + config['thread_id'], final=True)
    events.start(config['suite_id'], 'newsletter-prechecked')
    command = ['python3', str(PROJECT / 'scripts/run_bounded_job.py'), '--memory-mib', '4096',
               '--tasks', '512', '--receipt', str(output / 'model-bounded'), '--',
               'timeout', '10800', sys.executable, '-I', '-B', str(Path(__file__).resolve()),
               '--config', config['_path'], '--mode', 'model']
    child, code, failure = None, -1, None
    previous = {}
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Supervisor signal ' + str(signum))
    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        previous[signum] = signal.signal(signum, interrupted)
    try:
        with (output / 'model.log').open('x') as log:
            child = subprocess.Popen(command, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT)
            code = child.wait()
    except BaseException as error:
        failure = error
        if child is not None and child.poll() is None:
            child.terminate()  # The bounded launcher owns descendant cleanup.
            code = child.wait()
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        state, evidence = terminal_evidence(output, code, failure)
        events.finish(config['suite_id'], 'newsletter-prechecked', state, evidence)
        save(output / 'supervisor-terminal.json', {'state': state, **evidence})
        events_api['flush'](events)
    if failure:
        raise failure

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--mode', choices=['readiness', 'control', 'model', 'supervise'], required=True)
    parser.add_argument('--case', choices=['positive', 'wrong', 'incomplete'])
    args = parser.parse_args()
    config = read(args.config)
    config['_path'] = str(Path(args.config).resolve())
    try:
        if args.mode == 'control':
            control(config, args.case)
        else:
            {'readiness': readiness, 'model': model, 'supervise': supervise}[args.mode](config)
    except Exception as error:
        # A rejected repeat must not add files to a preserved episode attempt.
        base = Path(config['output']).parent / 'diagnostic-failures'
        base.mkdir(parents=True, exist_ok=True)
        target = base / (args.mode + '-' + uuid.uuid4().hex + '.json')
        save(target, {'error': type(error).__name__ + ': ' + str(error), 'mode': args.mode})
        raise

if __name__ == '__main__':
    main()
