"""Zero-provider browser checks of real folder APIs in both viewer modes."""
import argparse
import asyncio
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'common_agent_util'))
from agent_trace.sessions import make_handler
from scripts.trace_hub import make_handler as hub_handler


async def check_mode(mode,output):
    output.mkdir(parents=True,exist_ok=False);checks=[];errors=[]
    def check(name,value):
        assert value,name
        checks.append(name)
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);runs=root/'runs';runs.mkdir();pins={}
        for name,collection in [('checkout','Integration/checkout'),('smoke','Integration/smoke'),('similar','Integration-other'),('train','RL/experiment-1')]:
            run=runs/name;run.mkdir()
            for filename,data in [('metadata.json',dict(browsergym_version='fixture',trace_title=name,collection=collection,tags=['integration','checkout'] if name=='checkout' else ['integration','smoke'] if name=='smoke' else [])),
                                  ('steps.jsonl',dict(step=0,model_response={'choices':[{'message':{'content':'Fixture '+name}}]}))]:
                path=run/filename;path.write_text(json.dumps(data)+'\n');pins[path]=hashlib.sha256(path.read_bytes()).hexdigest()
        registry=root/'sources.json';registry.write_text(json.dumps({'project_root':str(root),'roots':[str(runs)]}))
        handler=make_handler(runs) if mode=='shared' else hub_handler(registry)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url='http://localhost:'+str(server.server_port)
        try:
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=True)
                page=await browser.new_page(viewport={'width':1400,'height':1000})
                page.on('pageerror',lambda error:errors.append(str(error)))
                async def select_collection(path):
                    parts=path.split('/')
                    for i in range(1,len(parts)):
                        toggle=page.locator('#collection [data-folder-toggle='+json.dumps('/'.join(parts[:i]))+']')
                        if await toggle.get_attribute('aria-expanded')=='false':await toggle.click()
                    await page.locator('#collection [data-collection='+json.dumps(path)+']').click()
                await page.goto(url+'/?collection=Integration#latest')
                await page.locator('#sessions .session').first.wait_for()
                await page.locator('#live').uncheck()
                check('parent includes two descendant folders only',await page.locator('#sessions .session').count()==2)
                check('collection is preserved in URL', 'collection=Integration' in page.url)
                await page.locator('#recording-location').wait_for()
                current_id=await page.evaluate('current.id')
                recording_path=await page.locator('#recording-location').inner_text()
                check('trace heading shows actual absolute recording directory',recording_path.startswith(str(runs)+'/') and recording_path.endswith('/'))
                sidebar_path=page.locator('#sessions [data-session-id='+json.dumps(current_id)+'] .recording-location')
                check('sidebar location below name has full path on hover',await sidebar_path.get_attribute('title')==recording_path and await sidebar_path.evaluate('(el)=>el.previousElementSibling.tagName==="B"'))
                await page.locator('#tag-filter summary').click()
                await page.locator('#tag-filter [data-tag="checkout"]').click()
                await page.wait_for_function("document.querySelectorAll('#sessions .session').length===1")
                check('tag filter intersects folder scope',await page.locator('#sessions .session').count()==1 and 'tag=checkout' in page.url)
                await page.locator('#tag-filter [data-tag="smoke"]').click()
                await page.wait_for_function("document.querySelectorAll('#sessions .session').length===0")
                check('multiple selected tags require all matches',await page.locator('#sessions .session').count()==0)
                await page.locator('#clear-tags').click()
                await page.wait_for_function("document.querySelectorAll('#sessions .session').length===2")
                check('clearing tags restores folder scope',await page.locator('#sessions .session').count()==2)
                check('nested folders initially collapsed',not await page.locator('#collection [data-collection="Integration/checkout"]').is_visible())
                toggle=page.locator('#collection [data-folder-toggle="Integration"]')
                await toggle.focus();await toggle.press('Enter')
                check('keyboard expands a folder branch',await page.locator('#collection [data-collection="Integration/checkout"]').is_visible())
                await select_collection('Integration/checkout')
                await page.wait_for_function("document.querySelectorAll('#sessions .session').length===1")
                check('selecting a nested folder filters episodes',await page.locator('#sessions .session').count()==1)
                await select_collection('Integration')
                await page.wait_for_function("document.querySelectorAll('#sessions .session').length===2")
                await toggle.click()
                await page.evaluate('refresh()')
                check('refresh preserves collapsed branch and parent filter',not await page.locator('#collection [data-collection="Integration/checkout"]').is_visible() and await page.evaluate('selectedCollection')=='Integration')
                await page.evaluate("window.keptCard=document.querySelector('#sessions .session')")
                await select_collection('RL')
                await page.wait_for_function("document.querySelectorAll('#sessions .session').length===1")
                check('RL folder displays one episode',await page.locator('#sessions .session').count()==1)
                await select_collection('Integration')
                await page.wait_for_function("document.querySelectorAll('#sessions .session').length===2")
                check('sidebar cards reused across filters',await page.evaluate('keptCard.isConnected'))
                await page.locator('#create-folder').click()
                await page.locator('#collection-path').fill('RL/new experiment/iteration 1')
                await page.locator('#collection-dialog button').filter(has_text='Save').click()
                await page.wait_for_function("document.querySelector('#collection').dataset.selectedCollection==='RL/new experiment/iteration 1'")
                check('empty folder selectable',await page.locator('#sessions .session').count()==0)
                check('empty folder clears previous recording location',await page.locator('#recording-location').is_hidden())
                check('empty state describes selected folder',await page.locator('#title').inner_text()=='No episodes in this folder')
                await page.reload();await page.locator('#collection').wait_for()
                await page.wait_for_function("document.querySelectorAll('#collection [data-collection]').length>1")
                check('selected folder ancestors revealed after reload',await page.locator('#collection [data-collection="RL/new experiment/iteration 1"]').is_visible())
                check('empty folder survives refresh',await page.locator('#collection').get_attribute('data-selected-collection')=='RL/new experiment/iteration 1')
                await page.locator('#live').uncheck()
                await select_collection('Integration')
                await page.wait_for_function("document.querySelectorAll('#sessions .session').length===2")
                await page.locator('#organize-folders').click();await page.locator('#select-folder').click()
                check('bulk select independent of opening traces',await page.locator('#sessions input:checked').count()==2)
                await page.locator('#edit-tags').click();await page.locator('#tag-input').fill('smoke, reviewed')
                await page.locator('#tag-dialog button').filter(has_text='Save').click()
                await page.wait_for_function("sessions.filter(s=>s.viewer_tags?.includes('reviewed')).length===2")
                check('bulk tag edit keeps original tags',await page.evaluate("sessions.find(s=>s.viewer_tags?.includes('checkout')).viewer_tags.includes('reviewed')"))
                await page.locator('#organize-folders').click();await page.locator('#select-folder').click()
                await page.locator('#edit-tags').click();await page.locator('#tag-operation').select_option('tag_remove');await page.locator('#tag-input').fill('smoke')
                await page.locator('#tag-dialog button').filter(has_text='Save').click()
                await page.wait_for_function("sessions.filter(s=>s.viewer_tags?.includes('reviewed')).every(s=>!s.viewer_tags.includes('smoke'))")
                check('bulk removal overrides declared tags without losing others',await page.evaluate("sessions.filter(s=>s.viewer_tags?.includes('reviewed')).length===2"))
                await page.reload();await page.wait_for_function("sessions.filter(s=>s.viewer_tags?.includes('reviewed')).length===2")
                await page.locator('#live').uncheck()
                check('tag edits survive reload',await page.evaluate("sessions.filter(s=>s.viewer_tags?.includes('reviewed')).every(s=>!s.viewer_tags.includes('smoke'))"))
                await page.locator('#organize-folders').click();await page.locator('#select-folder').click()
                await page.locator('#move-episodes').click();await page.locator('#collection-path').fill('RL/new experiment/iteration 1')
                await page.locator('#collection-dialog button').filter(has_text='Save').click()
                await page.wait_for_function("document.querySelector('#collection').dataset.selectedCollection==='RL/new experiment/iteration 1'&&document.querySelectorAll('#sessions .session').length===2")
                check('bulk move updates folder membership',await page.locator('#sessions .session').count()==2)
                check('logical move preserves displayed physical location',(await page.locator('#recording-location').inner_text()).startswith(str(runs)+'/'))
                nested_ident=await page.locator('#sessions .session').first.get_attribute('data-session-id')
                await page.goto(url+'/#'+nested_ident)
                await page.wait_for_function("document.querySelector('#collection [data-collection=\"RL/new experiment/iteration 1\"]')&&!document.querySelector('#collection [data-folder-toggle=\"RL\"]').disabled")
                check('unscoped episode link reveals nested ancestors',await page.locator('#collection [data-collection="RL/new experiment/iteration 1"]').is_visible() and await page.evaluate('selectedCollection')=='')
                await page.locator('#live').uncheck();await page.locator('#collection [data-folder-toggle="RL"]').click();await page.evaluate('refresh()')
                check('direct-link refresh preserves deliberate collapse',not await page.locator('#collection [data-collection="RL/new experiment/iteration 1"]').is_visible())
                await select_collection('Integration-other')
                await page.wait_for_function("document.querySelectorAll('#sessions .session').length===1")
                check('sibling prefix not included',await page.locator('#sessions .session').count()==1)
                ident=await page.locator('#sessions .session').get_attribute('data-session-id')
                await page.goto(url+'/?collection=RL#'+ident)
                await page.wait_for_function("document.querySelector('#collection').dataset.selectedCollection==='Integration-other'")
                check('deep link reveals the correct folder',await page.locator('#collection').get_attribute('data-selected-collection')=='Integration-other')
                state=await (await page.request.get(url+'/api/collections')).json()
                bad=await page.request.post(url+'/api/collections',data=json.dumps({'action':'create','path':'../escape'}),headers={'Content-Type':'application/json','If-Match':'"'+state['revision']+'"'})
                check('invalid folder rejected',bad.status==400)
                conflict=await page.request.post(url+'/api/collections',data=json.dumps({'action':'create','path':'Other'}),headers={'Content-Type':'application/json','If-Match':'"stale"'})
                check('stale edit rejected',conflict.status==409)
                cross=await page.request.post(url+'/api/collections',data=json.dumps({'action':'create','path':'Other'}),headers={'Content-Type':'application/json','Origin':'http://elsewhere.invalid','If-Match':'"'+state['revision']+'"'})
                check('cross-origin edit rejected',cross.status==403)
                if mode=='hub':
                    await page.request.post(url+'/api/collections',data=json.dumps({'action':'create','path':'Empty/folder'}),headers={'Content-Type':'application/json','If-Match':'"'+state['revision']+'"'})
                    await page.goto(url+'/#suites')
                    await page.wait_for_function("document.querySelector('#suite-view h2')?.textContent==='Episode suites'&&collectionState.revision")
                    await page.evaluate("document.querySelector('#live').checked=false")
                    check('cold suite landing can create folders',not await page.locator('#create-folder').is_disabled())
                    check('cold suite landing can select episodes',not await page.locator('#organize-folders').is_disabled())
                    check('cold suite landing includes empty folders',await page.locator('#collection [data-collection="Empty/folder"]').count()==1)
                else:
                    entered=asyncio.Event();release=asyncio.Event();first=True
                    async def delay_collection(route):
                        nonlocal first
                        if first:
                            first=False;response=await route.fetch();body=await response.body()
                            entered.set();await release.wait();await route.fulfill(response=response,body=body)
                        else:await route.continue_()
                    await page.route('**/api/collections',delay_collection)
                    await page.evaluate('window.olderRefresh=refresh(); void 0')
                    await asyncio.wait_for(entered.wait(),20)
                    saved=await (await page.request.post(url+'/api/collections',data=json.dumps({'action':'create','path':'Fresh/folder'}),headers={'Content-Type':'application/json','If-Match':'"'+state['revision']+'"'})).json()
                    await page.evaluate('refresh()');release.set();await page.evaluate('olderRefresh')
                    check('obsolete refresh cannot replace newer metadata',await page.evaluate('collectionState.revision')==saved['revision'])
                    check('obsolete refresh cannot hide empty folders',await page.locator('#collection [data-collection="Fresh/folder"]').count()==1)
                await page.set_viewport_size({'width':390,'height':844})
                check('mobile has no horizontal overflow',await page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                await page.screenshot(path=str(output/'mobile.png'),full_page=True)
                check('no JS errors',not errors)
                await browser.close()
            check('original recordings unchanged',all(hashlib.sha256(path.read_bytes()).hexdigest()==pin for path,pin in pins.items()))
        finally:
            server.shutdown();server.server_close();thread.join()
    (output/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'errors':errors,'model_calls':0},indent=2))
    return {'mode':mode,'passed':True,'checks':len(checks)}


async def main(output):
    results=await asyncio.gather(*(check_mode(mode,output/mode) for mode in ('shared','hub')),return_exceptions=True)
    for result in results:
        if isinstance(result,BaseException):raise result
    print(json.dumps(results))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
    asyncio.run(main(args.output))
