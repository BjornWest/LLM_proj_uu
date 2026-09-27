"""Bounded store-inspector acceptance; isolated browser contexts, no model calls."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys


async def run(url, output, cases):
    from playwright.async_api import async_playwright
    gate=asyncio.Semaphore(2)
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        async def check(name):
            async with gate:
                folder=output/name;folder.mkdir()
                context=await browser.new_context(viewport={'width':1500,'height':1100},accept_downloads=True)
                await context.tracing.start(screenshots=True,snapshots=True,sources=True)
                page=await context.new_page();errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                try:
                    async with page.expect_response(lambda r:r.url.endswith('/api/scenario')) as wait:
                        assert (await page.goto(url)).status==200
                    result=await (await wait.value).json()
                    await page.wait_for_function("document.querySelectorAll('.inventory-button').length>0")
                    intent_case=name in ('collect','inspect','value','reputation','cookies')
                    if intent_case:
                        await page.locator('#query').select_option({'collect':'nearest_pickup','inspect':'nearest_inspection','value':'unit_price'}.get(name,'cheapest'))
                        await page.locator('#task-family').select_option('beer' if name=='value' else 'footwear')
                        await page.locator('#world-preferences').select_option('reputation' if name=='reputation' else 'none')
                        await page.locator('#cookie-preferences').select_option('analytics_allowed' if name=='cookies' else 'none')
                        await page.locator('#memory').select_option('episodic')
                        await page.locator('#hidden').select_option('none')
                    if name=='sold-out':await page.locator('#stockout').fill('1')
                    if name=='basket':
                        await page.locator('#query').select_option('split_basket')
                        await page.locator('#basket-families').fill('footwear,laptops,dog_food')
                    if name=='france':
                        await page.locator('#destination-country').select_option('FR')
                        await page.locator('#destination-city').select_option('paris')
                    if name=='country':await page.locator('#destination-country').select_option('PT')
                    if name in ('malmo','amsterdam','lille'):
                        await page.locator('#geography-example').select_option(name)
                    if name in ('transfer','pickup','online'):
                        await page.get_by_text('Advanced store and catalog probabilities',exact=True).click()
                        profile='online_specialist' if name=='online' else 'local_shop'
                        await page.locator('#profile-weights').fill(json.dumps({p:int(p==profile) for p in ('local_shop','regional_chain','major_retailer','online_specialist')}))
                        await page.locator('#location-config').fill(json.dumps({'branch_carry_probability':1,'branch_stockout_probability':1 if name=='transfer' else 0,'transfer_probability':1}))
                        await page.locator('#stockout').fill('1' if name=='pickup' else '0')
                    if name=='named':
                        await page.locator('#task-family').select_option('laptops')
                        await page.locator('#query').select_option('average')
                    async with page.expect_response(lambda r:r.url.endswith('/api/scenario')) as wait:
                        await page.get_by_role('button',name='Load location example' if name in ('malmo','amsterdam','lille') else ('Try a beer task & local IPA catalog' if name=='beer' else ('Generate task & stores' if name in ('basket','named','france','country') or intent_case else 'Regenerate stores for this task')),exact=True).click()
                    response=await wait.value;assert response.status==200
                    result=await response.json();bundle=result['bundle'];public=bundle['public']
                    await page.wait_for_function("h=>document.querySelector('#status').textContent.includes(h)",arg=bundle['world_sha256'][:12])
                    assert await page.locator('#error').inner_text()==''
                    assert await page.locator('.store').count()==6
                    expected_relevant=sum(any(f in bundle['private_provenance']['family_scope'] for f in s['families']) for s in result['summary']['stores'])
                    assert await page.locator('.store.focus').count()==expected_relevant
                    for store in public['retailers'][:2]:
                        await page.locator('.inventory-button[data-store="'+store['retailer_id']+'"]').click()
                        assert store['name'] in await page.locator('#inventory-title').inner_text()
                        offers=[o for o in public['offers'] if o['retailer_id']==store['retailer_id']]
                        assert await page.locator('#inventory tr').count()==len(offers)+1
                    assert await page.locator('#overlap-matrix th').count()==7
                    if name=='sold-out':
                        assert all(o['stock_quantity']==0 for o in public['offers'])
                        assert 'Sold out' in await page.locator('#inventory').inner_text()
                    if name=='beer':
                        assert all(s['profile_id']=='drinks' for s in public['retailers'])
                        assert all(p['attributes']['production_region']=='Uppsala' for p in public['products'])
                    for button,value in (('download',result),('public',public),('index-download',public['web_index'])):
                        async with page.expect_download() as wait:await page.locator('#'+button).click()
                        download=await wait.value;path=folder/(button+'.json');await download.save_as(path)
                        assert json.loads(path.read_text())==value
                    async with page.expect_response(lambda r:r.url.endswith('/api/location-quotes')) as wait:
                        await page.locator('#refresh-quotes').click()
                    response=await wait.value;assert response.status==200
                    quotes=await response.json()
                    await page.wait_for_function("document.querySelector('#delivery-quote').textContent.length>0")
                    assert quotes['world_sha256']==bundle['world_sha256']
                    if name=='transfer':
                        assert all(q['pickup']['requires_stock_transfer'] and q['pickup']['ready_days']>0 for q in quotes['branches'])
                        assert 'Warehouse transfer' in await page.locator('#branch-quotes').inner_text()
                    if name=='pickup':
                        assert not quotes['delivery']['eligible']
                        assert all(q['pickup']['eligible'] and not q['pickup']['requires_stock_transfer'] for q in quotes['branches'])
                    if name=='online':
                        assert quotes['branches']==[]
                        assert 'Online-only' in await page.locator('#branch-quotes').inner_text()
                    if name=='france':assert result['task']['request']['context']['destination']=='FR'
                    if name=='country':assert result['task']['request']['context']['destination']=='PT'
                    if name in ('malmo','amsterdam','lille'):
                        loc=result['locations']['public'];first=loc['merchants'][0]['branches'][0]
                        assert first['location']['country']!=loc['user_location']['country']
                        assert loc['user_location']['city_id']==name
                        assert all('cycling' in q['pickup']['travel'] for q in quotes['branches'])
                        assert await page.locator('#travel-open').get_attribute('href')==result['travel_planner_url']
                    if intent_case:
                        async with page.expect_response(lambda r:r.url.endswith('/api/reference-outcome')) as wait:
                            await page.locator('#reference-outcome').click()
                        response=await wait.value;assert response.status==200
                        reference=await response.json()
                        assert reference['world_sha256']==bundle['world_sha256']
                        assert reference['outcome']['status'] in ('determined','no_match','uncertain')
                        assert reference['candidate_count']>0
                        if name in ('collect','inspect'):assert result['task']['world_memory_facts']
                        if name=='cookies':assert result['task']['resolved_task']['cookie_preferences']['analytics']=='allowed'
                        if name=='value':assert result['task']['resolved_task']['query']['unit']=='litre'
                    async with page.expect_download() as wait:await page.locator('#locations-download').click()
                    download=await wait.value;path=folder/'locations.json';await download.save_as(path)
                    assert json.loads(path.read_text())==result['locations']
                    task=result['task']
                    await page.wait_for_function("t=>document.querySelector('#task-message').textContent===t",arg=task['public']['user_message'])
                    assert set(l['family_id'] for l in task['request']['lines'])==set(bundle['private_provenance']['family_scope'])
                    assert await page.locator('#task-panel').evaluate("e=>e.compareDocumentPosition(document.querySelector('#controls')) & Node.DOCUMENT_POSITION_FOLLOWING")
                    if name=='named':
                        model=task['request']['lines'][0]['model']
                        assert any(g['group_id']==model['id'] and g['name']==model['name'] for g in public['product_groups'])
                    await page.locator('#seed').fill('99')
                    async with page.expect_response(lambda r:r.url.endswith('/api/scenario')) as wait:
                        await page.get_by_role('button',name='Regenerate stores for this task',exact=True).click()
                    regenerated=await (await wait.value).json()
                    assert regenerated['task']==task
                    assert regenerated['bundle']['world_sha256']!=bundle['world_sha256']
                    await page.screenshot(path=str(folder/'preview.png'),full_page=True)
                    if name=='default':
                        await page.locator('#store-count').fill('1')
                        async with page.expect_response(lambda r:r.url.endswith('/api/scenario')) as wait:
                            await page.get_by_role('button',name='Regenerate stores for this task',exact=True).click()
                        assert (await wait.value).status==400
                        await page.wait_for_function("document.querySelector('#error').textContent.length>0")
                    assert not errors
                    return {'case':name,'passed':True}
                except Exception as e:return {'case':name,'passed':False,'error':str(e),'page_errors':errors}
                finally:
                    await context.tracing.stop(path=str(folder/'trace.zip'));await context.close()
        results=await asyncio.gather(*(check(n) for n in cases));await browser.close()
    (output/'report.json').write_text(json.dumps({'workers':2,'cases':results},indent=2)+'\n')
    print(json.dumps(results));return all(r['passed'] for r in results)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--case',action='append',choices=('default','sold-out','basket','beer','named','france','transfer','pickup','online','country','malmo','amsterdam','lille','collect','inspect','value','reputation','cookies'));args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    libs=Path(__file__).resolve().parents[2]/'.local/system-libs/usr/lib/x86_64-linux-gnu'
    if libs.is_dir():os.environ['LD_LIBRARY_PATH']=str(libs)+':'+os.getenv('LD_LIBRARY_PATH','')
    with (args.output/'server.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-m','environments.product_world','serve','--port','0'],stdout=subprocess.PIPE,stderr=log,text=True)
        try:
            line=server.stdout.readline().strip()
            if not line.startswith('Catalog authoring: '):raise RuntimeError('Server failed')
            ok=asyncio.run(run(line.split(': ',1)[1],args.output,args.case or ['default','sold-out','basket','beer','named','france','transfer','pickup','online']))
        finally:server.terminate();server.wait(timeout=10)
    sys.exit(0 if ok else 1)


if __name__=='__main__':main()
