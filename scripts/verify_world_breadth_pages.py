"""Bounded native discovery/specification/quote/review checks across frozen worlds.

One first offered product per family across the supplied draws; no success-based
sampling, model calls or outcome grading. Retains failed journeys and screenshots.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit


def read(path):return json.loads(Path(path).read_text())
def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2))


def consent(page):
    button=page.get_by_role('button',name='Manage preferences',exact=True)
    if button.count() and button.is_visible():
        button.click()
        page.get_by_role('button',name='Reject optional cookies',exact=True).or_(page.get_by_role('button',name='Use necessary cookies only',exact=True)).click()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--publications',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'driver.py').write_bytes(Path(__file__).read_bytes())
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    from environments.connected_shopping.conformance import Document,product_check,quote_check
    from environments.product_world.locations import quote
    seen=set();results=[]
    for entry in read(a.publications):
        scenario=read(Path(entry['sample'])/'scenario.private.json');world=scenario['bundle'];public=world['public']
        runtime=Path(entry['runtime']);manifest=read(runtime/'manifest.json')
        origins={s['site_id']:s['origin'] for s in manifest['sites']}
        products={p['product_id']:p for p in public['products']}
        groups={v['product_id']:g for g in public['product_groups'] for v in g['variants']}
        # Every supplied draw gets its task family; then new families fill coverage.
        focus=Path(entry['sample']).name.split('-',1)[1]
        families=[focus]+sorted({p['category'] for p in products.values()}-seen-{focus})
        for family in families:
            offer=next(o for o in public['offers'] if products[o['product_id']]['category']==family)
            product=products[offer['product_id']];group=groups[product['product_id']];seen.add(family)
            case=Path(entry['sample']).name+'-'+family;out=a.output/case;out.mkdir()
            row={'case':case,'family':family,'passed':False,'offer_id':offer['offer_id'],'model_calls':0}
            env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':manifest['index_url'],'goal':'Scripted public catalog inspection'},headless=True,timeout=10000)
            try:
                env.reset();page=env.unwrapped.page;page.set_default_timeout(10000)
                # Name search for footwear because web-index entries represent models.
                term=group['name'] if family=='footwear' else product['product_id']
                page.get_by_role('searchbox',name='Search sites and products',exact=True).fill(term)
                page.get_by_role('combobox',name='Site type',exact=True).select_option('retailer')
                page.get_by_role('button',name='Search',exact=True).click()
                target=page.locator('main article h3 a').first
                target.click();consent(page)
                # The first indexed merchant/entry SKU is public discovery, not the
                # initial private offer used only to choose this family's query.
                sku=page.locator('#selected-sku').inner_text();product=products[sku];group=groups[sku]
                sid=next(k for k,v in origins.items() if urlsplit(v).netloc==urlsplit(page.url).netloc)
                offer=next(o for o in public['offers'] if o['retailer_id']==sid and o['product_id']==sku)
                row.update(product_url=page.url,sku=sku,retailer_id=sid,offer_id=offer['offer_id'])
                details=page.get_by_role('link',name='Read full product details',exact=True)
                if details.count():details.click()
                variant=next(v for v in group['variants'] if v['product_id']==sku)
                product_check(Document(page.content()).root,product,offer,group,variant['selection'])
                metrics=capture(env,out,'product');row['ax_semantic_nodes']=metrics['semantic_nodes']
                page.get_by_role('link',name='Check delivery total and arrival',exact=True).click()
                expected=quote(world,scenario['locations'],offer['offer_id'])
                quote_check(Document(page.content()).root,expected,offer,1,'delivery')
                row['quote_eligible']=expected['eligible'];row['quote_url']=page.url
                page.get_by_role('link',name='Independent product review',exact=True).click();consent(page)
                assert page.locator('#reader-panel').count()==1
                row['review_url']=page.url
                page.screenshot(path=str(out/'review.png'),full_page=False)
                row['passed']=True
            except Exception as exc:
                row.update(error=str(exc),exception_type=type(exc).__name__)
                try:env.unwrapped.page.screenshot(path=str(out/'failure.png'))
                except Exception:pass
            finally:env.close()
            save(out/'report.json',row);results.append(row);print(json.dumps(row),flush=True)
    report={'schema':'world-breadth-native-v1','passed':all(r['passed'] for r in results),'cases':results,'model_calls':0,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    save(a.output/'report.json',report)
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
