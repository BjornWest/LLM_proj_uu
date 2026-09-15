"""Explicit new environment revision; preserve catalog identities and old packages."""
import argparse,hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if os.path.lexists(a.output):raise FileExistsError(a.output)
 value=json.loads(a.base.read_text());build=ROOT/'.local/tricky-full-v1/build.json';b=json.loads(build.read_text())
 for task in value['tasks']:
  if task['kind']=='chaos':continue
  task.pop('revision');task['build']='tricky-full-v1';task['build_sha256']=sha(build);task['site_revision']=b['site_revision']
  paths={*task['source_sha256'],'intent_browser/tricky_full.py','intent_browser/tricky.py'}
  task['source_sha256']={p:sha(ROOT/p) for p in sorted(paths)}
  task['verification_scope']+=' Complete site restored; additional observed commits graded separately; unreviewed routes/patterns preserve unknown authorization. Shared full-site build in client and BrowserGym.'
  task['revision']=hashlib.sha256(json.dumps(task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(value,indent=2)+'\n')
if __name__=='__main__':main()
