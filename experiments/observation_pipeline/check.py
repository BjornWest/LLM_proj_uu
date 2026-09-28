"""Frozen-source integrated browser acceptance; no model calls or shared services."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).parent))
from pipeline import ROOT, IntegratedBrowser, ReadinessSpec, ObsoleteObservation
from background import tree_signature


def write(path,value):path.write_text(json.dumps(value,indent=2,default=str))
def await_(future):return future.result(timeout=40)


class Checks:
    def __init__(self,out):self.out,self.rows=out,[]
    def __call__(self,name,passed,**evidence):
        self.rows.append(dict(name=name,passed=bool(passed),**evidence));write(self.out/'checks.json',self.rows)
        if not passed:raise AssertionError(name)


def fresh(b,**kwargs):
    t=b.observe(**kwargs);await_(t.initial);await_(t.ready);return t


def target(b,t,term,role):
    found=await_(b.search(t,term,role=role,limit=100))
    exact=[n for n in found['items'] if n['name']==term]
    if len(exact)!=1:raise AssertionError(f'Ambiguous/missing {role} {term}: {found}')
    return exact[0]['ref']


def step(b,t,term,role,**kwargs):
    result=await_(b.step(t,target(b,t,term,role),**kwargs))
    next_=result['observation']
    if next_ is not None:await_(next_.initial);await_(next_.ready)
    return next_,result['receipt']


def parity(b,t,c,name):
    def inspect(w):
        snapshot=w.snapshots[t.ready.result()['snapshot_id']]
        before=w._stamp();live=w.lazy.send('Accessibility.getFullAXTree')['nodes'];after=w._stamp()
        return dict(equal=tree_signature(snapshot['nodes'])==tree_signature(live),
                    revision_equal=before==after==snapshot['stamp'],nodes=len(live),
                    fast_eligible=before['fast_eligible'])
    result=await_(b.diagnostic(inspect));c(name,result['equal'] and result['revision_equal'],**result)
    return result


STATIC='''<main><h1>Fixture</h1><label>Note <input id=note value=old></label>
<label><input id=check type=checkbox>Extra</label><button>Continue</button>
<a href=/next>Next page</a><style>#hidden{display:none}</style><button id=hidden>Hidden</button></main>'''
DYNAMIC='''<main id=app aria-busy=false><h1>Async fixture</h1><button id=update>Update</button>
<p id=status>Original</p><a href=/next>Next page</a></main><script>
document.querySelector('#update').onclick=()=>{
 window.calls=(window.calls||0)+1;
 const op=__intentReadinessV1.app.begin('content');
 document.querySelector('#app').setAttribute('aria-busy','true');
 setTimeout(()=>{document.querySelector('#status').textContent='Updated';
 document.querySelector('#app').setAttribute('aria-busy','false');
 __intentReadinessV1.app.end(op);},350);
};</script>'''


def fixture_tests(out):
    c=Checks(out)
    def setup(page):
        def route(r):
            dynamic='/dynamic' in r.request.url
            headers={} if dynamic else {'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'"}
            if '/override' in r.request.url:
                headers={'Content-Security-Policy':"script-src 'none'; script-src-elem 'unsafe-inline'"}
            r.fulfill(content_type='text/html',body=DYNAMIC if dynamic else STATIC,headers=headers)
        page.route('http://fixture.invalid/**',route);page.goto('http://fixture.invalid/')
    b=IntegratedBrowser(setup,static_origins=['http://fixture.invalid'])
    try:
        t=fresh(b);first=parity(b,t,c,'static initial foreground parity')
        c('explicit no-script origin eligible',first['fast_eligible'])
        def full_calls(w):return sum(x['method']=='Accessibility.getFullAXTree' for x in w.lazy.calls)
        before=await_(b.diagnostic(full_calls));await_(b.search(t,'Note'));await_(b.search(t,'Extra'))
        c('repeated searches do not recapture full AX',await_(b.diagnostic(full_calls))==before)
        for name,js,query,role in [
            ('property',"note.value='updated'",'Note','textbox'),
            ('checkbox','check.checked=true','Extra','checkbox'),
            ('cssom',"document.styleSheets[0].cssRules[0].style.display='block'",'Hidden','button'),
            ('focus','note.focus()','Note','textbox'),
        ]:
            await_(b.diagnostic(lambda w:w.page.evaluate(js)))
            try:await_(b.search(t,query));rejected=False
            except ObsoleteObservation:rejected=True
            c(name+' invalidates cache without foreground reread',rejected)
            t=fresh(b);parity(b,t,c,name+' recovery parity')
        await_(b.diagnostic(lambda w:w.page.evaluate('''() => {
          const s=document.createElement('style');s.textContent=
            '#hidden{display:none}@media (prefers-color-scheme:dark){#hidden{display:block}}';document.head.append(s);
        }''')))
        await_(b.diagnostic(lambda w:w.page.emulate_media(color_scheme='light')));t=fresh(b)
        await_(b.diagnostic(lambda w:w.page.emulate_media(color_scheme='dark')))
        try:await_(b.search(t,'Hidden'));rejected=False
        except ObsoleteObservation:rejected=True
        c('media-query changes invalidate cache',rejected)
        t=fresh(b);parity(b,t,c,'media-query recovery parity')
        t,receipt=step(b,t,'Next page','link')
        c('link navigation establishes new document readiness',receipt['document_replaced'] and receipt['readiness']['status']=='ready')
        parity(b,t,c,'navigation parity')
        old=t;t=fresh(b,reload=True)
        try:await_(b.search(old,'Note'));rejected=False
        except ObsoleteObservation:rejected=True
        c('same-url reload rejects previous observation',rejected)
        shot=await_(b.screenshot(t,out/'static.png',scope='main'))
        c('on-demand scoped screenshot ready',shot['status']=='ready',status=shot['status'])
        await_(b.diagnostic(lambda w:w.page.evaluate("document.querySelector('main').append(document.createElement('canvas'))")))
        t=fresh(b);shot=await_(b.screenshot(t,out/'uncertain.png',scope='main'))
        c('unsupported visuals remain inspectable and explicitly uncertain',shot['status']=='unknown' and shot['screenshot_saved'])

        t=fresh(b,url='http://fixture.invalid/dynamic')
        c('scripted page excluded from fast cache',not await_(b.diagnostic(lambda w:w._stamp()))['fast_eligible'])
        before=await_(b.diagnostic(full_calls));await_(b.search(t,'Update',role='button'))
        c('unknown app performs full validation',await_(b.diagnostic(full_calls))==before+1)
        spec=ReadinessSpec(scope='#app',signal_scope='content',timeout_ms=1500,
            condition={'kind':'text','selector':'#status','expected':'Updated'})
        t,receipt=step(b,t,'Update','button',spec=spec)
        c('async wait completes before observation',receipt['readiness']['status']=='ready' and receipt['readiness']['wait_seconds']>=.2)
        c('async action dispatched exactly once',await_(b.diagnostic(lambda w:w.page.evaluate('calls')))==1)
        c('next observation contains completed update',await_(b.search(t,'Updated'))['total_matches']>0)
        parity(b,t,c,'async completed parity')

        t=fresh(b,url='http://fixture.invalid/dynamic?timeout')
        limited=ReadinessSpec(scope='#app',signal_scope='content',timeout_ms=40)
        next_,receipt=step(b,t,'Update','button',spec=limited)
        c('pending wait withholds next ready observation',next_ is None and receipt['readiness']['status']=='pending')
        await_(b.diagnostic(lambda w:w.page.wait_for_function("document.querySelector('#status').textContent==='Updated'")))
        c('late completion is not replayed',await_(b.diagnostic(lambda w:w.page.evaluate('calls')))==1)
        t=fresh(b);parity(b,t,c,'late completion explicit recovery')
        t=fresh(b,url='http://fixture.invalid/override')
        c('script policy overrides disable fast path',not await_(b.diagnostic(lambda w:w._stamp()))['fast_eligible'])

        # Same URL with a changed response must not inherit its old cache policy.
        await_(b.diagnostic(lambda w:w.page.route('http://fixture.invalid/override',
            lambda r:r.fulfill(content_type='text/html',body=STATIC,
                              headers={'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'"}))))
        t=fresh(b,reload=True)
        c('new response independently qualifies',await_(b.diagnostic(lambda w:w._stamp()))['fast_eligible'])
        await_(b.diagnostic(lambda w:w.page.route('http://fixture.invalid/override',
            lambda r:r.fulfill(content_type='text/html',body=STATIC))))
        t=fresh(b,reload=True)
        c('same-url missing policy cannot inherit old qualification',not await_(b.diagnostic(lambda w:w._stamp()))['fast_eligible'])

        # Hold full capture; prove next model-facing shallow view and early tool order.
        entered,release=threading.Event(),threading.Event()
        def hold(stage,w):
            if stage=='before':
                entered.set()
                if not release.wait(5):raise TimeoutError('test gate not released')
        await_(b.diagnostic(lambda w:setattr(w,'capture_hook',hold)))
        t=b.observe();view=await_(t.initial);c('shallow visible before full completion',entered.wait(2) and not t.ready.done())
        pending=b.search(t,'Note');c('early tool waits for prefetched tree',not pending.done())
        release.set();c('early tool completes after prefetch',await_(pending)['total_matches']>0)
        await_(b.diagnostic(lambda w:setattr(w,'capture_hook',None)))
        write(out/'events.json',b.log);write(out/'receipts.json',b.receipts)
    finally:b.close()
    write(out/'result.json',dict(passed=True,checks=len(c.rows),model_calls=0))


def world_tests(out,cards):
    from environments.procedural_commerce.dense_preview import make_runtime
    c=Checks(out);runtime=make_runtime('large');origin=runtime.origins['nordhem']
    before_state=runtime.snapshot()
    def setup(page):page.goto(origin+'/products/shoe-42-black')
    b=IntegratedBrowser(setup,static_origins=runtime.origins.values())
    try:
        if cards:
            await_(b.diagnostic(lambda w:w.page.evaluate('''n=>{
              const root=document.createElement('section');root.setAttribute('aria-label','Stress listings');
              for(let i=0;i<n;i++){const el=document.createElement('article');
                el.innerHTML='<h2>Stress product '+i+'</h2><p>Description '+i+'</p><button>Inspect '+i+'</button>';root.append(el)}
              document.body.append(root);
            }''',cards)))
        t=fresh(b);initial=parity(b,t,c,'generated initial parity')
        c('generated no-script response eligible',initial['fast_eligible'])
        if cards:c('dense test exceeds 20000 AX nodes',initial['nodes']>20000,nodes=initial['nodes'])
        t,receipt=step(b,t,'Search the store','searchbox',operation='fill',text='shoe')
        c('fill waits and observes native value',receipt['readiness']['status']=='ready')
        parity(b,t,c,'generated fill parity')
        t,receipt=step(b,t,'Search','button')
        c('search navigation replaced document',receipt['document_replaced'])
        parity(b,t,c,'generated search results parity')
        # Publicly read destination from AX; return to known public product URL to
        # exercise explicit URL navigation as well as form navigation.
        t=fresh(b,url=origin+'/products/shoe-42-black')
        t,receipt=step(b,t,'View 2','radio')
        parity(b,t,c,'gallery CSS radio parity')
        t,receipt=step(b,t,'Add to cart','button')
        c('cart submission creates new document',receipt['document_replaced'])
        parity(b,t,c,'cart response parity')
        state=runtime.snapshot()
        c('exactly one cart quantity no order',state['carts']['nordhem']['quantity']==1 and not state['orders'])
        t,receipt=step(b,t,'Go to cart','link');parity(b,t,c,'cart navigation parity')
        c('other retailers unchanged',all(state['carts'][s]==before_state['carts'][s] for s in runtime.retailer_ids if s!='nordhem'))
        write(out/'events.json',b.log);write(out/'receipts.json',b.receipts)
        write(out/'final-state.json',runtime.snapshot())
        write(out/'rpc.json',await_(b.diagnostic(lambda w:w.lazy.calls)))
    finally:b.close();runtime.close()
    write(out/'result.json',dict(passed=True,checks=len(c.rows),model_calls=0,cards=cards))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case',choices=['fixture','world','dense']);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    if a.case:
        (fixture_tests(a.output) if a.case=='fixture' else world_tests(a.output,2000 if a.case=='dense' else 0));return
    paths=[*Path(__file__).parent.glob('*.py'),Path(__file__).with_name('revision.js'),
           ROOT/'experiments/lazy_observation/background.py',ROOT/'experiments/lazy_observation/prototype.py',
           ROOT/'experiments/readiness/visual.py',ROOT/'intent_browser/readiness.py',ROOT/'intent_browser/__init__.py',
           *sorted((ROOT/'environments/procedural_commerce').glob('*.py'))]
    snapshot=a.output/'source';hashes={}
    for path in paths:
        rel=path.relative_to(ROOT);dest=snapshot/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        raw=path.read_bytes();dest.write_bytes(raw);hashes[str(rel)]=hashlib.sha256(raw).hexdigest()
    write(a.output/'sources.json',hashes)
    def run(case):
        result=subprocess.run([sys.executable,str(snapshot/'experiments/observation_pipeline/check.py'),
            '--output',str(a.output/case),'--case',case],capture_output=True,text=True,timeout=180)
        (a.output/(case+'.log')).write_text(result.stdout+result.stderr)
        return dict(case=case,exit_code=result.returncode)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,['fixture','world','dense']))
    unchanged=all(hashlib.sha256((snapshot/rel).read_bytes()).hexdigest()==sha for rel,sha in hashes.items())
    passed=unchanged and all(r['exit_code']==0 for r in results)
    write(a.output/'result.json',dict(passed=passed,cases=results,snapshot_unchanged=unchanged,model_calls=0))
    print(json.dumps(results))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
