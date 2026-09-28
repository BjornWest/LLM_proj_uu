"""Check a published connected world against a frozen generation scenario."""
import argparse,json
from pathlib import Path
from environments.connected_shopping.conformance import run


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scenario',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    report=run(json.loads(a.scenario.read_text()),a.runtime,a.output,a.workers)
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))
    for row in report['cases']:
        if not row['passed']:print(json.dumps(row))
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
