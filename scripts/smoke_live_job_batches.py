"""Offline real workspace/iframe render of native live-call summaries; no inference."""
import json,os,subprocess,hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
p=subprocess.Popen(['node','tests/workspace-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True)
origin='http://127.0.0.1:'+str(json.loads(p.stdout.readline())['port'])
checks=[]
def check(name,value):
 assert value,name
 checks.append(name)
try:
 with sync_playwright() as pw:
  b=pw.chromium.launch(headless=True);page=b.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(origin);page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3);page.get_by_role('button',name='Open demo').click()
  jobs=page.request.get(origin+'/api/harness/jobs').json()['jobs'];job=next(j for j in jobs if j.get('task')=='rooms')
  calls=[{'action':"fill(bid='13', value='Aurora')",'status':'recorded','browser_stepped':True},
    {'action':"ax_search(query='Blue')",'status':'recorded','browser_stepped':False},
    {'action':"click(bid='14')",'status':'skipped','browser_stepped':False,'stop_reason':'document_or_navigation_changed'},
    {'action':"click(bid='99')",'status':'failed','error':'Not found'}]
  job.update(status='running',steps=[{'step':0,'calls':calls,'action':'\n'.join(c['action']+' ['+c['status']+']' for c in calls),'browser_stepped':True}],step_count=1,trace_ready=False)
  def route(r):
   data={'jobs':[job]} if r.request.url.split('?')[0].endswith('/jobs') else job
   r.fulfill(json=data)
  page.route('**/api/harness/jobs*',route);page.route('**/api/harness/jobs/**',route)
  writes=[];page.on('request',lambda r:writes.append(r.url) if r.method=='POST' and '/api/' in r.url else None)
  page.goto(origin+'/workspace/replays?run=h:'+job['id']);expect(page.locator('#trace-conversation')).to_contain_text('Aurora')
  check('Native calls shown without the legacy null-action placeholder','No action recorded' not in page.locator('#trace-conversation').inner_text())
  check('Conversation preserves all four calls and statuses',page.locator('#trace-conversation .tool').count()==4 and 'Skipped' in page.locator('#trace-conversation').inner_text())
  page.locator('#browser-trace-review .trace-tools-panel').get_by_role('button',name='Tools only',exact=True).click()
  panel=page.locator('#browser-trace-review .trace-tool-timeline');expect(panel).to_be_visible()
  check('Tools-only groups four calls under one model turn',panel.locator('.trace-tool-turn').count()==1 and panel.locator('.trace-tool-event').count()==4)
  check('AX tool is recorded even without a browser step',panel.locator('.trace-tool-event').nth(1).get_attribute('data-state')=='recorded')
  check('Skipped and failed calls remain distinct',panel.locator('.trace-tool-event[data-state=skipped]').count()==1 and panel.locator('.trace-tool-event[data-state=failed]').count()==1)
  frame=page.frame_locator('#run-viewer');expect(frame.locator('#steps')).to_contain_text('4 tool calls')
  check('Embedded watch view understands batch decisions',True)
  check('No model or job writes',not writes);check('No JavaScript errors',not errors)
  out=ROOT/'.local/live-batches-v1';out.mkdir(exist_ok=True);page.screenshot(path=str(out/'workspace.png'),full_page=True)
  (out/'browser-review.json').write_text(json.dumps({'passed':True,'checks':checks,'model_calls':0,'sources':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['deploy/daylight/client/workspace.js','deploy/daylight/client/tool-activity.js','deploy/daylight/client/harness.js']}},indent=2));b.close()
 print(json.dumps({'passed':True,'checks':len(checks),'model_calls':0}))
finally:p.terminate();p.wait(timeout=10)
