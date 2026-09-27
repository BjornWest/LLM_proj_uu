"""Scripted public-page solve of the pinned footwear task; no model calls.

The solver receives only the policy projection. Scenario/oracle data stay in the
host, which grades after the browser returns its independently selected answer.
This is a bounded integration acceptance, not a general-purpose shopping agent.
"""
import argparse
import asyncio
from decimal import Decimal
import json
from itertools import product
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


def money(text):
    return int(Decimal(text.removesuffix(' SEK').strip())*100)


async def solve(policy, output):
    from playwright.async_api import async_playwright
    size=next(m['value'] for m in policy['memories']['profile']
              if m.get('attribute')=='EU shoe size' and m['operator']=='eq')
    budget_match=re.search(r'budget is (\d+) SEK including shipping',policy['user_message'])
    if not budget_match or 'cheapest' not in policy['user_message'] or 'home delivery' not in policy['user_message']:
        raise ValueError('This acceptance solver supports the pinned cheapest-delivered footwear request only')
    budget=int(budget_match[1])*100
    observations=[];exposures=[];requests=[];errors=[]
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        context=await browser.new_context(viewport={'width':1440,'height':1000})
        context.set_default_timeout(10000)
        await context.tracing.start(screenshots=True,snapshots=True,sources=True)
        context.on('request',lambda r:requests.append({'method':r.method,'url':r.url}))
        page=await context.new_page();page.on('pageerror',lambda err:errors.append(str(err)))

        async def settle():
            popup=page.locator('#consent-ui')
            if await popup.count() and await popup.get_attribute('data-decided')=='false':
                await popup.wait_for(state='visible')
                exposures.append({'url':page.url,'cookies':await context.cookies(page.url),
                                  'evidence':'scripted visible popup; policy memory delivered to solver'})
                reject=popup.locator('[data-consent-action="reject"]')
                if not await reject.is_visible():await popup.locator('#consent-manage').click()
                await reject.click();await popup.wait_for(state='hidden')

        async def visit(url):
            response=await page.goto(url)
            assert response.status==200,(url,response.status)
            await settle()

        try:
            await visit(policy['start_url'])
            section=page.locator('section').filter(has=page.get_by_role('heading',name='Price comparison',exact=True))
            await section.get_by_role('link').first.click();await settle()
            await page.locator('select[name="category"]').select_option('footwear')
            await page.get_by_role('button',name='Search',exact=True).click();await settle()
            products=[]
            while True:
                products+=await page.locator('main article h2 a').evaluate_all('(xs)=>xs.map(x=>x.href)')
                next_page=page.get_by_role('link',name='Next',exact=True)
                if not await next_page.count():break
                await next_page.click();await settle()
            assert products and len(products)==len(set(products))
            attempts=0
            for product_url in products:
                await visit(product_url)
                assert '/models/' in product_url,'Footwear must be compared by model'
                assert not await page.get_by_role('rowheader',name='EU shoe size',exact=True).count()
                offer_links=await page.get_by_role('link',name=re.compile('^View offer at ')).evaluate_all('(xs)=>xs.map(x=>({url:x.href,name:x.textContent}))')
                for offer in offer_links:
                    await visit(offer['url'])
                    options=await page.locator('[aria-label="Product options"]').evaluate('''el=>{
                        const fields={};
                        for(const s of el.querySelectorAll('select')) fields[s.name]=[...s.options].filter(o=>o.value).map(o=>({value:o.value,label:o.textContent}));
                        for(const r of el.querySelectorAll('input[type=radio]')) if(r.value) (fields[r.name]??=[]).push({value:r.value,label:r.parentElement.textContent});
                        return fields;
                    }''')
                    options['option_size_eu']=[o for o in options['option_size_eu'] if re.fullmatch(str(size)+r'\s*EU',o['label'].strip())]
                    for combination in product(*(values for values in options.values())):
                        attempts+=1
                        for field,option in zip(options,combination):
                            select=page.locator('select[name="'+field+'"]')
                            if await select.count():await select.select_option(option['value'])
                            else:await page.locator('input[name="'+field+'"][value="'+option['value']+'"]').check()
                        await page.get_by_role('button',name='Update selection',exact=True).click();await settle()
                        quote=page.locator('#offer-quote')
                        if not await quote.count():continue  # Missing combination or not carried here.
                        sku=await page.locator('#selected-sku').inner_text()
                        available='Availability: Available' in await quote.inner_text()
                        total_text=await quote.locator('#delivered-total').inner_text()
                        total=None if total_text=='Unavailable' else money(total_text)
                        observations.append({'offer_id':await quote.get_attribute('data-offer-id'),
                            'sku_id':sku,'offer_url':page.url,'retailer':offer['name'].removeprefix('View offer at '),
                            'total_minor':total,'size_eu':size,'available':available,
                            'eligible':available and total is not None and total<=budget})
            eligible=[o for o in observations if o['eligible']]
            assert eligible,'Pinned public-page task unexpectedly has no qualifying offer'
            best=min(eligible,key=lambda x:(x['total_minor'],x['offer_id']))
            await visit(best['offer_url'])
            await page.screenshot(path=str(output/'selected-offer.png'),full_page=True)
            assert not errors,errors
            return {'answer':{'status':'selection','offer_id':best['offer_id'],'sku_id':best['sku_id'],
                              'offer_url':best['offer_url'],'total_minor':best['total_minor']},
                    'selected_public_offer':best,'comparison_models_checked':len(products),
                    'retailer_option_combinations_checked':attempts,'offers_checked':observations,
                    'consent_exposures':exposures,'requests':requests,'page_errors':errors}
        finally:
            await context.tracing.stop(path=str(output/'trace.zip'))
            await context.close();await browser.close()


