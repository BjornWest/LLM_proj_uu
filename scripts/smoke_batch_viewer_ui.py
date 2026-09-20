"""Read-only actual-handler review of a saved native-batch episode; no inference."""
import argparse, hashlib, json, os, subprocess
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--episode',type=Path,required=True);args=parser.parse_args()
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
out=ROOT/'.local/vercel-demo'/('batch-viewer-'+uuid4().hex[:8]);out.mkdir(parents=True)
process=subprocess.Popen(['node','tests/worker-replay-server.mjs'],cwd=ROOT/'deploy/daylight',env=dict(os.environ,REPLAY_EPISODE=str(args.episode.resolve())),stdout=subprocess.PIPE,text=True)
checks=[]
def check(name,value):
    assert value,name
    checks.append(name);print('PASS',name,flush=True)
try:
    info=json.loads(process.stdout.readline());origin='http://127.0.0.1:'+str(info['port'])
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1280,'height':1000});errors=[];writes=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:writes.append(r.url) if r.method=='POST' and not r.url.endswith('/login') else None)
        page.goto(origin+'/trace-viewer?source=harness&embed=1#'+info['id'])
        page.get_by_label('Your invitation code').fill('local-replay-code-'*3);page.get_by_role('button',name='Open demo').click()
        page.goto(origin+'/trace-viewer?source=harness&embed=1#'+info['id'])
        expect(page.locator('.browser-output-review')).to_be_visible()
        expect(page.locator('.browser-review-turn')).to_have_count(4)
        expect(page.locator('.browser-review-call')).to_have_count(11)
        expect(page.locator('.browser-review-reasoning')).to_have_count(4)
        check('Regular view exposes four model turns, eleven calls and four reasoning disclosures',True)
        expect(page.locator('.browser-review-answer-text')).to_contain_text('Exactly one request')
        check('Agent reply is readable without opening raw JSON',True)
        check('Raw execution details are initially collapsed',page.locator('.browser-output-review .browser-review-detail[open]').count()==0)
        page.locator('.browser-review-reasoning summary').first.click()
        expect(page.locator('.browser-review-reasoning pre').first).to_be_visible()
        check('Recorded reasoning can be opened directly',True)
        page.locator('.browser-review-reasoning summary').first.click()
        check('Full raw message history is collapsed initially',not page.locator('.browser-raw-records').evaluate('e=>e.open'))
        page.screenshot(path=str(out/'conversation.png'),full_page=True)
        page.get_by_role('button',name='Tools only',exact=True).click()
        expect(page.locator('.browser-output-review')).to_be_hidden();expect(page.locator('#chat')).to_be_hidden()
        expect(page.locator('.trace-tool-event')).to_have_count(11)
        titles=page.locator('.trace-tool-event-body>strong').all_text_contents()
        check('Tools retain the existing numbered layout',page.locator('.trace-tool-number').all_text_contents()==list(map(str,range(1,12))))
        check('Click and fill use recorded labels', 'Click “Submit booking request”' in titles and 'Fill “Meeting title”' in titles)
        groups=page.locator('.trace-tool-turn')
        expect(groups).to_have_count(4)
        check('Four prominent turn headers',page.locator('.trace-tool-turn-heading h3').all_text_contents()==['Turn 1','Turn 2','Turn 3','Turn 4'])
        check('Each turn contains its own calls',[groups.nth(i).locator('.trace-tool-event').count() for i in range(4)]==[3,6,1,1])
        check('Six-call batch is explicitly labeled','6 tool calls · one model response' in groups.nth(1).inner_text())
        check('Numbering continues across turn boundaries',[groups.nth(i).locator('ol').get_attribute('start') for i in range(4)]==['1','4','10','11'])
        check('Reply remains readable in tools-only view','Exactly one request' in page.locator('.trace-tool-answer').inner_text())
        check('Batch execution is not incorrectly marked unconfirmed','Execution unconfirmed' not in page.locator('.trace-tool-timeline').inner_text())
        page.screenshot(path=str(out/'tools.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        check('Mobile has no horizontal page overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
        page.screenshot(path=str(out/'tools-mobile.png'),full_page=True)
        page.get_by_role('button',name='Replay',exact=True).click();expect(page.locator('.browser-replay-stage img')).to_be_visible()
        check('Recorded replay still renders',True)
        check('No JavaScript errors',not errors);check('Zero model or browser-agent writes',not writes)
        browser.close()
    sources=['deploy/daylight/client/trace-browser.js','deploy/daylight/client/trace-browser.css','deploy/daylight/client/tool-activity.js','deploy/daylight/client/tool-activity.css','deploy/daylight/vendor/agent_trace/adapters/browsergym.py']
    (out/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'model_calls':0,'source_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in sources}},indent=2)+'\n');print(out/'report.json')
finally:
    process.terminate();process.wait(timeout=15)
