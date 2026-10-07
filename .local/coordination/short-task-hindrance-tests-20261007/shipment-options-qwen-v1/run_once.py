"""Matched Qwen address case; source is the promoted detached Git worktree."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent
ROOT = Path('/home/bjorn/code/LLM_proj_uu')


def pin(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, default=str)
        stream.write('\n')


def execute(case, preflight=False):
    plan = json.loads((OUT/'plan.private.json').read_text())
    from worktree_gate import require_promoted_worktree
    require_promoted_worktree(plan)
    selected = next(c for c in plan['cases'] if c['case_id'] == case)
    recipe = Path(selected['recipe'])
    archive = Path(plan['source_archive']).resolve()
    # Verify the original source union AND declared data closure before imports.
    ready = json.loads((OUT/'ready.json').read_text())
    if ready['driver'] != pin(__file__) or ready['plan'] != pin(OUT/'plan.private.json'):
        raise ValueError('Ready/driver binding changed')
    for entry in ready['inputs']:
        if pin(entry['path']) != entry:
            raise ValueError('Changed bound input: '+entry['path'])
    if not preflight:
        from supervise import verify_ready
        verify_ready(ready)
        claim = json.loads((OUT/'supervisor-start.json').read_bytes())
        if claim['ready'] != pin(OUT/'ready.json'):
            raise ValueError('Case was not claimed by this accepted supervisor')
        import sqlite3
        with sqlite3.connect('file:'+str(OUT/'completion.sqlite')+'?mode=ro', uri=True) as db:
            state = db.execute('SELECT state FROM episodes WHERE suite=? AND id=?',
                               (plan['suite_id'], case)).fetchone()
            subscriptions = db.execute('SELECT episode,final FROM subscriptions WHERE suite=? AND recipient=?',
                (plan['suite_id'], 'codex:'+plan['thread_id'])).fetchall()
        if (state != ('running',) or (case, 0) not in subscriptions
                or (None, 1) not in subscriptions):
            raise ValueError('Episode/completion subscriptions not registered before dispatch')
        entry = json.loads((OUT/(case+'-bounded/entry.json')).read_bytes())
        if entry['pid'] != os.getpid():
            raise ValueError('Case must execute in its own verified bounded scope')
    recovery = json.loads(Path(plan['recovery_receipt']['path']).read_text())
    if archive != Path(recovery['source_archive']).resolve():
        raise ValueError('Unexpected isolated source ROOT')
    for name, expected in {**recovery['original_source_sha256'], **recovery['supplemental_sha256']}.items():
        file = archive/name
        if file.is_symlink() or not file.resolve().is_relative_to(archive) or pin(file)['sha256'] != expected:
            raise ValueError('Changed isolated source/data member: '+name)
    policy = archive/'environments/product_world/data/product_feature_policies/catalogue_v2/manifest.json'
    for member in json.loads(policy.read_text())['concepts'].values():
        if pin(policy.parent/member['file'])['sha256'] != member['sha256']:
            raise ValueError('Original reviewed-policy closure changed')
    sys.dont_write_bytecode = True
    # Must precede every project import in this fresh process.
    sys.path[:] = [str(archive), str(OUT)] + [p for p in sys.path
        if Path(p or '.').resolve() not in (ROOT, archive, OUT)]
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')
    os.environ['HARNESS_AX_TOKENIZER'] = str(ROOT/'.local/website-38-concept-world-20261006-v1/assets/tokenizer.json')
    from environments.website_world import atomic_address_execution, generation, runtime
    from experiments.accepted_catalog_commerce import package_export
    from intent_browser.backend import ChatCompletionsBackend
    from intent_browser.connected_world_task import checked_files
    from intent_browser.openrouter import provider_options, DEFAULT_PROVIDERS
    for module in (atomic_address_execution, generation, runtime, package_export):
        if not Path(module.__file__).resolve().is_relative_to(archive):
            raise ValueError('Live project module entered frozen execution')
    for module in (generation, runtime, package_export):
        if Path(module.ROOT).resolve() != archive:
            raise ValueError('Frozen producer ROOT does not match source archive')
    manifest = generation.load(recipe)
    if selected['manifest'] != pin(recipe/'manifest.json'):
        raise ValueError('Original recipe manifest changed')
    if (plan['model'] != 'qwen/qwen3.8-27b' or plan['max_steps'] != 16
            or plan['max_requests'] != 16 or plan['max_input_tokens'] != 32000
            or plan['max_tokens'] != 16384 or plan['automatic_retries'] != 0):
        raise ValueError('Finite matched authorization changed')
    from grade_publication import publish_grade, viewer_health
    from grading_gate import require_grading
    grading_contract = require_grading(
        runner=atomic_address_execution.run,
        grader=atomic_address_execution.grading.grade_saved_return,
        projection=publish_grade, artifact='atomic-address-grade.private.json',
        allow_ungraded=plan['allow_ungraded'], reason=plan.get('ungraded_reason'))
    viewer_health()
    if preflight:
        print(json.dumps({'case':case,'source_count':len(manifest['source_sha256']),
                          'frozen_root':str(archive),'Runtime':runtime.__file__,'models':0}),flush=True)
        return
    ready = json.loads((OUT/'ready.json').read_text())
    if ready['driver'] != pin(__file__) or ready['plan'] != pin(OUT/'plan.private.json'):
        raise ValueError('Ready/driver binding changed')
    checked_files({r['path']:r['sha256'] for r in ready['inputs']})
    directory = OUT/case
    directory.mkdir(exist_ok=True)
    save(directory/'launch.json',{'case':case,'at':datetime.now(timezone.utc).isoformat(),
         'pid':os.getpid(),'ready':pin(OUT/'ready.json'),'automatic_retries':0,'world_draws':0})
    extra = {r['path']:r['sha256'] for r in ready['inputs']}
    extra.update({str(OUT/'ready.json'):pin(OUT/'ready.json')['sha256']})
    def admission():
        checked_files(extra)
        checked_files({r['path']:r['sha256'] for r in
            (plan['release']['tooling'], plan['release']['certificate'], plan['release']['promotion'])})
        for name, module in list(sys.modules.items()):
            if name.split('.')[0] in ('intent_browser', 'environments', 'experiments'):
                path = getattr(module, '__file__', None)
                if path and not Path(path).resolve().is_relative_to(archive):
                    raise ValueError('Development project module entered evaluation: ' + name)
    counters = {'requests':0,'reported_cost_usd':0.0,'responses_with_cost':0,
                'responses_without_cost':0,'prompt_tokens':0,'completion_tokens':0}
    def record(data):
        with (directory/'http-attempts.jsonl').open('a') as stream:
            stream.write(json.dumps(data,ensure_ascii=False,default=str)+'\n')
    @contextmanager
    def session(*, before_dispatch):
        from dotenv import dotenv_values
        values = dotenv_values(ROOT/'.env')
        key = os.environ.get('OPENROUTER_API_KEY') or values.get('OPENROUTER_API_KEY')
        if not key:
            raise ValueError('Existing OpenRouter key missing')
        options = provider_options(DEFAULT_PROVIDERS)
        backend = ChatCompletionsBackend('https://openrouter.ai/api/v1',plan['model'],key,
            timeout=180,max_tokens=plan['max_tokens'],request_options=options,
            session_routing=True,supports_images=True)
        def dispatch(request):
            before_dispatch()
            counters['requests'] += 1
            if counters['requests'] > plan['max_requests']:
                raise ValueError('Authorized request count exceeded')
            record({'event':'dispatch','attempt':counters['requests'],
                    'at':datetime.now(timezone.utc).isoformat(),
                    'request_sha256':sha256(request.content).hexdigest()})
        def response(res):
            res.read()
            try:
                body = res.json()
            except ValueError:
                body = {}
            usage = body.get('usage') or {}
            cost = usage.get('cost')
            if isinstance(cost,(int,float)):
                counters['reported_cost_usd'] += cost
                counters['responses_with_cost'] += 1
            else:
                counters['responses_without_cost'] += 1
            counters['prompt_tokens'] += usage.get('prompt_tokens') or 0
            counters['completion_tokens'] += usage.get('completion_tokens') or 0
            record({'event':'response','attempt':counters['requests'],
                    'at':datetime.now(timezone.utc).isoformat(),'http_status':res.status_code,
                    'model':body.get('model'),'provider':body.get('provider'),
                    'response_id':body.get('id'),'usage':usage,'reported_cost_usd':cost})
        backend.client.event_hooks = {'request':[dispatch],'response':[response]}
        try:
            yield backend
        finally:
            backend.close()
    from request_override import wording_runner
    from intent_browser.runner import run_episode
    revised_runner = wording_runner(run_episode, selected['wording']['path'])
    try:
        result = atomic_address_execution.run(recipe,directory/'live',policy_session=session,
            metadata={'trace_title':selected['trace_title'],'source':'shipment-options-qwen-v1',
                      'model':plan['model'],'driver':'llm','training_eligible':False},
            runner_options={'max_steps':16,'max_input_tokens':32000,
                            'trace_screenshots':True,'async_recording':True},
            authority_approval=selected['authority_approval'],quota_guard=admission,runner=revised_runner)
        grade_path = Path(result['trace'])/'atomic-address-grade.private.json'
        if not grade_path.is_file() or json.loads(grade_path.read_text()) != result['state_grading']:
            raise ValueError('System failure: automatic native grade missing or differs from result')
        policy_task = json.loads((Path(result['trace'])/'policy-task.json').read_bytes())
        declared = json.loads(Path(selected['wording']['path']).read_bytes())
        if (policy_task['task_id'] != declared['native_task_id']
                or policy_task['user_message'] != declared['user_message']
                or policy_task['memories'] != declared['memories']):
            raise ValueError('Revised policy request/memories/native outcome binding differs')
        visible = publish_grade(result, selected, OUT)
        save(directory/'grade-viewer-acceptance.json', visible)
        save(directory/'result.json',{**result,'case_id':case,'automatic_grading':True,
             'viewer_url':visible['viewer_url'],'grading_contract':grading_contract,
             'request_variant_id':declared['request_variant_id'],'grading_scope':plan['grading_scope'],
             'shipment_answer_content_scored':False,'usage':counters,'billing':'OpenRouter reported actual usage',
             'input_measurement':'Harness complete-request local Qwen tokenizer estimate; provider counters retained separately',
             'source_archive':str(archive),'automatic_retries':0,'world_draws':0,'training_eligible':False})
        print(json.dumps({'case':case,'trace':result['trace'],
                          'grade':result['state_grading']['verdict'],'usage':counters}),flush=True)
    except BaseException as error:
        save(directory/'failure.json',{'case':case,'type':type(error).__name__,
             'error':str(error),'usage':counters,'automatic_retries':0,'world_draws':0})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case',required=True,choices=['old-address','missing-optional-unit'])
    parser.add_argument('--preflight',action='store_true')
    args = parser.parse_args()
    execute(args.case,args.preflight)
