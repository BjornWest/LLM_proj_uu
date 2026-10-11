"""Prepare a partial inventory from exact task/compiler pins and recorded sources."""
import argparse
import json
from pathlib import Path
from training.browser_training.suite_source_inventory import build_inventory


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--trace',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    plan=json.loads(args.plan.read_bytes())
    result=build_inventory(args.trace,task=plan['task'],compiled=plan['compiled'],
        inputs=plan.get('inputs',[]),source_inputs=plan.get('source_inputs',[]))
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')


if __name__=='__main__':main()
