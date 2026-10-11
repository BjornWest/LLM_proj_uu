"""Four once-only OpenRouter episodes over accepted atomic recipes.

Each child owns its browser, backend, trace and cost ledger. Frozen native
grading is required; process success follows canonical and HTTP publication.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from hashlib import sha256
from functools import wraps
import importlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import signal
import sqlite3
import subprocess
import sys
import time
import types


def load(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def pin(path):
    return {'path': str(Path(path).absolute()), 'sha256': sha256(Path(path).read_bytes()).hexdigest()}


def checked(row):
    path = Path(row['path'])
    if path.is_symlink() or pin(path) != row:
        raise ValueError('Pinned input changed: ' + str(path))
    return path


def helpers(spec):
    return runpy.run_path(str(checked(spec['helpers'])))


def check_inputs(spec):
    checked(spec['driver'])
    for row in [*spec['additional_inputs'], *spec['counter']['files'],
                *spec['counter']['assets'], spec['counter']['approved_release']]:
        checked(row)
    declared = {Path(row['path']).resolve() for row in spec['counter']['files']}
    for name, module in list(sys.modules.items()):
        if name.startswith('_mimo_counter.') and Path(module.__file__).resolve() not in declared:
            raise ValueError('Undeclared counter source: '+name)


EpisodeDeadline = TimeoutError  # Keep the native runner's exact exception semantics.


def inspection_inputs(spec):
    """Validate immutable opt-in inputs before claiming any paid case."""
    config = spec.get('inspection')
    if config is None:
        return
    if not isinstance(config, dict) or config.get('enabled') is not True:
        raise ValueError('Inspection configuration requires explicit enabled=true')
    receipt = load(checked(config['package_receipt']))
    checked(receipt['loader'])
    root = Path(receipt['package_root']).resolve()
    for relative, digest in receipt['relative_source_sha256'].items():
        path = root/relative
        if not path.resolve().is_relative_to(root):
            raise ValueError('Inspection source escaped its declared root')
        checked({'path':str(path),'sha256':digest})
    plans = load(checked(config['compiled_suite']))['cases']
    for case in spec['cases']:
        matches = [row for row in plans if row['case'] == case['id']]
        if len(matches) != 1:
            raise ValueError('Inspection requires one exact native plan per case')
        plan = matches[0]
        checked(plan['compiled'])
        if (load(checked(plan['task'])) != load(Path(case['recipe'])/'atomic-product-task.private.json')
                or plan['world']['sha256'] != pin(Path(case['recipe'])/'pin/world.private.json')['sha256']):
            raise ValueError('Inspection task/world differs from actual native recipe')
        checked(plan['world'])


def inspection_summary(out, state):
    """Attach recording status to the durable native outcome, before analysis."""
    directory = Path(out)/'inspection'
    result = {'native_finalized_before_analysis':True}
    try:
        if state is None:
            failure = directory/'setup-failure.json'
            result.update(status='setup_unknown', setup_failure=load(failure) if failure.exists() else None)
        else:
            result.update(status='analysis_pending', recording=load(directory/'recording-status.json'),
                analysis_status_path=str(directory/'analysis-status.json'))
    except Exception as error:
        result.update(status='recording_status_unknown', error=type(error).__name__)
    return result


def validate_launch(spec):
    check_inputs(spec)
    inspection_inputs(spec)
    ready = load(checked(spec['ready']))
    approval = load(checked(spec['review_acceptance']))
    configuration = sha256(json.dumps({k:v for k,v in spec.items() if k not in (
        'ready','review_acceptance')}, sort_keys=True).encode()).hexdigest()
    if (ready['driver'] != spec['driver'] or ready['status'] != 'passed' or
            [r['case'] for r in ready['cases']] != ['A01','A02','A03','A04'] or
            [c['id'] for c in spec['cases']] != ['A01','A02','A03','A04'] or
            approval['status'] != 'approved' or approval['configuration_sha256'] != configuration):
        raise ValueError('Exact scripted readiness and reviewed configuration required')
    checked(approval['report'])
    blob = subprocess.check_output(['git','-C',spec['project_root'],'show',
        spec['caller_commit']+':scripts/mimo_atomic_suite.py'])
    if sha256(blob).hexdigest() != spec['driver']['sha256']:
        raise ValueError('Executed caller differs from reviewed committed blob')
    for row in ready['cases']:
        accepted = load(checked(row['result']))
        if accepted['status'] != 'graded_and_projected' or accepted['result']['task_completed'] is not True:
            raise ValueError('Actual native correct control required')
        if spec.get('inspection') is not None:
            recording = accepted.get('inspection', {}).get('recording', {})
            if recording.get('enabled') is not True or recording.get('provider_enabled') is not True:
                raise ValueError('Actual enabled inspection readiness required before dispatch')


def counter(spec, backend, h):
    directory = Path(spec['counter']['directory'])
    package = types.ModuleType('_mimo_counter')
    package.__path__ = [str(directory)]
    sys.modules[package.__name__] = package
    sys.meta_path.insert(0, h['FrozenSourceFinder']({'_mimo_counter': directory}))
    module = importlib.import_module('_mimo_counter.model_input_budget')
    return module.model_matched_input_counter(backend, assets_root=spec['counter']['assets_root'])


def scripted_policy(recipe):
    task = load(recipe/'atomic-product-task.private.json')
    ref = load(recipe/'atomic-product-reference.private.json')['expected_claims']
    steps, claims, answer = [], {}, 'Done.'
    if task['kind'] in ('read_listed_price', 'add_exact_variant_quantity'):
        catalog = load(recipe/'atomic-product-catalog.private.json')
        product = next(p for p in catalog['products'] if p['id'] == task['page_id'])
        variant = next(v for v in product['variants'] if v['offerId'] == task['offer_id'])
        steps = [('select', axis, value) for axis, value in variant['selection'].items()]
    if task['kind'] == 'read_listed_price':
        amount = f"{ref['price_minor']/100:.2f}"
        answer = 'The listed item price is ' + amount + ' SEK.'
        claims = {'interpretation': 'extracted', 'issues': [], 'total': {
            'amount': amount, 'currency': 'SEK', 'evidence': amount+' SEK'}, 'source_urls': []}
    elif task['kind'] == 'read_public_fact':
        answer = f"The reference weight is {ref['value']} g, for {ref['qualifier']}."
        claims = {'interpretation': 'extracted', 'issues': [],
            'value': {'value': ref['value'], 'evidence': str(ref['value'])+' g'},
            'unit': {'value': 'g', 'evidence': str(ref['value'])+' g'},
            'qualifier': {'value': ref['qualifier'], 'evidence': ref['qualifier']}, 'source_urls': []}
    elif task['kind'] == 'select_exact_variant':
        steps = [('select', axis, value) for axis, value in task['selection'].items()]
    else:
        steps += [('quantity', str(task['spec']['quantity'])), ('add',)]
    return steps, answer, claims


def inspection(spec, case, out, native_runner, *, deadline_guard=None):
    """Optional private recording; native task outcomes survive analysis failures."""
    config = spec.get('inspection')
    if config is None:
        return native_runner, None
    if config.get('enabled') is not True:
        raise ValueError('Inspection configuration requires explicit enabled=true')
    target = out/'inspection'
    try:
        target.mkdir(exist_ok=False)
        receipt = load(checked(config['package_receipt']))
        loader_path = checked(receipt['loader'])
        name = '_checked_suite_inspection_loader'
        module_spec = importlib.util.spec_from_file_location(name, loader_path)
        loader = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(loader)
        recording, sources = loader.load_recording(receipt['package_root'], receipt['relative_source_sha256'])
        try:
            plans = load(checked(config['compiled_suite']))['cases']
            plan = next(row for row in plans if row['case'] == case['id'])
            checked(plan['task']); checked(plan['compiled']); checked(plan['world'])
            if plan['world']['sha256'] != pin(Path(case['recipe'])/'pin/world.private.json')['sha256']:
                raise ValueError('Inspection world differs from actual native recipe')
            native_task = load(checked(plan['task']))
            recipe = Path(case['recipe'])
            if native_task != load(recipe/'atomic-product-task.private.json'):
                raise ValueError('Inspection plan differs from actual native task')
            compiler = importlib.import_module(recording.__package__+'.suite_task_requirements')
            from environments.website_world.atomic_product_task import make
            actual_compiled = compiler.compile_suite_task(native_task, native_inputs={
                'native_make':make, 'world':load(recipe/'pin/world.private.json'),
                'catalog':load(recipe/'atomic-product-catalog.private.json'),
                'bindings':load(recipe/'atomic-product-bindings.private.json'),
                'checkout_domain':load(recipe/'checkout-domain.private.json')})
            if actual_compiled != load(checked(plan['compiled'])):
                raise ValueError('Actual native root compiles different task obligations')
            entry = native_runner
            if deadline_guard is not None:
                @wraps(native_runner)
                def entry(*args, **kwargs):
                    deadline_guard()
                    return native_runner(*args, **kwargs)
            wrapped = recording.recording_runner(entry, enabled=True, expected_sources=sources,
                report=target/'recording-status.json')
        except BaseException:
            recording.release_package()
            raise
        return wrapped, {'recording':recording,'plan':plan,'target':target,'task_id':native_task['task_id']}
    except EpisodeDeadline:
        raise
    except Exception as error:
        try:
            save(target/'setup-failure.json', {'status':'unknown','error':type(error).__name__,
                'detail':str(error),'native_runner_preserved':True})
        except Exception:
            pass
        return native_runner, None


def inspection_analysis(state, result):
    if state is None:
        return
    recording, plan, target = state['recording'], state['plan'], state['target']
    try:
        inventory_module = importlib.import_module(recording.__package__+'.suite_source_inventory')
        reader = importlib.import_module(recording.__package__+'.task_model_prefix_coverage')
        sources = [{'path':p,'sha256':h} for p,h in recording.package_pins().items()]
        inventory = inventory_module.build_inventory(result['trace'], task=plan['task'],
            compiled=plan['compiled'], inputs=[plan['world']], source_inputs=sources)
        save(target/'inventory.json', inventory)
        prefixes = reader.replay_model(result['trace'], inventory, extracted_dataset_policy='none')
        save(target/'prefixes.json', prefixes)
        save(target/'analysis-status.json', {'status':'passed','field_templates':inventory['field_templates'],
            'mapped_field_templates':inventory['mapped_field_templates'],
            'prefixes':len(prefixes['prefixes']),'policy_delivery':'strict_receipts',
            'meaning':'analysis completed; not a model-success or full-coverage verdict',
            'coverage':'partial' if inventory['mapped_field_templates'] < inventory['field_templates'] else 'mapped',
            'native_task_verdict_unchanged':True})
    except EpisodeDeadline:
        raise
    except Exception as error:
        try:
            save(target/'analysis-status.json', {'status':'unknown','error':type(error).__name__,
                'detail':str(error),'native_task_verdict_unchanged':True})
        except Exception:
            pass  # Optional evidence storage may fail after native finalization.


def execute(spec, case, scripted=False):
    h = helpers(spec)
    check_inputs(spec)
    if not scripted:
        validate_launch(spec)
        with sqlite3.connect('file:'+str(Path(spec['output'])/'completion.sqlite')+'?mode=ro', uri=True) as db:
            if db.execute('SELECT state FROM episodes WHERE suite=? AND id=?',
                    (spec['suite_id'],case['id'])).fetchone() != ('running',):
                raise ValueError('Episode must be claimed by its subscribed supervisor')
    os.environ['LD_LIBRARY_PATH'] = spec['library_path']
    run = h['configure_case'](spec, case)
    from intent_browser.backend import ChatCompletionsBackend
    from intent_browser.runner import run_episode
    out = Path(spec['output'])/case['id']
    out.mkdir(parents=True, exist_ok=False)
    save(out/'start.json', {'case': case['id'], 'epoch': time.time(), 'pid': os.getpid(),
                            'scripted': scripted, 'driver': spec['driver']})
    cancelled = False
    def deadline_guard():
        if cancelled:
            raise EpisodeDeadline('Bounded episode deadline or termination')
    def deadline(*_):
        nonlocal cancelled
        cancelled = True
        deadline_guard()
    signal.signal(signal.SIGTERM, deadline)
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(150 if scripted else spec['episode_timeout'])
    holder, counts = {}, {'policy_requests': 0, 'formatter_requests': 0,
        'reported_cost_usd': 0.0, 'responses_without_cost': 0}
    steps, answer, claims = scripted_policy(Path(case['recipe'])) if scripted else ([], '', {})
    if scripted and spec.get('scripted_inspection_read') and case['id'] in ('A01','A02'):
        steps.append(('inspect',))

    def record(value):
        with (out/'http-attempts.jsonl').open('a') as stream:
            stream.write(json.dumps({'epoch': time.time(), **value})+'\n')

    def model_backend(phase, before):
        from dotenv import dotenv_values
        key = os.environ.get('OPENROUTER_API_KEY') or dotenv_values(
            Path(spec['project_root'])/'.env').get('OPENROUTER_API_KEY')
        if not key:
            raise ValueError('Existing OpenRouter credential missing')
        backend = ChatCompletionsBackend('https://openrouter.ai/api/v1', spec['model'], key,
            timeout=spec['request_timeout'], max_tokens=spec['max_tokens'],
            request_options={'provider': spec['provider_options'], 'reasoning': {'enabled': phase == 'policy'}},
            session_routing=True, supports_images=True)
        backend.begin_episode(spec['suite_id']+'-'+case['id']+'-'+phase)
        def dispatched(request):
            deadline_guard()
            before(); check_inputs(spec)
            counts[phase+'_requests'] += 1
            if phase == 'formatter' and counts['formatter_requests'] > 1:
                raise ValueError('Once-only formatter request exceeded')
            record({'event': 'dispatch', 'phase': phase,
                    'request_sha256': sha256(request.content).hexdigest()})
        def received(response):
            response.read()
            try: body = response.json()
            except ValueError: body = {}
            usage = body.get('usage') or {}
            cost = usage.get('cost')
            if type(cost) in (int, float): counts['reported_cost_usd'] += cost
            else: counts['responses_without_cost'] += 1
            record({'event': 'response', 'phase': phase, 'http_status': response.status_code,
                    'provider': body.get('provider'), 'model': body.get('model'), 'usage': usage,
                    'response_id': body.get('id')})
        backend.client.event_hooks = {'request': [dispatched], 'response': [received]}
        return backend

    @contextmanager
    def policy_session(*, before_dispatch):
        if scripted:
            import httpx
            backend = ChatCompletionsBackend('http://offline.invalid/v1', 'scripted', 'offline', supports_images=True)
            backend.client.close()
            def dispatch(request):
                deadline_guard()
                before_dispatch()
                page = holder['env'].unwrapped.page
                if steps:
                    step = steps.pop(0)
                    if step[0] == 'select':
                        _, axis, value = step
                        select = page.locator(f'select[data-selection="{axis}"]')
                        radio = page.locator(f'input[type="radio"][data-selection="{axis}"][value="{value}"]')
                        if select.count() == 1: name, args = 'select_option', {'bid':select.get_attribute('bid'),'options':value}
                        elif radio.count() == 1: name, args = 'check', {'bid':radio.get_attribute('bid')}
                        else:
                            button = page.locator(f'button[data-selection-button="{axis}"][data-value="{value}"]')
                            assert button.count() == 1
                            name, args = 'click', {'bid':button.get_attribute('bid')}
                    elif step[0] == 'inspect':
                        task = load(Path(case['recipe'])/'atomic-product-task.private.json')
                        if task['kind'] == 'read_listed_price':
                            query = page.locator('main [data-product-part="buying"] .amount').inner_text()
                        else:
                            query = str(load(Path(case['recipe'])/'atomic-product-reference.private.json')['expected_claims']['value'])
                        name, args = 'ax_search', {'query':query, 'context':2, 'limit':5, 'repeat':True}
                    elif step[0] == 'quantity':
                        field = page.locator('form[data-form="add"] input[name="quantity"]')
                        name, args = 'fill', {'bid':field.get_attribute('bid'),'value':step[1]}
                    else:
                        button = page.locator('form[data-form="add"] button')
                        assert button.is_enabled()
                        name, args = 'click', {'bid':button.get_attribute('bid')}
                else: name, args = 'send_msg_to_user', {'text':answer}
                counts['policy_requests'] += 1
                return httpx.Response(200, json={'choices':[{'finish_reason':'tool_calls','message':{
                    'role':'assistant','content':None,'tool_calls':[{'id':'script-'+str(counts['policy_requests']),
                    'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}],'usage':{}})
            backend.client = httpx.Client(transport=httpx.MockTransport(dispatch))
        else:
            backend = model_backend('policy', before_dispatch)
        try: yield backend
        finally: backend.close()

    class ScriptedFormatter:
        model = 'scripted-formatter'
        def complete(self, messages):
            payload = json.loads(messages[1]['content'])
            assert payload['final_answer'] == answer and payload['public_task']['user_message'] == case['public_request']
            counts['formatter_requests'] += 1
            assert counts['formatter_requests'] == 1
            text = json.dumps(claims)
            return types.SimpleNamespace(text=text, request={'messages':messages}, raw={
                'model':self.model,'provider':'offline-script','usage':{},'choices':[{
                'finish_reason':'stop','message':{'content':text}}]})
        def close(self): pass

    def runner(factory, backend, metadata, **kwargs):
        if kwargs['automatic_grading'].phase != 'external':
            raise ValueError('Automatic native grading must be attached')
        # Use the exact accepted native profile, disabling optional compute helpers.
        kwargs['harness_profile'] = h['policy_profile'](kwargs['harness_profile'], discovery=False)
        sizing_backend = types.SimpleNamespace(model=spec['model'], base_url='https://openrouter.ai/api/v1',
            request_options={'reasoning':{'enabled':True}}) if scripted else backend
        kwargs['input_counter'] = counter(spec, sizing_backend, h)
        kwargs['retry_policy'] = None
        def make_env(video=None):
            env = factory(video); holder['env'] = env
            return env
        wrapped, state = inspection(spec, case, out, run_episode, deadline_guard=deadline_guard)
        if state is not None:
            metadata = {**metadata, 'native_task_id':state['task_id']}
        holder['inspection'] = state
        try:
            return wrapped(make_env, backend, metadata, **kwargs)
        except BaseException:
            if state is not None:
                state['recording'].release_package()
                holder['inspection'] = None
            raise

    def projection(*, trace, grade):
        trace = Path(trace).resolve()
        if not trace.is_relative_to(out/'live/runs'):
            raise ValueError('Returned trace escaped declared output')
        result = h['verify_projection'](spec, trace)
        save(out/'grade-viewer.json', result)
        return result

    try:
        result = run(case['argument'], out/'live', policy_session=policy_session,
            metadata={'source':spec['suite_id'],'suite':spec['suite_id'],'case':case['id'],
                'model':'scripted' if scripted else spec['model'],'tags':['scripted'] if scripted else ['mimo-atomic4'],
                'training_eligible':False}, runner_options={'max_steps':8 if scripted else spec['max_steps'],
                'max_input_tokens':spec['max_input_tokens'],'trace_screenshots':True,'async_recording':False},
            viewer_projection=projection, quota_guard=lambda:check_inputs(spec), runner=runner,
            extraction_backend_factory=lambda _:ScriptedFormatter() if scripted else model_backend('formatter', lambda:None))
        h['module_origins'](spec, case)
        if result.get('status') != 'graded_and_projected':
            raise ValueError('Missing automatic grade or HTTP projection: '+str(result))
        if scripted and result.get('task_completed') is not True:
            raise ValueError('Scripted correct answer did not pass native grading')
        finalized = {'status':'graded_and_projected','case':case['id'],
                     'result':result,'usage':counts,'scripted':scripted}
        if spec.get('inspection') is not None:
            finalized['inspection'] = inspection_summary(out, holder.get('inspection'))
        # This immutable native outcome survives optional analysis failure/kill.
        save(out/'result.json', finalized)
        inspection_analysis(holder.get('inspection'), result)
    except BaseException as error:
        save(out/'failure.json', {'type':type(error).__name__,'message':str(error),'usage':counts})
        raise
    finally:
        if holder.get('inspection') is not None:
            holder['inspection']['recording'].release_package()
        signal.alarm(0)


def supervise(spec):
    validate_launch(spec)
    out = Path(spec['output']); out.mkdir(parents=True, exist_ok=True)
    save(out/'supervisor-start.json', {'epoch':time.time(),'pid':os.getpid(),'target_concurrency':4,
                                      'driver':spec['driver'],'automatic_retries':0})
    api = runpy.run_path(str(checked(spec['events_helper'])))
    events = api['Events'](out/'completion.sqlite')
    events.register(spec['suite_id'], [c['id'] for c in spec['cases']])
    recipient = 'codex:'+spec['thread_id']
    for case in spec['cases']:
        events.subscribe('mimo4-'+case['id'], spec['suite_id'], recipient, episode=case['id'], final=False)
    events.subscribe('mimo4-suite',spec['suite_id'],recipient,milestones=[2],final=True)
    helpers(spec)['register_roots'](spec)
    def one(case):
        ident = case['id']; events.start(spec['suite_id'], ident)
        code, failure = None, None
        try:
            checked(spec['launcher'])
            with (out/(ident+'-stdout.log')).open('x') as stdout, (out/(ident+'-stderr.log')).open('x') as stderr:
                process = subprocess.run(['python3', spec['launcher']['path'],'--memory-mib','2048','--tasks','256',
                    '--receipt',str(out/(ident+'-bounded')),'--','timeout','--kill-after=30s','10900s',
                    spec['python'],'-I','-B',spec['driver']['path'],'case',spec['spec_path'],ident],
                    stdout=stdout,stderr=stderr,timeout=11000)
                code = process.returncode
            result = load(out/ident/'result.json')
            finalized_before_analysis = (spec.get('inspection') is not None and
                result.get('inspection', {}).get('native_finalized_before_analysis') is True)
            if (code != 0 and not finalized_before_analysis) or result['status'] != 'graded_and_projected':
                raise ValueError('Child did not complete with published grade')
            grade = load(out/ident/'grade-viewer.json')
            if grade['status'] != 'verified': raise ValueError('Child HTTP proof missing')
            checked(grade['automatic']); checked(grade['canonical'])
            completed = result['result']['task_completed']
            payload = {'result':pin(out/ident/'result.json'),'viewer':grade,'usage':result['usage'],
                'task_verdict': 'pass' if completed is True else 'fail' if completed is False else 'inconclusive'}
            if finalized_before_analysis:
                payload['inspection'] = result['inspection']
                payload['analysis_child_exit_code'] = code
            state = 'succeeded'
        except BaseException as error:
            failure = {'type':type(error).__name__,'message':str(error)}
            state, payload = 'failed', {'system_failure':failure,'exit_code':code,'task_verdict':None}
        events.finish(spec['suite_id'],ident,state,payload)
        # Delivery is serialized by the supervisor, not simultaneous workers.
        return {'case':ident,'state':state,'exit_code':code,'payload':payload}
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(one,c) for c in spec['cases']]
        for future in as_completed(futures):
            results.append(future.result())
            api['flush'](events)
    save(out/'suite-result.json', {'suite':spec['suite_id'],'cases':results,'automatic_retries':0})


if __name__ == '__main__':
    mode, spec_path, *arguments = sys.argv[1:]
    spec = load(spec_path)
    if mode == 'supervise': supervise(spec)
    else:
        case = next(c for c in spec['cases'] if c['id'] == arguments[0])
        execute(spec, case, scripted=mode == 'scripted')
