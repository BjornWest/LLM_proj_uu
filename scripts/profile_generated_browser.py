"""No-inference profiling of frozen procedural storefronts and BrowserGym.

Creates isolated worlds, never touches existing servers, and records diagnostics
only (no task-success labels). Run from the repository with .venv/bin/python.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str))


def child(args):
    # Imports are from the frozen source, never the changing working tree.
    sys.path.insert(0, str(args.source))
    import browsergym.core.env as core
    from browsergym.core.task import AbstractBrowserTask
    from environments.procedural_commerce.dense_preview import make_runtime
    from intent_browser.ax_context import AXContext
    from intent_browser.ax_explorer import AXConfig
    from intent_browser.trace import Trace
    import psutil

    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    phases = []
    current = ['startup']
    handles = (output / 'phases.jsonl').open('x')

    def record(name, seconds, **extra):
        row = dict(stage=current[0], phase=name, seconds=seconds, **extra)
        phases.append(row)
        handles.write(json.dumps(row) + '\n'); handles.flush()

    def timed(name, fn):
        start = time.perf_counter()
        try:
            return fn()
        finally:
            record(name, time.perf_counter() - start)

    originals = {}
    for name in ('_pre_extract', '_post_extract', 'extract_dom_snapshot',
                 'extract_merged_axtree', 'extract_focused_element_bid',
                 'extract_dom_extra_properties', 'extract_screenshot'):
        originals[name] = getattr(core, name)
        def wrapped(*a, _name=name, **kw):
            return timed(_name, lambda: originals[_name](*a, **kw))
        setattr(core, name, wrapped)

    class Task(AbstractBrowserTask):
        def __init__(self, seed, url):
            super().__init__(seed); self.url = url

        def setup(self, page):
            page.goto(self.url)
            if args.extra_nodes:
                # Explicit synthetic structural stress, not generated products.
                page.evaluate('''count => {
                  const root=document.createElement('section');
                  root.setAttribute('aria-label','Synthetic profiling listings');
                  for(let i=0;i<count;i++) {
                    const article=document.createElement('article');
                    article.innerHTML='<h2>Profiling product '+i+'</h2><p>Item details and specifications '+i+'</p><button>Inspect '+i+'</button>';
                    root.append(article);
                  }
                  document.body.append(root);
                }''', args.extra_nodes)
            return 'Read-only scripted performance diagnostic.', {}

        def validate(self, page, chat_messages):
            return 0, False, '', {}

    runtime = env = trace = None
    records = []
    started = time.perf_counter()
    try:
        runtime = timed('world_start', lambda: make_runtime(args.scale))
        world_hash = hashlib.sha256(json.dumps(runtime._world, sort_keys=True).encode()).hexdigest()
        initial = runtime.snapshot()
        origin = runtime.origins['nordhem']
        env = core.BrowserEnv(task_entrypoint=Task, task_kwargs={'url': origin+'/'},
            headless=True, slow_mo=0, pre_observation_delay=args.delay,
            action_mapping=lambda code: code,
            wait_for_user_message=False, viewport={'width':1280,'height':900})
        obs, _ = timed('reset', lambda: env.reset(seed=7))
        explorer = timed('tokenizer_load', lambda: AXContext(AXConfig(
            tokenizer_path=str(args.tokenizer), overview_tokens=1000, incremental=True,
            revisit_reuse=True, agent_overview=True)))
        trace = Trace(output/'traces', {'scope':'scripted-performance-only', 'model_calls':0})
        for i in range(args.repeats):
            # Empty browser action isolates fixed wait and observation costs.
            current[0] = f'unchanged-{i}'
            obs, _, _, _, info = timed('step', lambda: env.step('pass'))
            timed('transition_render', lambda: explorer.overview(obs))
            timed('transition_trace_write', lambda: trace.observation(i,obs,''))
            obs = timed('decision_refresh', env._get_obs)
            text = timed('decision_index_and_overview', lambda: explorer.prepare_observation(obs))
            timed('decision_trace_write', lambda: trace.observation(i,obs,text,phase='decision'))
            explorer.acknowledge()
            records.append(dict(stage=current[0], raw_ax_nodes=len(obs['axtree_object']['nodes']),
                dom_nodes=sum(len(doc['nodes']['nodeName']) for doc in obs['dom_object']['documents']),
                overview_tokens=explorer.tokens(text), indexed_nodes=len(explorer.nodes),
                frames=len(env.page.frames), action_error=obs['last_action_error'],
                wait_seconds=info['wait_for_page_loading_stop']-info['wait_for_page_loading_start']))
        # Real document navigation as a separate measurement; stress appendage
        # is intentionally absent after navigation, and is not counted as dense.
        for i, path in enumerate(['/products/shoe-42-black','/cart']):
            current[0] = f'navigation-{i}'
            obs, _, _, _, info = timed('step', lambda p=path: env.step(f'page.goto({origin+p!r})'))
            records.append(dict(stage=current[0], raw_ax_nodes=len(obs['axtree_object']['nodes']),
                action_error=obs['last_action_error'], url_path=path))
        unchanged = initial == runtime.snapshot()
        write(output/'result.json', dict(ok=all(not r['action_error'] for r in records) and unchanged,
            phase_records=phases, observations=records, world_sha256=world_hash,
            state_unchanged=unchanged, server_count=len(runtime.servers), model_calls=0,
            scale=args.scale, extra_synthetic_cards=args.extra_nodes,
            pre_observation_delay=args.delay, slow_mo=0,
            elapsed_before_close=time.perf_counter()-started,
            task_completed=None, grading='not performed; read-only diagnostics',
            process_threads=psutil.Process().num_threads()))
    finally:
        current[0] = 'cleanup'
        if env: timed('browser_close', env.close)
        if runtime: timed('world_close', runtime.close)
        if trace:
            trace.events.close(); trace.lifecycle.close()
        handles.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path)
    p.add_argument('--child', action='store_true')
    p.add_argument('--scale', choices=['small','large'], default='large')
    p.add_argument('--extra-nodes',type=int,default=0)
    p.add_argument('--delay',type=float,default=.5)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--concurrency',type=int,nargs='+',default=[1,2,4,8])
    p.add_argument('--concurrency-extra-cards',type=int,default=0)
    p.add_argument('--skip-isolated',action='store_true')
    p.add_argument('--tokenizer',type=Path,default=Path('training/.cache/qwen38-tokenizer/tokenizer.json').resolve())
    args=p.parse_args();args.output=args.output.resolve()
    if args.child:
        return child(args)
    args.output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1]
    source=args.output/'source'
    source_root=args.source.resolve() if args.source else root
    for relative in ['intent_browser','environments/procedural_commerce']:
        shutil.copytree(source_root/relative,source/relative,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (source/'environments/__init__.py').touch()
    hashes={str(f.relative_to(source)):digest(f) for f in source.rglob('*') if f.is_file()}
    import browsergym.core,psutil
    bgroot=Path(browsergym.core.__file__).parent
    package_hashes={str(f.relative_to(bgroot)):digest(f) for f in bgroot.rglob('*') if f.suffix in ('.py','.js')}
    write(args.output/'manifest.json',dict(source_sha256=hashes, browsergym_sha256=package_hashes,
        profiler_sha256=digest(Path(__file__)),tokenizer_sha256=digest(args.tokenizer),
        source_root=str(source_root), concurrency=args.concurrency,
        concurrency_extra_cards=args.concurrency_extra_cards,
        design='Serial isolated phase comparisons, then parallel identical-world concurrency waves. No inference.',
        host_cpu_count=os.cpu_count(),host_memory=psutil.virtual_memory()._asdict()))
    shutil.copy2(__file__,args.output/'profiler.py')
    env={**os.environ,'LD_LIBRARY_PATH':str(root/'.local/system-libs/usr/lib/x86_64-linux-gnu'),
        'TOKENIZERS_PARALLELISM':'false','OMP_NUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1'}
    def run(label,scale='large',delay=.5,extra=0):
        cmd=[sys.executable,str(args.output/'profiler.py'),'--child','--source',str(source),
             '--output',str(args.output/label),'--scale',scale,'--delay',str(delay),
             '--extra-nodes',str(extra),'--tokenizer',str(args.tokenizer),'--repeats',str(args.repeats)]
        with (args.output/(label+'.log')).open('x') as log:
            result=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=150)
        if result.returncode:
            raise RuntimeError(f'{label} failed; see retained log')
        result=json.loads((args.output/label/'result.json').read_text())
        if not result['ok']:raise RuntimeError(f'{label} correctness check failed')
        print(label,'passed',flush=True)
        return label
    # These are intentionally isolated to identify per-stage cost, not independent
    # acceptance cases that benefit from competing for resources.
    if not args.skip_isolated:
        for label,scale,delay,extra in [('small-default','small',.5,0),('large-default','large',.5,0),
               ('large-zero-delay','large',0,0),('stress-500','large',0,500),('stress-2000','large',0,2000)]:
            run(label,scale,delay,extra)
    for n in args.concurrency:
        if not 1 <= n <= 32: raise ValueError('Concurrency must be 1..32')
        if psutil.virtual_memory().available < n*700_000_000:
            print('Stopping before memory pressure at concurrency',n,flush=True);break
        samples=[];stop=threading.Event();parent=psutil.Process()
        def sample():
            while not stop.wait(.2):
                descendants=parent.children(recursive=True);rss=0
                for proc in descendants:
                    try:rss+=proc.memory_info().rss
                    except psutil.Error:pass
                samples.append(dict(monotonic=time.monotonic(),child_rss_sum=rss,
                    process_count=len(descendants),available_memory=psutil.virtual_memory().available,
                    host_cpu_percent=psutil.cpu_percent(),host_swap=psutil.swap_memory()._asdict()))
        monitor=threading.Thread(target=sample,daemon=True);monitor.start();start=time.perf_counter()
        try:
            with concurrent.futures.ThreadPoolExecutor(n) as pool:
                labels=list(pool.map(lambda i:run(f'parallel-{n}-{i}','large',0,args.concurrency_extra_cards),range(n)))
        finally:stop.set();monitor.join()
        write(args.output/f'wave-{n}.json',dict(concurrency=n,wall_seconds=time.perf_counter()-start,
            cases=labels,samples=samples,rss_note='Summed RSS double-counts shared pages; whole-host available memory also recorded.'))
    write(args.output/'closure.json',dict(snapshot_unchanged=all(digest(source/k)==v for k,v in hashes.items()),
        working_source_changed=[k for k,v in hashes.items() if not (root/k).is_file() or digest(root/k)!=v],
        model_calls=0))


if __name__=='__main__':main()
