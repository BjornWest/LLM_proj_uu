#!/usr/bin/env python3
"""One corrected-stack Modal B06; default is a source-only dry run."""
from hashlib import sha256
from contextlib import closing
from pathlib import Path
import argparse
import json
import os
import secrets
import sqlite3
import subprocess
import runpy
import urllib.request
import signal
import sys
import time
import traceback

sys.dont_write_bytecode = True
from lifecycle import ChildFailure, checked, cleanup_gpu, Heartbeat, pin, read, run_child, save, validate_platform
from pilot_relay import canonical, serve
from producer_transport import http, projection_binding

HERE = Path(__file__).resolve().parent
BINDING_RELATIVE = '.local/coordination/qwen-capability-sweep-20261010/remote-infrastructure-v1/Training-serving-binding-v1.json'
BOUNDED_LAUNCHER_SHA = '385a42ea57d32cd77c4f949cb4b1e3e655a67ace6cd3b6d29f91f2dc834ac53a'
BINDING_SHA = 'f8bdca769f3ff9a34ee3bae08e53c85281af602b78fb2d31777c538dbf780c0d'
PATCH = dict(original_source_sha256='7d1dae2075f0ae425648b91f8c94358ea874db4972d5263f44ef8b268187fbe4',
             patched_source_sha256='93f9b8ec0097f5b4d416e9106442900727a3aa7ca48930469fca88a1fd33c064',
             patch_sha256='f4fecc3c543354c6d8ee0cbc2674374337ce8d1cc6c41da361240b61b631c3c3')


def verify_pins(value):
    """Validate all explicit pin objects, not arbitrary task prose dictionaries."""
    if isinstance(value, dict):
        if set(value) == {'path','sha256'}:
            checked(value)
        else:
            for child in value.values(): verify_pins(child)
    elif isinstance(value, list):
        for child in value: verify_pins(child)


def child_environment():
    allowed={'PATH','HOME','LANG','LC_ALL','TZ','TMPDIR','XDG_RUNTIME_DIR',
             'DBUS_SESSION_BUS_ADDRESS','DISPLAY','WAYLAND_DISPLAY','WSL_INTEROP',
             'WSL_DISTRO_NAME','DOCKER_HOST','DOCKER_CONTEXT','PLAYWRIGHT_BROWSERS_PATH'}
    env={key:value for key,value in os.environ.items() if key in allowed}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='',TOKENIZERS_PARALLELISM='false')
    # Explicit allowlist removes inherited optimize flags and all API secrets.
    return env


def owned_sources(commit):
    root=HERE.parents[2]
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()!=commit:
        raise ValueError('Owned source HEAD differs from reviewed Training commit')
    paths=[*HERE.glob('*.py'),HERE/'README.md',
           root/'training/envs/rl/pyproject.toml',root/'training/envs/rl/uv.lock',
           root/'training/browser_training/__init__.py',
           root/'training/browser_training/vllm_qwen_schema_patch.py',
           root/'training/scripts/apply_vllm_qwen_schema_patch.py']
    rows=[]
    for path in paths:
        relative=str(path.relative_to(root))
        committed=subprocess.check_output(['git','show',commit+':'+relative],cwd=root)
        if path.read_bytes()!=committed:
            raise ValueError('Owned image/controller source differs from reviewed commit: '+relative)
        rows.append(pin(path))
    return rows


