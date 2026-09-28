"""Scripted AX/visual acceptance in two independent browser processes; no inference."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments/lazy_observation'))
sys.path.insert(0,str(Path(__file__).parent))
from background import BackgroundBrowser, ObsoleteObservation, tree_signature, STAMP
from visual import capture_visual, wait_visual


def write(path,value):path.write_text(json.dumps(value,indent=2,default=str))
def wait(f):return f.result(timeout=20)


class Checks:
    def __init__(self,output):self.output,self.rows=output,[]
    def __call__(self,name,passed,**evidence):
        self.rows.append(dict(name=name,passed=bool(passed),**evidence))
        write(self.output/'checks.json',self.rows)
        if not passed:raise AssertionError(name)


HTML='''<style>#hidden {display:none}</style><main><h1>Catalog</h1>
<label>Note <input id="note" value="original"></label>
<label><input type=checkbox id=check>Insure</label>
<button id=buy onclick="clicks++">Buy</button><button id=hidden>Hidden offer</button>
<div id=other>Original</div></main><script>window.clicks=0</script>'''


def ax_tests(output):
    c=Checks(output)
    def setup(page):
        page.route('http://fixture.invalid/**',lambda r:r.fulfill(content_type='text/html',body=HTML))
        page.goto('http://fixture.invalid/start')
    b=BackgroundBrowser(setup,strict=True)
    try:
        def observe():t=b.observe();wait(t.ready);return t
        t=observe()
        c('insecure-origin document stamp available',bool(wait(b.diagnostic(lambda w:w.page.evaluate(STAMP)))['document']))
        found=wait(b.search(t,'Buy',role='button'))
        oracle=wait(b.diagnostic(lambda w:w.lazy.search('Buy',role='button')))
        c('unchanged strict search equals independent foreground search',found['items']==oracle['items'])
        c('strict result labels foreground validation',found['freshness']=='full_foreground_AX_equal_at_validation')
        wait(b.act(t,found['items'][0]['ref']))
        c('unchanged strict action executes exactly once',wait(b.diagnostic(lambda w:w.page.evaluate('clicks')))==1)

        for name,script,query in [
            ('value-property',"note.value='new value'",'new value'),
            ('checked-property','check.checked=true','Insure'),
            ('cssom',"document.styleSheets[0].cssRules[0].style.display='block'",'Hidden offer'),
            ('focus','note.focus()','Note'),
            ('dom-text',"other.textContent='Updated region'",'Updated region'),
        ]:
            t=observe();stamp=wait(b.diagnostic(lambda w:w.page.evaluate(STAMP)))
            wait(b.diagnostic(lambda w:w.page.evaluate(script)))
            after=wait(b.diagnostic(lambda w:w.page.evaluate(STAMP)))
            rejected=False
            try:wait(b.search(t,query))
            except ObsoleteObservation:rejected=True
            c(name+' stale snapshot rejected',rejected,dom_stamp_changed=stamp!=after)
            fresh=observe();result=wait(b.search(fresh,query))
            c(name+' explicit fresh capture recovers',result['total_matches']>0)
            saved=wait(b.diagnostic(lambda w:next(iter(w.snapshots.values()))['nodes']))
            full=wait(b.diagnostic(lambda w:w.lazy.send('Accessibility.getFullAXTree')['nodes']))
            c(name+' fresh full tree exactly equals foreground',tree_signature(saved)==tree_signature(full))

        t=observe();old=wait(b.diagnostic(lambda w:w.page.evaluate(STAMP)))
        wait(b.diagnostic(lambda w:w.page.reload()))
        try:wait(b.search(t,'Buy'));rejected=False
        except ObsoleteObservation:rejected=True
        c('same-url reload rejects old document',rejected)
        fresh=observe();new=wait(b.diagnostic(lambda w:w.page.evaluate(STAMP)))
        c('reload gets independent document identity',old['document']!=new['document'])
        c('new document usable after explicit fresh observation',wait(b.search(fresh,'Buy',role='button'))['total_matches']==1)

        def change(stage,w):
            if stage=='after':w.page.evaluate("other.textContent='Late update'")
        wait(b.diagnostic(lambda w:setattr(w,'capture_hook',change)))
        t=b.observe();wait(t.initial)
        try:wait(t.ready);rejected=False
        except ObsoleteObservation:rejected=True
        c('mutation during background capture discards result',rejected)
        wait(b.diagnostic(lambda w:setattr(w,'capture_hook',None)))
        t=observe()
        c('no action replay during recovery',wait(b.diagnostic(lambda w:w.page.evaluate('clicks')))==0)
        # Synthetic density parity, not a rerun of the historical generated world.
        wait(b.diagnostic(lambda w:w.page.evaluate('''() => {
          const root=document.createElement('section');
          for(let i=0;i<2000;i++) {
            const row=document.createElement('article');
            row.innerHTML='<h2>Listing '+i+'</h2><p>Description '+i+'</p><button>Inspect '+i+'</button>';
            root.append(row);
          }
          document.body.append(root);
        }''')))
        t=observe();saved=wait(b.diagnostic(lambda w:next(iter(w.snapshots.values()))['nodes']))
        result=wait(b.search(t,'Inspect 1999',role='button'))
        full=wait(b.diagnostic(lambda w:w.lazy.send('Accessibility.getFullAXTree')['nodes']))
        c('large tree exact foreground parity',len(saved)>20000 and tree_signature(saved)==tree_signature(full),nodes=len(saved))
        c('large tree deep result is found',result['total_matches']==1)
        write(output/'events.json',b.log)
    finally:b.close()
    write(output/'result.json',dict(passed=True,checks=len(c.rows),model_calls=0))


def visual_tests(output):
    from PIL import Image
    from playwright.sync_api import sync_playwright
    c=Checks(output);buffer=BytesIO();Image.new('RGB',(16,16),(12,180,70)).save(buffer,format='PNG')
    font=Path('/usr/share/fonts/fonts-go/Go-Regular.ttf').read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path.startswith('/slow'):time.sleep(.3)
            body=font if self.path.endswith('.ttf') else buffer.getvalue()
            code=404 if self.path=='/broken' else 200
            if code==404:body=b'not an image'
            self.send_response(code);self.send_header('Content-Type','font/ttf' if self.path.endswith('.ttf') else 'image/png')
            self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    evidence=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':800,'height':600})
            def run(name,markup,expected='ready',timeout=1500):
                page.set_content(markup,wait_until='domcontentloaded')
                result=capture_visual(page,output/(name+'.png'),scope='#region',timeout_ms=timeout)
                evidence.append(dict(name=name,**result));write(output/'visual.json',evidence)
                c(name,result['status']==expected,status=result['status'])
                if expected!='ready':c(name+' has no screenshot',(not result['screenshot_saved']) and not (output/(name+'.png')).exists())
                return result
            fast=run('plain','<main id=region><button>Continue</button></main>')
            c('plain requires no fixed 500ms delay',fast['before']['elapsed_ms']<500)
            delayed=run('delayed-image',f'<main id=region><img src="{origin}/slow.png" width=100 height=100></main>')
            c('delayed image actually waited',delayed['before']['elapsed_ms']>=200)
            pixel=Image.open(output/'delayed-image.png').convert('RGB').getpixel((40,40))
            c('saved screenshot contains decoded image',pixel==(12,180,70),pixel=pixel)
            fonts=run('delayed-font',f'<style>@font-face{{font-family:Probe;src:url({origin}/slow.ttf)}} #region{{font-family:Probe}}</style><main id=region>Waiting for local font</main>')
            c('font gate waits for loading',fonts['before']['elapsed_ms']>=200)
            animated=run('finite-animation','<style>@keyframes move{from{transform:translateX(0)}to{transform:translateX(120px)}}#box{animation:move .3s forwards}</style><main id=region><button id=box>Continue</button></main>')
            c('finite animation completes before capture',animated['before']['elapsed_ms']>=200)
            run('broken-image',f'<main id=region><img src="{origin}/broken" width=100 height=100></main>','failed')
            run('canvas-unsupported','<main id=region><canvas width=30 height=30></canvas></main>','unknown')
            run('busy-timeout','<main id=region aria-busy=true>Loading</main>','pending',100)
            run('offscreen','<main id=region style="margin-top:900px">Scroll to me</main>','unknown')
            outside=run('unrelated-animation','<style>@keyframes spin{to{transform:rotate(360deg)}}aside{animation:spin 1s infinite}</style><main id=region>Stable content</main><aside>Spinner</aside>')
            c('outside animation does not block scoped gate',outside['before']['elapsed_ms']<500)
            run('infinite-inside','<style>@keyframes spin{to{transform:rotate(360deg)}}span{display:block;animation:spin 1s infinite}</style><main id=region><span>Spinner</span></main>','unknown')
            # Test-only interference precisely between the precheck and screenshot.
            page.set_content('<main id=region>Before</main>')
            class ChangeOnCapture:
                def evaluate(self,*args,**kwargs):return page.evaluate(*args,**kwargs)
                def screenshot(self,*args,**kwargs):
                    page.locator('#region').evaluate("el=>el.textContent='After'")
                    return page.screenshot(*args,**kwargs)
            changed=capture_visual(ChangeOnCapture(),output/'changed.png',scope='#region')
            c('change across screenshot never labelled ready',changed['status']=='unknown' and changed['screenshot_saved'])
            evidence.append(dict(name='change-across-capture',**changed));write(output/'visual.json',evidence)
            page.route('http://visual.invalid/**',lambda r:r.fulfill(content_type='text/html',body='<main id=region>Identical</main>'))
            page.goto('http://visual.invalid/')
            class ReloadOnCapture(ChangeOnCapture):
                def screenshot(self,*args,**kwargs):
                    page.reload()
                    return page.screenshot(*args,**kwargs)
            reloaded=capture_visual(ReloadOnCapture(),output/'reload.png',scope='#region')
            c('identical new document cannot pass old screenshot check',reloaded['status']=='unknown' and reloaded['screenshot_saved'])
            evidence.append(dict(name='reload-across-capture',**reloaded));write(output/'visual.json',evidence)
            browser.close()
    finally:server.shutdown();server.server_close()
    write(output/'result.json',dict(passed=True,checks=len(c.rows),model_calls=0,
                                  font_sha256=hashlib.sha256(font).hexdigest()))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case',choices=['ax','visual']);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    if a.case:
        (ax_tests if a.case=='ax' else visual_tests)(a.output);return
    paths=[Path(__file__),ROOT/'experiments/readiness/visual.py',
           ROOT/'experiments/lazy_observation/background.py',ROOT/'experiments/lazy_observation/prototype.py']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    write(a.output/'sources.json',hashes)
    def child(case):
        result=subprocess.run([sys.executable,__file__,'--output',str(a.output/case),'--case',case],
                              capture_output=True,text=True,timeout=100)
        (a.output/(case+'.log')).write_text(result.stdout+result.stderr)
        return dict(case=case,exit_code=result.returncode)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(child,['ax','visual']))
    unchanged=all(hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==h for path,h in hashes.items())
    passed=unchanged and all(r['exit_code']==0 for r in results)
    write(a.output/'result.json',dict(passed=passed,sources_unchanged=unchanged,cases=results,model_calls=0))
    if not passed:raise SystemExit('Check child logs; saved failures retained')
    print(json.dumps(results))


if __name__=='__main__':main()
