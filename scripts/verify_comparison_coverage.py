"""Four layout journeys plus retailer-only recovery, with isolated world sessions."""
import argparse,json,hashlib,traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from urllib.request import urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode


def run(spec):
    case,pin,coverage_path,root=spec
    from environments.connected_shopping.runtime import Runtime
    from environments.connected_shopping.pins import load_pin
    from environments.connected_shopping.pages import money
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    scenario,_=load_pin(pin);coverage=json.loads(Path(coverage_path).read_text());out=Path(root)/case;out.mkdir();report={'case':case,'passed':False,'checks':[],'metrics':[],'model_calls':0}
    with Runtime(scenario,comparison_coverage=coverage) as rt:
        env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':rt.index_origin,'goal':'Privileged scripted site-coverage acceptance'},headless=True,viewport={'width':1440,'height':1000},timeout=10000)
        try:
            env.reset();page=env.unwrapped.page;errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            def dismiss():
                if page.locator('#consent-ui').count() and page.locator('#consent-ui').is_visible():
                    b=page.get_by_role('button',name='Use necessary cookies only',exact=True)
                    if b.count():b.click()
                    else:page.get_by_role('button',name='Manage preferences',exact=True).click();page.get_by_role('button',name='Reject optional cookies',exact=True).click()
                    page.locator('#consent-ui').wait_for(state='hidden')
            def snap(label):report['metrics'].append({'stage':label,**capture(env,out,label)})
            if case=='retailer-only-recovery':
                tracked={i for d in rt.comparison_designs.values() for i in d.by_id}
                missing=next(i for i in rt.comparisons if i['id'] not in tracked and any(o['product_id']==i['id'] or rt.group_for[o['product_id']]['group_id']==i['id'] for o in rt.offers.values()))
                for sid,d in rt.comparison_designs.items():
                    page.goto(rt.origins[sid]+'/search?'+urlencode({'q':missing['name']}));dismiss()
                    assert page.locator('#result-count').inner_text()=='0 comparison products'
                    for path in [missing['path'],'/details?'+urlencode({'id':missing['id']})]:
                        try:urlopen(rt.origins[sid]+path)
                        except HTTPError as e:assert e.code==404
                        else:raise AssertionError('Untracked detail leaked')
                snap('missing-from-comparators')
                page.get_by_role('link',name='Search the web',exact=True).first.click()
                page.get_by_role('searchbox',name='Search sites and products',exact=True).fill(missing['name']);page.get_by_role('combobox',name='Site type',exact=True).select_option('retailer');page.get_by_role('button',name='Search',exact=True).click();snap('retailer-discovery')
                page.locator('main article h3 a').first.click();dismiss();selected=page.locator('#selected-sku').inner_text()
                assert selected==missing['id'] or rt.group_for[selected]['group_id']==missing['id'];snap('retailer-product')
                assert rt.bindings['comparison_products'][missing['id']]==[]
                report['checks']+=['all_comparator_searches_empty','direct_url_denial','index_retains_retailers','native_retailer_only_recovery','no_nonexistent_comparison_binding']
            else:
                d=rt.comparison_designs[case];origin=rt.origins[case]
                page.goto(origin);dismiss();snap('home')
                item=next((x for x in d.items if d.offers(x)),d.items[0]);family=item['category']
                if d.layout=='ledger':page.locator('header details summary').click()
                if d.layout=='finder':page.get_by_role('link',name='All '+{'laptops':'laptops','footwear':'footwear'}[family],exact=True).click()
                else:page.locator('header').get_by_role('link',name={'footwear':'Footwear','laptops':'Laptops','beer':'Beer','wine':'Wine','cat_food':'Cat food','dog_food':'Dog food'}[family],exact=True).first.click()
                if d.layout=='ledger':page.get_by_text('Change search and filters',exact=True).click()
                snap('search')
                facets=page.locator('#filters input[type=checkbox]')
                if facets.count():facets.first.check();page.get_by_role('button',name='Apply filters',exact=True).click()
                if d.layout=='ledger':page.get_by_text('Change search and filters',exact=True).click()
                if d.filter_config['price_ceiling']:
                    page.locator('#filters input[name=max_price]').fill('0');page.get_by_role('button',name='Apply filters',exact=True).click();assert page.locator('#result-count').inner_text()=='0 comparison products'
                    if d.layout=='ledger':page.get_by_text('Change search and filters',exact=True).click()
                else:assert not page.locator('#filters input[name=max_price]').count()
                page.get_by_role('link',name='Clear filters',exact=True).click()
                if d.layout=='ledger':page.get_by_text('Change search and filters',exact=True).click()
                page.locator('#filters input[name=q]').fill(item['name']);page.get_by_role('button',name='Apply filters',exact=True).click()
                page.locator('main').get_by_role('link',name=item['name'],exact=True).first.click();snap('product')
                if d.layout=='finder':page.get_by_role('link',name='See '+str(len(d.offers(item)))+' retailer listings',exact=True).click()
                elif d.layout=='specialist':page.locator('details.offer summary').first.click()
                snap('retailers')
                page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                if d.offers(item):
                    row=min(d.offers(item),key=lambda r:(r['advertised_price_minor'],r['retailer_id']));name=rt.stores[row['retailer_id']]['name']
                    assert money(row['advertised_price_minor']) in page.locator('main').inner_text()
                    page.get_by_role('link',name='View offer at '+name,exact=True).click();dismiss();assert page.url.startswith(rt.origins[row['retailer_id']]+'/products/'+row['entry_product_id'])
                    report['checks']+=['tracked_retailer_price','outbound_retailer']
                else:
                    assert not page.get_by_role('link',name='View offer at',exact=False).count()
                    assert 'no tracked retailer listings' in page.locator('main').inner_text().lower()
                    report['checks']+=['tracked_product_zero_retailers_preserved']
                report['checks']+=['native_category_navigation','available_facet_action','price_control_capability','clear_and_search','product_navigation','mobile_width']
            assert not errors,errors;assert not rt.snapshot()['orders'];report['checks']+=['no_js_errors','no_orders'];report['passed']=True
        except Exception:
            report['error']=traceback.format_exc()
            try:page.screenshot(path=str(out/'failure.png'))
            except Exception:pass
        finally:env.close()
        report['manifest']=rt.public_manifest;report['provenance']=rt.provenance
    report['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()};(out/'report.json').write_text(json.dumps(report,indent=2))
    return {k:report.get(k) for k in ['case','passed','checks','error']}


def main():
    p=argparse.ArgumentParser();p.add_argument('--pin',default='.local/coordination/connected-shopping-world/product-pin-v2');p.add_argument('--coverage',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--case');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    from environments.connected_shopping.__main__ import source_hashes
    sources=source_hashes();sources[__file__]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    names=[a.case] if a.case else ['comparison-general-a','comparison-general-b','comparison-footwear','comparison-laptops','retailer-only-recovery']
    with ProcessPoolExecutor(max_workers=2) as pool:cases=list(pool.map(run,[(n,a.pin,a.coverage,str(a.output)) for n in names]))
    report={'schema':'comparison-coverage-browser-v1','sources':sources,'coverage_sha256':hashlib.sha256(Path(a.coverage).read_bytes()).hexdigest(),'cases':cases,'model_calls':0};(a.output/'suite.json').write_text(json.dumps(report,indent=2));print(json.dumps(cases,indent=2))
    if not all(c['passed'] for c in cases):raise SystemExit(1)
if __name__=='__main__':main()
