"""Scripted cross-site journeys on one immutable input; isolated runtimes, no inference."""
import argparse,json,hashlib,traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from urllib.parse import urlencode


def run(spec):
    name,pin,root=spec
    from environments.connected_shopping.runtime import Runtime
    from environments.connected_shopping.pins import load_pin
    from environments.connected_shopping.pages import money
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    scenario,_=load_pin(pin);out=Path(root)/name;out.mkdir();report={'case':name,'checks':[],'model_calls':0}
    with Runtime(scenario) as rt:
        (out/'public-manifest.json').write_text(json.dumps(rt.public_manifest,indent=2))
        env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':rt.index_origin,'goal':'Scripted connected-world acceptance'},headless=True,viewport={'width':1440,'height':1000},slow_mo=0,timeout=10000)
        try:
            env.reset();page=env.unwrapped.page;errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            def dismiss():
                if page.locator('#consent-ui').count():
                    page.wait_for_function("()=>document.getElementById('consent-ui').hidden===false || document.getElementById('consent-ui').dataset.decided==='true'")
                    if page.locator('#consent-ui').is_visible():
                        reject=page.get_by_role('button',name='Use necessary cookies only',exact=True)
                        if reject.count():reject.click()
                        else:
                            page.get_by_role('button',name='Manage preferences',exact=True).click();page.get_by_role('button',name='Reject optional cookies',exact=True).click()
                        page.locator('#consent-ui').wait_for(state='hidden')
            capture(env,out,'index')
            offers=[o for o in rt.offers.values() if rt.products[o['product_id']]['category']=='footwear']
            offer=next(o for o in offers if rt.quote(o['offer_id'])['eligible']);sku=offer['product_id'];sid=offer['retailer_id']
            if name=='discovery-reviews-delivery':
                page.get_by_role('searchbox',name='Search sites and products',exact=True).fill(rt.group_for[sku]['name'])
                page.get_by_role('combobox',name='Site type',exact=True).select_option('aggregator');page.get_by_role('button',name='Search',exact=True).click()
                page.locator('main article h3 a').click();dismiss();assert rt.group_for[sku]['name'] in page.locator('main').inner_text();assert sku not in page.locator('main').inner_text();capture(env,out,'aggregator')
                page.get_by_role('link',name='View offer at '+rt.stores[sid]['name'],exact=True).click();dismiss()
                variant=next(v for v in rt.group_for[sku]['variants'] if v['product_id']==sku)
                for field,value in variant['selection'].items():
                    locator=page.locator('[name="option_'+field+'"]')
                    if locator.first.get_attribute('type')=='radio':page.locator('[name="option_'+field+'"][value="'+value+'"]').check()
                    else:locator.select_option(value)
                page.get_by_role('button',name='Update selection',exact=True).click();dismiss()
                assert page.locator('#selected-sku').inner_text()==sku
                expected=rt.quote(offer['offer_id']);assert page.locator('#delivered-total').inner_text()==money(expected['total_minor'])
                capture(env,out,'store')
                page.goto(rt.index_origin)
                page.get_by_role('searchbox',name='Search sites and products',exact=True).fill(rt.stores[sid]['name'])
                page.get_by_role('combobox',name='Site type',exact=True).select_option('merchant_reviews')
                page.get_by_role('button',name='Search',exact=True).click()
                page.locator('main article h3 a').first.click();dismiss()
                assert page.get_by_role('heading',name=rt.stores[sid]['name']+' reviews',exact=True).is_visible();capture(env,out,'merchant')
                page.get_by_role('link',name='Visit website',exact=True).first.click();dismiss();assert page.url.rstrip('/')==rt.origins[sid]
                page.goto(rt.index_origin)
                page.get_by_role('searchbox',name='Search sites and products',exact=True).fill(rt.group_for[sku]['name'])
                page.get_by_role('combobox',name='Site type',exact=True).select_option('product_reviews')
                page.get_by_role('button',name='Search',exact=True).click()
                page.locator('main article h3 a').first.click();dismiss()
                article=next(a for a in rt.product_reviews['public']['articles'] if a['id']==rt.group_for[sku]['group_id'])
                assert article['reviewed_sku'] in page.locator('main').inner_text();capture(env,out,'product-review')
                retailer=page.get_by_role('link',name='View this size and fit option at a retailer',exact=True)
                if retailer.count():
                    retailer.first.click();dismiss();assert page.locator('#selected-sku').inner_text()==article['reviewed_sku'];report['checks'].append('reviewed_exact_sku_retailer_binding')
                report['checks']+=['index_model_search','index_to_model_aggregator','retailer_exact_sku_selection','geographic_total','merchant_corpus_identity','merchant_to_store','model_review_scope']
            elif name=='variants-and-availability':
                page.goto(rt.origins[sid]+'/products/'+sku);dismiss();g=rt.group_for[sku]
                unlisted=next(v for v in g['variants'] if (sid,v['product_id']) not in rt.offer_by_store)
                for field,value in unlisted['selection'].items():
                    locator=page.locator('[name="option_'+field+'"]')
                    if locator.first.get_attribute('type')=='radio':page.locator('[name="option_'+field+'"][value="'+value+'"]').check()
                    else:locator.select_option(value)
                page.get_by_role('button',name='Update selection',exact=True).click();dismiss()
                assert page.locator('#selected-sku').inner_text()==unlisted['product_id'] and 'store does not list' in page.locator('main').inner_text()
                assert not page.locator('#delivered-total').count();capture(env,out,'unlisted')
                original=next(v for v in g['variants'] if v['product_id']==sku)
                for field,value in original['selection'].items():
                    locator=page.locator('[name="option_'+field+'"]')
                    if locator.first.get_attribute('type')=='radio':page.locator('[name="option_'+field+'"][value="'+value+'"]').check()
                    else:locator.select_option(value)
                page.get_by_role('button',name='Update selection',exact=True).click();dismiss()
                assert page.locator('#selected-sku').inner_text()==sku
                sold=next(o for o in rt.offers.values() if o['stock_quantity']==0)
                page.goto(rt.origins[sold['retailer_id']]+'/products/'+sold['product_id']);dismiss()
                assert 'warehouse insufficient stock' in page.locator('#offer-quote').inner_text();capture(env,out,'sold-out')
                report['checks']+=['canonical_unlisted_variant','no_stale_previous_quote','native_selection_recovery','soldout_not_unlisted']
            else:
                page.goto(rt.origins[sid]+'/quote?'+urlencode({'offer_id':offer['offer_id']}));dismiss()
                branch=rt.merchants[sid]['branches'][0]
                page.get_by_role('combobox',name='Method',exact=True).select_option('pickup');page.get_by_role('combobox',name='Branch',exact=True).select_option(branch['branch_id']);page.get_by_role('button',name='Calculate quote',exact=True).click();dismiss()
                expected=rt.quote(offer['offer_id'],method='pickup',branch_id=branch['branch_id']);assert page.locator('#delivered-total').inner_text()==money(expected['total_minor']);capture(env,out,'pickup')
                page.get_by_role('link',name='Plan a journey to this branch',exact=True).click();assert page.get_by_role('heading',name='Your journey',exact=True).is_visible();assert branch['name'].split(' — ')[0] in page.locator('body').inner_text();capture(env,out,'travel')
                page.goto(rt.origins[sid]+'/quote?'+urlencode({'offer_id':offer['offer_id'],'method':'inspect','branch_id':branch['branch_id']}));dismiss();assert page.get_by_role('heading',name='Inspection availability',exact=True).is_visible();capture(env,out,'inspection')
                report['checks']+=['pickup_same_quote_source','branch_to_travel','inspection_separate_from_purchase']
            page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');assert not errors,errors
            snap=rt.snapshot();assert not snap['orders'] and not snap['commerce_mutations']
            for journal in snap['consent'].values():
                for s in journal['sessions'].values():assert not any(s['preferences'].values())
            report['checks']+=['no_commerce_mutation','consent_necessary_only','mobile_width','no_js_errors'];report['passed']=True
        except Exception:
            report['passed']=False;report['error']=traceback.format_exc()
            try:env.unwrapped.page.screenshot(path=str(out/'failure.png'))
            except Exception:pass
        finally:
            report['journal']=rt.snapshot();env.close()
    report['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    (out/'report.json').write_text(json.dumps(report,indent=2))
    return {k:report.get(k) for k in ('case','checks','passed','error')}


def main():
    p=argparse.ArgumentParser();p.add_argument('--pin',type=Path,default=Path('.local/coordination/connected-shopping-world/product-pin-v1'));p.add_argument('--output',type=Path,required=True);p.add_argument('--case',choices=['discovery-reviews-delivery','variants-and-availability','pickup-travel-inspection']);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    from environments.connected_shopping.__main__ import source_hashes
    sources=source_hashes();sources[__file__]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with ProcessPoolExecutor(max_workers=2) as pool:cases=list(pool.map(run,[(name,str(a.pin),str(a.output)) for name in ([a.case] if a.case else ['discovery-reviews-delivery','variants-and-availability','pickup-travel-inspection'])]))
    result={'schema':'connected-shopping-browser-v1','sources':sources,'pin_sha256':hashlib.sha256((a.pin/'pins.json').read_bytes()).hexdigest(),'cases':cases,'model_calls':0}
    (a.output/'suite.json').write_text(json.dumps(result,indent=2));print(json.dumps(cases,indent=2))
    if not all(c['passed'] for c in cases):raise SystemExit(1)


if __name__=='__main__':main()
