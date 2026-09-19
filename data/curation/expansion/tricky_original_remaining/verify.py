"""NEW original-task cohort through the frozen native-adoption wrapper.

Overrides exist only in this child process; historical wrapper bytes stay intact.
Uses its bounded subprocesses, MockTransport, source guards and fresh observation.
"""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from data.curation.expansion.runtime_snapshot import activate, fingerprints
FROZEN=activate()
from data.curation.expansion import adopt_tricky_native as base
from data.curation.expansion.tricky_original_remaining.tasks import RemainingTask
from data.curation.expansion.tricky_original_remaining.driver import Driver

original_hashes=base.hashes
def hashes():
    files=original_hashes()
    if FROZEN:
        files={k:v for k,v in files.items() if not k.startswith('intent_browser/')}
        files.update(fingerprints(FROZEN,ROOT))
    loader=ROOT/'data/curation/expansion/runtime_snapshot.py'
    files[str(loader.relative_to(ROOT))]=base.hashlib.sha256(loader.read_bytes()).hexdigest()
    for p in Path(__file__).parent.iterdir():
        if p.suffix in ('.py','.json'):files[str(p.relative_to(ROOT))]=base.hashlib.sha256(p.read_bytes()).hexdigest()
    return files


if __name__=='__main__':
    base.TASKS=[f'TO{i}' for i in range(15,22)]
    base.NativeAction=RemainingTask
    base.ActionDriver=lambda task,case,holder:Driver(task,case!='positive',holder)
    base.hashes=hashes
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--task',choices=base.TASKS);p.add_argument('--negative',action='store_true');p.add_argument('--child',action='store_true')
    a=p.parse_args()
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
    if a.child:
        if not a.task:p.error('Child requires task')
        raise SystemExit(0 if base.case(a.task,a.negative,a.output) else 1)
    a.output.mkdir(parents=True,exist_ok=False);rows=[]
    for tid in [a.task] if a.task else base.TASKS:
        for negative in (False,True):
            name=tid+('-negative' if negative else '-positive');target=a.output/name
            cmd=[sys.executable,'-m','data.curation.expansion.tricky_original_remaining.verify','--child','--task',tid,'--output',str(target)]
            if negative:cmd+=['--negative']
            execution=base.execute_case(cmd,a.output/(name+'.log'),120)
            path=target/'report.json';report=json.loads(path.read_text()) if path.exists() else {'passed':False}
            row={'task_id':tid,'negative':negative,'execution':execution,'report':str(path),'passed':report['passed'] and execution['returncode']==0};rows.append(row)
            (a.output/'report.json').write_text(json.dumps({'schema_version':1,'profile':'core-tools-v3','model_calls':0,'cases':rows,'passed':all(r['passed'] for r in rows)},indent=2)+'\n')
            print(json.dumps(row),flush=True)
            if not row['passed']:raise SystemExit('Stopped on failure; preserve evidence')
