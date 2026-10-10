"""Zero-provider UI checks for recorded episode stop reasons in both viewers."""
import argparse,asyncio,hashlib,json,os,sys,tempfile,threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT.parent/'common_agent_util')]
from agent_trace.sessions import make_handler
from scripts.trace_hub import make_handler as hub_handler

async def check_mode(mode,output):
    output.mkdir(parents=True,exist_ok=False);checks=[];errors=[]
    def check(name,value):
        assert value,name
        checks.append(name)
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);runs=root/'runs';runs.mkdir();pins={}
        cases=[('turns',{'stop_reason':'max_steps','step_count':24},'Turn limit stop (24 / 24 turns)'),
               ('under-limit',{'stop_reason':'max_steps','step_count':3},'Turn limit stop (3 / 24 turns)'),
               ('custom',{'stop_reason':'constructor'},'constructor'),
               ('tokens',{'stop_reason':'max_input_tokens'},'Input token limit reached (32,000 tokens)'),
               ('manual',{'stop_reason':'user_close'},'Manually closed'),
               ('interrupt',None,'Interrupted'),
               ('error',{'stop_reason':'error','execution_error':'\n\r\n<img src=x onerror=alert(1)> browser error'},'Run error'),
               ('normal',{'stop_reason':'agent_finished','error':'Grading failure'},'Agent finished'),
               ('unknown',{'step_count':24},'End reason not recorded'),
               ('active',None,None)]
        for name,episode,label in cases:
            run=runs/name;run.mkdir()
            values={'metadata.json':{'browsergym_version':'fixture','driver':'scripted_validation','tags':['scripted'],'trace_title':name,'max_steps':24,'max_input_tokens':32000},
                    'steps.jsonl':{'step':0,'model_response':{'choices':[{'finish_reason':'length','message':{'content':'Fixture '+name}}]}},
                    'evaluation.json':{'safe_success':False},
                    'events.jsonl':{'event':'episode_finished','stop_reason':'interrupted','error':'KeyboardInterrupt'} if name=='interrupt' else {'event':'episode_started'}}
            if episode is not None:values['episode.json']=episode
            for filename,data in values.items():
                path=run/filename;path.write_text(json.dumps(data)+'\n');pins[path]=hashlib.sha256(path.read_bytes()).hexdigest()
        registry=root/'sources.json';registry.write_text(json.dumps({'project_root':str(root),'roots':[str(runs)]}))
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(runs) if mode=='shared' else hub_handler(registry))
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();base='http://localhost:'+str(server.server_port)
        try:
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=True);page=await browser.new_page(viewport={'width':1440,'height':1000})
                page.on('pageerror',lambda e:errors.append(str(e)))
                catalog=await (await page.request.get(base+'/api/sessions')).json()
                ids={name:hashlib.sha256(('browsergym:'+name).encode()).hexdigest()[:20] for name,_,_ in cases}
                check('catalog contains all fixtures',set(ids.values())=={row['id'] for row in catalog})
                await page.goto(base+'/#'+ids['turns']);await page.wait_for_function('(id)=>current?.id===id',arg=ids['turns'])
                await page.locator('#live').uncheck()
                check('unopened sidebar shows end reason',await page.locator('#sessions [data-session-id='+json.dumps(ids['manual'])+'] .episode-end-label').inner_text()=='Ended: Manually closed')
                for name,episode,label in cases:
                    await page.goto(base+'/#'+ids[name]);await page.wait_for_function('(id)=>current?.id===id',arg=ids[name])
                    if label is None:
                        check('unfinished trace clears previous end banner',await page.locator('#episode-end').is_hidden())
                        continue
                    check(name+' end reason visible with diagnostics off',await page.locator('#episode-end .episode-end-label').inner_text()=='Episode ended: '+label and not await page.locator('#diagnostics').is_checked())
                    sidebar=page.locator('#sessions [data-session-id='+json.dumps(ids[name])+'] .episode-end-label')
                    check(name+' end reason in sidebar',await sidebar.inner_text()=='Ended: '+label)
                    details=page.locator('#episode-end > details')
                    check(name+' raw end details collapsed',not await details.evaluate('(el)=>el.open'))
                    await details.locator(':scope > summary').click()
                    check(name+' readable JSON available',await details.get_by_role('button',name='Readable JSON',exact=True).get_attribute('aria-pressed')=='true')
                    check(name+' detail shows raw source', 'source' in await details.inner_text())
                    await page.locator('#search').fill('fixture')
                    check(name+' open details survive search',await details.evaluate('(el)=>el.open'))
                    await page.locator('#search').fill('')
                    if name=='interrupt':check('lifecycle fallback is explained','events.jsonl:episode_finished' in await details.inner_text())
                    if name=='error':
                        check('recorded error renders as inert text',await page.locator('#episode-end img').count()==0 and '<img src=x onerror=alert(1)>' in await page.locator('#episode-end').inner_text())
                        check('error preview uses first nonempty line',await page.locator('#episode-end > .muted').inner_text()=='Recorded error: <img src=x onerror=alert(1)> browser error')
                    if name=='normal':check('grading failure does not masquerade as execution error','Grading failure' not in await page.locator('#episode-end').inner_text())
                completed=runs/'active'/'episode.json';completed.write_text(json.dumps({'stop_reason':'user_close'})+'\n')
                pins[completed]=hashlib.sha256(completed.read_bytes()).hexdigest()
                # Exercise the real live timer, allowing the shared catalog's check interval.
                await page.locator('#live').check()
                await page.wait_for_function('current?.episode_end?.reason==="user_close"',timeout=10000)
                await page.locator('#live').uncheck()
                check('live completion shows recorded reason',await page.locator('#episode-end .episode-end-label').inner_text()=='Episode ended: Manually closed')
                card=page.locator('#sessions [data-session-id='+json.dumps(ids['active'])+']')
                order=await card.evaluate('(el)=>Array.from(el.children).map(child=>child.className)')
                check('live completion keeps sidebar order',order.index('episode-end-label')<order.index('max-isl'))
                await page.reload();await page.wait_for_function('(id)=>current?.id===id',arg=ids['active']);await page.locator('#live').uncheck()
                check('reload keeps same sidebar order',order==await card.evaluate('(el)=>Array.from(el.children).map(child=>child.className)'))
                await page.goto(base+'/#'+ids['tokens']);await page.wait_for_function('(id)=>current?.id===id',arg=ids['tokens'])
                await page.screenshot(path=str(output/'desktop.png'))
                await page.set_viewport_size({'width':390,'height':844})
                check('mobile layout fits',await page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                await page.screenshot(path=str(output/'mobile.png'),full_page=True)
                await page.goto(base+'/?tag=__missing_tag__#latest');await page.wait_for_function('sessions.length&&current===null')
                check('empty filtered scope clears end reason',await page.locator('#episode-end').is_hidden())
                check('no JavaScript errors',not errors)
                await browser.close()
            check('saved originals unchanged',all(hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in pins.items()))
        finally:server.shutdown();server.server_close();worker.join()
    result={'mode':mode,'passed':True,'checks':checks,'errors':errors,'model_calls':0}
    (output/'report.json').write_text(json.dumps(result,indent=2));return {'mode':mode,'checks':len(checks),'passed':True}

async def main(output):
    results=await asyncio.gather(*(check_mode(mode,output/mode) for mode in ('shared','hub')),return_exceptions=True)
    for result in results:
        if isinstance(result,BaseException):raise result
    print(json.dumps(results))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
    asyncio.run(main(args.output))
