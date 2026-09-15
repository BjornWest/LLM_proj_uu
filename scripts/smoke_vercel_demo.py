"""Offline end-to-end verification of the separate Vercel demo. No inference calls."""
import json
import os
import re
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]

def main():
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.environ.get('LD_LIBRARY_PATH', '')
    process = subprocess.Popen(['node', 'tests/mock_server.mjs'], cwd=ROOT/'deploy/daylight', stdout=subprocess.DEVNULL)
    output = ROOT/'.local/vercel-demo'
    output.mkdir(parents=True, exist_ok=True)
    try:
        for _ in range(50):
            try:
                urlopen('http://localhost:8881/login', timeout=1)
                break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width':1500,'height':980})
            errors=[]
            page.on('pageerror',lambda error: errors.append(str(error)))
            page.goto('http://localhost:8881')
            page.get_by_label('Your invitation code').fill('offline-test-code-'*4)
            page.get_by_role('button',name='Open demo').click()
            page.wait_for_selector('#site')
            results=[]
            for area in ['booking','shop','preferences']:
                page.locator('[data-area="'+area+'"]').click()
                page.frame_locator('#site').locator('#content h1').wait_for()
                page.locator('#tasks-tab').click()
                page.locator('#run').click()
                page.wait_for_timeout(250)
                expect(page.locator("#status")).to_have_text(re.compile("Finished|Stopped"),timeout=30000)
                assert page.locator('#status').inner_text().lower()=='finished',(area,page.locator('#status').inner_text(),page.locator('#notice').inner_text(),page.locator('#steps').inner_text(),errors)
                state=page.evaluate('window.demoWorld.state')
                if area=='booking': assert state['bookings'][0]['room']=='Å101' and len(state['bookings'])==1
                elif area=='shop': assert state['orders'][0]['total']==118
                else: assert state['preferences']=={'frequency':'monthly','tips':False}
                trace=page.locator('#trace').get_attribute('href')
                record=page.request.get("http://localhost:8881"+trace).json()
                assert record['evaluation'] is None and record['browsergym'] is False
                assert all(s['request'] and s['response'] and s['client_result'] for s in record['steps'])
                results.append({'area':area,'status':record['status'],'requests':len(record['steps']),'runtime':record['runtime']})
            before=page.evaluate('window.demoWorld.state')
            page.locator('#chat-tab').click()
            page.locator('#question').fill('What is on this page?')
            page.locator('#send-chat').click()
            expect(page.locator("#chat-notice")).to_contain_text("Model spend")
            assert page.evaluate('window.demoWorld.state')==before
            stale=page.evaluate('''async()=>{const {snapshot,execute}=await import('/assets/observation.js');const doc=document.querySelector('#site').contentDocument;
              const b=doc.createElement('button');b.textContent='Transient close';doc.body.append(b);const old=snapshot(doc);const id=old.observation.controls.find(c=>c.label==='Transient close').id;b.remove();
              try{execute({action:'click',id},old,doc);return false}catch(e){return e.message.includes('page changed')}}''')
            assert stale
            page.screenshot(path=str(output/'vercel-demo-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(output/'vercel-demo-mobile.png'),full_page=True)
            assert not errors,errors
            (output/'offline-smoke.json').write_text(json.dumps({'cases':results,'interactive_chat_no_state_change':True,'stale_control_rejected':True,'page_errors':errors,'paid_calls':0},indent=2)+'\n')
            browser.close()
        print('Three task flows, interactive chat, stale-control rejection, private trace downloads: passed. No paid calls.')
    finally:
        process.terminate()
        process.wait(timeout=10)

if __name__=='__main__': main()
