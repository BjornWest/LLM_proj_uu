"""Isolated native-browser checks; no model calls or external map requests."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from .runtime import Runtime
from environments.product_world.travel import export_travel_planner
from environments.product_world.scenario import generate_scenario


async def run(url,export,folder):
    from playwright.async_api import async_playwright
    gate=asyncio.Semaphore(2);results=[]
    branches=[p for p in export['public']['places'] if p['kind']=='branch']
    local=next(p for p in branches if p['city']=='Uppsala')
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True)
        async def check(name):
            async with gate:
                target=folder/name;target.mkdir()
                context=await browser.new_context(viewport={'width':1380,'height':1000})
                await context.tracing.start(screenshots=True,snapshots=True,sources=True)
                page=await context.new_page();errors=[];requests=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:requests.append(r.url))
                try:
                    assert (await page.goto(url)).status==200
                    if name in ('journey','cycling'):
                        await page.get_by_label('To',exact=True).fill(local['name'])
                        await page.locator('form').first.get_by_label('Travel by').select_option('cycling' if name=='cycling' else 'walking')
                        await page.get_by_role('button',name='Find journey',exact=True).click()
                        assert await page.locator('.result.selected').get_attribute('data-mode')==('cycling' if name=='cycling' else 'walking')
                        assert await page.locator('.result').count()==3
                        await page.get_by_role('link',name='Reverse journey').click()
                        assert (await page.locator('#journey-places').inner_text()).startswith(local['label'])
                    elif name=='ambiguous':
                        await page.get_by_label('To',exact=True).fill('Uppsala')
                        await page.get_by_role('button',name='Find journey',exact=True).click()
                        assert await page.get_by_role('heading',name='Choose your places').count()==1
                        await page.get_by_label('To',exact=True).select_option(local['place_id'])
                        await page.get_by_role('button',name='Confirm places').click()
                        assert local['label'] in await page.locator('#journey-places').inner_text()
                    elif name=='unknown':
                        await page.get_by_label('To',exact=True).fill('An address outside this collection')
                        await page.get_by_role('button',name='Find journey',exact=True).click()
                        assert 'Location not found' in await page.locator('.error').inner_text()
                        assert await page.locator('.metric').count()==0
                    elif name=='branch-to-branch':
                        await page.get_by_label('From',exact=True).fill(branches[0]['label'])
                        await page.get_by_label('To',exact=True).fill(branches[1]['label'])
                        await page.get_by_role('button',name='Find journey',exact=True).click()
                        labels=await page.locator('#journey-places').inner_text()
                        assert branches[0]['label'] in labels and branches[1]['label'] in labels
                    else:
                        form=page.locator('form').nth(1)
                        await form.get_by_label('Sort results').select_option('duration')
                        await page.get_by_role('button',name='Search places',exact=True).click()
                        expected=sorted((t for t in export['public']['trips'] if t['origin_id']=='user-home' and t['destination_id']!='user-home' and t['mode']=='driving'),key=lambda t:(t['duration_minutes'] is None,t['duration_minutes'] or 0,t['destination_id']))
                        assert await page.locator('.place').first.get_attribute('data-place')==expected[0]['destination_id']
                        await page.get_by_role('link',name='Next',exact=True).click()
                        assert await page.locator('.place').first.get_attribute('data-place')==expected[12]['destination_id']
                    await page.screenshot(path=str(target/'page.png'),full_page=True)
                    assert not errors
                    assert all(r.startswith(url.split('/w/')[0]) for r in requests)
                    return {'case':name,'passed':True,'external_requests':0}
                except Exception as e:return {'case':name,'passed':False,'error':str(e),'page_errors':errors}
                finally:
                    await context.tracing.stop(path=str(target/'trace.zip'));await context.close()
        results=await asyncio.gather(*(check(n) for n in ('journey','cycling','ambiguous','unknown','branch-to-branch','nearest')))
        await browser.close()
    (folder/'report.json').write_text(json.dumps({'workers':2,'cases':results},indent=2)+'\n')
    print(json.dumps(results));return all(r['passed'] for r in results)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    libs=Path('.local/system-libs/usr/lib/x86_64-linux-gnu').resolve()
    if libs.is_dir():os.environ['LD_LIBRARY_PATH']=str(libs)+':'+os.getenv('LD_LIBRARY_PATH','')
    s=generate_scenario({'seed':2,'family':'footwear','destination_city':'uppsala'},{'seed':42,'models_per_store':2},{})
    export=export_travel_planner(s['bundle'],s['locations'])
    (args.output/'public-export.json').write_text(json.dumps(export['public'],ensure_ascii=False,indent=2))
    with Runtime() as runtime:ok=asyncio.run(run(runtime.register(export),export,args.output))
    raise SystemExit(0 if ok else 1)


if __name__=='__main__':main()
