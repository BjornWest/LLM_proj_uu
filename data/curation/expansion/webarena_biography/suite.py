"""Bounded, cached-image-only validation. Touches only the biography container."""
import argparse,base64,hashlib,json,os,subprocess,sys,time
from pathlib import Path
import urllib.request
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent
NAME='curation-webarena-biography-v1';ORIGIN='http://localhost:19099'
IMAGE='am1n3e/webarena-verified-reddit@sha256:0594908059a03e5f610005689440a95c05e776e734006197c7b1eba12734cb46'
def cmd(*a):return subprocess.check_output(a,text=True).strip()
def inspect():
 d=json.loads(cmd('docker','inspect',NAME))[0];assert d['Config']['Labels'].get('intent.owner')=='curation-biography' and not d['Mounts'];return d
def sql(query):return cmd('docker','exec',NAME,'su','postgres','-c','psql -d postmill -Atc "'+query+'"')
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 old=inspect();cmd('docker','rm','-f',NAME)
 cmd('docker','run','-d','--pull','never','--name',NAME,'--label','intent.owner=curation-biography','--label','intent.reset-scope=isolated-disposable','-p','127.0.0.1:19099:80','-p','127.0.0.1:19098:8877','-e','WA_ENV_CTRL_EXTERNAL_SITE_URL='+ORIGIN,'--memory','2g','--cpus','2',IMAGE)
 for _ in range(60):
  try:
   sql('SELECT 1');cmd('docker','exec',NAME,'env-ctrl','init','--base-url',ORIGIN);break
  except subprocess.CalledProcessError:time.sleep(1)
 else:raise RuntimeError('Owned server not ready')
 baseline=sql("SELECT encode(convert_to(COALESCE(biography,''),'UTF8'),'base64') FROM users WHERE username='MarvelsGrantMan136'").replace('\n','')
 warm=[]
 for path in ['/','/user/MarvelsGrantMan136','/user/MarvelsGrantMan136/edit_biography']:
  response=urllib.request.urlopen(urllib.request.Request(ORIGIN+path,headers={'X-Postmill-Auto-Login':'MarvelsGrantMan136:test1234'}),timeout=60);assert response.status==200;warm.append({'url':response.url,'status':response.status,'body_sha256':hashlib.sha256(response.read()).hexdigest()})
 setup={'image':IMAGE,'container_before':old['Id'],'container_after':inspect()['Id'],'baseline_biography_base64':baseline,'warm_gets':warm,'scope':'Fresh owned image; between cases restore only its original biography field. Full sites retained; warm GETs perform no policy actions.'}
 (a.output/'setup.json').write_text(json.dumps(setup,indent=2))
 rows=[]
 for variant in ['positive','wrong','correct-then-wrong','missing-final-read']:
  sql("UPDATE users SET biography=convert_from(decode('"+baseline+"','base64'),'UTF8') WHERE username='MarvelsGrantMan136'")
  assert sql("SELECT encode(convert_to(COALESCE(biography,''),'UTF8'),'base64') FROM users WHERE username='MarvelsGrantMan136'").replace('\n','')==baseline
  output=a.output/variant
  with (a.output/(variant+'.log')).open('x')as log:
   result=subprocess.run([sys.executable,str(HERE/'run.py'),'--variant',variant,'--output',str(output)],stdout=log,stderr=subprocess.STDOUT,timeout=240)
  row={'variant':variant,'returncode':result.returncode,'report':str(output/'report.json')}
  if (output/'report.json').exists():row['result']=json.loads((output/'report.json').read_text())
  rows.append(row);(a.output/'report.json').write_text(json.dumps({'schema':'webarena-biography-suite-v1','model_calls':0,'rows':rows,'complete':len(rows)==4,'passed':len(rows)==4 and all(r['returncode']==0 and r['result']['passed']for r in rows)},indent=2));print(variant,result.returncode,flush=True)
  if result.returncode:raise SystemExit(result.returncode)
if __name__=='__main__':main()
