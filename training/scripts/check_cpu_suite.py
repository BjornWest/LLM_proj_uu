#!/usr/bin/env python3
"""Run existing lightweight training tests in bounded parallel shards; no downloads.

Optional framework tests may skip in the small environment; inspect report.json.
GPU/model/remote execution is not authorized or enabled by this command.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workers',type=int,choices=range(1,5),default=2)
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    output=(a.output or ROOT/'reports'/f'cpu-suite-{time.time_ns()}').resolve()
    output.mkdir(parents=True,exist_ok=False)
    files=sorted(ROOT.joinpath('tests').glob('test_*.py'))
    def execute(index):
        paths=files[index::a.workers]
        xml=output/f'shard-{index}.xml'
        with (output/f'shard-{index}.log').open('w') as stream:
            result=subprocess.run([sys.executable,'-m','pytest','-q',f'--junitxml={xml}',*[str(path) for path in paths]],
                                  cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        totals={key:0 for key in ('tests','errors','failures','skipped')}
        if xml.exists():
            for suite in ET.parse(xml).getroot().iter('testsuite'):
                for key in totals:totals[key]+=int(suite.attrib.get(key,0))
        totals['passed']=totals['tests']-totals['errors']-totals['failures']-totals['skipped']
        return dict(shard=index,exit_code=result.returncode,files=len(paths),**totals)
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        shards=list(pool.map(execute,range(a.workers)))
    report=dict(status='PASS' if all(r['exit_code']==0 for r in shards) else 'FAIL',shards=shards,
                passed=sum(r['passed'] for r in shards),skipped=sum(r['skipped'] for r in shards),output=str(output))
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return int(report['status']!='PASS')


if __name__=='__main__':raise SystemExit(main())