def plan(args):
    checked(dict(path=str(args.spec.resolve()), sha256=args.spec_sha256))
    checked(dict(path=str(args.caller.resolve()), sha256=args.caller_sha256))
    checked(dict(path=str(args.request.resolve()), sha256=args.request_sha256))
    spec = read(args.spec)
    verify_pins(spec)
    if args.execute:
        checked(spec['review_report'])
        acceptance=read(checked(spec['scripted_runtime_acceptance']))
        if acceptance.get('execution_commit')!=spec['reviewed_commit'] or acceptance.get('new_outer_caller_source_review_pending') is not False:
            raise ValueError('Final reviewed outer caller/acceptance execution binding required')
        rows=acceptance.get('rows',[])
        if {r.get('case') for r in rows}!={'positive','wrong','missing'} or any(r.get('native_canonical_HTTP_passed') is not True or r.get('actual_browser') is not True or r.get('provider_requests')!=0 for r in rows):
            raise ValueError('Actual released browser/runtime acceptance required before allocation')
    if spec.get('schema') != 'modal-full-B06-v1' or spec.get('case') != 'B06':
        raise ValueError('Reviewed full B06 contract required')
    if spec.get('parser_patch_binding') != PATCH:
        raise ValueError('Reviewed parser patch differs')
    if any(k in spec for k in ('maximum_episode_seconds','episode_deadline_utc','policy_grading_reserve_seconds')):
        raise ValueError('No custom episode-duration alarm permitted')
    binding_path = checked(dict(path=str(args.project_root.resolve()/BINDING_RELATIVE),sha256=BINDING_SHA))
    binding = read(binding_path)
    if binding['first_case']['commit'] != '95e9ac988ea515f7194cbdc82ae327e248fc94fa':
        raise ValueError('B06 task lineage differs')
    counter = checked(spec['ordered_counter_source'])
    projection = projection_binding(HERE/'pilot_relay.py', counter)
    inventory = read(checked(spec['venv_dependency_inventory']))
    verify_pins(inventory)
    # Run the released caller with its pinned interpreter. No imports of mutable
    # project modules are needed in the controller's lifecycle helpers.
    python = inventory['interpreter']
    if not Path(python).is_absolute() or not Path(python).is_file():
        raise ValueError('Pinned caller interpreter absent')
    manifest = read(checked(read(checked(spec['isolation_binding']))['manifest']))
    isolation = read(checked(spec['isolation_binding']))
    expected_caller=Path(isolation['root'])/'scripts/modal_b06_full_episode.py'
    if args.caller.resolve()!=expected_caller.resolve() or args.caller_sha256!=manifest['source_sha256']['scripts/modal_b06_full_episode.py']:
        raise ValueError('Executed caller must match reviewed isolation-root manifest')
    if isolation['commit']!=spec['reviewed_commit']:
        raise ValueError('Review/spec/execution commit differs')
    for name, digest in manifest['source_sha256'].items():
        checked(dict(path=str(Path(isolation['root'])/name),sha256=digest))
    recipe = checked(spec['recipe_manifest'])
    for name, digest in read(recipe)['files'].items():
        checked(dict(path=str(recipe.parent/name),sha256=digest))
    launcher=checked(dict(path=str(args.project_root/'scripts/run_bounded_job.py'),sha256=BOUNDED_LAUNCHER_SHA))
    if args.execute:
        if Path(sys.prefix).resolve()!=Path(args.project_root/'training/.venv').resolve():
            raise ValueError('Use the project Training/Modal SDK interpreter')
        with urllib.request.urlopen(isolation['viewer_url']+'/api/sessions',timeout=10) as response:
            if response.status!=200:raise ValueError('Viewer is not ready before allocation')
        claims=Path(spec['claims_directory']);claims.mkdir(parents=True,exist_ok=True)
        test_path=claims/('.write-preflight-'+secrets.token_hex(8))
        try:
            with test_path.open('x') as probe:probe.write('CPU preflight; no episode claim')
        finally:test_path.unlink(missing_ok=True)
    own_sources=owned_sources(args.source_commit)
    return dict(case='B06',episode_seconds=None,provider_max_seconds=86400,
                training_source_commit=args.source_commit,owned_source_pins=own_sources,bounded_launcher=pin(launcher),
                queue_seconds=600,startup_seconds=480,request_seconds=600,
                retries=0,weights_download=False,gpu='RTX-PRO-6000',gpu_count=1,
                parser_patch=PATCH,counter_projection=projection,
                spec=pin(args.spec),caller=pin(args.caller),qualification_request=pin(args.request),
                source_sha256={p.name:sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')},
                serving_binding=pin(binding_path),caller_python=python), binding, spec


def prepare_live(output, qualification, projection, binding_pin, origin, run_id):
    """Pin actual installed-parser receipts; passing parity is supplied later."""
    life = qualification['platform_lifetime']
    deadline = validate_platform(life)
    if qualification['deadline'] != deadline or qualification['serving_session_id'] != run_id:
        raise ValueError('Actual fresh session/platform expiry differs')
    digest = sha256(canonical(projection)).hexdigest()
    if qualification['counter_projection_sha256'] != digest or qualification['parser_patch_sha256'] != PATCH['patch_sha256']:
        raise ValueError('Live parser/counter fingerprint differs')
    raw = qualification['parser_patch_receipt']
    manifest=raw['manifest']
    if len(manifest)!=1 or manifest[0]['original_sha256'] != PATCH['original_source_sha256'] or manifest[0]['patched_sha256'] != PATCH['patched_source_sha256'] or raw['vllm_source_patch_sha256'] != PATCH['patch_sha256']:
        raise ValueError('Actual installed parser source differs')
    regression = qualification['parser_regression']
    if regression['passed'] is not True or regression['serving_session_id'] != run_id or regression['patched_source_sha256'] != PATCH['patched_source_sha256']:
        raise ValueError('Actual installed parser regression failed')
    save(output/'parser-regression.json',regression)
    save(output/'parser-patch-receipt.json',dict(passed=True,serving_session_id=run_id,**PATCH,
         regression_receipt=pin(output/'parser-regression.json'),installation=raw))
    save(output/'server-identity.json',qualification)
    save(output/'deployment.json',dict(qualification=qualification,serving_session_id=run_id,
         deadline=deadline,platform_lifetime=life,server_identity=pin(output/'server-identity.json')))
    save(output/'processor-proof.json',dict(passed=True,official_processor=qualification['processor'],
         image_processor_sha256=qualification['identity']['image_processor_sha256'],
         qualification='Official cached processor geometry; image/history token parity independently required.'))
    return dict(pilot_id=run_id,serving_session_id=run_id,identity=qualification['identity'],
        platform_lifetime=life,gpu_deadline_utc=deadline,server_context=131072,isl=100000,
        serving_binding=binding_pin,deployment_receipt=pin(output/'deployment.json'),
        parser_patch_receipt=pin(output/'parser-patch-receipt.json'),
        processor_parity_proof=pin(output/'processor-proof.json'),
        relay_source=pin(HERE/'pilot_relay.py'),relay_base_url=origin+'/v1',base_url=origin+'/v1')


def admit_count_proof(proof, qualification, projection):
    if proof.get('passed') is not True or proof.get('ready') is not True:
        raise ValueError('Actual general parity failed; no B06 dispatch')
    for key in ('serving_session_id','deadline','platform_lifetime','identity','parser_patch_sha256','counter_projection_sha256'):
        if proof.get(key)!=qualification[key]:
            raise ValueError('General parity belongs to another deployment: '+key)
    if proof.get('runtime_projection')!=projection:
        raise ValueError('General parity projection differs')


def completed_episode(spec, run_id, caller, caller_sha256):
    """Read existing durable Events, allowing SQLite crashed-journal recovery.

    Exit124 may interrupt notification after a verified grade was committed.
    Neither the process exit code nor an unverified failure artifact is a verdict.
    """
    stem=Path(spec['claims_directory'])/sha256(run_id.encode()).hexdigest()
    database=stem.with_suffix('.sqlite')
    # mode=rw cannot create a missing database, but permits SQLite to roll back
    # an interrupted later notification transaction and expose committed grades.
    with closing(sqlite3.connect(database.as_uri()+'?mode=rw',uri=True,timeout=5)) as db:
        row=db.execute('SELECT state,payload FROM episodes WHERE suite=? AND id=?',
                       (run_id,'B06')).fetchone()
    if row is None or row[0]!='succeeded':
        raise ValueError('No durable verified B06 completion in Events')
    evidence=json.loads(row[1])
    completion=stem.with_name(stem.name+'-completion.json')
    completion_error=None
    completion_pin=None
    if completion.exists():
        try:receipt=read(completion)
        except json.JSONDecodeError as error:
            completion_error=str(error) # Interrupted non-atomic notification write.
        else:
            if receipt['evidence']!=evidence:
                raise ValueError('Completion receipt differs from durable Events')
            completion_pin=pin(completion)
    consumer=runpy.run_path(str(checked(dict(path=str(Path(caller).resolve()),sha256=caller_sha256))))
    verdict=consumer['verify_terminal'](evidence)
    metadata=read(Path(evidence['trace'])/'metadata.json')
    tags=metadata.get('tags')
    if (metadata.get('model')!='Qwen/Qwen3.8-27B-FP8' or metadata.get('driver')!='modal-real-model'
        or not isinstance(tags,list) or 'model' not in tags or 'scripted' in tags):
        raise ValueError('Completed trace is not the authorized real model episode')
    with (Path(evidence['trace'])/'steps.jsonl').open() as steps:
        responses=sum(json.loads(line).get('model_response') is not None for line in steps)
    if responses<1:raise ValueError('No actual model response in completed episode trace')
    return dict(model_episodes=1,model_responses=responses,task_verdict=verdict,
                completion_evidence=evidence,events_database=str(database),
                completion_receipt=completion_pin,completion_receipt_error=completion_error)


def execute(args, selected, binding, spec):
    # Import/build Modal resources only after local source admission. The image
    # uses the existing lock/cache; CPU preflight stops before GPU on mismatches.
    from dotenv import dotenv_values
    for key,value in dotenv_values(args.project_root/'.env').items():
        if key in ('MODAL_TOKEN_ID','MODAL_TOKEN_SECRET') and value:
            os.environ.setdefault(key,value)
    import modal
    import serving_worker as worker
    args.output.mkdir(parents=True,exist_ok=False)
    selected['uploaded_sources'] = {target:pin(source)['sha256'] for source,target in worker.EXTRA}
    selected['uploaded_sources'].update({'/opt/rl/'+name:pin(worker.OWN_TRAINING/'envs/rl'/name)['sha256'] for name in ('pyproject.toml','uv.lock')})
    if selected['uploaded_sources']['/opt/rl/uv.lock'] != binding['runtime']['lock_sha256']:
        raise ValueError('Serving lock differs before allocation')
    save(args.output/'plan.json',selected)
    run_id=time.strftime('qwen-b06-fixed-%Y%m%d-%H%M%S-')+secrets.token_hex(4)
    token=secrets.token_urlsafe(32)
    report=dict(status='INCOMPLETE',run_id=run_id,model_episodes=0)
    with modal.enable_output(), worker.app.run():
        save(args.output/'app.json',dict(app_id=worker.app.app_id,url=worker.app.get_dashboard_url()))
        prepared=worker.cpu_prepare.remote(binding,selected['uploaded_sources'])
        save(args.output/'cache.json',prepared)
        with modal.Queue.ephemeral() as messages:
            call=worker.gpu_server.spawn(run_id,binding,prepared,token,messages,sha256(canonical(selected['counter_projection'])).hexdigest())
            with cleanup_gpu(call,messages,report,args.output/'report.json'):
                try:
                    save(args.output/'call.json',dict(call_id=call.object_id,run_id=run_id))
                    with Heartbeat(messages) as heartbeat:
                        started=messages.get(timeout=600,partition='events')
                        if started['phase']!='started':raise RuntimeError('Worker did not start: '+str(started))
                        save(args.output/'started.json',started)
                        ready=messages.get(timeout=520,partition='events')
                        if ready['phase']!='ready':raise RuntimeError('Worker failed before readiness: '+str(ready))
                        fresh=ready['qualification']
                        with serve(('127.0.0.1',0),upstream=ready['tunnel_url'],add_token=token,deadline=fresh['deadline']) as address:
                            origin='http://127.0.0.1:'+str(address[1])
                            save(args.output/'health-response.json',http(origin,'/health',timeout=10,expect_json=False))
                            live=prepare_live(args.output,fresh,selected['counter_projection'],selected['serving_binding'],origin,run_id)
                            env=child_environment()
                            command=[selected['caller_python'],'-B',str(HERE/'qualify_full.py'),
                              '--origin',origin,'--binding',selected['serving_binding']['path'],
                              '--identity',str(args.output/'server-identity.json'),'--output',str(args.output),
                              '--request',str(args.request),'--counter-source',spec['ordered_counter_source']['path']]
                            run_child(command,args.output/'qualification.log',cwd=args.project_root,env=env,
                                      heartbeat=heartbeat,platform_expiry=fresh['deadline'],operation_timeout=600)
                            proof=read(args.output/'readiness.json')
                            admit_count_proof(proof,fresh,selected['counter_projection'])
                            live.update(qualification_receipt=pin(args.output/'readiness.json'),
                                        complete_wire_count_parity_proof=pin(args.output/'readiness.json'),dispatch_authorized=True)
                            save(args.output/'live.json',live)
                            heartbeat.check()
                            report['episode_invocations']=1
                            report['model_episodes']=None # Unknown until actual trace/completion evidence.
                            save(args.output/'episode-dispatch.json',dict(at=time.time(),case='B06',spec=selected['spec'],live=pin(args.output/'live.json')))
                            command=[selected['caller_python'],'-B',str(args.caller),'--spec',str(args.spec),
                                     '--spec-sha256',args.spec_sha256,'--live',str(args.output/'live.json'),
                                     '--live-sha256',pin(args.output/'live.json')['sha256'],'--output',str(args.output/'B06')]
                            # No aggregate episode operation_timeout here.
                            command=[sys.executable,'-B',selected['bounded_launcher']['path'],
                                '--memory-mib','4096','--tasks','512','--receipt',str(args.output/'episode-bounds'),'--',*command]
                            try:
                                run_child(command,args.output/'episode.log',cwd=args.project_root,env=env,
                                          heartbeat=heartbeat,platform_expiry=fresh['deadline'])
                            except BaseException as error:
                                # Stop inference before inspecting potentially incomplete
                                # grade evidence. No episode/provider retry is possible.
                                report.update(caller_exit_code=getattr(error,'returncode',None),
                                              terminal_interruption=True)
                                try:messages.put('stop',timeout=5,partition='commands')
                                except Exception as stop_error:
                                    report['stop_notification_error']=type(stop_error).__name__
                                try:
                                    report.update(completed_episode(spec,run_id,args.caller,args.caller_sha256))
                                except Exception:
                                    report['completion_verification_error']=traceback.format_exc()
                                    raise error
                                if not isinstance(error,ChildFailure) or error.returncode!=124:
                                    raise
                            else:
                                report.update(completed_episode(spec,run_id,args.caller,args.caller_sha256))
                            report.update(status='MODEL_EPISODE_GRADED_AND_PROJECTED')
                except BaseException:
                    report.update(status='FAIL',error=traceback.format_exc())
                    raise
    if report['status']!='MODEL_EPISODE_GRADED_AND_PROJECTED':
        raise RuntimeError('Run/cleanup did not complete; inspect report')
    print(json.dumps({k:v for k,v in report.items() if k!='gpu_report'},indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,required=True)
    p.add_argument('--source-commit',required=True,help='Exact reviewed Training Git commit for this runner')
    for name in ('spec','caller','request'):
        p.add_argument('--'+name,type=Path,required=True)
        p.add_argument('--'+name+'-sha256',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--execute',action='store_true')
    args=p.parse_args()
    for name in ('project_root','spec','caller','request','output'):
        setattr(args,name,getattr(args,name).resolve())
    try:
        selected,binding,spec=plan(args)
    except BaseException:
        if args.execute and not args.output.exists():
            args.output.mkdir(parents=True)
            save(args.output/'startup-or-controller-failure.json',dict(status='FAIL',gpu_allocations=0,model_episodes=0,error=traceback.format_exc()))
        raise
    if not args.execute:
        print(json.dumps(selected,indent=2));return
    def interrupted(signum,frame):raise InterruptedError('Controller interrupted by signal '+str(signum))
    old={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:
        for sig in old:signal.signal(sig,interrupted)
        execute(args,selected,binding,spec)
    except BaseException:
        # Preserve early setup failures too; do not overwrite any prior report.
        args.output.mkdir(parents=True,exist_ok=True)
        error_path=args.output/'startup-or-controller-failure.json'
        if not error_path.exists():save(error_path,dict(status='FAIL',error=traceback.format_exc()))
        raise
    finally:
        for sig,handler in old.items():signal.signal(sig,handler)


if __name__=='__main__':main()
