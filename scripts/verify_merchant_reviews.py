"""Native browser/AX acceptance; public generated reviews, no model calls."""
import argparse,json,hashlib,traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from urllib.parse import urlsplit
from urllib.request import urlopen


def run(spec):
    mode,root=spec
    from environments.product_world.stores import generate_store_world
    from environments.product_world.reviews import generate_reviews
    from environments.merchant_reviews.runtime import Runtime
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    world=generate_store_world(42,store_count=8,models_per_store=3,focus_families=['footwear','laptops'])
    bundle=generate_reviews(world,seed=42,reviews_per_store=48 if mode=='normal' else 0)
    out=Path(root)/mode;out.mkdir();report={'mode':mode,'model_calls':0,'checks':[],'captures':[]}
    (out/'public.json').write_text(json.dumps(bundle['public'],ensure_ascii=False,indent=2))
    rt=Runtime(bundle['public']);env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':rt.origin,'goal':'Scripted review-site acceptance'},headless=True,viewport={'width':1440,'height':1000},slow_mo=0,timeout=10000)
    try:
        env.reset();page=env.unwrapped.page;errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        report['captures'].append(capture(env,out,'home'))
        company=rt.catalog.companies[0];name=company['name'];cid=company['company_id']
        page.get_by_role('searchbox',name='Search company or category',exact=True).fill(company['domain'])
        page.locator('.hero').get_by_role('button',name='Search',exact=True).click()
        assert page.get_by_role('heading',name='Companies (1)',exact=True).is_visible()
        report['captures'].append(capture(env,out,'search'))
        page.locator('main').get_by_role('link',name=name,exact=True).click()
        assert page.get_by_role('heading',name=name+' reviews',exact=True).is_visible()
        report['captures'].append(capture(env,out,'company'))
        ids=page.locator('[id]').evaluate_all('(els)=>els.map(e=>e.id)');assert len(ids)==len(set(ids))
        # Every link at the initial profile has a real local route or real fragment.
        for link in sorted(set(page.locator('a').evaluate_all('(els)=>els.map(e=>e.href)'))):
            assert urlsplit(link).netloc==urlsplit(rt.origin).netloc
            with urlopen(link.split('#')[0],timeout=3) as r:assert r.status==200
        report['checks']+=['home_search','unique_company_match','company_profile','unique_dom_ids','profile_links_resolve']
        if mode=='normal':
            score=page.locator('.score').inner_text()
            page.get_by_role('link',name=f'1-star reviews ({company["statistics"]["star_counts"]["1"]})',exact=True).click()
            assert page.get_by_role('combobox',name='Rating',exact=True).input_value()=='1'
            assert page.locator('.score').inner_text()==score
            page.get_by_role('combobox',name='Topic',exact=True).select_option('delivery')
            page.get_by_role('combobox',name='Sort reviews',exact=True).select_option('oldest')
            page.get_by_role('button',name='Apply filters',exact=True).click()
            expected=sorted([r for r in company['reviews'] if r['stars']==1 and r['topic']=='delivery'],key=lambda r:(r['published_date'],r['review_id']))[:20]
            actual=page.locator('.review-list article h3 a').evaluate_all('(els)=>els.map(e=>e.getAttribute("href").split("/").pop())')
            assert actual==[r['review_id'] for r in expected]
            report['captures'].append(capture(env,out,'filtered'))
            page.get_by_role('link',name='Clear filters',exact=True).click()
            page.get_by_role('link',name='Next',exact=True).click()
            assert page.get_by_text('Page 2 of 3',exact=True).is_visible()
            selected=page.locator('.review-list article').first.locator('h3 a').get_attribute('href')
            page.locator('.review-list article').first.get_by_role('link',name='Read this review',exact=True).click()
            assert page.url.endswith(selected)
            r=rt.catalog.by_review[selected.split('/')[-1]][1]
            assert page.get_by_role('img',name=f'{r["stars"]} out of 5 stars',exact=True).count()==1
            assert r['body'] in page.locator('body').inner_text()
            reply=next((r for r in company['reviews'] if r['company_reply']),None)
            if reply:
                page.goto(rt.origin+'/reviews/'+reply['review_id'])
                page.locator('summary').click();assert reply['company_reply']['body'] in page.locator('body').inner_text()
            report['checks']+=['histogram_filters','overall_score_preserved','topic_and_sort','pagination','review_permalink','company_reply']
        else:
            assert page.locator('.score').inner_text()=='Not rated'
            assert page.get_by_text('No reviews match these filters.',exact=True).is_visible()
            report['checks'].append('empty_corpus_not_zero_score')
        page.goto(rt.origin+'/categories');page.locator('main .categories a').first.click()
        category=page.get_by_role('combobox',name='Category',exact=True).input_value();assert category
        page.get_by_role('searchbox',name='Company or website',exact=True).fill('no-such-company-xyz')
        page.get_by_role('button',name='Search companies',exact=True).click()
        assert page.get_by_role('heading',name='Companies (0)',exact=True).is_visible()
        page.goto(rt.origin+'/about');assert page.get_by_role('heading',name='One corpus, one average',exact=True).is_visible()
        page.set_viewport_size({'width':390,'height':844});page.goto(rt.origin+'/review/'+cid)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors,errors
        report['checks']+=['category_navigation','empty_search','methodology','mobile_width','no_js_errors'];report['passed']=True
    except Exception:
        report['passed']=False;report['error']=traceback.format_exc()
        try:(out/'failure-body.txt').write_text(env.unwrapped.page.locator('body').inner_text())
        except Exception:pass
    finally:
        report['access_log']=rt.access_log();env.close();rt.close()
        report['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return {'case':mode,'passed':report['passed'],'checks':report['checks'],'error':report.get('error')}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    files=[Path(__file__),*Path('environments/merchant_reviews').glob('*.py'),Path('environments/product_world/reviews.py'),Path('environments/product_world/stores.py')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (a.output/'driver.py').write_bytes(Path(__file__).read_bytes())
    with ProcessPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[(m,str(a.output)) for m in ['normal','empty']]))
    report={'schema':'merchant-review-browser-v1','sources':hashes,'cases':results,'model_calls':0}
    (a.output/'suite.json').write_text(json.dumps(report,indent=2));print(json.dumps(results,indent=2))
    if not all(r['passed'] for r in results):raise SystemExit(1)
if __name__=='__main__':main()
