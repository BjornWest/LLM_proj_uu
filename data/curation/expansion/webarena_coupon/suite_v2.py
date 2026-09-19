"""Two independent browser contexts at a time; no persistent site mutations."""
import argparse,json,os,subprocess,sys
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,CURATION_FROZEN_RUNTIME=str(ROOT/'.local/curation-expansion/frozen-runtime-v1'))
    keys=[(t,v) for t in range(689,694) for v in ['positive','wrong']]+[(689,v) for v in ['correct-then-wrong','abandon','blocked-submit','missing-capture','blank-name','wrong-email']]
    def one(key):
        tid,variant=key;name=f'{tid}-{variant}';target=a.output/name
        with (a.output/(name+'.log')).open('x') as log:
            try:rc=subprocess.run([sys.executable,str(HERE/'run_v2.py'),'--task',str(tid),'--variant',variant,'--output',str(target)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=150).returncode
            except subprocess.TimeoutExpired:rc=124
        report=target/'report.json'
        return {'task_id':str(tid),'variant':variant,'returncode':rc,'report':str(report),'passed':rc==0 and report.exists() and json.loads(report.read_text())['passed']}
    rows=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(one,k) for k in keys]):
            row=future.result();rows.append(row);print(json.dumps(row),flush=True)
            (a.output/'report.json').write_text(json.dumps({'schema':'webarena-coupon-suite-v2','complete':len(rows)==len(keys),'passed':len(rows)==len(keys) and all(r['passed'] for r in rows),'cases':rows,'model_calls':0,'workers':2},indent=2))
if __name__=='__main__':main()
