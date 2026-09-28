"""Real-browser background AX tests; simulated inference, no model calls."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time

from background import BackgroundBrowser, ObsoleteObservation
from prototype import StaleTarget


def write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str))


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def await_(future): return future.result(timeout=35)


MARKUP = '''<main aria-label="Catalog"><h1>Catalog</h1>
<section aria-label="A"><button id="a" onclick="clicks.push('A')">Buy</button></section>
<section aria-label="B"><button id="b" onclick="clicks.push('B')">Buy</button></section>
<label>Delivery note <input id="note" value="original"></label>
<div id="deep"><button id="deepbutton" onclick="clicks.push('deep')">Deep needle</button></div>
</main><script>window.clicks=[];for(let i=0;i<15;i++){let d=document.createElement('div');deep.parentNode.insertBefore(d,deep);d.append(deep)}</script>'''
URL = 'http://127.0.0.1:48124/test'


def fixture(page):
    page.route('http://127.0.0.1:48124/**', lambda route:route.fulfill(
        status=200, content_type='text/html', body=MARKUP))
    page.goto(URL)


def correctness(output):
    checks=[]; logs=[]
    def check(name, condition, **details):
        checks.append(dict(name=name, passed=bool(condition), **details))
        write(output/'checks.json',checks)
        if not condition: raise AssertionError(name)
    entered, release = threading.Event(), threading.Event()
    def hook(stage, browser):
        if stage=='before':
            entered.set()
            if not release.wait(10): raise TimeoutError('Test gate not released')
    b=BackgroundBrowser(fixture, capture_hook=hook)
    try:
        ticket=b.observe(); initial=await_(ticket.initial)
        check('shallow delivered before full capture completes',entered.wait(2) and not ticket.ready.done())
        check('shallow declares partial coverage',not initial['complete_document'])
        original=json.dumps(initial,sort_keys=True)
        search=b.search(ticket,'Deep needle',role='button')
        check('early tool waits while caller remains free',not search.done())
        release.set(); found=await_(search)
        check('early search finds previously unloaded node',found['total_matches']==1)
        check('snapshot search declares time scope','snapshot_not_live' in found['coverage'])
        check('background never mutates delivered shallow',json.dumps(initial,sort_keys=True)==original)
        full_before=await_(b.diagnostic(lambda w:sum(c['method']=='Accessibility.getFullAXTree' and c['returned_nodes']>10 for c in w.lazy.calls)))
        a=await_(b.search(ticket,'A',role='region'))['items'][0]['ref']
        scoped=await_(b.search(ticket,'Buy',role='button',scope=a))
        check('scoped duplicates remain distinct',scoped['total_matches']==1)
        await_(b.act(ticket,scoped['items'][0]['ref']))
        check('native action executes once',await_(b.diagnostic(lambda w:w.page.evaluate('clicks')))==['A'])
        try: await_(b.search(ticket,'Buy')); rejected=False
        except ObsoleteObservation: rejected=True
        check('action invalidates snapshot',rejected)
        check('cached searches make no additional full AX calls',await_(b.diagnostic(lambda w:sum(c['method']=='Accessibility.getFullAXTree' and c['returned_nodes']>10 for c in w.lazy.calls)))==full_before)
        t=b.observe();await_(t.ready)
        # A previously delivered same-document target remains usable while a
        # new observation warms its complete snapshot; the action still waits.
        deepref=await_(b.search(t,'Deep needle',role='button'))['items'][0]['ref']
        entered.clear();release.clear()
        t=b.observe();await_(t.initial);entered.wait(2)
        early_action=b.act(t,deepref)
        check('early native action waits for background AX',not early_action.done())
        release.set();await_(early_action)
        check('early native action executes exactly once after full publication',await_(b.diagnostic(lambda w:w.page.evaluate('clicks')))==['A','deep'])
        relevant=[e['phase'] for e in b.log if e.get('epoch')==t.epoch]
        check('capture precedes native dispatch',relevant.index('full_published')<relevant.index('action_start'))
        t=b.observe();await_(t.ready)
        note=await_(b.search(t,'Delivery note',role='textbox'))['items'][0]['ref']
        await_(b.diagnostic(lambda w:w.page.locator('#note').evaluate("el=>el.value='property-only change'")))
        try:await_(b.act(t,note,operation='fill',text='must not execute'));rejected=False
        except StaleTarget:rejected=True
        check('property-only stale action rejected',rejected and await_(b.diagnostic(lambda w:w.page.locator('#note').input_value()))=='property-only change')
        t=b.observe();await_(t.ready)
        ref=await_(b.search(t,'Deep needle',role='button'))['items'][0]['ref']
        await_(b.diagnostic(lambda w:w.page.locator('#deepbutton').evaluate("el=>el.textContent='Delete account'")))
        try:await_(b.act(t,ref));rejected=False
        except ObsoleteObservation:rejected=True
        check('DOM change rejects old snapshot before action',rejected and await_(b.diagnostic(lambda w:w.page.evaluate('clicks')))==['A','deep'])
        # Supersede while the old capture is in flight (after CDP reply but before publication).
        captured, continue_ = threading.Event(),threading.Event()
        def hold_after(stage,w):
            if stage=='after':
                captured.set()
                if not continue_.wait(10):raise TimeoutError('supersession gate')
        await_(b.diagnostic(lambda w:setattr(w,'capture_hook',hold_after)))
        old=b.observe();await_(old.initial);check('old capture held',captured.wait(5))
        new=b.observe(url=URL+'?new')
        continue_.set()
        try:await_(old.ready);rejected=False
        except ObsoleteObservation:rejected=True
        await_(new.ready)
        check('new navigation discards pending old snapshot',rejected and len(await_(b.diagnostic(lambda w:w.snapshots)))==1)
        try:await_(b.search(old,'Buy'));rejected=False
        except ObsoleteObservation:rejected=True
        check('old observation cannot search new document',rejected)
        # A mutation between full-tree response and publication must discard it.
        def mutate_after(stage,w):
            if stage=='after':w.page.locator('#b').evaluate("el=>el.textContent='Changed during capture'")
        await_(b.diagnostic(lambda w:setattr(w,'capture_hook',mutate_after)))
        t=b.observe();await_(t.initial)
        try:await_(t.ready);rejected=False
        except ObsoleteObservation:rejected=True
        check('mutation during capture cannot publish stale full snapshot',rejected)
        await_(b.diagnostic(lambda w:setattr(w,'capture_hook',None)))
        t=b.observe();await_(t.ready)
        check('explicit recapture recovers changed label',await_(b.search(t,'Changed during capture',role='button'))['total_matches']==1)
        # Background error remains visible to both readiness and tool callers.
        def fail(stage,w):
            if stage=='before':raise RuntimeError('injected capture failure')
        await_(b.diagnostic(lambda w:setattr(w,'capture_hook',fail)))
        t=b.observe();await_(t.initial)
        try:await_(b.search(t,'Buy'));rejected=False
        except RuntimeError as error:rejected=str(error)=='injected capture failure'
        check('capture errors propagate without automatic retry',rejected)
        check('failed captures never cause click replay',await_(b.diagnostic(lambda w:w.page.evaluate('clicks')))==[])
        check('all browser operations on one owner thread',len(set(x['thread'] for x in b.log))==1)
        check('browser owner differs from caller',b.owner_thread!=threading.get_ident())
        check('no automatic DOM snapshots or screenshots',not any(c['method'] in ('DOMSnapshot.captureSnapshot','Page.captureScreenshot') for c in await_(b.diagnostic(lambda w:w.lazy.calls))))
        logs.extend(b.log)
    finally:b.close()
    try:b.observe();rejected=False
    except RuntimeError:rejected=True
    check('closed worker refuses new observations',rejected)
    # Same-URL reload is independently rejected via document stamp.
    b=BackgroundBrowser(fixture)
    try:
        t=b.observe();await_(t.ready)
        await_(b.diagnostic(lambda w:w.page.reload()))
        try:await_(b.search(t,'Buy'));rejected=False
        except ObsoleteObservation:rejected=True
        check('external same-URL reload rejected',rejected)
        # Close while a new capture is pending.
        entered.clear();release.clear()
        await_(b.diagnostic(lambda w:setattr(w,'capture_hook',hook)))
        t=b.observe();view=await_(t.initial);entered.wait(2)
        close_future=ThreadPoolExecutor(1)
        closing=close_future.submit(b.close)
        deadline=time.monotonic()+2
        while not b.closed and time.monotonic()<deadline:time.sleep(.005)
        release.set();await_(closing);close_future.shutdown()
        try:await_(t.ready);rejected=False
        except ObsoleteObservation:rejected=True
        check('close during capture discards pending publication',rejected)
        logs.extend(b.log)
    finally:b.close()
    write(output/'events.json',logs)
    write(output/'result.json',dict(passed=True,checks=checks,model_calls=0))


def performance(output, source, cards):
    sys.path.insert(0,str(source))
    from environments.procedural_commerce.dense_preview import make_runtime
    runtime=make_runtime('large'); initial_state=runtime.snapshot()
    def setup(page):
        page.goto(runtime.origins['nordhem']+'/')
        if cards:
            page.evaluate('''count=>{const root=document.createElement('section');root.setAttribute('aria-label','Stress listings');
              for(let i=0;i<count;i++){const el=document.createElement('article');el.innerHTML='<h2>Stress product '+i+'</h2><p>Details '+i+'</p><button>Inspect '+i+'</button>';root.append(el)}document.body.append(root)}''',cards)
    b=BackgroundBrowser(setup)
    rows=[]
    try:
        await_(b.setup_future)
        query='Stress product '+str(cards-1) if cards else 'Shop'
        # Sequential for latency isolation. Alternate modes to avoid simple warmup bias.
        for delay in [0,.5,2.5]:
            for repeat in range(3):
                for mode in (['overlap','serial'] if repeat%2==0 else ['serial','overlap']):
                    start=time.perf_counter();t=b.observe();view=await_(t.initial);initial_at=time.perf_counter()
                    if mode=='serial':await_(t.ready)
                    inference_start=time.perf_counter()
                    time.sleep(delay) # Deliberately simulated inference, never a model claim.
                    inference_end=time.perf_counter()
                    found=await_(b.search(t,query,limit=20));end=time.perf_counter()
                    meta=await_(t.ready)
                    events=[x for x in b.log if x.get('epoch')==t.epoch]
                    stamps={x['phase']:x['time'] for x in events}
                    assert found['total_matches']>0 and not view['complete_document']
                    rows.append(dict(mode=mode,delay_seconds=delay,repeat=repeat,
                        initial_seconds=initial_at-start,
                        full_seconds=stamps['full_published']-stamps['full_start'],
                        inference_start_seconds=inference_start-start,
                        simulated_inference_seconds=inference_end-inference_start,
                        tool_wait_seconds=found['queue_wait_seconds'],
                        tool_compute_seconds=found['execution_seconds'],
                        total_seconds=end-start,full_nodes=meta['nodes'],
                        shallow_nodes=view['fetched_nodes'],matches=found['total_matches']))
                    write(output/'samples.json',rows)
        # Independent fresh full AX query on the same unchanged page, no cached search.
        oracle=await_(b.diagnostic(lambda w:w.lazy.search(query,limit=20)))
        assert all(r['matches']==oracle['total_matches'] for r in rows)
        assert runtime.snapshot()==initial_state
        write(output/'events.json',b.log)
        write(output/'rpc.json',await_(b.diagnostic(lambda w:w.lazy.calls)))
        grouped=[]
        for delay in [0,.5,2.5]:
            for mode in ['overlap','serial']:
                samples=[r for r in rows if r['mode']==mode and r['delay_seconds']==delay]
                grouped.append(dict(mode=mode,delay_seconds=delay,**{key:statistics.median(r[key] for r in samples)
                    for key in ['initial_seconds','full_seconds','tool_wait_seconds','tool_compute_seconds','total_seconds','full_nodes','shallow_nodes']}))
        write(output/'result.json',dict(passed=True,model_calls=0,simulated_inference=True,
            cards=cards,summary=grouped,samples=len(rows),world_unchanged=True,search_oracle_matches=True))
    finally:b.close();runtime.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path,default=Path('.local/generated-browser-profile-v3/source'))
    p.add_argument('--child',choices=['correctness','performance'])
    p.add_argument('--cards',type=int,default=0)
    p.add_argument('--correctness-only',action='store_true')
    args=p.parse_args();args.output=args.output.resolve();args.source=args.source.resolve()
    args.output.mkdir(parents=True,exist_ok=False)
    if args.child:
        if args.child=='correctness':correctness(args.output)
        else:performance(args.output,args.source,args.cards)
        return
    root=Path(__file__).resolve().parents[2];here=Path(__file__).parent
    source=args.output/'source'
    for rel in ['intent_browser','environments/procedural_commerce']:
        shutil.copytree(args.source/rel,source/rel,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (source/'environments/__init__.py').touch()
    for name in ['prototype.py','background.py','run_background.py']:shutil.copy2(here/name,args.output/name)
    files={str(f.relative_to(args.output)):sha(f) for f in args.output.rglob('*') if f.is_file()}
    import importlib.metadata
    versions={name:importlib.metadata.version(name) for name in ['playwright','browsergym-core']}
    write(args.output/'manifest.json',dict(source_sha256=files,versions=versions,model_calls=0))
    env={**os.environ,'LD_LIBRARY_PATH':str(root/'.local/system-libs/usr/lib/x86_64-linux-gnu'),
         'PYTHONDONTWRITEBYTECODE':'1','TOKENIZERS_PARALLELISM':'false'}
    def run(label,case,cards=0):
        with (args.output/(label+'.log')).open('x') as log:
            process=subprocess.Popen([sys.executable,str(args.output/'run_background.py'),'--child',case,
                '--output',str(args.output/label),'--source',str(source),'--cards',str(cards)],
                env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:code=process.wait(timeout=240)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait();raise RuntimeError(label+' timed out')
            if code:raise RuntimeError(label+' failed; retained log')
        print(label,'passed',flush=True)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda i:run('correctness-'+str(i),'correctness'),range(2)))
    if not args.correctness_only:
        for cards in [0,2000]:run('performance-'+str(cards),'performance',cards)
    write(args.output/'closure.json',dict(source_unchanged=all(sha(args.output/k)==v for k,v in files.items())))


if __name__=='__main__':main()
