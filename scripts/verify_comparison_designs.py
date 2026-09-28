"""Native AX/layout and action acceptance; isolated preview servers, no inference."""
import argparse,json,hashlib,traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor


def run(spec):
    key,pin,published,output=spec
    from environments.connected_shopping.comparison_preview import Preview
    from environments.connected_shopping.pages import money
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    out=Path(output)/key;out.mkdir();report={'case':key,'passed':False,'captures':[],'model_calls':0}
    with Preview(pin,published) as rt:
        d=rt.designs[key];origin=rt.sites[key].origin
        env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':origin,'goal':'Scripted comparison layout acceptance'},headless=True,viewport={'width':1440,'height':1000},timeout=10000)
        try:
            env.reset();page=env.unwrapped.page;errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.get_by_role('button',name='Use necessary cookies only',exact=True).click();page.locator('#consent-ui').wait_for(state='hidden')
            report['captures'].append(capture(env,out,'home'))
            family=d.family or 'footwear';page.locator('main').get_by_role('link',name='See all '+{'footwear':'footwear','laptops':'laptops'}[family],exact=True).click()
            report['captures'].append(capture(env,out,'search'))
            checks=page.locator('#filters input[type=checkbox]')
            if checks.count():checks.first.check();page.get_by_role('button',name='Apply filters',exact=True).click();assert page.locator('#filters input[type=checkbox]').first.is_checked()
            page.locator('#filters input[name=max_price]').fill('0');page.get_by_role('button',name='Apply filters',exact=True).click();assert page.locator('#result-count').inner_text()=='0 comparison products'
            page.get_by_role('link',name='Clear filters',exact=True).click()
            assert page.locator('#filters input[type=checkbox]:checked').count()==0
            assert page.locator('main article .lowest-retailers a').count()>0
            picks=page.locator('input[name^=pick]');assert picks.count()>=2;picks.nth(0).check();picks.nth(1).check();page.get_by_role('button',name='Compare selected products',exact=True).click();assert page.get_by_role('heading',name='Compare product facts',exact=True).is_visible();report['captures'].append(capture(env,out,'compare'))
            item=next(x for x in d.items if x['category']==family and d.offers(x))
            page.get_by_role('searchbox',name='Search products',exact=True).fill(item['name']);page.get_by_role('button',name='Search',exact=True).click();page.locator('main article h3 a').filter(has_text=item['name']).first.click()
            assert page.get_by_role('heading',name=item['name'],exact=True).is_visible()
            report['captures'].append(capture(env,out,'product'))
            if d.layout=='specialist':
                page.get_by_role('link',name='Full product specifications',exact=True).click();assert page.get_by_role('heading',name=item['name']+' specifications',exact=True).is_visible();page.get_by_role('link',name='Return to retailer prices',exact=True).click()
            row=d.offers(item)[0];sid=row['retailer_id'];name=rt.owner.stores[sid]['name']
            page.get_by_role('combobox',name='Retailer',exact=True).select_option(sid);page.get_by_role('button',name='Update offers',exact=True).click()
            if d.layout=='specialist':page.locator('details.offer summary').click()
            assert money(row['advertised_price_minor']) in page.locator('#prices').inner_text()
            assert d.stock_text(item,row) in page.locator('#prices').inner_text()
            report['captures'].append(capture(env,out,'offer'))
            page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.get_by_role('link',name='View offer at '+name,exact=True).click();assert page.url.startswith(rt.owner.origins[sid]+'/products/'+row['entry_product_id'])
            assert not errors,errors
            report['passed']=True;report['checks']=['category_navigation','facet_action','zero_price_filter','clear_filters','two_product_comparison','search_detail_navigation','published_offer_price','retailer_filter','native_disclosure_or_table','bound_retailer_link','mobile_width','no_js_errors']
        except Exception:report['error']=traceback.format_exc();page.screenshot(path=str(out/'failure.png'))
        finally:env.close()
    report['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()};(out/'report.json').write_text(json.dumps(report,indent=2))
    return {'case':key,'passed':report['passed'],'error':report.get('error'),'metrics':[{k:c[k] for k in ['title','semantic_nodes','max_depth','roles','full_nonverbose_projection_tokens','tokenizer']} for c in report['captures']]}


def main():
    p=argparse.ArgumentParser();p.add_argument('--pin',default='.local/coordination/connected-shopping-world/product-pin-v2');p.add_argument('--published',default='.local/connected-shopping/preview-v2');p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    source={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),*Path('environments/connected_shopping').glob('*.py')]}
    with ProcessPoolExecutor(max_workers=2) as pool:cases=list(pool.map(run,[(key,a.pin,a.published,str(a.output)) for key in ['directory','specialist-footwear','specialist-laptops']]))
    result={'schema':'comparison-design-acceptance-v1','sources':source,'cases':cases,'model_calls':0};(a.output/'suite.json').write_text(json.dumps(result,indent=2));print(json.dumps(cases,indent=2))
    if not all(c['passed'] for c in cases):raise SystemExit(1)
if __name__=='__main__':main()
