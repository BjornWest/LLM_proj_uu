"""Isolated timing of the integrated path; simulated inference, not LLM episodes."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0,str(Path(__file__).parent))
from pipeline import IntegratedBrowser
from background import tree_signature


def wait(f):return f.result(timeout=45)
def write(path,value):path.write_text(json.dumps(value,indent=2))


def measure(output,cards):
    from environments.procedural_commerce.dense_preview import make_runtime
    runtime=make_runtime('large');initial=runtime.snapshot()
    def setup(page):
        page.goto(runtime.origins['nordhem']+'/')
        if cards:page.evaluate('''n=>{const root=document.createElement('section');
          for(let i=0;i<n;i++){const el=document.createElement('article');
            el.innerHTML='<h2>Stress product '+i+'</h2><p>Description '+i+'</p><button>Inspect '+i+'</button>';root.append(el)}
          document.body.append(root)}''',cards)
    b=IntegratedBrowser(setup,static_origins=runtime.origins.values());rows=[]
    try:
        wait(b.setup_future)
        for repeat in range(3):
            modes=['foreground_reference','cached_serial','cached_overlap']
            if repeat%2:modes.reverse()
            for mode in modes:
                wait(b.diagnostic(lambda w:setattr(w,'static_origins',frozenset() if mode=='foreground_reference' else frozenset(runtime.origins.values()))))
                started=time.perf_counter();t=b.observe();view=wait(t.initial);initial_time=time.perf_counter()-started
                if mode!='cached_overlap':wait(t.ready)
                time.sleep(.5) # Explicit isolated simulated decode interval.
                query='Stress product 1999' if cards else 'Shop'
                result=wait(b.search(t,query,limit=100));elapsed=time.perf_counter()-started
                meta=wait(t.ready);events=[e for e in b.log if e.get('epoch')==t.epoch]
                times={e['phase']:e['time'] for e in events}
                rows.append(dict(mode=mode,repeat=repeat,cards=cards,nodes=meta['nodes'],
                    initial_seconds=initial_time,full_seconds=times['full_published']-times['full_start'],
                    search_seconds=result['execution_seconds'],queue_seconds=result['queue_wait_seconds'],
                    total_seconds=elapsed,freshness=result['freshness'],matches=result['total_matches']))
                write(output/'samples.json',rows)
                assert result['total_matches']>0
                def parity(w):
                    saved=w.snapshots[t.ready.result()['snapshot_id']]['nodes']
                    return tree_signature(saved)==tree_signature(w.lazy.send('Accessibility.getFullAXTree')['nodes'])
                assert wait(b.diagnostic(parity))
        assert runtime.snapshot()==initial
        summaries=[]
        for mode in ['foreground_reference','cached_serial','cached_overlap']:
            subset=[r for r in rows if r['mode']==mode]
            summaries.append(dict(mode=mode,nodes=subset[0]['nodes'],**{
                key:statistics.median(r[key] for r in subset) for key in
                ['initial_seconds','full_seconds','search_seconds','queue_seconds','total_seconds']}))
        write(output/'result.json',dict(passed=True,model_calls=0,simulated_inference_seconds=.5,
            samples=len(rows),world_unchanged=True,all_foreground_parity=True,summary=summaries))
        write(output/'events.json',b.log)
    finally:b.close();runtime.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    # Intentional serial execution: isolate latency from competing test browsers.
    for cards in [0,2000]:
        out=a.output/str(cards);out.mkdir();measure(out,cards)


if __name__=='__main__':main()
