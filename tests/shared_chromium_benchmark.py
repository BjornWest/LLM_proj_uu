"""Explicit synthetic memory/startup measurement; no providers or world generation."""
import argparse
import json
import multiprocessing as mp
import os
from pathlib import Path
import time

import psutil
from shared_chromium_controls import worker
from intent_browser.chromium_pool import PoolSupervisor


def snapshot():
    processes=[psutil.Process(os.getpid())]+psutil.Process(os.getpid()).children(recursive=True)
    rows=[]
    for process in processes:
        try:
            memory=process.memory_full_info()
            rows.append({'pid':process.pid,'name':process.name(),'pss':memory.pss,'uss':memory.uss,
                         'rss':memory.rss,'threads':process.num_threads()})
        except psutil.NoSuchProcess:pass
    totals={name:sum(p[name]for p in rows)for name in ('pss','uss','rss','threads')}
    return {'processes':rows,'totals':totals,'semantics':'instantaneous descendant process sums; PSS proportions shared pages, RSS double-counts them'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['native','shared'],required=True)
    parser.add_argument('--workers',type=int,choices=[2,4,8],required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir()
    context=mp.get_context('spawn');supervisor=None;jobs=[];began=time.monotonic()
    try:
        descriptor=None
        if args.mode=='shared':
            supervisor=PoolSupervisor(args.output/'pool',max_leases=args.workers*2,per_server=args.workers)
            client=supervisor.start();descriptor=str(supervisor.descriptor_path)
        launch_started=time.monotonic()
        for i in range(args.workers):
            parent,child=context.Pipe();process=context.Process(target=worker,
                args=(descriptor,'world-'+str(i),child,args.mode=='shared'))
            process.start();child.close();jobs.append((process,parent))
        ready=[]
        for process,parent in jobs:
            if not parent.poll(60):raise TimeoutError('Worker did not become ready')
            ready.append(parent.recv())
        startup=time.monotonic()-launch_started
        assert all(x['ready']and x['title']=='world-'+str(i)for i,x in enumerate(ready))
        memory=snapshot()
        for _,parent in jobs:parent.send('act')
        for i,(_,parent)in enumerate(jobs):
            assert parent.poll(15)and parent.recv()['basket']=='world-'+str(i)
        for _,parent in jobs:parent.send('inspect')
        for i,(_,parent)in enumerate(jobs):
            assert parent.poll(15);state=parent.recv()
            assert state['basket']=='world-'+str(i)
            assert [x['value']for x in state['cookies']]==['world-'+str(i)]
        pool_status=client.status()if supervisor else None
        if pool_status:
            assert len(pool_status['leases'])==2*args.workers
            assert len(pool_status['groups'])==2
            for group in pool_status['groups']:
                assert len(supervisor.inspect_contexts(group['id'])['browserContextIds'])==args.workers
        for _,parent in jobs:parent.send('close')
        for process,_ in jobs:process.join(15);assert process.exitcode==0
        if supervisor:assert client.status()['leases']==[]
        result={'mode':args.mode,'workers':args.workers,'startup_seconds':startup,
                'total_seconds':time.monotonic()-began,'memory':memory,'pool':pool_status,
                'metadata':{'tags':['scripted']},'model_calls':0,'task_capability_claim':False,
                'settings':{'headless':True,'slow_mo':0,'video':False,'initial_capture':'native full DOM/AX/PNG',
                            'OPENBLAS_NUM_THREADS':os.environ.get('OPENBLAS_NUM_THREADS')},
                'limitations':['Small synthetic routed pages; no generated-world, RL, or34-episode qualification',
                               'One snapshot/run; timings include local contention, not isolated decode latency']}
        (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'mode':args.mode,'workers':args.workers,'startup_seconds':startup,'memory':memory['totals']}))
    finally:
        for process,parent in jobs:
            if process.is_alive():process.kill();process.join(10)
            parent.close()
        if supervisor:supervisor.close()


if __name__=='__main__':main()
