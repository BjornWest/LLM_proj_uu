"""Offline browser check of quota containment; no worker/model/Blob calls."""
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

def main():
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH', '')
    output = ROOT/'.local/control'/('polling-'+uuid4().hex[:8]); output.mkdir(parents=True)
    server = subprocess.Popen(['node','tests/workspace-server.mjs'], cwd=ROOT/'deploy/daylight', stdout=subprocess.PIPE, text=True)
    origin = 'http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port'])
    checks=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            for route in ['/workspace','/harness']:
                page=browser.new_page(); reads=[]; writes=[]
                page.on('request',lambda r:reads.append(r.url) if '/api/harness/' in r.url and r.method=='GET' else None)
                page.on('request',lambda r:writes.append(r.url) if '/api/' in r.url and r.method=='POST' else None)
                page.goto(origin+'/login');page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3)
                page.get_by_role('button',name='Open demo').click();page.wait_for_load_state('networkidle')
                page.add_init_script("""(() => {
                  const realSet=window.setTimeout.bind(window),realClear=window.clearTimeout.bind(window);
                  let now=0,id=1000000;const timers=new Map();
                  window.setTimeout=(fn,ms,...args)=>{if(ms<3000)return realSet(fn,ms,...args);const key=++id;timers.set(key,{at:now+ms,fn:()=>fn(...args)});return key};
                  window.clearTimeout=key=>{timers.delete(key);realClear(key)};
                  window.advancePollClock=async ms=>{now+=ms;for(const [key,t] of [...timers])if(t.at<=now){timers.delete(key);t.fn()}await new Promise(r=>realSet(r,250))};
                })()""")
                page.goto(origin+route);page.wait_for_load_state('networkidle')
                baseline=len(reads);page.evaluate("advancePollClock(15000)");page.wait_for_timeout(150)
                assert len(reads)==baseline,route+' idle polling before 60 seconds'
                checks.append(route+' no 15-second idle refresh')
                page.evaluate("window.testHidden=true;Object.defineProperty(document,'hidden',{get:()=>window.testHidden});document.dispatchEvent(new Event('visibilitychange'))")
                page.evaluate("advancePollClock(180000)");page.wait_for_timeout(150)
                assert len(reads)==baseline,route+' background requests'
                checks.append(route+' hidden tab makes zero polls')
                page.evaluate("window.testHidden=false;document.dispatchEvent(new Event('visibilitychange'))")
                page.wait_for_load_state('networkidle')
                assert len(reads)>baseline,route+' did not refresh on return'
                checks.append(route+' visible return refreshes')
                assert not writes,route+' replay issued writes';page.close()
            browser.close()
        report={'passed':True,'checks':checks,'model_calls':0,'blob_calls':0}
        (output/'report.json').write_text(json.dumps(report,indent=2));print(output/'report.json')
    finally:
        server.terminate();server.wait(timeout=10)

if __name__=='__main__':main()
