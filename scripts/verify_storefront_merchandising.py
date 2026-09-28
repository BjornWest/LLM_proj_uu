"""Native collection/merchandising journeys in three retailer shells, no model calls."""
import argparse,hashlib,json,traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


def run(spec):
    pin,output,design=spec;out=Path(output)/design;out.mkdir()
    from environments.connected_shopping.pins import load_pin
    from environments.connected_shopping.runtime import Runtime
    from environments.connected_shopping.storefront import collection_path,section_path
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from intent_browser.ax_context import AXContext
    from intent_browser.standard_profile import standard_profile
    scenario,_=load_pin(Path(pin))
    report={'design':design,'passed':False,'model_calls':0,'checks':[]}
    def read(name):
        path=Path(pin)/name
        return json.loads(path.read_text()) if path.exists() else None
    with Runtime(scenario,consent=False,comparison_coverage=read('coverage.public.json'),comparison_profiles=read('comparison-profiles.json'),advertising=read('advertising.public.json')) as rt:
        sid=next(s for s,d in rt.designs.items() if d==design);row=rt.storefront_by_store[sid]
        report.update(site=sid,provenance=rt.provenance)
        env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':rt.origins[sid], 'goal':'Scripted storefront acceptance'},headless=True,viewport={'width':1440,'height':1000},timeout=10000)
        try:
            env.reset();page=env.unwrapped.page;errors=[];page.on('pageerror',lambda x:errors.append(str(x)))
            def capture(name):
                ax=AXContext(standard_profile(helpers=False,data_tools=False).ax_config)
                ax.capture(env.unwrapped._get_obs())
                projection=[ax._project(ax.ref(i),False) for i in range(len(ax.nodes))]
                (out/(name+'-ax.json')).write_text(json.dumps({'semantic_nodes':len(projection),'projection':projection},ensure_ascii=False,indent=2))
                page.screenshot(path=str(out/(name+'.png')))
                return ax
            if design=='dense-storefront':page.locator('header summary').filter(has_text='Shop by category').click()
            ax=capture('home')
            collection=row['collections'][0]
            nav=page.get_by_role('navigation',name='Shop by category',exact=True)
            assert nav.is_visible()
            for c in row['collections']:assert nav.get_by_role('link',name=c['title'],exact=True).is_visible()
            assert not page.get_by_role('navigation',name='Pagination',exact=True).count()
            for section in row['sections']:assert page.get_by_role('heading',name=section['title'],exact=True).count()==1
            nav.get_by_role('link',name=collection['title'],exact=True).click()
            assert page.get_by_role('heading',name=collection['title'],exact=True).is_visible()
            capture('collection')
            # Use the rendered search form, not URL injection, to retain collection scope.
            form=page.locator('main form.search-form').first
            sku=collection['product_ids'][0]
            form.get_by_role('searchbox',name='Search products',exact=True).fill(sku)
            form.get_by_role('button',name='Search',exact=True).click()
            assert page.locator('main').inner_text().count('1 product listings')==1
            page.locator('main a[href$="/products/'+sku+'"]').first.click()
            assert page.locator('#selected-sku').inner_text()==sku
            capture('product')
            report['checks']+=['generated_categories_in_native_shell','no_home_pagination','native_collection_search_retains_scope','exact_sku_reachable']
            for section in row['sections']:
                page.goto(rt.origins[sid])
                page.get_by_role('link',name='Explore '+section['title'].lower(),exact=True).click()
                assert page.get_by_role('heading',name=section['title'],exact=True).is_visible()
            for label,heading in [('Returns','Returns'),('Purchase information','Purchase information'),('Contact & stores','Contact & stores')]:
                page.get_by_role('navigation',name='Customer service',exact=True).get_by_role('link',name=label,exact=True).click()
                assert page.get_by_role('heading',name=heading,exact=True).is_visible()
            assert not errors,errors
            assert not rt.snapshot()['commerce_mutations']
            report['checks']+=['all_merchandising_sections_navigate','compact_footer_routes','no_page_errors_or_commerce_mutations']
            report['passed']=True
        except Exception:report['error']=traceback.format_exc()
        finally:env.close()
    report['artifacts']={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    (out/'report.json').write_text(json.dumps(report,indent=2));return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pin',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    from environments.connected_shopping.__main__ import source_hashes
    sources=source_hashes()
    for f in [Path(__file__),*(Path('intent_browser')/name for name in ('ax_context.py','ax_explorer.py','standard_profile.py'))]:sources[str(f)]=hashlib.sha256(f.read_bytes()).hexdigest()
    with ProcessPoolExecutor(max_workers=2) as pool:cases=list(pool.map(run,[(str(args.pin),str(args.output),d) for d in ('editorial-boutique','dense-storefront','technical-catalog')]))
    drift=[f for f,h in sources.items() if hashlib.sha256(Path(f).read_bytes()).hexdigest()!=h]
    result={'schema':'storefront-merchandising-browser-v1','cases':cases,'sources':sources,'source_drift':drift,'model_calls':0}
    (args.output/'report.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'cases':[{k:c.get(k) for k in ('design','passed','error')} for c in cases],'source_drift':drift}))
    if drift or not all(c['passed'] for c in cases):raise SystemExit(1)

if __name__=='__main__':main()
