"""Actual shared viewer + invitation API + PC library, zero model/browser-agent calls."""
import json, os, subprocess, hashlib
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
out=ROOT/'.local/vercel-demo'/('library-backend-'+uuid4().hex[:8]);out.mkdir(parents=True)
process=subprocess.Popen(['node','tests/library-integration-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True)
info=json.loads(process.stdout.readline());origin='http://127.0.0.1:'+str(info['port']);checks=[]
def check(name,value):
 assert value,name
 checks.append(name);print('PASS',name,flush=True)
try:
 with sync_playwright() as p:
  browser=p.chromium.launch();context=browser.new_context(viewport={'width':1512,'height':1040});page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  check('Anonymous library reads rejected',page.request.get(origin+'/api/library/sessions').status==401)
  page.goto(origin+'/workspace/replays');page.get_by_label('Your invitation code').fill('offline-library-code-'*3);page.get_by_role('button',name='Open demo').click();page.locator('#all-replays-link').click()
  rows=page.locator('#global-rows tr[data-run^="l:"]');expect(rows).to_have_count(2)
  stats=page.request.get(origin+'/__fixture/stats').json();check('Opening history reads summaries without projection or media',stats['sessions']==0 and stats['assets']==0)
  check('Historical unknown mode preserved',rows.first.get_attribute('data-kind')=='unknown')
  page.locator('#global-site').select_option('tricky-health');expect(rows).to_have_count(1);rows.locator('.run-title').click()
  frame=page.frame_locator('#shared-trace-viewer');expect(frame.locator('#chat .bubble')).not_to_have_count(0)
  stats=page.request.get(origin+'/__fixture/stats').json();check('One full projection and no screenshot downloaded for message view',stats['sessions']==1 and stats['assets']==0)
  frame.get_by_role('button',name='Tools only',exact=True).click();expect(frame.locator('.trace-tool-event')).to_have_count(12);check('Twelve original browser tool events displayed',True)
  frame.get_by_role('button',name='Replay',exact=True).click();image=frame.locator('.browser-replay-stage img');expect(image).to_have_js_property('complete',True);expect(image).to_be_visible()
  check('Authorized PC image rendered with nonzero dimensions',image.evaluate('e=>e.naturalWidth')>0)
  first=image.get_attribute('src');frame.get_by_role('button',name='Next →',exact=True).click();expect(frame.locator('.browser-replay [role=status]')).to_contain_text('Step 1');check('Exact recorded next screenshot served',image.get_attribute('src')!=first)
  page.screenshot(path=str(out/'replay.png'),full_page=True)
  check('Auth remains required on asset URLs',browser.new_context().request.get(origin+first).status==401)
  for index,expected in [(0,False),(1,None)]:
   response=page.request.get(origin+'/api/library/sessions/'+info['sessions'][index]);session=response.json();check('Recorded outcome preserved '+str(index),session['library_metadata']['evaluation']['safe_success'] is expected)
  page.goto(origin+'/workspace/replays?run=l:'+info['sessions'][1]);expect(page.frame_locator('#shared-trace-viewer').locator('#chat .bubble')).not_to_have_count(0);expect(page.locator('#review-grade')).to_have_text('Unknown')
  page.frame_locator('#shared-trace-viewer').get_by_role('button',name='Tools only',exact=True).click();check('Format error retains zero browser actions','No tool calls' in page.frame_locator('#shared-trace-viewer').locator('.trace-tool-timeline').inner_text())
  foreign=browser.new_context().new_page();foreign.goto(origin);foreign.get_by_label('Your invitation code').fill('offline-foreign-code-'*3);foreign.get_by_role('button',name='Open demo').click()
  check('Other invite cannot read projection or images',foreign.request.get(origin+'/api/library/sessions/'+info['sessions'][0]).status==404 and foreign.request.get(origin+first).status==404)
  stats=page.request.get(origin+'/__fixture/stats').json();check('Read-only review made no jobs, actions or model calls',stats['writes']==0 and stats['model_calls']==0);check('No JavaScript errors',not errors)
  browser.close()
 sources=['deploy/daylight/lib/library.mjs','deploy/daylight/lib/library-client.mjs','deploy/daylight/control-server.mjs','deploy/daylight/api/index.mjs','deploy/daylight/build.mjs','deploy/daylight/prepare-viewer.mjs']
 report={'passed':True,'checks':checks,'stats':stats,'paid_calls':0,'scope':'Actual invitation handler → local PC control HTTP service → isolated SQLite and immutable library objects; existing exported common projections. No deployed parity claim.','sources':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}}
 (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'report':str(out/'report.json'),'checks':len(checks)}))
finally:
 process.terminate();process.wait(timeout=10)
