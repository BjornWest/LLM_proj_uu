"""Derive a new immutable package, retaining the certified base browser loop.

No downloads. Does not mutate the base, historical certificates or traces.
"""
import argparse,copy,json,shutil,hashlib,os
from pathlib import Path
from intent_browser.environment_package import verify,inventory
from intent_browser.hosted_tasks import check_package
ROOT=Path(__file__).resolve().parents[1]
OVERLAY=['tricky.py','tricky_privacy.py','tricky_membership.py','tricky_authorized.py','tricky_full.py','team_worker.py','backend.py','openrouter.py','demo.py']
def main():
 p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--fixtures',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if os.path.lexists(a.output):raise FileExistsError(a.output)
 base=verify(a.base);check_package(a.fixtures);a.output.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(a.base,a.output)
 shutil.rmtree(a.output/'fixtures');shutil.copytree(a.fixtures,a.output/'fixtures')
 for name in OVERLAY:shutil.copy2(ROOT/'intent_browser'/name,a.output/'runtime/intent_browser'/name)
 shutil.copy2(ROOT/'config/team_tasks.json',a.output/'runtime/config/team_tasks.json')
 for name in ['verify_tricky_full.py','check_tricky_full_effects.py']:shutil.copy2(ROOT/'scripts'/name,a.output/'runtime/scripts'/name)
 value=copy.deepcopy(base);value['derivation']={'base_sha256':hashlib.sha256((a.base/'manifest.json').read_bytes()).hexdigest(),'scope':'Complete Tricky site replaces task-selected fixtures; certified base runner/Chaos closure retained byte-for-byte.','runtime_overlays':OVERLAY,'site_revision':json.loads((a.fixtures/'tricky-full-v1/build.json').read_text())['site_revision']}
 for d in value['datasets']:
  if d['id']=='trickyarena':d['scope']='Complete pinned site with original routes/layouts and shared state instrumentation; P07/P10/P11 derived verifiers only. Missing upstream media documented.';d['site_revision']=value['derivation']['site_revision']
 (a.output/'manifest.json').unlink();value['files']=inventory(a.output);(a.output/'manifest.json').write_text(json.dumps(value,indent=2)+'\n');verify(a.output)
 for name in ('runner.py','trace.py','observation.py','chaos.py','chaos_verifier.py'):
  assert (a.output/'runtime/intent_browser'/name).read_bytes()==(a.base/'runtime/intent_browser'/name).read_bytes()
 print(json.dumps({'package':str(a.output),'site_revision':value['derivation']['site_revision'],'files':len(value['files'])}))
if __name__=='__main__':main()
