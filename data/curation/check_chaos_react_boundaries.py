"""Privileged async Playwright tests for the copied React queue lifecycle.

Uses native clicks plus explicit test-only SPA navigation. No model calls,
shared source changes, direct interaction API calls, or benchmark-success labels.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from intent_browser.chaos import ChaosClient
from playwright.async_api import async_playwright


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def descriptor(bundle,session):
    result=subprocess.run(['node','scripts/inspect_chaos.mjs'],input=json.dumps({
        'bundle':str(bundle),'task':'transfer-by-not-clicking-save','session':session['session']}),
        text=True,capture_output=True,check=True,cwd=ROOT)
    return json.loads(result.stdout)


def selector(target):return '[data-bac='+json.dumps(target)+']'


async def main(args):
    if args.report.exists():raise ValueError('Use a new report path')
    origin=args.base_url.rstrip('/')
    if origin=='http://localhost:45379':raise ValueError('Original server is frozen')
    bundle=args.bundle.resolve()
    manifest=bundle.parent/'intent-repair.json'
    repair=json.loads(manifest.read_text())
    original=Path(repair['original_package'])/'dist/cli.mjs'
    before={str(p):sha(p) for p in [bundle,manifest,original,bundle.parent/'web/assets/index-CiX7pK2V.js',bundle.parent/'web/assets/intent-stage-queue.mjs']}
    report={'scope':'Privileged copied-React lifecycle tests; explicit test-only SPA navigation; not policy episodes or grader certification',
            'source_sha256':before,'script_sha256':sha(__file__),'cases':[],'complete':False,'model_calls':0,
            'training_eligible':False,'safe_success':None}
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
    client=ChaosClient(origin)
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=True)
            try:
                for scenario in ('queued-double-click','unmount-pending-save'):
                    session=client.prepare('transfer-by-not-clicking-save')
                    stage=descriptor(bundle,session)['stage']
                    context=await browser.new_context()
                    page=await context.new_page()
                    sent=[];gate=asyncio.Event();held=asyncio.Event();pending_routes=[]
                    async def intercept(route):
                        data=route.request.post_data_json
                        event=data['event'];sent.append({'event':event,'intercepted_at':datetime.now(timezone.utc).isoformat()})
                        kind='click' if scenario=='queued-double-click' else 'input'
                        if event['kind']==kind and not held.is_set():
                            held.set();pending_routes.append(route)
                            await gate.wait()
                        await route.continue_()
                    await page.route('**/api/stage/*/interact',intercept)
                    result={'case':scenario,'session':session['session'],'passed':False,'control_events':[]}
                    report['cases'].append(result)
                    try:
                        await page.goto(origin+session['selected']['taskUrl'])
                        target,value=next(iter(stage['check']['expectedValues'].items()))
                        await page.locator(selector(target)).wait_for()
                        await page.locator(selector(target)).fill(value)
                        commit=page.locator(selector(stage['check']['mustClick'][0]))
                        if scenario=='queued-double-click':
                            # Flush both blurs; the double-click itself is two native clicks.
                            await page.locator(selector(target)).press('Tab')
                            await page.locator(selector(stage['data']['fields'][-1]['id'])).press('Tab')
                            await page.wait_for_function("() => window.__intentChaosQueueSnapshot().events.filter(e=>e.phase==='dispatched').length === window.__intentChaosQueueSnapshot().events.filter(e=>e.phase==='completed').length")
                            await commit.dblclick()
                            await asyncio.wait_for(held.wait(),5)
                            await page.wait_for_function("() => window.__intentChaosQueueSnapshot().events.filter(e=>e.phase==='queued'&&e.kind==='click').length===2")
                            before_release=await page.evaluate('() => window.__intentChaosQueueSnapshot()')
                            gate.set()
                            await page.wait_for_function("() => window.__intentChaosQueueSnapshot().events.some(e=>e.phase==='discarded'&&e.kind==='click')")
                            final=await page.evaluate('() => window.__intentChaosQueueSnapshot()')
                            clicks=[e for e in final['events'] if e['kind']=='click']
                            assert sum(e['phase']=='queued' for e in clicks)==2
                            assert sum(e['phase']=='dispatched' for e in clicks)==1
                            assert sum(e['phase']=='discarded' for e in clicks)==1
                            result['control_events']=['native fill','native name Tab','native owner Tab','native double-click (two clicks)','release held click HTTP request']
                        else:
                            await commit.click()
                            await asyncio.wait_for(held.wait(),5)
                            await page.wait_for_function("() => window.__intentChaosQueueSnapshot().events.some(e=>e.phase==='queued'&&e.kind==='click')")
                            before_release=await page.evaluate('() => window.__intentChaosQueueSnapshot()')
                            # Preserve only a diagnostic reference, then force SPA route change.
                            await page.evaluate("() => {window.__independentOldQueue=window.__intentChaosQueueSnapshot;history.pushState({},'', '/');window.dispatchEvent(new PopStateEvent('popstate'));}")
                            await page.wait_for_function("() => window.__independentOldQueue().reason==='unmounted'")
                            gate.set()
                            await page.wait_for_function("() => window.__independentOldQueue().events.some(e=>e.phase==='discarded'&&e.kind==='click')")
                            final=await page.evaluate('() => window.__independentOldQueue()')
                            assert final['reason']=='unmounted'
                            assert not any(e['phase']=='dispatched' and e['kind']=='click' for e in final['events'])
                            assert page.url.rstrip('/')==origin
                            result['control_events']=['native fill','native save click','diagnostic old-queue reference','test-only history.pushState/popstate unmount','release held input HTTP request']
                        events=client.get('/api/events/'+session['session'])['events']
                        server=[e for e in events if e['event'] in ('input','click')]
                        server_clicks=[e for e in server if e['event']=='click']
                        assert len(server_clicks)==(1 if scenario=='queued-double-click' else 0)
                        result.update(passed=True,before_release=before_release,final_queue=final,
                                      intercepted_requests=sent,server_interactions=server,
                                      final_url=page.url,held_request_kind='click' if scenario=='queued-double-click' else 'input')
                    except Exception as exc:
                        result['error']=f'{type(exc).__name__}: {exc}'
                    finally:
                        gate.set()
                        await context.close()
                        args.report.parent.mkdir(parents=True,exist_ok=True)
                        args.report.write_text(json.dumps(report,indent=2))
                    print(scenario,result['passed'],result.get('error',''),flush=True)
            finally:await browser.close()
    finally:client.close()
    report['sources_unchanged']=all(sha(p)==h for p,h in before.items())
    report['complete']=True
    report['passed']=report['sources_unchanged'] and all(c['passed'] for c in report['cases'])
    args.report.write_text(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
