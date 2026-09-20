"""Read-only current release acceptance. Never creates a job or manual session."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--origin',default='https://browseragent.vercel.app')
    p.add_argument('--assets',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    invitation=json.loads((ROOT/'.local/vercel-demo/invitation-codes.json').read_text())['bjorn']
    code=invitation if isinstance(invitation,str) else invitation['code'];checks=[]
    def check(label,ok):
        assert ok,label
        checks.append(label)
    with httpx.Client(base_url=a.origin,headers={'Origin':a.origin},trust_env=False,timeout=45) as client:
        check('anonymous preview protected',client.get('/environments/prislyktan/').status_code==303)
        check('owner invitation accepted',client.post('/login',data={'code':code}).status_code==303)
        paths={'workspace.html':'/','harness.html':'/harness','trace-viewer.html':'/trace-viewer',
               **{n:'/assets/'+n for n in ('workspace.js','workspace.css','trace-browser.js','trace-viewer.js','tool-activity.js','dashboard.js')}}
        for name,url in paths.items():
            response=client.get(url);check('exact release asset '+name,response.status_code==200 and response.content==(a.assets/name).read_bytes())
        config=client.get('/api/harness/config').json();before=client.get('/api/harness/jobs').json()['jobs']
        expected={r['id'] for f in ('team_tasks.json','expanded_team_tasks.json','prislyktan_tasks.json') for r in json.loads((ROOT/'config'/f).read_text())['tasks']}|{'rooms'}
        check('all exact task IDs advertised live',len(expected)==224 and {t['id'] for t in config['tasks']}==expected and all(t['available'] for t in config['tasks']) and config['worker']['online'] and config['worker']['mode']=='live')
        manual=client.get('/api/manual/config').json()
        check('Prislyktan manual and Ask available',manual['ask_enabled'] and any(s['site_id']=='prislyktan' and s['available'] for s in manual['sites']))
        manifest=json.loads((a.assets/'prislyktan/manifest.json').read_text())
        for name,want in manifest['output_files'].items():
            response=client.get('/environments/prislyktan/'+name)
            check('preview hash '+name,response.status_code==200 and hashlib.sha256(response.content).hexdigest()==want)
        os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000})
            context.add_cookies([{'name':c.name,'value':c.value,'url':a.origin,'httpOnly':True,'sameSite':'Lax'} for c in client.cookies.jar])
            page=context.new_page();errors=[];writes=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:writes.append(r.method) if r.method not in ('GET','HEAD','OPTIONS') else None)
            page.goto(a.origin);expect(page.locator('.site-choice[data-site=prislyktan]')).to_be_visible(timeout=30000)
            page.locator('.site-choice[data-site=prislyktan]').click();expect(page.locator('#local-prislyktan-launch')).to_be_visible()
            check('preview link points to authenticated original design',page.locator('#local-prislyktan-launch a').get_attribute('href')=='/environments/prislyktan/')
            page.screenshot(path=str(a.output/'workspace.png'))
            page.goto(a.origin+'/environments/prislyktan/');page.get_by_role('searchbox',name='Sök produkter').wait_for()
            page.screenshot(path=str(a.output/'preview.png'))
            check('preview has no browser errors or writes',not errors and not writes)
            browser.close()
        check('no jobs created',[j['id'] for j in before]==[j['id'] for j in client.get('/api/harness/jobs').json()['jobs']])
        (a.output/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'model_calls':0,'new_jobs':0,'new_manual_sessions':0},indent=2)+'\n')
        print(json.dumps({'passed':True,'checks':len(checks),'model_calls':0}))

if __name__=='__main__':main()
