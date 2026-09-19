"""Catalog launch controls against offline worker advertisements; no model/jobs."""
import hashlib,json,os,subprocess
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
def main():
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
 out=ROOT/'.local/vercel-demo'/('catalog-launch-ui-'+uuid4().hex[:8]);out.mkdir(parents=True);checks=[]
 def check(name,value):assert value,name;checks.append(name);print('PASS',name,flush=True)
 process=subprocess.Popen(['node','tests/workspace-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True);origin='http://127.0.0.1:'+str(json.loads(process.stdout.readline())['port'])
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch();page=browser.new_page(viewport={'width':1512,'height':1040});errors=[];launches=[];all_writes=[];jobs=[];reject=False
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:all_writes.append(r.url) if r.method=='POST' else None)
   page.goto(origin);page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3);page.get_by_role('button',name='Open demo').click();expect(page.locator('#site-count')).to_have_text('9');all_writes.clear()
   config=page.request.get(origin+'/api/harness/config').json();legacy=[task for task in config['tasks'] if not task.get('expanded')];catalog=page.request.get(origin+'/api/task-catalog').json();examples=[task for task in catalog['tasks'] if task['site_id']=='tricky-shop'][:8]
   def binding(task,**changes):return {'id':task['id'],'expanded':True,'available':True,'goal':task['goal'],'title':task['id'],'revision':'revision-1','site_id':task['site_id'],'collection':task['dataset'],'condition':task['condition'],**changes}
   bindings=[binding(task) for task in examples];bindings[1]['available']=False;bindings[2].pop('available');bindings[3]['available']='true';bindings[4]['goal']='Not the reviewed goal';bindings[5]['site_id']='tricky-health';bindings[6].pop('revision');bindings[7]['expanded']=False
   config['tasks']=legacy+bindings;config['worker'].update(mode='live',online=True);config['enabled']=True
   page.route('**/api/harness/config',lambda route:route.fulfill(json=config))
   def broker(route):
    nonlocal reject
    if route.request.method=='GET':return route.fulfill(json={'jobs':jobs})
    body=route.request.post_data_json;launches.append(body)
    if reject:return route.fulfill(status=503,json={'error':'Offline launch rejected'})
    task=next(task for task in config['tasks'] if task['id']==body['task']);job={'id':str(uuid4()),'status':'queued','task':task['id'],'task_name':task['title'],'task_revision':task['revision'],'goal':task['goal'],'site_id':task['site_id'],'collection':task['collection'],'condition':task['condition'],'interaction_kind':'task','required_execution_mode':'live','steps':[],'created_at':'2026-09-20T12:00:00Z'};jobs.insert(0,job);return route.fulfill(json=job)
   page.route('**/api/harness/jobs',broker)
   page.route('**/api/harness/jobs/*',lambda route:route.fulfill(json=next(job for job in jobs if job['id']==route.request.url.rsplit('/',1)[-1])))
   page.goto(origin+'/workspace?site=tricky-shop&view=research');expect(page.locator('#catalog-readiness')).to_have_text('1 of 42 available to the agent')
   check('Only explicit true with matching ID, goal, site, revision and expanded marker enables launch',True)
   expect(page.locator('.site-choice[data-site=tricky-shop] .site-task-count')).to_have_text('42 tasks');expect(page.locator('.site-choice[data-site=tricky-shop] .site-worker-count')).to_have_text('+ 2 worker tasks');expect(page.locator('#task-cards button')).to_have_count(2);check('Expanded advertisements do not duplicate cards or sidebar counts',True)
   def open_objective(task):
    page.locator('#catalog-search').fill(task['id']);page.locator('#catalog-cards button').click();expect(page.locator('#catalog-dialog')).to_be_visible()
   for task in examples[1:]:
    open_objective(task);expect(page.locator('#catalog-launch')).to_be_hidden();check(task['id']+' remains review-only',True);page.get_by_role('button',name='Close review objective').click()
   task=examples[0];open_objective(task);expect(page.locator('#catalog-launch')).to_be_visible();page.locator('#catalog-launch').click();expect(page.locator('#dialog-goal')).to_have_text(task['goal']);check('Launch review preserves exact objective and revision','revision-1' in page.locator('#dialog-task-facts').inner_text());page.locator('#try-task').click();expect(page.locator('#review-view')).to_be_visible();expect(page.frame_locator('#run-viewer').locator('#run-summary')).to_have_text(task['goal'])
   check('One explicit launch sends only trusted fixed fields and live execution requirement',launches==[{'task':task['id'],'interaction_kind':'task','required_execution_mode':'live','task_revision':'revision-1','goal':task['goal']}])
   def research():page.locator('.site-choice[data-site=tricky-shop]').click();page.locator('#research-tab').click()
   research();open_objective(task);page.locator('#catalog-launch').click();bindings[0]['available']=False;page.evaluate('document.dispatchEvent(new Event("visibilitychange"))');expect(page.locator('#try-task')).to_be_disabled();page.locator('#try-task').dispatch_event('click');check('Withdrawn availability blocks a stale dialog and forced click',len(launches)==1);page.locator('#task-dialog .dialog-close').click()
   bindings[0]['available']=True;page.evaluate('document.dispatchEvent(new Event("visibilitychange"))');expect(page.locator('#catalog-readiness')).to_have_text('1 of 42 available to the agent');open_objective(task);page.locator('#catalog-launch').click();bindings[0]['revision']='revision-2';page.evaluate('document.dispatchEvent(new Event("visibilitychange"))');expect(page.locator('#try-task')).to_be_disabled();page.locator('#try-task').dispatch_event('click');check('Revision change requires reviewing a fresh launch rather than replacing the trusted snapshot',len(launches)==1);page.locator('#task-dialog .dialog-close').click();open_objective(task);page.locator('#catalog-launch').click();expect(page.locator('#dialog-task-facts')).to_contain_text('revision-2');page.locator('#try-task').click();expect(page.locator('#review-view')).to_be_visible();check('Reopened launch submits the new exact revision',len(launches)==2 and launches[-1]['task_revision']=='revision-2')
   research();open_objective(task);page.locator('#catalog-launch').click();config['tasks']=legacy+bindings[1:];page.evaluate('document.dispatchEvent(new Event("visibilitychange"))');expect(page.locator('#try-task')).to_be_disabled();page.locator('#try-task').dispatch_event('click');check('Removed registry row blocks submission',len(launches)==2);page.locator('#task-dialog .dialog-close').click()
   config['tasks']=legacy+bindings;config['worker']['mode']='rehearsal';page.evaluate('document.dispatchEvent(new Event("visibilitychange"))');expect(page.locator('#catalog-readiness')).to_have_text('0 of 42 available to the agent');open_objective(task);expect(page.locator('#catalog-launch')).to_be_hidden();check('Rehearsal cannot launch a supposedly available catalog row',True);page.get_by_role('button',name='Close review objective').click()
   config['worker']['mode']='live';page.evaluate('document.dispatchEvent(new Event("visibilitychange"))');expect(page.locator('#catalog-readiness')).to_have_text('1 of 42 available to the agent');open_objective(task);page.locator('#catalog-launch').click();reject=True;page.locator('#try-task').click();expect(page.locator('#task-launch-status')).to_contain_text('No automatic retry');expect(page.locator('#try-task')).to_be_enabled();check('Backend rejection preserves visible error and makes no automatic retry',len(launches)==3);page.locator('#task-dialog .dialog-close').click()
   page.set_viewport_size({'width':390,'height':844});open_objective(task);check('Catalog launch dialog fits mobile viewport',page.evaluate('document.documentElement.scrollWidth<=innerWidth'));page.screenshot(path=str(out/'mobile.png'),full_page=True)
   check('Only explicit mocked job launches were requested',len(all_writes)==len(launches));check('No browser errors',not errors);browser.close()
  (out/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'scope':'Actual workspace with mocked runtime config/job endpoint; no real jobs or model calls','paid_calls':0,'sources':{name:hashlib.sha256((ROOT/'deploy/daylight/client'/name).read_bytes()).hexdigest() for name in ['workspace.js','workspace.html']}},indent=2));print(json.dumps({'checks':len(checks),'report':str(out/'report.json')}))
 finally:process.terminate();process.wait(timeout=10)
if __name__=='__main__':main()
