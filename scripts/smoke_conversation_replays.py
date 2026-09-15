"""Saved conversation UI against the actual API, with offline inference only."""
import hashlib,json,os,subprocess
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]

def main():
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
    out=ROOT/'.local/vercel-demo'/('conversation-replays-'+uuid4().hex[:8]);out.mkdir(parents=True)
    server=subprocess.Popen(['node','tests/workspace-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True)
    origin='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port']);checks=[]
    def check(name,value):
        assert value,name
        checks.append(name);print('PASS',name,flush=True)
    try:
      with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1512,'height':1040});errors=[];writes=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:writes.append(r.url) if r.method=='POST' and '/api/' in r.url else None)
        page.goto(origin);page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3);page.get_by_role('button',name='Open demo').click()
        def ask(goal):
            expect(page.locator('#question')).to_be_enabled();page.locator('#question').fill(goal);page.locator('#question').press('Enter')
            expect(page.locator('#send-question')).to_have_attribute('data-running','false',timeout=30000)
            return page.request.get(origin+page.locator('#conversation .record-link').last.get_attribute('href')).json()
        first=ask('Show availability for three people on Wednesday')
        second=ask('Thanks. Summarize that availability again.')
        check('Successive actual chat turns share identity but keep distinct original traces',first['id']!=second['id'] and first['conversation_id']==second['conversation_id'])
        page.locator('#research-tab').click();expect(page.locator('#replay-rows tr[data-kind=ask]')).to_have_count(1)
        check('Per-site history groups two turns in one conversation', '2 turns' in page.locator('#replay-rows tr[data-kind=ask]').inner_text())
        page.locator('#replay-rows tr[data-kind=ask] .run-title').click();expect(page.locator('#trace-conversation .transcript-turn[data-trace]')).to_have_count(2)
        log=page.locator('#trace-conversation')
        check('Each user turn appears once in recorded order',log.locator('.user .transcript-text').all_text_contents()==[first['goal'],second['goal']])
        check('Assistant answers render as readable text without action JSON',log.locator('.assistant .transcript-text').last.inner_text()==second['steps'][-1]['action']['message'] and all(not text.startswith('{') for text in log.locator('.assistant .transcript-text').all_text_contents()))
        check('Tool receipts have separate right-side bubbles',log.locator('.tool').count()==sum(s.get('action',{}).get('action')!='done' for t in [first,second] for s in t['steps']))
        positions=log.evaluate("el=>[...el.querySelectorAll('.transcript-bubble')].map(b=>({role:b.className,x:b.getBoundingClientRect().x,right:b.getBoundingClientRect().right,align:getComputedStyle(b).alignSelf}))")
        check('Model aligns left and user/tools align right',all(b['align']==('flex-start' if 'assistant' in b['role'] else 'flex-end') for b in positions))
        check('Raw records remain exact behind collapsed evidence details',not page.locator('#trace-raw-details').evaluate('e=>e.open') and json.loads(page.locator('#browser-trace-json').text_content())==[first,second])
        check('Every original turn retains an authenticated download',log.locator('.transcript-turn a').count()==2)
        page.screenshot(path=str(out/'conversation.png'),full_page=True)
        preview=page.locator('#browser-trace-review').evaluate("el=>{const copy=el.cloneNode(true);copy.querySelectorAll('a,#trace-raw-details').forEach(n=>n.remove());return copy.outerHTML}")
        css=(ROOT/'deploy/daylight/client/tool-activity.css').read_text()
        (out/'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Daylight conversation preview</title><style>'+css+'body{margin:0;background:#f5f7f3;color:#29413b;font:15px/1.6 system-ui;padding:24px}main{max-width:920px;margin:auto}.browser-trace-review{padding:24px;border:1px solid #dbe3db;border-radius:14px;background:white}.trace-conversation{max-height:none}h1{font-size:24px}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><main><h1>Daylight · conversation replay</h1><p>Local design preview using scripted test messages. No real model calls. Model on the left; user and tools on the right. Expand a bubble to inspect its recorded evidence.</p>'+preview+'</main></html>')

        before=len(writes);page.goto(origin+'/workspace/replays?run=d:'+second['id']);expect(log.locator('.user')).to_have_count(2)
        check('Old per-turn deep links open the entire conversation read-only',len(writes)==before)
        page.locator('#all-replays-link').click();page.locator('#global-kind').select_option('ask');expect(page.locator('#global-rows tr')).to_have_count(1)
        check('Global library uses the same session grouping', '2 turns' in page.locator('#global-rows tr').inner_text())
        page.locator('#global-search').fill('Summarize that');expect(page.locator('#global-rows tr')).to_have_count(1)
        check('Search finds follow-up turns within their conversation', '2 turns' in page.locator('#global-rows tr').inner_text());page.locator('#global-search').fill('')
        page.locator('.site-choice[data-site=campus]').click();page.locator('#reset-page').click()
        third=ask('<img src=x onerror="window.traceInjected=true"> New conversation')
        check('Start fresh creates a separate session',third['conversation_id']!=first['conversation_id'])
        page.locator('#all-replays-link').click();page.locator('#global-kind').select_option('ask');expect(page.locator('#global-rows tr')).to_have_count(2)
        page.locator('#global-rows tr').filter(has_text='New conversation').locator('.run-title').click();expect(log.locator('.user')).to_have_count(1)
        check('Recorded content is rendered as text without executing HTML',log.locator('.user .transcript-text').inner_text()==third['goal'] and log.locator('img').count()==0 and not page.evaluate('Boolean(window.traceInjected)'))
        page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(out/'conversation-mobile.png'),full_page=True)
        check('Mobile conversation fits the viewport',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        # Deterministic saved-evidence cases exercise the trusted renderer directly;
        # these are presentation fixtures, not newly executed browser actions.
        before=len(writes)
        page.evaluate("""async()=>{
          const {renderTraceConversation}=await import('/assets/tool-activity.js');
          const action={action:'click',id:'126'};
          const step=(label,receipt)=>({action,output:JSON.stringify(action),observation:{controls:[{id:'126',label}],text:'Exact policy observation: '+label},client_result:receipt});
          renderTraceConversation(document.querySelector('#trace-conversation'),[
            {id:'saved-evidence-fixture',goal:'Review recorded actions',created_at:'2026-09-15T12:00:00Z',status:'interrupted',interruption:{reason:'new message'},steps:[
              step('Cancel October appointment',{description:'Clicked October',page_after:{text:'Transition-only toast'}}),
              step('Cancel November appointment',null)]},
            {id:'rejected-output-fixture',goal:'Parser failure',created_at:'2026-09-15T12:01:00Z',status:'error',steps:[{output:'Plain text response',error:'Invalid action JSON'}]},
            {id:'empty-fixture',goal:'No response',created_at:'2026-09-15T12:02:00Z',status:'pending',steps:[]}
          ]);
        }""")
        check('Repeated action IDs keep the label from each exact pre-action observation',log.locator('.tool .transcript-text').all_text_contents()==['click · Cancel October appointment','click · Cancel November appointment'])
        check('Post-action feedback stays separate from policy observation',log.locator('.tool').first.locator('details').nth(0).inner_text().find('Transition-only toast')==-1 and 'transition feedback' in log.locator('.tool').first.locator('details').nth(1).inner_text())
        check('Interrupted output with no receipt is never labelled applied', 'interrupted output' in log.locator('.assistant .transcript-label').nth(1).inner_text() and 'No execution receipt' in log.locator('.tool .transcript-label').nth(1).inner_text())
        check('Rejected and absent responses remain visibly distinct', 'output rejected' in log.inner_text() and 'Invalid action JSON' in log.inner_text() and 'No model response was recorded' in log.inner_text())
        check('Saved evidence viewing sends no API writes',len(writes)==before)
        check('No browser JavaScript errors',not errors)
        browser.close()
      report={'passed':True,'checks':checks,'paid_calls':0,'policy':'Actual handler with offline model; edge-case rendering fixtures are saved evidence, not agent results','sources':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in [ROOT/'deploy/daylight/client'/n for n in ['workspace.js','workspace.html','workspace.css','tool-activity.js','tool-activity.css']]+[ROOT/'deploy/daylight/lib/agent.mjs']}}
      (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'checks':len(checks),'report':str(out/'report.json')}))
    finally:server.terminate();server.wait(timeout=10)
if __name__=='__main__':main()
