"""Ten controlled biography cases on a separate owned service; no paid calls.

Sequential because each case changes the same account's biography. The source
field is restored between cases; unrestricted model runs need full fresh reset.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent
NAME='curation-webarena-biography-batch02';ORIGIN='http://localhost:19089'
IMAGE='am1n3e/webarena-verified-reddit@sha256:0594908059a03e5f610005689440a95c05e776e734006197c7b1eba12734cb46'
def cmd(*args):return subprocess.check_output(args,text=True,stderr=subprocess.PIPE).strip()
def inspect():
    d=json.loads(cmd('docker','inspect',NAME))[0]
    assert d['Config']['Labels'].get('intent.owner')=='curation-biography-batch02' and not d['Mounts']
    assert d['HostConfig']['PortBindings']['80/tcp']==[{'HostIp':'127.0.0.1','HostPort':'19089'}]
    return d
def sql(query):
    inspect()
    return cmd('docker','exec','--user','postgres',NAME,'psql','-d','postmill','-Atc',query)
def dump(path,value):path.write_text(json.dumps(value,indent=2)+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    assert NAME not in cmd('docker','ps','-a','--format','{{.Names}}').splitlines(), 'Existing service requires separate ownership/reset review'
    cmd('docker','image','inspect',IMAGE)
    cmd('docker','run','-d','--pull','never','--name',NAME,'--label','intent.owner=curation-biography-batch02',
        '--label','intent.reset-scope=isolated-disposable','-p','127.0.0.1:19089:80','-p','127.0.0.1:19088:8877',
        '-e','WA_ENV_CTRL_EXTERNAL_SITE_URL='+ORIGIN,'--memory','2g','--cpus','2',IMAGE)
    for _ in range(90):
        try:
            sql('SELECT 1');cmd('docker','exec',NAME,'env-ctrl','init','--base-url',ORIGIN);break
        except subprocess.CalledProcessError:time.sleep(1)
    else:raise RuntimeError('Owned forum failed initialization; preserve container/logs')
    field="SELECT encode(convert_to(COALESCE(biography,''),'UTF8'),'base64') FROM users WHERE username='MarvelsGrantMan136'"
    baseline=sql(field).replace('\n','');warm=[]
    for path in ['/','/user/MarvelsGrantMan136','/user/MarvelsGrantMan136/edit_biography']:
        response=urllib.request.urlopen(urllib.request.Request(ORIGIN+path,headers={'X-Postmill-Auto-Login':'MarvelsGrantMan136:test1234'}),timeout=60)
        assert response.status==200
        warm.append({'url':response.url,'status':response.status,'body_sha256':hashlib.sha256(response.read()).hexdigest()})
    d=inspect();dump(a.output/'setup.json',{'image':IMAGE,'container_id':d['Id'],'image_id':d['Image'],
        'baseline_biography_base64':baseline,'warm_gets':warm,'model_calls':0,
        'isolation':'Separate complete source image; field restore only between controlled scripted cases. No shared19099/9999/18999 operations.'})
    cases=[(tid,variant) for tid in range(400,404) for variant in ['positive','wrong']]+[(400,'correct-then-wrong'),(400,'missing-final-read')]
    rows=[]
    for tid,variant in cases:
        sql("UPDATE users SET biography=convert_from(decode('"+baseline+"','base64'),'UTF8') WHERE username='MarvelsGrantMan136'")
        assert sql(field).replace('\n','')==baseline
        output=a.output/f'{tid}-{variant}'
        with (a.output/f'{tid}-{variant}.log').open('x') as log:
            result=subprocess.run([sys.executable,str(HERE/'run.py'),'--task',str(tid),'--variant',variant,'--output',str(output)],
                stdout=log,stderr=subprocess.STDOUT,timeout=240,env=os.environ.copy())
        row={'task_id':tid,'variant':variant,'returncode':result.returncode,'report':str(output/'report.json')}
        if (output/'report.json').exists():row['result']=json.loads((output/'report.json').read_text())
        rows.append(row)
        dump(a.output/'report.json',{'schema':'webarena-biography-batch02-suite-v1','model_calls':0,'rows':rows,
             'complete':len(rows)==len(cases),'passed':len(rows)==len(cases) and all(r['returncode']==0 and r['result']['passed'] for r in rows)})
        print(tid,variant,result.returncode,flush=True)
        if result.returncode:raise SystemExit(result.returncode)

if __name__=='__main__':main()
