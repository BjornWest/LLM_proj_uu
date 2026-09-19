"""Bounded new-profile positive/negative cases, independent of historical runs."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
from pathlib import Path
import sys
from data.curation.expansion.webarena.inventory import ROOT
from data.curation.expansion.webarena.batch04_driver import BATCH, STATEFUL
from data.curation.expansion.webarena.run_bounded import execute_case

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--task',type=int,choices=BATCH,action='append',required=True)
    parser.add_argument('--variant',choices=['positive','negative'],action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--observation-chars',type=int,default=48000)
    parser.add_argument('--timeout',type=float,default=150)
    parser.add_argument('--workers',type=int,choices=range(1,5),default=2)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    executions=[];tasks=[]
    keys=[(task,variant) for task in args.task for variant in args.variant]
    if len(keys)!=len(set(keys)):raise ValueError('Duplicate task/variant')
    if any(task in STATEFUL for task,variant in keys) and args.workers!=1:
        raise ValueError('Shared-state cases must run with one worker')
    def one(key):
        task,variant=key
        target=args.output/f'{task}-{variant}'
        command=[sys.executable,str(ROOT/'data/curation/expansion/webarena/batch04_case.py'),
                 '--task',str(task),'--variant',variant,'--output',str(target),'--observation-chars',str(args.observation_chars)] + (['--allow-isolated-writes'] if task in STATEFUL else [])
        record=execute_case(command,args.output/f'{task}-{variant}.log',args.timeout)
        record.update(task_id=task,variant=variant)
        rows=json.loads((target/'report.json').read_text())['tasks'] if (target/'report.json').exists() else []
        (args.output/f'{task}-{variant}-execution.json').write_text(json.dumps(record,indent=2))
        return record,rows
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(one,key) for key in keys]):
            record,rows=future.result();executions.append(record);tasks.extend(rows)
            print(json.dumps(record),flush=True)
    executions.sort(key=lambda r:(r['task_id'],r['variant']))
    tasks.sort(key=lambda r:(r['task_id'],r['variant']))
    (args.output/'report.json').write_text(json.dumps({'schema':'webarena-native-browser-suite-v1','tasks':tasks,'executions':executions,'network_model_calls':0,'workers':args.workers},indent=2))
if __name__=='__main__':main()
