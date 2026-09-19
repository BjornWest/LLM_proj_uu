"""Bounded new-profile positive/negative cases, independent of historical runs."""
import argparse
import json
from pathlib import Path
import sys
from data.curation.expansion.webarena.inventory import ROOT, BATCH
from data.curation.expansion.webarena.run_bounded import execute_case

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--task',type=int,choices=BATCH,action='append',required=True)
    parser.add_argument('--variant',choices=['positive','negative'],action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=150)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    executions=[];tasks=[]
    for task in args.task:
        for variant in args.variant:
            target=args.output/f'{task}-{variant}'
            command=[sys.executable,str(ROOT/'data/curation/expansion/webarena/native_case.py'),
                     '--task',str(task),'--variant',variant,'--output',str(target)]
            record=execute_case(command,args.output/f'{task}-{variant}.log',args.timeout)
            record.update(task_id=task,variant=variant);executions.append(record)
            if (target/'report.json').exists():tasks+=json.loads((target/'report.json').read_text())['tasks']
            (args.output/f'{task}-{variant}-execution.json').write_text(json.dumps(record,indent=2));print(json.dumps(record),flush=True)
    (args.output/'report.json').write_text(json.dumps({'schema':'webarena-native-browser-suite-v1','tasks':tasks,'executions':executions,'network_model_calls':0},indent=2))
if __name__=='__main__':main()
