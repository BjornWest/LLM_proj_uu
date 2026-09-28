"""Bounded native BrowserGym acceptance: three structures and six product families."""
import argparse,hashlib,json,traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor


def run(spec):
    family,layout,root=spec
    from environments.product_world.generator import generate_catalog
    from environments.product_review_sites.generate import generate_reviews
    from environments.product_review_sites.runtime import Runtime
    from environments.product_review_sites.data import fact_text
    from environments.product_review_sites.presentation import vocabulary
    from environments.product_review_sites.facets import token
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    words=vocabulary(family)
    case=family+'-'+layout;out=Path(root)/case;out.mkdir()
    world=generate_catalog(seed=42,model_count=8,model_families=[family]*8)
    export=generate_reviews(world,seed=42,opinions_per_review=24)
    (out/'public.json').write_text(json.dumps(export['public'],ensure_ascii=False,indent=2))
    rt=Runtime(export['public'],families=[family],layout=layout,page_size=4,seed=42)
    env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':rt.origin,'goal':'Scripted product-review acceptance'},headless=True,viewport={'width':1440,'height':1000},slow_mo=0,timeout=10000)
    report={'case':case,'model_calls':0,'checks':[],'captures':[]}
    try:
        env.reset();page=env.unwrapped.page;errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        report['captures'].append(capture(env,out,'home'))
        page.get_by_role('link',name='Explore reviews',exact=True).click()
        assert page.get_by_role('heading',name='Reviews (8)',exact=True).is_visible()
        page.get_by_role('link',name='Next',exact=True).click()
        assert page.get_by_text('Page 2 of 2',exact=True).is_visible()
        a=rt.db.articles[0];v=rt.db.variants[a['reviewed_sku']]
        page.get_by_role('searchbox',name='Product or keyword',exact=True).fill(v['sku'])
        page.get_by_role('button',name='Apply filters',exact=True).click()
        assert page.get_by_role('heading',name='Reviews (1)',exact=True).is_visible()
        report['captures'].append(capture(env,out,'search'))
        page.locator('main').get_by_role('link',name=a['model_name'],exact=True).click()
        assert page.get_by_role('heading',name=a['model_name']+' review',exact=True).is_visible()
        report['captures'].append(capture(env,out,'review'))
        ids=page.locator('[id]').evaluate_all('(els)=>els.map(e=>e.id)');assert len(ids)==len(set(ids))
        if layout=='editorial-magazine':page.get_by_role('link',name='2. '+words.facts_title,exact=True).click()
        for k in v['facts']:assert fact_text(v,k) in page.locator('main').inner_text(),k
        page.get_by_role('link',name=v['sku'],exact=True).click()
        assert 'This is the '+words.item+' covered' in page.locator('main').inner_text()
        page.get_by_role('link',name='Return to review',exact=True).click()
        report['checks']+=['home_catalog_native_navigation','catalog_pagination','exact_sku_search','unique_ids','canonical_facts_visible','tested_variant_identity']
        if layout=='editorial-magazine':page.get_by_role('link',name='2. '+words.facts_title,exact=True).click()
        page.locator('summary').filter(has_text=words.alternatives).click()
        other=next(x for x in rt.db.variants.values() if x['model_id']==a['id'] and x['sku']!=v['sku'])
        page.get_by_role('link',name=other['name'],exact=True).click()
        assert 'catalog facts only' in page.locator('main').inner_text()
        page.get_by_role('link',name='Return to review',exact=True).click()
        if layout=='editorial-magazine':page.get_by_role('link',name='3. Reader responses',exact=True).click()
        assert page.get_by_text('Page 1 of 6',exact=True).is_visible()
        page.get_by_role('link',name='Next',exact=True).click()
        assert page.get_by_text('Page 2 of 6',exact=True).is_visible()
        score=page.locator('#readers .score').inner_text()
        page.get_by_role('combobox',name='Rating',exact=True).select_option('1')
        page.get_by_role('combobox',name='Sort reader notes',exact=True).select_option('lowest')
        page.get_by_role('button',name='Filter reader notes',exact=True).click()
        expected=rt.db.opinions(a,{'stars':'1','sort':'lowest'})[:4]
        links=page.locator('#readers .entry a').filter(has_text='Read this reader note')
        assert links.count()==len(expected)
        actual=[links.nth(i).get_attribute('href').split('/')[-1] for i in range(links.count())]
        assert actual==[r['id'] for r in expected]
        assert page.locator('#readers .score').inner_text()==score
        if expected:
            links.first.click();assert expected[0]['body'] in page.locator('main').inner_text()
        report['checks']+=['other_variant_not_reviewed','reader_pagination','filter_exact_corpus','overall_score_stable','reader_permalink']
        page.goto(rt.origin+'/compare')
        peer=rt.db.articles[1]
        page.get_by_role('combobox',name='First '+words.item,exact=True).select_option(a['id'])
        page.get_by_role('combobox',name='Second '+words.item,exact=True).select_option(peer['id'])
        page.get_by_role('button',name='Compare',exact=True).click()
        assert a['reviewed_sku'] in page.locator('table').inner_text() and peer['reviewed_sku'] in page.locator('table').inner_text()
        report['captures'].append(capture(env,out,'comparison'))
        page.goto(rt.origin+'/catalog')
        report['captures'].append(capture(env,out,'catalog'))
        facets=rt.db.facets();key=next(k for k,f in facets.items() if f['kind']=='choice' and not f['exclude'] and len(f['values'])>=2)
        values=facets[key]['values'][:2]
        for value in values:
            locator=page.locator('input[type=checkbox][name="f.'+key+'"]')
            for i in range(locator.count()):
                if locator.nth(i).get_attribute('value')==token(value):locator.nth(i).check();break
            else:raise AssertionError('Missing available facet choice')
        page.get_by_role('button',name='Apply filters',exact=True).click()
        wanted={a['id'] for a in rt.db.articles if (set(rt.db.variants[a['reviewed_sku']]['facts'].get(key,[]))&set(values) if isinstance(rt.db.variants[a['reviewed_sku']]['facts'].get(key),list) else rt.db.variants[a['reviewed_sku']]['facts'].get(key) in values)}
        assert page.get_by_role('heading',name=f'Reviews ({len(wanted)})',exact=True).is_visible()
        assert page.locator('input[name="f.'+key+'"]:checked').count()==2
        if len(wanted)>4:
            page.get_by_role('link',name='Next',exact=True).click()
            assert page.locator('input[name="f.'+key+'"]:checked').count()==2
            report['checks'].append('multiselect_preserved_across_pages')
        report['checks'].append('native_multiselect_or')
        range_key=next((k for k,f in facets.items() if f['kind']=='range'),None)
        if range_key:
            limit=facets[range_key]['values'][0]
            page.locator('[name="max.'+range_key+'"]').select_option(str(limit))
            page.get_by_role('button',name='Apply filters',exact=True).click()
            wanted={id for id in wanted if rt.db.variants[rt.db.by_id[id]['reviewed_sku']]['facts'][range_key]<=limit}
            assert page.get_by_role('heading',name=f'Reviews ({len(wanted)})',exact=True).is_visible()
            report['checks'].append('native_numeric_range_and_choices')
        if 'ingredients' in facets:
            page.get_by_role('link',name='Clear filters',exact=True).click()
            value=facets['ingredients']['values'][0]
            boxes=page.locator('input[name="x.ingredients"]')
            for i in range(boxes.count()):
                if boxes.nth(i).get_attribute('value')==token(value):boxes.nth(i).check();break
            page.get_by_role('button',name='Apply filters',exact=True).click()
            wanted=[a for a in rt.db.articles if value not in rt.db.variants[a['reviewed_sku']]['facts']['ingredients']]
            assert page.get_by_role('heading',name=f'Reviews ({len(wanted)})',exact=True).is_visible()
            report['checks'].append('native_ingredient_exclusion')
        page.get_by_role('link',name='Clear filters',exact=True).click()
        page.get_by_role('searchbox',name='Product or keyword',exact=True).fill('this-product-does-not-exist')
        page.get_by_role('button',name='Apply filters',exact=True).click()
        assert page.get_by_role('heading',name='Reviews (0)',exact=True).is_visible()
        # Traverse new public archives through native clicks, retaining the same data.
        page.goto(rt.origin+'/reviews/'+a['id'])
        page.locator('.byline').get_by_role('link',name=a['author'],exact=True).click()
        assert page.get_by_role('heading',name=a['author'],exact=True).is_visible()
        page.goto(rt.origin+'/activity')
        page.get_by_role('combobox',name='Activity category',exact=True).select_option(family)
        page.get_by_role('combobox',name='Activity rating',exact=True).select_option('2')
        page.get_by_role('button',name='Filter activity',exact=True).click()
        expected_activity=sorted(((x,c) for x in rt.db.articles for c in x['reader_opinions'] if c['stars']==2),key=lambda pair:(pair[1]['date'],pair[1]['id']),reverse=True)
        assert page.locator('main .entry').count()==min(4,len(expected_activity))
        if expected_activity:
            first=expected_activity[0][1]
            page.locator('main .entry').first.locator('strong a').click()
            assert page.get_by_role('heading',name=first['handle'],exact=True).is_visible()
            assert first['body'] in page.locator('main').inner_text()
        report['captures'].append(capture(env,out,'member-archive'))
        page.goto(rt.origin+'/reviews/'+a['id'])
        if layout=='lab-directory':
            key=next(iter(v['facts']))
            page.locator('nav[aria-label="On this page"]').get_by_role('link',name=__import__('environments.product_review_sites.data',fromlist=['field_info']).field_info(family,key)[0],exact=True).click()
            assert page.url.endswith('#fact-'+key)
            page.locator('#fact-'+key+' a').first.click()
            assert page.get_by_role('heading',name=__import__('re').compile(r'Reviews \(\d+\)')).is_visible()
        if layout=='community-feed':
            page.locator('#rating-distribution a').first.click()
            assert page.get_by_role('combobox',name='Rating',exact=True).input_value()=='5'
        report['checks']+=['contributor_archive','native_activity_filter','reader_archive','reference_structure_navigation']
        page.goto(rt.origin+'/methodology');assert page.get_by_role('heading',name='Facts and opinions',exact=True).is_visible()
        page.goto(rt.origin+'/reviews/'+a['id']);page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors,errors
        report['checks']+=['native_two_product_comparison','typed_attribute_filters','empty_search','methodology','mobile_width','no_js_errors'];report['passed']=True
    except Exception:
        report['passed']=False;report['error']=traceback.format_exc()
        try:
            (out/'failure-body.txt').write_text(env.unwrapped.page.locator('body').inner_text())
            env.unwrapped.page.screenshot(path=str(out/'failure.png'))
        except Exception:pass
    finally:
        report['access_log']=rt.access_log();env.close();rt.close()
        report['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return {k:report[k] for k in ('case','passed','checks')} | {'error':report.get('error')}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    paths=[Path(__file__),Path('scripts/inspect_retail_ax.py'),*Path('environments/product_review_sites').glob('*.py'),*Path('environments/product_world').glob('*.py'),*Path('intent_browser').glob('*.py')]
    hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}
    (a.output/'driver.py').write_bytes(Path(__file__).read_bytes())
    specs=[('footwear',d) for d in ('lab-directory','editorial-magazine','community-feed')]+[('laptops','editorial-magazine'),('dog_food','lab-directory'),('cat_food','lab-directory'),('beer','community-feed'),('wine','community-feed')]
    with ProcessPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[(f,d,str(a.output)) for f,d in specs]))
    report={'schema':'product-review-browser-v1','sources':hashes,'cases':results,'model_calls':0}
    (a.output/'suite.json').write_text(json.dumps(report,indent=2));print(json.dumps(results,indent=2))
    if not all(r['passed'] for r in results):raise SystemExit(1)


if __name__=='__main__':main()
