"""Saved tool timeline and per-decision inventory; real handler, zero paid calls."""
import hashlib,json,os,subprocess
from uuid import uuid4
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
root=Path(__file__).resolve().parents[1];os.environ['LD_LIBRARY_PATH']=str(root/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
out=root/'.local/vercel-demo'/('trace-tools-'+uuid4().hex[:8]);out.mkdir(parents=True)
server=subprocess.Popen(['node','tests/workspace-server.mjs'],cwd=root/'deploy/daylight',stdout=subprocess.PIPE,text=True)
origin='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port'])
checks=[]
def check(name,value):
    assert value,name
    checks.append(name);print('PASS',name)
try:
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1512,'height':1040});errors=[];writes=[]
        page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
        page.goto(origin);page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3);page.get_by_role('button',name='Open demo').click()
        for goal in ['Show availability for three people on Wednesday','Thanks. Summarize that again.']:
            expect(page.locator('#question')).to_be_enabled();page.locator('#question').fill(goal);page.locator('#question').press('Enter');expect(page.locator('#send-question')).to_have_attribute('data-running','false',timeout=30000)
        page.locator('#research-tab').click();page.locator('#replay-rows tr[data-kind=ask] .run-title').click();expect(page.locator('#trace-conversation .user')).to_have_count(2);writes.clear()
        page.get_by_role('button',name='Tools only',exact=True).click();expect(page.locator('#trace-conversation')).to_be_hidden()
        check('Tools-only view hides conversation and shows four browser actions in order',page.locator('.trace-tool-event-body>strong').all_text_contents()==['select · Building · Ångström','select · Day · Wednesday','select · People · 3','select · Duration · 60'])
        check('Answers are excluded; chronological numbers are contiguous',page.locator('.trace-tool-number').all_text_contents()==['1','2','3','4'])
        page.locator('.trace-toolbox>summary').click();expect(page.locator('.trace-tool-card')).to_have_count(5)
        check('Available inventory includes unused tools from the actual recorded schema',page.locator('.trace-tool-card>strong').all_text_contents()==['click','select','check','fill','done'])
        check('Selected action is distinguished from other available tools',page.locator('.trace-tool-card[data-selected=true]>strong').inner_text()=='select')
        page.locator('.trace-tool-decision').select_option(index=5)
        check('Inventory selects an exact later turn/step',page.locator('.trace-tool-card[data-selected=true]>strong').inner_text()=='done')
        page.screenshot(path=str(out/'timeline-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844});check('Mobile tool inventory and timeline fit viewport',page.evaluate('document.documentElement.scrollWidth<=innerWidth'));page.screenshot(path=str(out/'timeline-mobile.png'),full_page=True)
        page.get_by_role('button',name='Conversation',exact=True).click();expect(page.locator('#trace-conversation')).to_be_visible();expect(page.locator('.trace-tool-timeline')).to_be_hidden()
        check('Switching back preserves all conversation turns',page.locator('#trace-conversation .user').count()==2)
        page.evaluate("""async()=>{const {renderTraceConversation}=await import('/assets/tool-activity.js');const action={action:'click',id:'126'};renderTraceConversation(document.querySelector('#trace-conversation'),[{id:'fixture',goal:'Saved fixture',steps:[{request:{tools:[]},action,observation:{text:'October target',controls:[{id:'126',label:'October'}]},client_result:{error:'Failed',page_after:{text:'Transition only'}}},{action,observation:{text:'November target',controls:[{id:'126',label:'November'}]}}]}])}""")
        expect(page.locator('.trace-tool-card')).to_have_count(0);check('Explicit zero tools stays distinct from unavailable inventory','explicitly lists no tools' in page.locator('.trace-tool-inventory').inner_text())
        page.locator('.trace-tool-decision').select_option(index=1);check('Unknown inventory is never derived from the used click action','not present' in page.locator('.trace-tool-inventory').inner_text() and page.locator('.trace-tool-card').count()==0)
        page.get_by_role('button',name='Tools only',exact=True).click();check('Failed and unconfirmed calls remain distinct',page.locator('.trace-tool-state').all_text_contents()==['Failed','Execution unconfirmed'])
        check('Same target IDs use labels from each exact recorded step',page.locator('.trace-tool-event-body>strong').all_text_contents()==['click · October','click · November'])
        page.locator('.trace-tool-event-step').first.click();check('Timeline step opens its own available-tool inventory',page.locator('.trace-tool-decision').input_value()=='fixture:0' and page.locator('.trace-toolbox').evaluate('e=>e.open'))
        page.goto(origin+'/workspace/replays');page.locator('#global-kind').select_option('task');page.locator('#global-rows .run-title').first.click()
        page.get_by_role('button',name='Tools only',exact=True).click();check('BrowserGym tools-only view preserves repeated recorded actions',page.locator('.trace-tool-event-body>strong').all_text_contents()==['click(126)','click(126)'])
        page.locator('.trace-toolbox>summary').click();check('BrowserGym inventory is unknown without published request definitions','not present' in page.locator('.trace-tool-inventory').inner_text())
        check('BrowserGym execution evidence preserves published browser_stepped flags','"browser_stepped": true' in page.locator('.trace-tool-event-body pre').first.text_content())
        page.evaluate("""async()=>{const {renderTraceConversation}=await import('/assets/tool-activity.js');renderTraceConversation(document.querySelector('#trace-conversation'),[{id:'empty',goal:'No actions',steps:[{request:{tools:[{type:'function',function:{name:'<img src=x onerror=window.badTool=true>',description:'Recorded text'}}]},action:{action:'done',message:'Answer'}}]}])}""")
        check('No calls produces an explicit empty timeline','No tool calls are recorded' in page.locator('.trace-tool-timeline').inner_text())
        check('Available definitions are text, never executed HTML',page.locator('.trace-tool-card img').count()==0 and not page.evaluate('Boolean(window.badTool)'))
        check('Tool review remains read-only',not writes);check('No browser errors',not errors)
        browser.close()
    (out/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'paid_calls':0,'scope':'Actual handler with offline model, scripted edge-case presentation fixtures','sources':{name:hashlib.sha256((root/'deploy/daylight/client'/name).read_bytes()).hexdigest() for name in ['tool-activity.js','tool-activity.css','workspace.js']}},indent=2))
    print(json.dumps({'checks':len(checks),'report':str(out/'report.json'),'paid_calls':0}))
finally:
    server.terminate();server.wait(timeout=10)
