"""Six-site manual UI contract with mocked sessions; no model/remote browser calls.

The six open/close cases deliberately share one owner's session sequence to check
slot release. Independent regression suites can run alongside this process.
"""
import hashlib,json,os,subprocess
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
def main():
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
 out=ROOT/'.local/vercel-demo'/('generic-manual-ui-'+uuid4().hex[:8]);out.mkdir(parents=True);checks=[]
 def check(name,value):assert value,name;checks.append(name);print('PASS',name,flush=True)
 process=subprocess.Popen(['node','tests/workspace-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True);origin='http://127.0.0.1:'+str(json.loads(process.stdout.readline())['port'])
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch();image_page=browser.new_page(viewport={'width':1000,'height':800});image_page.set_content('<h1>UI fixture screenshot</h1><p>No dataset browser is running.</p>');png=image_page.screenshot();image_page.close()
   page=browser.new_page(viewport={'width':1512,'height':1040});errors=[];requests=[];sessions=[];serial=0;failure=None;locks=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   site_ids=['tricky-shop','tricky-health','tricky-news','tricky-music','webarena-shopping','webarena-forum']
   settings={'enabled':True,'ask_enabled':True,'sites':[{'site_id':sid,'available':True,'unavailable_reason':None,'default_task':'legacy-'+sid,'tasks':[{'id':'browse.'+sid,'title':'Browse website','ask_enabled':False,'browse_only':True,'available':True,'unavailable_reason':None},{'id':'legacy-'+sid,'title':'Reference fixture','ask_enabled':True,'available':True}]} for sid in site_ids]}
   def frame(session):
    nonlocal serial
    serial+=1;session['frame']={'id':str(serial),'width':1000,'height':800,'page_url':'https://example.invalid/fixture'}
   def remote(route):
    nonlocal failure
    path=route.request.url.removeprefix(origin);body=route.request.post_data_json if route.request.method=='POST' else None;requests.append((route.request.method,path,body))
    def reply(value,status=200):route.fulfill(status=status,json=value)
    if path.endswith('/config'):return reply(settings)
    if '/frame/' in path:return route.fulfill(content_type='image/png',body=png)
    if path=='/api/manual/sessions':
     if body is None:return reply({'sessions':sessions})
     if failure:
      status,message=failure;failure=None;return reply({'error':message},status)
     task=body['task'];generic=task.startswith('browse.');sid=task.removeprefix('browse.').removeprefix('legacy-');session={'id':str(uuid4()),'site_id':sid,'task':task,'task_name':task,'status':'ready','controller':'human','ask_enabled':not generic,'browse_only':generic,'created_at':'2026-09-19T12:00:00Z','reference_goal':None if generic else 'Reference goal','evaluation':None,'reference_evaluation':None,'action_count':0};frame(session);sessions.insert(0,session);return reply(session)
    session=next(s for s in sessions if s['id'] in path)
    if path.endswith('/action'):
     locks.append(page.locator('#manual-reload').is_disabled() and page.locator('#manual-send-text').is_disabled());session['action_count']+=1;frame(session)
    elif path.endswith('/observe'):frame(session)
    elif path.endswith('/close'):session.update(status='finished',trace_ready=True)
    return reply(session)
   page.route('**/api/manual/**',remote)
   page.goto(origin);page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3);page.get_by_role('button',name='Open demo').click();expect(page.locator('#site-count')).to_have_text('9')
   check('Loading all sites never opens a session',not any(method=='POST' for method,_,_ in requests))
   for sid in site_ids:
    page.locator('.site-choice[data-site="'+sid+'"]').click();expect(page.locator('#manual-task')).to_have_value('browse.'+sid);expect(page.locator('#manual-open')).to_be_enabled();page.locator('#manual-open').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false')
    check(sid+' defaults to generic session and disables Ask despite global capability',sessions[0]['task']=='browse.'+sid and page.locator('#remote-question').is_disabled() and page.locator('#remote-send').is_disabled() and 'Manual browsing only' in page.locator('#remote-agent-status').inner_text())
    expect(page.locator('.manual-reference')).to_be_hidden();expect(page.locator('#manual-navigation')).to_be_visible()
    before=len(requests);page.evaluate("document.querySelector('#remote-question').value='Must not send';document.querySelector('#remote-ask-form').dispatchEvent(new Event('submit',{cancelable:true}))");check(sid+' submit handler rejects forced Ask without a request',not any(method=='POST' for method,_,_ in requests[before:]))
    for action in ['back','forward','reload']:
     page.locator('#manual-'+action).click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');check(sid+' '+action+' uses ordinary action/receipt path',next(body for method,path,body in reversed(requests) if path.endswith('/action'))['action']=={'type':action})
    if sid=='tricky-shop':
     page.screenshot(path=str(out/'generic-desktop.png'),full_page=True);page.set_viewport_size({'width':390,'height':844});expect(page.locator('#manual-navigation')).to_be_visible();check('Generic navigation stays visible and fits mobile width',page.evaluate('document.documentElement.scrollWidth<=innerWidth'));page.screenshot(path=str(out/'generic-mobile.png'),full_page=True);page.set_viewport_size({'width':1512,'height':1040})
     before=len([r for r in requests if r[0]=='POST']);page.reload();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');check('Generic session restores without inference, a new session or fabricated objective',page.locator('#remote-send').is_disabled() and page.locator('.manual-reference').is_hidden() and len([r for r in requests if r[0]=='POST'])==before)
    page.locator('#manual-close').click();expect(page.locator('#manual-status')).to_contain_text('finished');check(sid+' closed navigation is disabled and ungraded',page.locator('#manual-reload').is_disabled() and sessions[0]['evaluation'] is None)
   check('Navigation commands lock conflicting inputs',locks and all(locks))
   page.locator('#research-tab').click();page.locator('#replay-kind').select_option('manual');page.locator('#replay-rows .run-title').first.click();expect(page.locator('#manual-review')).to_be_visible();check('Generic saved review hides reference grading and pending objective',page.locator('#manual-review-reference').is_hidden() and 'no task setup' in page.locator('#manual-review-goal').inner_text() and page.locator('#review-grade').inner_text()=='Not graded')
   page.locator('.site-choice[data-site=webarena-forum]').click()
   selected=settings['sites'][-1]['tasks'][0]
   for reason,word in [('pool_busy','in use'),('resetting','being reset'),('service_unavailable','unavailable')]:
    selected.update(available=False,unavailable_reason=reason);page.locator('#manual-check').click();expect(page.locator('#manual-open')).to_be_disabled();expect(page.locator('#manual-availability')).to_contain_text(word);before=len(requests);page.locator('#manual-open').dispatch_event('click');check(reason+' disables opening and never retries',not any(method=='POST' for method,_,_ in requests[before:]))
   selected.update(available=True,unavailable_reason=None);page.locator('#manual-check').click();expect(page.locator('#manual-open')).to_be_enabled()
   for status in [429,503]:
    failure=(status,'Browser pool busy' if status==429 else 'Browser service unavailable');before=len([r for r in requests if r[0]=='POST']);page.locator('#manual-open').click();expect(page.locator('#manual-error')).to_contain_text('No command will be retried');expect(page.locator('#manual-open')).to_be_disabled();check(str(status)+' start failure stays stopped until explicit status refresh',len([r for r in requests if r[0]=='POST'])==before+1);page.locator('#manual-check').click();expect(page.locator('#manual-open')).to_be_enabled()
   page.locator('#manual-task').select_option('legacy-webarena-forum');page.locator('#manual-open').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');expect(page.locator('#remote-send')).to_be_enabled();expect(page.locator('#manual-navigation')).to_be_hidden();check('Legacy Ask remains enabled and generic navigation stays bounded',True)
   sessions[0].pop('ask_enabled');page.locator('#manual-check').click();expect(page.locator('#remote-send')).to_be_enabled();check('Missing historical capability retains legacy Ask compatibility',True)
   sessions[0]['ask_enabled']=False;page.locator('#manual-check').click();expect(page.locator('#remote-send')).to_be_disabled();check('Explicit false wins over global enabled on restored session',True)
   page.set_viewport_size({'width':390,'height':844});check('Manual controls fit mobile width',page.evaluate('document.documentElement.scrollWidth<=innerWidth'));page.screenshot(path=str(out/'mobile.png'),full_page=True)
   page.set_viewport_size({'width':1512,'height':1040});page.screenshot(path=str(out/'desktop.png'),full_page=True)
   check('No Ask or model requests dispatched',not any(path.endswith('/ask') or path in ['/api/start','/api/step','/api/harness/jobs'] for method,path,_ in requests if method=='POST'));check('No browser errors',not errors);browser.close()
  (out/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'paid_calls':0,'scope':'Mock manual API and frame; six-site UI contract, not real driver/lease acceptance','sources':{name:hashlib.sha256((ROOT/'deploy/daylight/client'/name).read_bytes()).hexdigest() for name in ['workspace.js','workspace.html','workspace.css']}},indent=2));print(json.dumps({'checks':len(checks),'report':str(out/'report.json')}))
 finally:process.terminate();process.wait(timeout=10)
if __name__=='__main__':main()
