"""Bounded native-browser/AX acceptance for R13. Scripted, no inference."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import traceback
from urllib.request import urlopen
from urllib.parse import urlsplit


def run(spec):
    flow,kind,root=spec
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from environments.procedural_commerce.dense_preview import make_runtime
    from scripts.inspect_retail_ax import capture
    out=Path(root)/(flow+'-'+kind);out.mkdir()
    report={'flow':flow,'kind':kind,'model_calls':0,'checks':[],'captures':[]}
    runtime=make_runtime('large' if kind=='generic' else 'small',flow)
    env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':'about:blank','goal':'Scripted layout acceptance'},headless=True,viewport={'width':1440,'height':1000},slow_mo=0,timeout=15000)
    try:
        env.reset();page=env.unwrapped.page;errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        origin=runtime.origins['nordhem'];world=runtime._world
        offer=next(o for o in world['offers'] if o['retailer_id']=='nordhem' and o['stock_quantity']>0 and (o['product_id']=='shoe-42-black' if kind=='shoe' else not o['product_id'].startswith('shoe-')))
        sku=offer['product_id'];product=next(p for p in world['products'] if p['product_id']==sku)
        url=origin+'/products/'+sku
        page.goto(url);report['captures'].append(capture(env,out,'initial'))
        assert page.get_by_role('button',name='Add to cart',exact=True).count()==1
        page.get_by_role('radio',name='View 2',exact=True).check()
        assert page.get_by_role('radio',name='View 2',exact=True).is_checked()
        assert page.locator('[data-gallery-panel]:visible').count()==1
        page.locator('summary',has_text='Specifications and product identity').click()
        assert page.get_by_role('table',name='Product specifications').is_visible()
        page.locator('summary',has_text='Shop by department').click()
        assert page.get_by_role('navigation',name='Departments',exact=True).is_visible()
        report['captures'].append(capture(env,out,'expanded'))
        report['checks'].extend(['direct_product_load','gallery_selection','spec_disclosure','department_disclosure'])
        # Resolve every distinct linked route on the inspected page, without JS/state mutation.
        links=sorted(set(page.locator('a').evaluate_all('(nodes)=>nodes.map(n=>n.href)')))
        checked=[]
        for link in links:
            u=urlsplit(link)
            assert u.netloc==urlsplit(origin).netloc,link
            target=link.split('#')[0]
            with urlopen(target,timeout=5) as r:
                html=r.read().decode();assert r.status==200
                assert 'Product unavailable at this store' not in html
            checked.append(target)
        report['linked_routes']=sorted(set(checked));report['checks'].append('all_rendered_links_resolve')
        destination=page.locator('.product-card').first.get_by_role('link',name='View product',exact=True).get_attribute('href')
        page.locator('.product-card').first.get_by_role('link',name='View product',exact=True).click()
        assert page.url==destination and page.get_by_role('heading',level=1).count()==1
        page.go_back();assert page.url==url
        page.get_by_role('searchbox',name='Search the store',exact=True).fill(product['name'])
        page.locator('header').get_by_role('button',name='Search',exact=True).click()
        page.locator('.product-card').filter(has=page.get_by_role('heading',name=product['name'],exact=True)).get_by_role('link',name='View product',exact=True).click()
        report['checks'].extend(['related_product_navigation','search_and_open'])
        if kind=='shoe':
            page.get_by_role('combobox',name='EU shoe size',exact=True).select_option('eu475')
            page.get_by_role('radio',name='Blue',exact=True).check()
            page.get_by_role('button',name='Update selection',exact=True).click()
            assert page.get_by_role('button',name='Add to cart',exact=True).count()==0
            assert 'This combination is not listed' in page.locator('body').inner_text()
            page.get_by_role('combobox',name='EU shoe size',exact=True).select_option('eu42')
            page.get_by_role('button',name='Update selection',exact=True).click()
            assert page.get_by_role('button',name='Add to cart',exact=True).count()==0
            assert 'out of stock' in page.locator('body').inner_text()
            page.get_by_role('radio',name='Black',exact=True).check()
            page.get_by_role('button',name='Update selection',exact=True).click()
            report['checks'].extend(['unlisted_combination','soldout_combination','recover_selection'])
        page.get_by_label('Quantity',exact=True).fill(str(offer['stock_quantity']+1))
        page.get_by_role('button',name='Add to cart',exact=True).click()
        assert runtime.snapshot()['carts']['nordhem'] is None
        assert not page.get_by_label('Quantity',exact=True).evaluate('(e)=>e.checkValidity()')
        report['checks'].append('native_quantity_bound')
        page.get_by_label('Quantity',exact=True).fill('1')
        extras=page.locator('.purchase-form input[type=checkbox]')
        for i in range(extras.count()):extras.nth(i).uncheck()
        page.get_by_role('button',name='Add to cart',exact=True).click()
        assert '/products/' in page.url
        assert runtime.snapshot()['carts']['nordhem']['offer_id']==offer['offer_id']
        assert page.get_by_role('link',name='Shopping bag (1)',exact=True).is_visible()
        report['captures'].append(capture(env,out,'added'))
        page.get_by_role('link',name='Go to cart',exact=True).click()
        page.get_by_role('link',name='Continue to checkout',exact=True).click()
        if flow=='wizard':
            page.get_by_label('Full name',exact=True).fill('Alex Andersson');page.get_by_label('Email',exact=True).fill('alex@example.test');page.get_by_label('Phone',exact=True).fill('0700000000')
            page.get_by_role('button',name='Continue to address',exact=True).click()
            page.get_by_label('Street address',exact=True).fill('Testgatan 12');page.get_by_label('Postcode',exact=True).fill('12345');page.get_by_label('City',exact=True).fill('Stockholm')
            page.get_by_role('button',name='Continue to delivery',exact=True).click()
            page.get_by_role('button',name='Review order',exact=True).click()
        elif flow=='express':page.get_by_label('Receipt email',exact=True).fill('alex@example.test')
        else:
            page.get_by_label('Full name',exact=True).fill('Alex Andersson');page.get_by_label('Email',exact=True).fill('alex@example.test')
            page.locator('summary',has_text='2. Delivery address').click()
            page.get_by_label('Street address',exact=True).fill('Testgatan 12');page.get_by_label('Postcode',exact=True).fill('12345');page.get_by_label('City',exact=True).fill('Stockholm')
        if flow=='accordion':
            page.locator('summary',has_text='3. Delivery').click()
            page.get_by_role('button',name='Update order summary',exact=True).click()
        page.locator('input[name=confirm]').check()
        page.get_by_role('button',name='Place simulated order',exact=True).click()
        assert '/receipt/' in page.url
        snapshot=runtime.snapshot();assert len(snapshot['orders'])==1
        order=snapshot['orders'][0];assert order['quote']['offer_id']==offer['offer_id'];assert order['quote']['quantity']==1
        assert order['quote']['extra'] is False
        assert not errors,errors
        report['checks'].extend(['canonical_cart','cart_indicator','checkout_'+flow,'one_correct_order_no_extra','no_js_errors'])
        report['snapshot']=snapshot;report['captures'].append(capture(env,out,'receipt'))
        report['passed']=True
    except Exception:
        report['passed']=False;report['error']=traceback.format_exc()
        report['snapshot']=runtime.snapshot()
        try:
            (out/'failure-body.txt').write_text(env.unwrapped.page.locator('body').inner_text())
            capture(env,out,'failure')
        except Exception:pass
    finally:
        env.close();runtime.close()
        report['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return {'case':out.name,'passed':report['passed'],'error':report.get('error'),'checks':len(report['checks'])}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--case',action='append',choices=[f+'-'+k for f in ('express','accordion','wizard') for k in ('generic','shoe')]);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),*Path('environments/procedural_commerce').glob('*.py')]}
    cases=[(f,k,str(a.output)) for f in ('express','accordion','wizard') for k in ('generic','shoe') if not a.case or f+'-'+k in a.case]
    with ProcessPoolExecutor(max_workers=2) as pool:rows=list(pool.map(run,cases))
    (a.output/'suite.json').write_text(json.dumps({'source_hashes':sources,'cases':rows,'model_calls':0},indent=2));print(json.dumps(rows,indent=2))
    if not all(r['passed'] for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
