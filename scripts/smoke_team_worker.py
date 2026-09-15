"""Real local HTTP + BrowserGym worker smoke, scripted decisions, no model calls."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from uuid import uuid4
import zipfile
import httpx

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chaos-build',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    folder=(args.output or ROOT/'.local/team-worker'/('smoke-'+uuid4().hex[:8])).resolve()
    folder.mkdir(parents=True,exist_ok=False)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    origin=f'http://127.0.0.1:{port}'
    code=secrets.token_urlsafe(36);other_code=secrets.token_urlsafe(36)
    token=secrets.token_urlsafe(48)
    env={**os.environ,'PORT':str(port),'HARNESS_TEST_DATA':str(folder/'store'),
         'DEMO_SESSION_SECRET':secrets.token_urlsafe(48),
         'DEMO_INVITES_JSON':json.dumps({'alice':hashlib.sha256(code.encode()).hexdigest(),'bob':hashlib.sha256(other_code.encode()).hexdigest()}),
         'HARNESS_WORKER_TOKEN':token,'HARNESS_URL':origin,'HARNESS_MODE':'rehearsal',
         'HARNESS_DATA_DIR':str(folder/'worker')}
    for key in ('OPENROUTER_API_KEY','DAYLIGHT_OPENROUTER_API_KEY','MODEL_API_KEY','PARALLEL_API_KEY'):env.pop(key,None)
    if args.chaos_build:env['HARNESS_CHAOS_BUILD']=str(args.chaos_build.resolve())
    log=(folder/'server.log').open('w')
    server=subprocess.Popen(['node','tests/harness-server.mjs'],cwd=ROOT/'deploy/daylight',env=env,stdout=log,stderr=subprocess.STDOUT)
    client=httpx.Client(base_url=origin,headers={'Origin':origin},trust_env=False,timeout=30)
    checks=[];jobs=[]
    def check(name,condition):
        checks.append({'check':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    try:
        for _ in range(50):
            try:
                if client.get('/login').status_code==200:break
            except httpx.TransportError:pass
            time.sleep(.1)
        check('anonymous harness rejected',client.get('/api/harness/jobs').status_code==401)
        check('worker token missing rejected',client.post('/api/harness/worker/poll',json={}).status_code==401)
        check('login',client.post('/login',data={'code':code}).status_code==303)
        check('private harness UI',client.get('/harness').status_code==200)
        # Advertise known test capabilities; the actual worker claims/executes each job itself.
        tasks=['rooms']+(['chaos-confirmshaming'] if args.chaos_build else [])
        with httpx.Client(base_url=origin,headers={'Authorization':'Bearer '+token},trust_env=False) as machine:
            machine.post('/api/harness/worker/poll',json={'worker_id':str(uuid4()),'mode':'rehearsal','tasks':tasks}).raise_for_status()
        from intent_browser.demo import EXAMPLES
        for task in tasks:
            value={'task':task}
            if task=='rooms':value['goal']=EXAMPLES['booking']['goal']
            response=client.post('/api/harness/jobs',json=value);response.raise_for_status();job_id=response.json()['id']
            with (folder/(task+'-worker.log')).open('w') as out:
                result=subprocess.run([sys.executable,'-m','intent_browser.team_worker','--once'],
                    cwd=ROOT,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=180)
            check(task+' worker exit',result.returncode==0)
            job=client.get('/api/harness/jobs/'+job_id).json();jobs.append(job)
            check(task+' terminal',job['status']=='finished')
            check(task+' steps present',len(job['steps'])>0)
            check(task+' scripted explicit',job['mode']=='rehearsal')
            check(task+' independent safe success',job['evaluation']['safe_success'] is True)
            check(task+' remote screenshot',client.get(job['image']).status_code==200)
            step=job['steps'][0]
            check(task+' exact decision text',client.get(f'/api/harness/jobs/{job_id}/artifacts/'+step['artifact']['text']).status_code==200)
            issue=client.post(f'/api/harness/jobs/{job_id}/issues',json={'step':step['step'],'comment':'Smoke feedback: check this decision'}).json()
            check(task+' issue linked',issue['step']==step['step'] and issue['episode']==job['episode'])
            check(task+' feedback persisted',len(client.get('/api/harness/jobs/'+job_id).json()['issues'])==1)
            archive=client.get(f'/api/harness/jobs/{job_id}/trace');archive.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
                originals=folder/'worker/runs'/job['episode']
                for name in zipped.namelist():
                    file=originals.parent/name
                    check(task+' archive bytes '+name,zipped.read(name)==file.read_bytes())
                steps=[json.loads(line) for line in zipped.read(job['episode']+'/steps.jsonl').decode().splitlines()]
                check(task+' zero model requests',all(s.get('model_request') is None for s in steps))
                lifecycle=[json.loads(line)['event'] for line in zipped.read(job['episode']+'/events.jsonl').decode().splitlines()]
                check(task+' evaluate before close',lifecycle.index('evaluation_completed')<lifecycle.index('environment_close_started'))
                check(task+' feedback outside policy',all('Smoke feedback' not in json.dumps(s.get('messages')) for s in steps))
            client.post('/logout')
            client.post('/login',data={'code':other_code})
            check(task+' other invite denied',client.get('/api/harness/jobs/'+job_id).status_code==404)
            check(task+' other invite image denied',client.get(job['image']).status_code==404)
            client.post('/logout');client.post('/login',data={'code':code})
        report={'passed':True,'model_calls':0,'jobs':jobs,'checks':checks,
                'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                    ['intent_browser/team_worker.py','intent_browser/runner.py','deploy/daylight/lib/harness.mjs','deploy/daylight/api/index.mjs']}}
        (folder/'report.json').write_text(json.dumps(report,indent=2))
        print(json.dumps({'report':str(folder/'report.json'),'checks':len(checks),'passed':True}))
    finally:
        server.terminate();server.wait(timeout=10);client.close();log.close()

if __name__=='__main__':main()
