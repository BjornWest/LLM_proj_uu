#!/usr/bin/env python3
"""Own serving/qualification lifetimes on an already allocated SSH host.

Plan is default. No provisioning, downloads, episode dispatch or credentials.
The reviewed Evaluation caller runs separately on this host after readiness;
its bound finish marker ends serving. Provider deletion stays on the workstation.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time
from uuid import UUID

sys.path.insert(0,str(Path(__file__).resolve().parent))
from qwen_suite_qualification import read_pin, pin, publish, process_identity, owned_listener, health


def load(row):return json.loads(read_pin(row))


class CleanupFailure(RuntimeError):
    """Terminal evidence is saved, but an owned service did not verify stopped."""


def verify_cache(spec, host, parent):
    cache=Path(spec['cache_root'])
    if (not cache.is_absolute() or not cache.is_dir() or cache.is_symlink()
            or cache.resolve()!=cache.absolute() or cache.stat().st_uid!=os.geteuid()
            or not os.access(cache,os.W_OK)):
        raise ValueError('Absolute owned writable ordinary cache directory required')
    for boundary in (host.resolve(),parent.resolve()):
        if cache.resolve().is_relative_to(boundary) or boundary.is_relative_to(cache.resolve()):
            raise ValueError('Cache must be separate from frozen sources and run outputs')
    for name in ('link-libs','vllm','triton'):
        child=cache/name
        if child.is_symlink() or (child.exists() and (not child.is_dir() or child.resolve()!=child.absolute())):
            raise ValueError('Ordinary cache write directory required: '+name)
    for child in cache.rglob('*'):
        if not child.is_symlink():continue
        # The reviewed compiler helper independently checks this read-only
        # library link against the actual pinned CUDA toolkit before use.
        if child==cache/'link-libs/libcudart.so':continue
        if not child.resolve().is_relative_to(cache.resolve()):
            raise ValueError('Cache descendant alias escapes private cache')


def rental_values(rental, now):
    for key in ('run_id','instance_id'):
        if str(UUID(rental[key]))!=rental[key]:raise ValueError('Canonical rental UUID required')
    seconds=rental['approved_rental_seconds'];start=rental['allocation_utc'];end=rental['deadline_utc']
    if (rental['run_id']==rental['instance_id'] or type(seconds) is not int or not 0<seconds<=86400
            or type(start) not in (int,float) or not math.isfinite(start)
            or type(end) not in (int,float) or not math.isfinite(end) or start+seconds!=end
            or not start<=now<end or rental.get('allocation_authorized') is not True):
        raise ValueError('Actual approved allocation-anchored finite rental required')
    return end


def verify_sources(spec):
    index=load(spec['host_source_export']['index'])
    root=index['roots'][spec['host_source_export']['root_id']]
    path=Path(spec['host_root'])
    if not path.is_absolute() or path.is_symlink():raise ValueError('Absolute ordinary host root required')
    for name,row in root['files'].items():
        target=path/name
        if target.resolve().is_relative_to(path.resolve()) is not True:raise ValueError('Host source escapes root')
        expected=0o755 if row['mode']=='100755' else 0o644
        if target.stat().st_mode&0o777!=expected:raise ValueError('Frozen mode differs: '+name)
        if target.is_symlink() or not target.is_file() or sha256(target.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Frozen host input differs: '+name)
    for key in ('rental','runtime','request','runtime_lock'):read_pin(spec[key])
    if spec.get('reuse_capability') is not None:read_pin(spec['reuse_capability'])
    needed=['serve_qwen_suite.py','qualify_qwen_wire.py','measure_qwen_host.py','qwen_suite_qualification.py','qwen_host_worker.py']
    if spec.get('execution_backend')=='container-monitored-v1':
        needed.append('qwen_container_services.py')
        read_pin(spec['container_launcher'])
    if any('training/scripts/'+name not in root['files'] for name in needed):
        raise ValueError('Complete reviewed worker scripts required in host export')


def unit_argv(spec, run, remaining):
    """Use systemd control-group cleanup: vLLM/NVCC children may create sessions."""
    if spec.get('execution_backend')=='container-monitored-v1':
        from qwen_container_services import launch_argv
        return launch_argv(spec,run,remaining,'qwen-'+run.name)
    memory=spec['server_memory_mib']
    if type(memory) is not int or not 49152<=memory<=65536:raise ValueError('Explicit serving cap48..64GiB required')
    if not math.isfinite(remaining) or remaining<1:raise TimeoutError('Rental ended')
    name='qwen-'+run.name
    entry=Path(spec['host_root'])/'training/scripts/serve_qwen_suite.py'
    env={'HOME':os.environ['HOME'],'USER':os.environ.get('USER',''),
         'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
         'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'}
    return ['/usr/bin/systemd-run','--user','--quiet','--service-type=exec','--unit='+name,
        '--property=RuntimeMaxSec='+str(remaining),'--property=MemoryMax='+str(memory<<20),
        '--property=MemorySwapMax=0','--property=KillMode=control-group','--property=TimeoutStopSec=10',
        '--property=StandardOutput=append:'+str(run/'vllm.log'),'--property=StandardError=inherit',
        '--property=WorkingDirectory='+str(run),'/usr/bin/env','-i',
        *[key+'='+value for key,value in env.items()],spec['rl_python'],'-I','-B',str(entry),
        '--snapshot',spec['snapshot'],'--receipt',str(run/'installed-serving.json'),'--cache-root',spec['cache_root'],
        '--max-num-seqs',str(spec.get('max_num_seqs',8))]


class Units:
    def call(self, argv, timeout=10):
        result=subprocess.run(argv,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=timeout)
        if result.returncode:raise RuntimeError('systemd operation failed: '+argv[1])
        return result.stdout

    def state(self,name):
        text=self.call(['/usr/bin/systemctl','--user','show',name,'--property=LoadState,ActiveState,MainPID,InvocationID,ControlGroup,WorkingDirectory'])
        return dict(line.split('=',1) for line in text.splitlines() if '=' in line)

    def stop(self,name,invocation,*,expected_directory=None):
        before=self.state(name)
        if before.get('LoadState')=='not-found':return
        if invocation is None and (expected_directory is None or before.get('WorkingDirectory')!=str(expected_directory)):
            raise ValueError('Unknown invocation is not bound to this run directory')
        if invocation is not None and before.get('InvocationID') not in ('',invocation):
            raise ValueError('Service invocation changed; do not stop another owner')
        self.call(['/usr/bin/systemctl','--user','stop',name],timeout=15)
        after=self.state(name)
        if after.get('MainPID','0')!='0' or after.get('ActiveState') not in ('inactive','failed'):
            raise RuntimeError('Serving service did not stop')


def run_command(argv, log, end, *, stopped=lambda:False):
    """Bound short qualification children; they never run browser episodes."""
    remaining=end-time.time()
    if remaining<=0 or stopped():raise TimeoutError('Rental ended/stopped before command')
    with log.open('xb') as output:
        os.chmod(log,0o600)
        child=subprocess.Popen(argv,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
                               start_new_session=True,env={k:v for k,v in os.environ.items() if k in ('HOME','USER','PATH','LANG')})
        try:
            while child.poll() is None:
                if stopped() or time.time()>=end:raise TimeoutError('Command exceeded original rental')
                time.sleep(.1)
            if child.returncode:raise RuntimeError('Qualification child failed; inspect '+str(log))
        finally:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=2)


def artifacts(root):
    """Stable worker evidence only; caller output is finalized by its own owner."""
    rows=[]
    allowed=('wire','measured','ready','qwen-'+root.name,'qwen-'+root.name+'-qualification')
    paths=list(root.iterdir())
    for child in tuple(paths):
        if child.name in allowed and child.is_dir() and not child.is_symlink():
            paths.extend(child.rglob('*'))
    for path in sorted(paths):
        relative=path.relative_to(root)
        if len(relative.parts)>1 and relative.parts[0] not in allowed:
            continue
        if path.is_symlink():raise ValueError('No symlinks in private artifact return')
        if not path.is_file():continue
        if path.name=='terminal-artifacts.json':continue
        digest=sha256()
        with path.open('rb') as stream:
            before=os.fstat(stream.fileno())
            while block:=stream.read(1<<20):digest.update(block)
            after=os.fstat(stream.fileno())
        current=path.stat()
        signature=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
        if signature(before)!=signature(after) or signature(after)!=signature(current):
            raise ValueError('Worker artifact changed while hashing: '+str(relative))
        rows.append({'path':str(relative),'sha256':digest.hexdigest(),'bytes':after.st_size})
    return {'schema':'qwen-worker-terminal-artifacts-v1','status':'worker_files_finalized',
        'scope':'Worker files only; caller subtree/final snapshots/grades require separate finalization',
        'excluded_subtrees':'All except wire/measured/ready and two own guardian receipts, including suite',
        'files':rows,'task_success_asserted':False}


def execute(spec, units=None, *, clock=time.time, sleep=time.sleep):
    if spec.get('execution_backend') not in (None,'systemd-v1','container-monitored-v1'):
        raise ValueError('Unknown serving execution backend')
    if units is None and spec.get('execution_backend')=='container-monitored-v1':
        from qwen_container_services import ContainerServices
        units=ContainerServices(spec)
    units=units or Units();rental=load(spec['rental']);end=rental_values(rental,clock())
    if 'microsoft' in platform.release().lower():raise ValueError('Execute on the approved Linux VM, not WSL')
    verify_sources(spec)
    if spec.get('dispatch_approval') is not None:read_pin(spec['dispatch_approval'])
    if spec.get('reuse_capability') is None and rental.get('qualification_authorized') is not True:
        raise ValueError('First-stack diagnostics require approval before GPU service starts')
    parent=Path(spec['output_parent'])
    if (not parent.is_absolute() or not parent.is_dir() or parent.is_symlink()
            or parent.stat().st_uid!=os.geteuid() or parent.stat().st_mode&0o077):
        raise ValueError('Private owned output parent required')
    host=Path(spec['host_root']).resolve()
    if parent.resolve().is_relative_to(host) or host.is_relative_to(parent.resolve()):
        raise ValueError('Runtime writes must remain outside frozen host sources')
    verify_cache(spec,host,parent)
    run=parent/rental['run_id'];run.mkdir(mode=0o700,exist_ok=False)
    name='qwen-'+rental['run_id'];started=False;invocation=None;stopped=[];owner=None
    original={}
    def stop(signum,_):stopped.append(signum)
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):original[sig]=signal.signal(sig,stop)
    result={'status':'failed','run_id':rental['run_id'],'instance_id':rental['instance_id'],
        'deadline_utc':end,'provider_billing_stopped':False,'task_success_asserted':False,
        'execution_backend':spec.get('execution_backend','systemd-v1')}
    try:
        if stopped:raise InterruptedError('Worker stopped before launch')
        if units.state(name).get('LoadState')!='not-found':raise ValueError('Service name already exists')
        command=unit_argv(spec,run,end-clock())
        started=True
        units.call(command,timeout=min(10,end-clock()))
        state=units.state(name);invocation=state['InvocationID'];pid=int(state['MainPID'])
        if not invocation or pid<=0:raise ValueError('Actual owned service process required')
        owner=process_identity(pid);owner_pin=publish(run/'serving-process.json',owner)
        startup=min(end,clock()+900)
        launch_path=run/'installed-serving.json'
        while True:
            if stopped or clock()>=startup:raise TimeoutError('Startup stopped/deadline; no retry')
            if process_identity(pid)!=owner:raise ValueError('Serving process replaced during startup')
            if launch_path.is_file():
                launch=load(pin(launch_path))
                if launch.get('status')=='failed':raise RuntimeError('Serving source guard failed')
                if launch.get('status')=='source_checks_passed_before_exec':
                    if launch.get('pid')!=pid:raise ValueError('Launch receipt owner differs')
                    try:
                        owned_listener(owner,8000)
                        if health('http://127.0.0.1:8000',timeout=min(2,startup-clock())):break
                    except (OSError,ValueError):pass
            sleep(.25)
        launch_pin=pin(launch_path)
        current={**rental,'serving_session_id':launch['attempt_id']}
        current_pin=publish(run/'rental.json',current)
        if spec.get('reuse_capability') is None:
            if rental.get('qualification_authorized') is not True:raise ValueError('First-stack diagnostics need separate approval')
            argv=[spec['rl_python'],'-I','-B',str(Path(spec['host_root'])/'training/scripts/qualify_qwen_wire.py')]
            for key,row in {'runtime':spec['runtime'],'request':spec['request'],'launch':launch_pin,'owner':owner_pin,'rental':current_pin}.items():
                argv+=['--'+key,row['path'],'--'+key+'-sha256',row['sha256']]
            argv+=['--snapshot',spec['snapshot'],'--deadline-utc',str(end),'--output',str(run/'wire'),'--execute']
            run_command(argv,run/'wire.log',end,stopped=lambda:bool(stopped))
            wire=pin(run/'wire/wire-proof.json')
        else:wire=None
        log=run/'startup-vllm.log'
        with (run/'vllm.log').open('rb') as stream:data=stream.read((4<<20)+1)
        if len(data)>4<<20:raise ValueError('Startup log exceeds evidence bound')
        log.write_bytes(data);log.chmod(0o600)
        context={'runtime':spec['runtime'],'launch':launch_pin,'owner':owner_pin,'rental':current_pin,
            'runtime_lock':spec['runtime_lock'],'startup_log':pin(log),'wire':wire,'reuse_capability':spec.get('reuse_capability')}
        context_pin=publish(run/'measurement-context.json',context)
        run_command([spec['rl_python'],'-I','-B',str(Path(spec['host_root'])/'training/scripts/measure_qwen_host.py'),
            '--context',context_pin['path'],'--context-sha256',context_pin['sha256'],'--output',str(run/'measured'),'--execute'],
            run/'measurement.log',end,stopped=lambda:bool(stopped))
        measured=load(pin(run/'measured/measurement-result.json'))
        approval=spec.get('dispatch_approval')
        binding={'schema':'qwen-fresh-instance-binding-v1','runtime':spec['runtime'],
            'capability':measured['capability'],'deployment':measured['deployment'],'launch':launch_pin,
            'raw_base_url':'http://127.0.0.1:8000','qualification_base_url':'http://127.0.0.1:8001','dispatch_approval':approval}
        binding_pin=publish(run/'qualification-binding.json',binding)
        # Own the small adapter through a separate deadline-bounded service.
        adapter=name+'-qualification'
        if spec.get('execution_backend')=='container-monitored-v1':
            from qwen_container_services import launch_argv
            command=launch_argv(spec,run,end-clock(),adapter,binding=binding_pin)
        else:
            command=unit_argv(spec,run,end-clock())
            command=[x.replace('--unit='+name,'--unit='+adapter).replace('--property=MemoryMax='+str(spec['server_memory_mib']<<20),'--property=MemoryMax='+str(512<<20)).replace(str(run/'vllm.log'),str(run/'qualification.log')) for x in command]
            index=command.index(spec['rl_python'])
            command=command[:index]+[spec['browser_python'],'-I','-B',str(Path(spec['host_root'])/'training/scripts/qwen_suite_qualification.py'),
                '--binding',binding_pin['path'],'--binding-sha256',binding_pin['sha256'],'--output',str(run/'ready')]
        if units.state(adapter).get('LoadState')!='not-found':raise ValueError('Adapter unit name already exists')
        adapter_started=True
        units.call(command,timeout=min(10,end-clock()))
        adapter_invocation=units.state(adapter)['InvocationID']
        if not adapter_invocation:raise ValueError('Adapter invocation not observed')
        ready_end=min(end,clock()+30)
        while not (run/'ready/adapter-ready.json').is_file():
            if stopped or clock()>=ready_end:raise TimeoutError('Qualification adapter startup failed')
            sleep(.1)
        if stopped:raise InterruptedError('Stopped during readiness publication')
        adapter_ready=load(pin(run/'ready/adapter-ready.json'))
        adapter_owner=process_identity(int(units.state(adapter)['MainPID']))
        if adapter_ready['process']!=adapter_owner:
            raise ValueError('Qualification readiness belongs to another process')
        result.update(status='serving_qualified',serving_session_id=launch['attempt_id'],live=pin(run/'ready/qualified-serving-live.json'))
        publish(run/'worker-ready.json',result);print(json.dumps(result),flush=True)
        # No episode is dispatched by this worker. Evaluation's reviewed caller
        # runs on this same host; a bound terminal marker ends our serving lifetime.
        next_unit_check=0
        while not stopped and clock()<end:
            if process_identity(pid)!=owner:raise ValueError('Serving process died/replaced')
            if process_identity(adapter_owner['pid'])!=adapter_owner:
                raise ValueError('Qualification process died/replaced')
            if clock()>=next_unit_check:
                for service,expected,identity in ((name,invocation,owner),(adapter,adapter_invocation,adapter_owner)):
                    state=units.state(service)
                    if (state.get('InvocationID')!=expected or state.get('MainPID')!=str(identity['pid'])
                            or state.get('ActiveState')!='active'):
                        raise ValueError('Owned service died/replaced: '+service)
                next_unit_check=clock()+1
            marker=run/'finish.json'
            if marker.is_file():
                finish=load(pin(marker))
                if any(finish.get(k)!=result[k] for k in ('run_id','instance_id','serving_session_id')):
                    raise ValueError('Finish marker belongs to another run')
                if finish.get('reason') not in ('completed','caller_failed','aborted'):raise ValueError('Typed terminal reason required')
                result.update(status='caller_terminal',finish=pin(marker));break
            sleep(.25)
        else:result['status']='stopped' if stopped else 'rental_deadline'
        return result
    except BaseException as error:
        result.update(status='failed',error_type=type(error).__name__,error=str(error));raise
    finally:
        # Record-only handlers keep repeated stop signals from interrupting evidence.
        errors=[]
        if locals().get('adapter_started'):
            try:units.stop(name+'-qualification',locals().get('adapter_invocation'),expected_directory=run)
            except BaseException as error:errors.append(type(error).__name__)
        if started:
            try:units.stop(name,invocation,expected_directory=run)
            except BaseException as error:errors.append(type(error).__name__)
        result.update(stop_signals=stopped,cleanup_errors=errors,serving_stopped=started and not errors)
        if errors:result['status']='cleanup_failed'
        try:
            publish(run/'worker-terminal.json',result)
            index=artifacts(run) if not errors else {
                'schema':'qwen-worker-terminal-artifacts-v1','status':'not_finalized',
                'reason':'Owned service cleanup failed; worker log may still be written',
                'files':[],'task_success_asserted':False}
            publish(run/'terminal-artifacts.json',index)
        finally:
            for sig,handler in original.items():signal.signal(sig,handler)
        if errors:raise CleanupFailure('Owned service cleanup failed; inspect worker-terminal.json')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True);parser.add_argument('--spec-sha256',required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    spec=load({'path':str(args.spec.absolute()),'sha256':args.spec_sha256})
    if spec.get('schema')!='qwen-ssh-serving-worker-v1':raise ValueError('Typed reviewed host worker spec required')
    if not args.execute:
        print(json.dumps({'status':'plan_only','model_or_cloud_actions':False,'steps':['owned systemd serving','optional approved once-only wire','actual installed/processor/backend measurement','qualification adapter','wait for external caller terminal','stop services and index artifacts'],'spec':pin(args.spec)}));return
    execute(spec)


if __name__=='__main__':main()
