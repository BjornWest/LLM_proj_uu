"""Isolated scripted lazy/full AX parity and latency experiment; no inference."""
import argparse
from collections import Counter
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import sys
import time


def write(path, value):
    path.write_text(json.dumps(value,indent=2,default=str))


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def child(args):
    sys.path.insert(0,str(args.source))
    from prototype import LazyAX, StaleTarget, UnsupportedStructure, semantic
    from playwright.sync_api import sync_playwright
    from browsergym.core import observation as bg
    from intent_browser.browser_events import BrowserEvents
    from environments.procedural_commerce.dense_preview import make_runtime
    output=args.output;output.mkdir(exist_ok=False,parents=True)
    checks=[];timings=[];captures=[]
    def check(name, passed, **detail):
        row={'name':name,'passed':bool(passed),**detail};checks.append(row)
        write(output/'checks-partial.json',checks)
        if not passed:raise AssertionError(name)
    def timed(name,fn):
        start=time.perf_counter();value=fn();timings.append({'phase':name,'seconds':time.perf_counter()-start})
        return value
    def full(page):
        bg._pre_extract(page)
        try:
            dom=bg.extract_dom_snapshot(page)
            tree=bg.extract_merged_axtree(page)
            bg.extract_dom_extra_properties(dom,1)
            bg.extract_focused_element_bid(page)
        finally:bg._post_extract(page)
        bg.extract_screenshot(page)
        return tree
    def projection(nodes, *, content_only=False):
        return Counter((n.get('role',{}).get('value',''),str(n.get('name',{}).get('value','')),
                        str(n.get('value',{}).get('value','')))
                       for n in nodes if not n.get('ignored') and not (
                           content_only and n.get('role',{}).get('value') in ('generic','LabelText')
                           and not n.get('name',{}).get('value') and not n.get('value',{}).get('value')))
    def controls(nodes):
        roles={'button','checkbox','radio','textbox','combobox','option','slider','spinbutton','switch','link'}
        return Counter(json.dumps(semantic(n),sort_keys=True) for n in nodes
                       if not n.get('ignored') and n.get('role',{}).get('value') in roles)
    runtime=None
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1280,'height':900})
        events=BrowserEvents();events.start(context);page=context.new_page()
        try:
            if args.case=='correctness':
                markup='''<main aria-label="Catalog"><h1>Catalog</h1>
                  <label>Delivery note <input id="note"></label>
                  <label><input id="agree" type="checkbox">Optional extra</label>
                  <section aria-label="Branch A"><button id="buyA">Buy</button></section>
                  <section aria-label="Branch B"><button id="buyB">Buy</button></section>
                  <button id="notice">Show notice</button><div id="messages"></div>
                  <div id="shadow"></div><div id="deep"></div></main>
                  <script>
                    window.clicks=[];buyA.onclick=()=>clicks.push('A');buyB.onclick=()=>clicks.push('B');
                    notice.onclick=()=>{const el=document.createElement('div');el.role='status';el.textContent='Saved successfully';messages.append(el);setTimeout(()=>el.remove(),40)};
                    shadow.attachShadow({mode:'open'}).innerHTML='<button>Shadow control</button>';
                    let p=deep;for(let i=0;i<12;i++){let d=document.createElement('div');p.append(d);p=d}
                    p.innerHTML='<button>Deep needle</button><p hidden>Secret invisible text</p>';
                  </script>'''
                # A real document navigation on a trustworthy loopback origin
                # runs existing init scripts (set_content on about:blank does not).
                page.route('http://127.0.0.1:48123/fixture',lambda route:route.fulfill(status=200,content_type='text/html',body=markup))
                page.goto('http://127.0.0.1:48123/fixture')
                lazy=LazyAX(page,events=events)
                overview=lazy.overview();check('overview declares incomplete coverage',not overview['complete_document'])
                unknown=lazy.search('Deep needle',role='button');check('global search finds unloaded deep node',unknown['total_matches']==1 and unknown['strategy']=='full_ax_fallback')
                check('hidden DOM text excluded from accessible search',lazy.search('Secret invisible text')['total_matches']==0)
                check('open shadow DOM search',lazy.search('Shadow control',role='button')['total_matches']==1)
                scope=lazy.search('Branch B',role='region')['items'][0]['ref']
                found=lazy.search('Buy',scope=scope,role='button')
                check('scoped duplicate labels distinguished',found['total_matches']==1)
                ref=found['items'][0]['ref'];token=lazy.prepare_target(ref);lazy.act(token)
                check('correct scoped button clicked once',page.evaluate('clicks')==['B'])
                children=lazy.children(scope,limit=1)
                check('lazy branch traversal includes scoped button',any(x['name']=='Buy' for x in children['items']))
                check('multi-term search',lazy.search(['Deep','Shadow'],role='button')['total_matches']==2)
                page.evaluate("()=>{const b=document.createElement('button');b.textContent='Newly inserted control';document.querySelector('main').append(b)}")
                check('new unloaded content discoverable',lazy.search('Newly inserted control',role='button')['total_matches']==1)
                page.get_by_text('Secret invisible text',exact=True).evaluate('el=>el.hidden=false')
                check('newly exposed content discoverable',lazy.search('Secret invisible text')['total_matches']>0)
                checkbox=lazy.search('Optional extra',role='checkbox')['items'][0]['ref']
                lazy.watch(checkbox);token=lazy.prepare_target(checkbox);lazy.act(token)
                changes=lazy.poll();check('checked change delivered',any(x.get('properties',{}).get('checked')=='true' for x in changes['changes']))
                note=lazy.search('Delivery note',role='textbox')['items'][0]['ref']
                lazy.watch(note);lazy.act(lazy.prepare_target(note),operation='fill',text='Leave at desk')
                check('input value change delivered',any(x.get('value')=='Leave at desk' for x in lazy.poll()['changes']))
                page.locator('#note').evaluate("el=>el.value='Changed via JS property'")
                check('property-only value change without mutation event',any(x.get('value')=='Changed via JS property' for x in lazy.poll()['changes']))
                box=lazy.geometry(note)['model'];check('targeted geometry without DOM snapshot',box['width']>0 and box['height']>0)
                token=lazy.prepare_target(ref);page.locator('#buyB').evaluate("el=>el.textContent='Delete account'")
                try:lazy.act(token);rejected=False
                except StaleTarget:rejected=True
                check('relabelled target rejected before mutation',rejected and page.evaluate('clicks')==['B'])
                newref=lazy.search('Delete account',role='button')['items'][0]['ref']
                token=lazy.prepare_target(newref);page.locator('#buyB').evaluate("el=>el.closest('section').setAttribute('aria-label','Different account')")
                try:lazy.act(token);rejected=False
                except StaleTarget:rejected=True
                check('changed ancestor rejects stale target',rejected)
                buy_a=lazy.search('Buy',role='button')['items'][0]['ref']
                token=lazy.prepare_target(buy_a);page.locator('#buyA').evaluate('el=>el.disabled=true')
                try:lazy.act(token);rejected=False
                except StaleTarget:rejected=True
                check('disabled target rejected',rejected and page.evaluate('clicks')==['B'])
                page.locator('#buyA').evaluate('el=>el.disabled=false')
                token=lazy.prepare_target(buy_a)
                page.evaluate("()=>{const d=document.createElement('div');d.id='cover';d.style='position:fixed;inset:0;z-index:99999;background:white';document.body.append(d)}")
                try:lazy.act(token,timeout=150);blocked=False
                except Exception as error:blocked=type(error).__name__=='TimeoutError'
                check('occlusion fails without forced click or replay',blocked and page.evaluate('clicks')==['B'])
                page.locator('#cover').evaluate('el=>el.remove()')
                newref=lazy.search('Delete account',role='button')['items'][0]['ref'];lazy.watch(newref)
                page.locator('#buyB').evaluate('el=>el.remove()')
                check('removed watched node unavailable',any(x.get('unavailable') for x in lazy.poll()['changes']))
                notice=lazy.search('Show notice',role='button')['items'][0]['ref']
                events.drain();lazy.act(lazy.prepare_target(notice));page.wait_for_timeout(80)
                event_result=lazy.poll()['events'];write(output/'transient-events.json',event_result)
                check('existing feedback retains short-lived notice','Saved successfully' in json.dumps(event_result))
                before_full=timed('full_capture',lambda:full(page));fresh=lazy.send('Accessibility.getFullAXTree')['nodes']
                write(output/'parity-difference.json',{'only_full':list((projection(before_full['nodes'])-projection(fresh)).items()),'only_lazy':list((projection(fresh)-projection(before_full['nodes'])).items())})
                check('named and control content parity with BrowserGym',projection(before_full['nodes'],content_only=True)==projection(fresh,content_only=True))
                check('control properties parity with BrowserGym',controls(before_full['nodes'])==controls(fresh))
                check('no DOM snapshot or screenshot in lazy path',not any(x['method'] in ['DOMSnapshot.captureSnapshot','Page.captureScreenshot'] for x in lazy.calls))
                stale=lazy.search('Deep needle',role='button')['items'][0]['ref']
                page.reload()
                try:lazy.inspect(stale);rejected=False
                except StaleTarget:rejected=True
                check('same URL reload invalidates references',rejected)
                stale=lazy.search('Deep needle',role='button')['items'][0]['ref']
                page.goto('data:text/html,<main><button>New document</button></main>')
                try:lazy.inspect(stale);rejected=False
                except StaleTarget:rejected=True
                check('navigation invalidates old references',rejected)
                page.set_content('<iframe srcdoc="<button>Frame child</button>"></iframe>');page.wait_for_timeout(50)
                try:lazy.overview();unsupported=False
                except UnsupportedStructure:unsupported=True
                check('frames explicitly require fallback',unsupported)
                full_frame=full(page)
                check('full BrowserGym fallback retains frame control',any(n.get('role',{}).get('value')=='button' and n.get('name',{}).get('value')=='Frame child' for n in full_frame['nodes']))
                write(output/'rpc.json',lazy.calls);lazy.close()
            else:
                runtime=make_runtime('large');state=runtime.snapshot()
                page.goto(runtime.origins['nordhem']+'/')
                if args.cards:
                    page.evaluate('''count=>{const root=document.createElement('section');root.setAttribute('aria-label','Stress listings');
                      for(let i=0;i<count;i++){const el=document.createElement('article');el.innerHTML='<h2>Stress product '+i+'</h2><p>Details '+i+'</p><button>Inspect '+i+'</button>';root.append(el)}document.body.append(root)}''',args.cards)
                # Ordinary generic controls used solely to test incremental feedback.
                page.evaluate('''()=>{const s=document.createElement('section');s.setAttribute('aria-label','Probe controls');s.innerHTML='<label><input id="profile-toggle" type="checkbox">Probe toggle</label>';document.body.prepend(s)}''')
                lazy=LazyAX(page,events=events)
                overview=timed('lazy_cold_overview',lazy.overview)
                check('bounded initial fetch on this fixture',overview['fetched_nodes']<500,fetched=overview['fetched_nodes'])
                if args.cards:
                    branch=next(n for n in lazy.nodes.values() if n.get('name',{}).get('value')=='Stress listings')
                    wide=timed('lazy_wide_branch',lambda:lazy.children(lazy.ref(branch),limit=20))
                    write(output/'wide-branch.json',wide)
                # Locate one DOM node to bootstrap the targeted cost experiment,
                # not a hidden policy capability. Global discovery is timed below.
                root=lazy.send('DOM.getDocument',{'depth':0})['root']['nodeId']
                node=lazy.send('DOM.querySelector',{'nodeId':root,'selector':'#profile-toggle'})['nodeId']
                partial=lazy.send('Accessibility.getPartialAXTree',{'nodeId':node,'fetchRelatives':True})['nodes']
                lazy._store(partial)
                raw=next(x for x in partial if x.get('role',{}).get('value')=='checkbox')
                ref=lazy.ref(raw);lazy.watch(ref)
                for i in range(4):
                    # Alternate full/lazy order to reduce simple warmup bias.
                    operations=[('full_capture',lambda:full(page)),('lazy_watched_refresh',lazy.poll)]
                    if i%2:operations.reverse()
                    for name,fn in operations:
                        value=timed(name,fn)
                        if name=='full_capture':captures.append(value)
                    token=lazy.prepare_target(ref)
                    timed('lazy_targeted_action',lambda:lazy.act(token))
                    changes=timed('lazy_after_action',lazy.poll)
                    expected='true' if i%2==0 else 'false'
                    check(f'checked feedback {i}',any(x.get('properties',{}).get('checked')==expected for x in changes['changes']))
                query='Stress product '+str(args.cards-1) if args.cards else 'Shop'
                found=timed('global_search_full_fallback',lambda:lazy.search(query,limit=100))
                # Independent expected substring semantics from full BrowserGym capture.
                oracle=full(page)
                expected=sum(not n.get('ignored') and query.casefold() in str(n.get('name',{}).get('value','')).casefold() for n in oracle['nodes'])
                check('whole-page search completeness',found['total_matches']==expected,expected=expected,actual=found['total_matches'])
                fresh=lazy.send('Accessibility.getFullAXTree')['nodes']
                write(output/'parity-difference.json',{'only_full':list((projection(oracle['nodes'])-projection(fresh)).items()),'only_lazy':list((projection(fresh)-projection(oracle['nodes'])).items())})
                check('named and control content parity',projection(oracle['nodes'],content_only=True)==projection(fresh,content_only=True))
                check('control properties parity',controls(oracle['nodes'])==controls(fresh))
                check('world unchanged',runtime.snapshot()==state)
                write(output/'rpc.json',lazy.calls)
                write(output/'overview.json',overview)
                write(output/'counts.json',dict(full_ax_nodes=len(oracle['nodes']),cold_fetched_nodes=overview['fetched_nodes'],synthetic_cards=args.cards))
                lazy.close()
            write(output/'result.json',dict(passed=all(c['passed'] for c in checks),checks=checks,
                timings=timings,model_calls=0,task_success=None,scope='experimental scripted observation parity'))
        finally:
            events.close();browser.close()
            if runtime:runtime.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path,default=Path('.local/generated-browser-profile-v3/source'))
    p.add_argument('--child',action='store_true');p.add_argument('--case',default='correctness')
    p.add_argument('--cards',type=int,default=0)
    p.add_argument('--correctness-only',action='store_true')
    args=p.parse_args();args.output=args.output.resolve();args.source=args.source.resolve()
    if args.child:return child(args)
    root=Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True,exist_ok=False)
    source=args.output/'source'
    for relative in ['intent_browser','environments/procedural_commerce']:
        shutil.copytree(args.source/relative,source/relative,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (source/'environments/__init__.py').touch()
    for name in ['run.py','prototype.py']:shutil.copy2(Path(__file__).parent/name,args.output/name)
    files={str(f.relative_to(args.output)):sha(f) for f in args.output.rglob('*') if f.is_file()}
    write(args.output/'manifest.json',dict(source_sha256=files,model_calls=0,recordings=False,
        note='Isolated experimental snapshot; production harness unchanged'))
    env={**os.environ,'LD_LIBRARY_PATH':str(root/'.local/system-libs/usr/lib/x86_64-linux-gnu'),
         'TOKENIZERS_PARALLELISM':'false','PYTHONDONTWRITEBYTECODE':'1'}
    def run(label,case,cards):
        cmd=[sys.executable,str(args.output/'run.py'),'--child','--source',str(source),
             '--output',str(args.output/label),'--case',case,'--cards',str(cards)]
        with (args.output/(label+'.log')).open('x') as f:
            process=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            try:code=process.wait(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait()
                raise RuntimeError(label+' timed out; dedicated process group stopped, evidence retained')
        if code:raise RuntimeError(label+' failed; inspect retained log')
        print(label,'passed',flush=True)
    # Independent correctness checks first; performance comparisons isolated to
    # avoid attributing competition for CPU to the chosen observation strategy.
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda i:run('correctness-'+str(i),'correctness',0),range(2)))
    if not args.correctness_only:
        for cards in [0,500,2000]:run('performance-'+str(cards),'performance',cards)
    write(args.output/'closure.json',dict(source_unchanged=all(sha(args.output/k)==v for k,v in files.items())))


if __name__=='__main__':main()
