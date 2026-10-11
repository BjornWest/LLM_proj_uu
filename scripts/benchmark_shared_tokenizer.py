"""Zero-provider Linux private-memory comparison, fresh independent processes.

This measures vocabulary sharing, not browser/world or whole-rollout memory.
No assets are downloaded. The foreground bounded wrapper owns all children.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def memory(pid):
    fields={}
    for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
        if ':' in line:
            key,value=line.split(':',1)
            if value.strip().endswith('kB'):fields[key]=int(value.strip().split()[0])*1024
    return {'private_bytes':sum(fields.get(k,0) for k in ('Private_Clean','Private_Dirty','Private_Hugetlb')),
            'rss_bytes':fields['Rss'],'pss_bytes':fields['Pss']}


def worker(args):
    from intent_browser.shared_tokenizer import SharedTokenizerConfig,load_tokenizer
    shared=SharedTokenizerConfig(args.socket) if args.worker=='shared' else None
    tokenizer=load_tokenizer(args.asset,shared=shared,normalization=args.normalization)
    ids=tokenizer.encode('Compare the price of two offers, including delivery. å 商品',add_special_tokens=False).ids
    token_digest=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()
    print(json.dumps({'pid':os.getpid(),'memory':memory(os.getpid()),'token_ids_sha256':token_digest,
                      'tokenizers_imported':'tokenizers' in sys.modules}),flush=True)
    sys.stdin.readline()  # Owner releases all clients after simultaneous memory sample.


def line(process, seconds=30):
    ready,_,_=select.select([process.stdout],[],[],seconds)
    if not ready:raise TimeoutError('Finite benchmark readiness exceeded')
    value=process.stdout.readline()
    if not value:raise RuntimeError('Benchmark child did not report readiness')
    return json.loads(value)


def run(args):
    from intent_browser.shared_tokenizer import asset_digest
    rows=[]
    for mode in ('local','shared'):
        children=[];service=None
        with tempfile.TemporaryDirectory() as directory:
            socket_path=str(Path(directory)/'tokens.sock')
            try:
                if mode=='shared':
                    manifest=Path(directory)/'assets.json'
                    manifest.write_text(json.dumps([{'path':str(Path(args.asset).resolve()),
                        'sha256':asset_digest(args.asset),'normalization':args.normalization}]))
                    service=subprocess.Popen([sys.executable,'-B','-m','intent_browser.tokenizer_service',
                        '--socket',socket_path,'--manifest',str(manifest),'--max-clients',str(args.workers)],cwd=ROOT,stdout=subprocess.PIPE,text=True)
                    children.append(service)
                    if line(service).get('ready') is not True:
                        raise RuntimeError('Tokenizer host did not report readiness')
                workers=[subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),
                    '--worker',mode,'--asset',args.asset,'--normalization',args.normalization,
                    '--socket',socket_path],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
                    for _ in range(args.workers)]
                children.extend(workers)
                results=[line(p) for p in workers]
                # All children are now loaded/alive; USS counts exclude shared pages.
                for result in results:result['memory']=memory(result['pid'])
                shared_memory=memory(service.pid) if service else None
                rows.append({'mode':mode,'workers':results,'service':shared_memory,
                    'workers_private_bytes':sum(r['memory']['private_bytes'] for r in results),
                    'service_private_bytes':shared_memory['private_bytes'] if shared_memory else 0})
                for process in workers:
                    process.stdin.write('\n');process.stdin.flush();process.communicate(timeout=5)
            finally:
                for process in children:
                    if process.poll() is None:process.terminate()
                for process in children:
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    assert len({w['token_ids_sha256'] for row in rows for w in row['workers']})==1
    assert all(not r['tokenizers_imported'] for r in rows[1]['workers'])
    for row in rows:row['total_private_bytes']=row['workers_private_bytes']+row['service_private_bytes']
    report={'scope':'Tokenizer vocabulary infrastructure only; fresh independent Python processes, no browser/world/model.',
            'asset_sha256':asset_digest(args.asset),'normalization':args.normalization,'worker_count':args.workers,
            'measure':'Linux smaps_rollup private clean+dirty+hugetlb; RSS/PSS also retained per process',
            'results':rows,'private_bytes_saved':rows[0]['total_private_bytes']-rows[1]['total_private_bytes'],
            'token_ids_parity':True,'model_dispatches':0,'downloads':0}
    with Path(args.output).open('x') as destination:json.dump(report,destination,indent=2);destination.write('\n')
    print(json.dumps({'output':args.output,'private_bytes_saved':report['private_bytes_saved']}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset',required=True)
    parser.add_argument('--normalization',choices=['raw','ascii-json'],default='raw')
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--output')
    parser.add_argument('--worker',choices=['local','shared'],help=argparse.SUPPRESS)
    parser.add_argument('--socket',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.worker:worker(args)
    else:
        if not 2<=args.workers<=8 or not args.output:parser.error('Need 2–8 workers and exclusive output path')
        run(args)


if __name__=='__main__':main()
