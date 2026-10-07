"""Serial actual browser smoke for revised words; zero providers/world draws."""
from contextlib import contextmanager
from hashlib import sha256
import json, os, signal, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
REPO=Path('/home/bjorn/code/LLM_proj_uu')
CASE=sys.argv[1]
if CASE not in {'old-address','missing-optional-unit'}:raise ValueError('Unknown finite case')
OUT=HERE/'binding-smoke-v1'
OUT.mkdir(exist_ok=True)
read=lambda p:json.loads(Path(p).read_bytes())
def save(p,v):
    with Path(p).open('x') as f:json.dump(v,f,indent=2,ensure_ascii=False)
def pin(p):
    p=Path(p).resolve();return {'path':str(p),'sha256':sha256(p.read_bytes()).hexdigest()}
plan=read(HERE/'plan.private.json')
prepared=read(HERE/'prepared-ready-v1.json')
inputs=prepared['inputs']+[prepared[k] for k in ('driver','supervisor','plan')]
def checked_inputs():
    for r in inputs:
        if pin(r['path'])!=r:raise ValueError('Changed smoke source/input: '+r['path'])
checked_inputs()
from worktree_gate import require_promoted_worktree
require_promoted_worktree(plan)
ROOT=Path(plan['source_archive']).resolve()
recovery=read(plan['recovery_receipt']['path'])
for name,h in {**recovery['original_source_sha256'],**recovery['supplemental_sha256']}.items():
    p=ROOT/name
    if p.is_symlink() or not p.resolve().is_relative_to(ROOT) or pin(p)['sha256']!=h:raise ValueError('Changed runtime source/data')
sys.dont_write_bytecode=True
sys.path[:]=[str(ROOT),str(HERE)]+[p for p in sys.path if Path(p or '.').resolve() not in {ROOT,HERE,REPO}]
os.environ['LD_LIBRARY_PATH']=str(REPO/'.local/system-libs/usr/lib/x86_64-linux-gnu')
os.environ['HARNESS_AX_TOKENIZER']=str(REPO/'.local/website-38-concept-world-20261006-v1/assets/tokenizer.json')
from environments.website_world import atomic_address_execution,generation,runtime
from experiments.accepted_catalog_commerce import package_export
for module in (atomic_address_execution,generation,runtime,package_export):
    if not Path(module.__file__).resolve().is_relative_to(ROOT):raise ValueError('Live source import')
for module in (generation,runtime,package_export):
    if module.ROOT!=ROOT:raise ValueError('Wrong runtime ROOT')
from grade_publication import publish_grade,viewer_health
viewer_health()
selected=next(c for c in plan['cases'] if c['case_id']==CASE)
APPROVAL=selected['authority_approval']
recipe=Path(selected['recipe'])
generation.load(recipe)
exec(compile((HERE/'browser_binding_case.py').read_bytes(),str(HERE/'browser_binding_case.py'),'exec'),globals())
try:
    result=browser_case(CASE,recipe)
    checked_inputs()
    for name,module in list(sys.modules.items()):
        if name.split('.')[0] in {'environments','experiments','intent_browser'}:
            source=getattr(module,'__file__',None)
            if source and not Path(source).resolve().is_relative_to(ROOT):raise ValueError('Live project entered smoke')
    save(OUT/(CASE+'-terminal.json'),{'status':'actual_revised_request_native_grade_viewer_pass','case':CASE,'check':pin(OUT/CASE/'check.json'),'provider_requests':0,'world_draws':0,'commit':plan['release']['commit'],'grading_scope':plan['grading_scope']})
    print(json.dumps({'case':CASE,'status':'pass','provider_requests':0,'native_verdict':result['native_verdict'],'scripted_calls':result['steps']}),flush=True)
except BaseException as e:
    save(OUT/(CASE+'-failure.json'),{'status':'system_failure','type':type(e).__name__,'error':str(e),'provider_requests':0})
    raise
