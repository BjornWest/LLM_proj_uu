"""Offline browser checks for fullscreen layout and chat keyboard interactions."""
import hashlib,json,os,subprocess
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
def main():
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
    out=ROOT/'.local/vercel-demo'/('chat-controls-'+uuid4().hex[:8]);out.mkdir(parents=True)
    server=subprocess.Popen(['node','tests/workspace-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True)
    origin='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port']);checks=[]
    def check(name,value):
        assert value,name
        checks.append(name);print('PASS',name,flush=True)
    try:
      with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1512,'height':1040});errors=[];starts=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:starts.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/api/start') else None)
        page.goto(origin);page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3);page.get_by_role('button',name='Open demo').click()
        for name,path,frame_selector,send,toggle in [('workspace','/workspace','#site-frames iframe','#send-question','#toggle-agent'),('original','/demo','#site','#send-chat','#toggle-sidebar')]:
            page.set_viewport_size({'width':1512,'height':1040});page.goto(origin+path);question=page.locator('#question');expect(question).to_be_enabled();frame=page.frame_locator(frame_selector);frame.get_by_role('heading',name='Reserve a study room').wait_for()
            count=len(starts);question.fill('Draft to preserve');page.evaluate('(selector)=>{window.savedFrame=document.querySelector(selector);window.savedDocument=savedFrame.contentDocument}',frame_selector)
            page.locator('#enter-fullscreen').click();expect(page.locator('#exit-fullscreen')).to_be_visible()
            outer=page.locator('#interactive-explore' if name=='workspace' else '.extension-layout').bounding_box()
            check(name+' full screen fills viewport with site and sidebar',outer['x']==0 and outer['y']==0 and outer['width']==1512 and outer['height']==1040 and page.locator('#agent-sidebar').is_visible())
            check(name+' surrounding navigation hidden',page.locator('.app-header' if name=='workspace' else '.browser-toolbar').is_hidden())
            question.focus();question.press('Escape');expect(page.locator('#exit-fullscreen')).to_be_hidden()
            check(name+' Escape from chat restores layout and draft without remounting',question.input_value()=='Draft to preserve' and page.evaluate('savedFrame.isConnected && savedFrame.contentDocument===savedDocument') and page.locator('#enter-fullscreen').evaluate('b=>document.activeElement===b'))
            page.locator('#enter-fullscreen').click();frame.locator('#room-people').focus();frame.locator('#room-people').press('Escape');expect(page.locator('#exit-fullscreen')).to_be_hidden();check(name+' Escape works while website has keyboard focus',True)
            page.locator('#enter-fullscreen').click();frame.get_by_role('link',name='Shop',exact=True).click();frame.get_by_role('heading',name='Ready for your next idea.').wait_for();frame.get_by_role('button',name='Add A5 notebook',exact=True).press('Escape');expect(page.locator('#exit-fullscreen')).to_be_hidden();check(name+' Escape survives website document navigation',True)
            page.locator(toggle).click();expect(page.locator('#agent-sidebar')).to_be_hidden();page.locator('#enter-fullscreen').click();expect(page.locator('#agent-sidebar')).to_be_visible();page.locator('#exit-fullscreen').click();expect(page.locator('#agent-sidebar')).to_be_hidden();page.locator(toggle).click();check(name+' exit button restores prior sidebar visibility',True)
            page.set_viewport_size({'width':390,'height':844});page.locator('#enter-fullscreen').click();exit_box=page.locator('#exit-fullscreen').bounding_box();composer=question.bounding_box()
            check(name+' mobile keeps exit and chat input on screen',0<=exit_box['y']<844 and composer['y']+composer['height']<=844 and page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            page.screenshot(path=str(out/(name+'-mobile.png')),full_page=True);page.locator('#exit-fullscreen').click();page.set_viewport_size({'width':1512,'height':1040});page.locator('#enter-fullscreen').click()
            question.fill('Find rooms');question.press('Shift+Enter');question.press('f');question.type('or three people.');goal=question.input_value();check(name+' Shift+Enter inserts a newline without sending',goal=='Find rooms\nfor three people.' and len(starts)==count)
            question.dispatch_event('keydown',{'key':'Enter','code':'Enter','isComposing':True});question.dispatch_event('keydown',{'key':'Enter','code':'Enter','keyCode':229});question.dispatch_event('keydown',{'key':'Enter','code':'Enter','repeat':True});check(name+' composing and held Enter do not submit',len(starts)==count)
            question.press('Enter');expect(page.locator(send)).to_be_disabled();question.dispatch_event('keydown',{'key':'Enter','code':'Enter'});expect(page.locator(send)).to_be_enabled(timeout=30000)
            check(name+' Enter sends the exact multiline request once',len(starts)==count+1 and starts[-1]['goal']==goal and starts[-1]['mode']=='assist')
            check(name+' agent run keeps full screen active',page.locator('#exit-fullscreen').is_visible() and page.locator('#conversation .tool-activity[data-state=applied]').count()>0)
            question.fill('   ');question.press('Enter');check(name+' blank Enter does not send',len(starts)==count+1)
            page.screenshot(path=str(out/(name+'-desktop.png')),full_page=True)
            if name=='workspace':
                page.locator('#sidebar-tasks').click();expect(page.locator('#research-view')).to_be_visible();check('Opening task view exits focused layout',not page.locator('body').evaluate("b=>b.classList.contains('site-fullscreen')"))
            else:page.locator('#exit-fullscreen').click()
        check('No browser JavaScript errors',not errors);browser.close()
      sources=['workspace.html','workspace.js','workspace.css','dashboard.js','tool-activity.js','tool-activity.css']
      (out/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'paid_calls':0,'policy':'Offline transport; no model reliability claim','source_sha256':{name:hashlib.sha256((ROOT/'deploy/daylight/client'/name).read_bytes()).hexdigest() for name in sources}},indent=2))
      print(json.dumps({'checks':len(checks),'report':str(out/'report.json'),'paid_calls':0}))
    finally:server.terminate();server.wait(timeout=10)
if __name__=='__main__':main()
