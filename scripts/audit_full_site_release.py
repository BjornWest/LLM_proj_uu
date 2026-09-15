"""Retained final artifact audit; no model/browser/network calls."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];LOCAL=ROOT/'.local/tricky-full-v1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 build=json.loads((ROOT/'environments/tricky_full/build-record.json').read_text());public=json.loads((ROOT/'environments/inspection_full/manifest.json').read_text());package=ROOT/'.local/environment-packages/portable-full-v2';p=json.loads((package/'manifest.json').read_text())
 assert public['site_revision']==build['site_revision']==p['derivation']['site_revision']
 assert public['files']==build['dist_sha256']
 for name,h in public['files'].items():assert sha(ROOT/'environments/inspection_full/dist'/name)==h==sha(package/'fixtures/tricky-full-v1/dist'/name)
 original=json.loads((ROOT/'.local/environment-packages/portable-v2/manifest.json').read_text());unchanged={}
 for prefix in ('chaos/','miniwob/','vendor/','resources/'):
  files={name:v for name,v in original['files'].items() if name.startswith(prefix)};assert files=={name:v for name,v in p['files'].items() if name.startswith(prefix)};unchanged[prefix]=len(files)
 reports={};artifact_checks=0
 for name in ['parity-final/report.json','client-final/report.json','acceptance-final/report.json','effects-final/report.json','container-final/positive/report.json','container-final/negative/report.json','container-final/manual/report.json']:
  path=LOCAL/name;r=json.loads(path.read_text());assert r['passed'],name
  for row in r.get('rows',[]):
   for file,h in row.get('files',{}).items():assert sha(ROOT/row['trace']/file)==h;artifact_checks+=1
  for row in r.get('cases',[]):
   for file,h in row.get('artifact_sha256',{}).items():assert sha(path.parent/'runs'/row['episode']/file)==h;artifact_checks+=1
  if any(row.get('artifacts') for row in r.get('cases',[])):
   code="const fs=require('fs'),crypto=require('crypto'),r=JSON.parse(fs.readFileSync('/evidence/report.json'));let n=0;for(const row of r.cases)for(const [file,h]of Object.entries(row.artifacts||{})){if(crypto.createHash('sha256').update(fs.readFileSync('/evidence/'+file)).digest('hex')!==h)throw Error('Artifact mismatch');n++}console.log(n)"
   artifact_checks+=int(subprocess.check_output(['docker','run','--rm','--network','none','--read-only','--entrypoint','node','-v',str(path.parent)+':/evidence:ro','intent-browser-control:full-sites-v2','-e',code],text=True))
  reports[str(path.relative_to(ROOT))]={'sha256':sha(path),'count':len(r.get('rows',r.get('cases',r.get('checks',[]))))}
 for name in ('runner.py','trace.py','observation.py','chaos.py','chaos_verifier.py'):
  assert sha(package/'runtime/intent_browser'/name)==sha(ROOT/'.local/environment-packages/portable-v2/runtime/intent_browser'/name)
 out={'schema_version':1,'status':'local_and_container_validated','site_revision':build['site_revision'],'source_revision':public['source_revision'],'source_files':len(build['source']['files']),'public_assets':len(public['files']),'public_bytes':sum((ROOT/'environments/inspection_full/dist'/name).stat().st_size for name in public['files']),'identical_client_native_asset_files':len(public['files']),'unchanged_package_families':unchanged,'package_sha256':sha(package/'manifest.json'),'reports':reports,'verified_recorded_artifact_hashes':artifact_checks,'model_calls':0,'training_eligibility_changed':False,'source_sha256':{str(f.relative_to(ROOT)):sha(f) for f in [ROOT/'config/team_tasks.json',ROOT/'environments/inspection_full/manifest.json',ROOT/'environments/tricky_full/build-record.json',ROOT/'intent_browser/tricky_full.py',ROOT/'intent_browser/tricky.py',ROOT/'intent_browser/tricky_privacy.py',ROOT/'intent_browser/tricky_membership.py',ROOT/'intent_browser/tricky_authorized.py']}}
 (ROOT/'config/full_site_validation.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({'site_revision':out['site_revision'],'reports':len(reports),'assets':len(public['files'])}))
if __name__=='__main__':main()