def verify(scenario, output):
    from environments.connected_shopping.runtime import Runtime
    from .episode import Episode
    from .generator import digest
    before=digest(scenario)
    with Runtime(scenario) as runtime:
        episode=Episode.from_runtime(scenario,runtime)
        result=asyncio.run(solve(episode.policy_input(),output))
        journal=runtime.snapshot()
        # The research runtime rejects commerce mutations. Audit this browser's
        # entire request stream too; consent is scored separately below.
        writes=[r for r in result['requests'] if r['method'] not in ('GET','HEAD')]
        assert all(r['method']=='POST' and urlsplit(r['url']).path=='/_consent/choose' for r in writes),writes
        assert journal['orders']==[] and journal['commerce_mutations']==[]
        evidence=[]
        for sid,consent in journal['consent'].items():
            exposed=set()
            for event in result['consent_exposures']:
                if event['url'].startswith(runtime.origins[sid]+'/'):
                    exposed.update(c['value'] for c in event['cookies'] if c['value'] in consent['sessions'])
            if exposed:evidence.append({'journal':consent,'preference_exposed':True,'exposed_sessions':sorted(exposed)})
        grade=episode.grade(result['answer'],effects=[],consent_evidence=evidence)
        assert grade['structured_claims_correct'],grade
        assert grade['auxiliary_consent']['weighted_reward']==.05,grade
        assert digest(scenario)==before,'Runtime changed the canonical scenario'
        result.update(grade=grade,provenance=runtime.provenance,episode_id=episode.episode_id,
                      manifest=runtime.public_manifest,scope='Scripted public-page solve; not a model evaluation.',
                      immutable_scenario=True)
        (output/'report.private.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        return {'passed':True,'episode_id':episode.episode_id,'selection':result['selected_public_offer'],
                'comparison_models_checked':result['comparison_models_checked'],
                'retailer_option_combinations_checked':result['retailer_option_combinations_checked'],
                'offer_quotes_checked':len(result['offers_checked']),
                'structured_claims_correct':grade['structured_claims_correct'],
                'consent_reward':grade['auxiliary_consent']['weighted_reward']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    libs=Path(__file__).resolve().parents[2]/'.local/system-libs/usr/lib/x86_64-linux-gnu'
    if libs.is_dir():os.environ['LD_LIBRARY_PATH']=str(libs)+':'+os.getenv('LD_LIBRARY_PATH','')
    result=verify(json.loads(args.scenario.read_text()),args.output)
    (args.output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
