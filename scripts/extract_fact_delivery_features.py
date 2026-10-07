#!/usr/bin/env python3
"""Extract opt-in renderer-native delivered-part features at a saved prefix."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.browser_training.fact_delivery_features import extract
from training.browser_training.fact_prefix_series import extract_prefixes
from training.browser_training.fact_compare_review_features import project, bind_obligations
from hashlib import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    prefix=parser.add_mutually_exclusive_group(required=True)
    prefix.add_argument('--step', type=int)
    prefix.add_argument('--all-prefixes', action='store_true')
    parser.add_argument('--recipient', default='main')
    parser.add_argument('--task', type=Path, help='Optional formal comparison/review task')
    parser.add_argument('--requirements', type=Path, help='Exact required-obligations.private.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if bool(args.task)!=bool(args.requirements):
        parser.error('--task and --requirements must be supplied together')
    result = extract_prefixes(args.trace,recipient=args.recipient) if args.all_prefixes else extract(args.trace, step=args.step, recipient=args.recipient)
    if args.task:
        task=json.loads(args.task.read_text())
        binding=bind_obligations(task,json.loads(args.requirements.read_text()))
        binding['artifacts']={name:{'path':str(path.resolve()),'sha256':sha256(path.read_bytes()).hexdigest()}
                              for name,path in [('task',args.task),('requirements',args.requirements)]}
        result['task_requirement_binding']=binding
        if args.all_prefixes:
            for prefix in result['prefixes']:
                prefix['required_observed']=project(task,prefix['native_coverage'])
            result['task_requirement_joins']='bounded_native_task_projection_runtime_unqualified'
        else:
            result['required_observed']=project(task,result)
    with args.output.open('x') as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'features': result.get('features'),
                      'diagnostics': result.get('diagnostics'),
                      'prefix_count':len(result.get('prefixes',[]))}))


if __name__ == '__main__':
    main()
