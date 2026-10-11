"""Compose committed harness into accepted task trees; keep native data exact."""
from pathlib import Path
from hashlib import sha256
import subprocess,os,json,shutil,tempfile
P=Path('/home/bjorn/code/LLM_proj_uu');O=Path(__file__).resolve().parent
plan=json.loads((O/'source-plan-v1.json').read_text())
def git(*args,env=None,input=None):return subprocess.check_output(['git','-C',str(P),*args],env=env,input=input)
def pin(p):return {'path':str(p.resolve()),'sha256':sha256(p.read_bytes()).hexdigest()}
source=plan['source_hook_commit'];entries=[]
for line in git('ls-tree','-r',source,'intent_browser','scripts/episode_queue.py','scripts/episode_queue_channel.py').decode().splitlines():
 head,name=line.split('\t');mode,typ,blob=head.split();assert typ=='blob' and mode in ('100644','100755');entries.append((mode,blob,name))
roots={};mapping=[]
for c in plan['cases']:
 base=c['commit']
 if base not in roots:
  with tempfile.TemporaryDirectory() as d:
   env={**os.environ,'GIT_INDEX_FILE':str(Path(d)/'index')}
   git('read-tree',base,env=env)
   git('update-index','--index-info',env=env,input=''.join(f'{m} {b}\t{n}\n' for m,b,n in entries).encode())
   tree=git('write-tree',env=env).decode().strip()
   commit=git('commit-tree',tree,'-p',base,input=b'Compose reviewed queued runner into accepted MiMo task sources\n').decode().strip()
  root=O/'roots'/base[:8];root.parent.mkdir(exist_ok=True)
  git('worktree','add','--detach',str(root),commit)
  roots[base]=(root,commit)
 root,commit=roots[base]
 old=Path(c['recipe']);new=O/'recipes'/c['id'];shutil.copytree(old,new)
 m=json.loads((new/'manifest.json').read_text());original=json.loads((old/'manifest.json').read_text());changes={}
 for _,blob,name in entries:
  digest=sha256((root/name).read_bytes()).hexdigest();m['source_sha256'][name]=digest
 for name in m['source_sha256']:
  assert sha256((root/name).read_bytes()).hexdigest()==m['source_sha256'][name],name
 ep=new/'execution.private.json';v=json.loads(ep.read_text());before=json.loads((old/ep.name).read_text());v['source_sha256']=m['source_sha256'];ep.write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n')
 inverse=dict(v);inverse['source_sha256']=before['source_sha256'];assert inverse==before
 m['files'][ep.name]=sha256(ep.read_bytes()).hexdigest()
 (new/'manifest.json').write_text(json.dumps(m,indent=2,ensure_ascii=False)+'\n')
 for name in original['files']:
  if name!=ep.name:assert (old/name).read_bytes()==(new/name).read_bytes(),name
 c.update(original_root=c['root'],original_commit=base,original_recipe=c['recipe'],root=str(root),commit=commit,recipe=str(new),argument=str(new),recipe_manifest=pin(new/'manifest.json'))
 if 'source' in c['callable']:c['callable']['source']=pin(root/'environments'/Path(c['callable']['source']['path']).relative_to(Path(c['original_root'])/'environments'))
 mapping.append({'case':c['id'],'old_manifest':pin(old/'manifest.json'),'new_manifest':pin(new/'manifest.json'),'native_world_task_reference_and_other_bytes_unchanged':True,'execution_inverse':True,'source_root':str(root),'commit':commit})
plan['case_dependencies']={c['id']:[pin(Path(c['root'])/'scripts/product_width_watch.py'),pin(Path(c['root'])/'intent_browser/backend.py')] for c in plan['cases']}
plan['shared_inputs'].extend([pin(O/'compose.py')]);plan['helpers']=pin(Path('/home/bjorn/code/LLM_proj_uu-worktrees/eval-luna34-20261011-v1/scripts/luna_suite.py'))
(O/'composed-spec-v1.json').write_text(json.dumps(plan,indent=2,ensure_ascii=False)+'\n')
(O/'composition-v1.json').write_text(json.dumps({'harness_commit':source,'case_bindings':mapping,'source_files':[{ 'path':str(roots[next(iter(roots))][0]/n),'sha256':sha256((roots[next(iter(roots))][0]/n).read_bytes()).hexdigest()} for _,_,n in entries],'model_calls':0},indent=2)+'\n')
print(json.dumps({'roots':[(str(r),c) for r,c in roots.values()],'recipes':len(mapping),'native_bytes_unchanged':True}))
