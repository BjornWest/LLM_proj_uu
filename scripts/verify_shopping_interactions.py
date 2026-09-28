"""Offline browser + actual harness AX acceptance; isolated cases, no model calls."""
import argparse,hashlib,json,traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from urllib.parse import urlencode


def run(spec):
    name,output=spec;out=Path(output)/name;out.mkdir()
    from environments.connected_shopping.test_interaction_patterns import specimen,destination
    from environments.connected_shopping.runtime import Runtime
    from environments.connected_shopping.pages import money
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from intent_browser.ax_context import AXContext
    from intent_browser.standard_profile import standard_profile
    report={'case':name,'checks':[],'passed':False,'model_calls':0}
    s=specimen()
    (out/'scenario.private.json').write_text(json.dumps(s,indent=2))
    with Runtime(s,consent=False) as rt:
        env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':rt.index_origin,'goal':'Offline shopping interaction acceptance'},headless=True,viewport={'width':1440,'height':1000},timeout=10000)
        try:
            env.reset();page=env.unwrapped.page;errors=[];page.on('pageerror',lambda x:errors.append(str(x)))
            def capture(label,query):
                ax=AXContext(standard_profile(helpers=False,data_tools=False).ax_config)
                ax.capture(env.unwrapped._get_obs())
                full=[ax._project(ax.ref(i),False) for i in range(len(ax.nodes))]
                found=ax.search(query,limit=20,repeat=True,verbose=False)
                links=ax.search(query,role='link',limit=20,repeat=True,verbose=False)
                result={'semantic_nodes':len(full),'projection':full,'query':query,'search':found,'links':links}
                (out/(label+'-ax.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
                page.screenshot(path=str(out/(label+'.png')))
                return ax,result
            if name=='retailer-home':
                sid='store-001';page.goto(rt.origins[sid])
                assert page.get_by_role('link',name='Shop the collection',exact=True).is_visible()
                assert not page.get_by_role('navigation',name='Pagination',exact=True).count()
                assert not page.get_by_role('navigation',name='Other websites',exact=True).count()
                capture('home','collection')
                page.get_by_role('link',name='Shop the collection',exact=True).click()
                assert page.get_by_role('table',name='Product price list',exact=True).is_visible()
                first=page.locator('main table tbody tr th a').first;model=first.inner_text();first.click()
                assert page.get_by_role('heading',name=model,exact=True).is_visible()
                # Independent discovery starts from the known index, not a store shortcut.
                page.goto(rt.index_origin)
                page.get_by_role('searchbox',name='Search sites and products',exact=True).fill(rt.stores[sid]['name'])
                page.get_by_role('combobox',name='Site type',exact=True).select_option('merchant_reviews')
                page.get_by_role('button',name='Search',exact=True).click()
                page.locator('main article h3 a').first.click()
                assert page.get_by_role('heading',name=rt.stores[sid]['name']+' reviews',exact=True).is_visible()
                report['checks']+=['home_collections_without_pagination','model_price_list_to_variant_page','merchant_reviews_found_through_index']
            elif name=='discovery':
                item=next(x for x in rt.comparisons if x['kind']=='model' and x['listings'])
                page.goto(rt.origins['aggregator']+'/search?'+urlencode({'q':item['name']}))
                ax,record=capture('search',item['name'])
                # Harness result links include both advice and a product sharing the name.
                links=[n for n in ax.nodes if n['role']=='link' and n['name']==item['name']]
                assert len(links)>=2
                query_links=record['links']['items']
                assert any(n.get('name')==item['name'] for n in query_links)
                # Resolve the ambiguous name using only projected public AX:
                # ascend past the heading, then inspect its containing article.
                contexts=[];chosen=None
                for n in links:
                    i=ax.nodes.index(n);parent=n['parent']
                    while parent is not None and ax.nodes[parent]['role'] not in ('article','row'):
                        parent=ax.nodes[parent]['parent']
                    assert parent is not None
                    context=ax.read(ax.ref(parent),view='subtree',depth=4,limit=50,repeat=True,verbose=False)
                    contexts.append(context)
                    text=json.dumps(context,ensure_ascii=False)
                    if 'SEK' in text and 'retailer' in text.lower():
                        chosen=ax._project(ax.ref(i),False)
                assert chosen is not None, 'No public AX price/merchant evidence distinguished a product'
                scoped=ax.search(item['name'],role='link',scope_ref=contexts[-1]['root'],repeat=True)
                assert len(scoped['items'])==1
                (out/'match-contexts.json').write_text(json.dumps({'contexts':contexts,'scoped_search':scoped,'selected':chosen},ensure_ascii=False,indent=2))
                page.locator('[bid="'+chosen['bid']+'"]').click()
                assert page.get_by_text('Show retailer offers',exact=True).is_visible()
                assert not page.get_by_role('link',name='View offer at '+rt.stores[item['listings'][0]['retailer_id']]['name'],exact=True).is_visible()
                page.get_by_text('Show retailer offers',exact=True).click()
                merchant=page.get_by_role('link',name='View offer at '+rt.stores[item['listings'][0]['retailer_id']]['name'],exact=True)
                assert merchant.is_visible();merchant.click()
                sku=page.locator('#selected-sku').inner_text();offer=rt.offer_by_store[(item['listings'][0]['retailer_id'],sku)]
                assert money(offer['price_minor']) in page.locator('main').inner_text()
                capture('retailer',rt.group_for[sku]['name'])
                report['checks']+=['same_name_review_and_product_links','harness_search_and_parent_context','collapsed_offers_require_native_open','retailer_identity_and_price_match']
            else:
                sid='store-001' if name=='split-destination' else 'store-002'
                offer=next(o for o in rt.offers.values() if o['retailer_id']==sid)
                if name=='split-destination':
                    page.goto(rt.origins[sid]+'/search?'+urlencode({'q':rt.products[offer['product_id']]['name']}))
                    ax,record=capture('retail-list',rt.products[offer['product_id']]['name'])
                    assert any(n['role']=='table' for n in ax.nodes)
                    assert any(n['role']=='columnheader' and n['name']=='Item price' for n in ax.nodes)
                    report['checks'].append('retail_list_has_table_row_and_column_semantics')
                page.goto(rt.origins[sid]+'/products/'+offer['product_id'])
                assert not page.locator('#delivered-total').count()
                page.get_by_role('link',name='Check delivery total and arrival',exact=True).click()
                assert not page.locator('#delivered-total').count()
                fields=destination(rt,sid)
                if name=='split-destination':
                    page.locator('[name="postcode_1"]').fill(''.join(rt.interaction_patterns['destination']['postcode_parts']))
                    assert len(page.locator('[name="postcode_1"]').input_value())==3
                else:page.locator('[name="postcode"]').fill('00000')
                page.get_by_role('button',name='Calculate quote',exact=True).click()
                assert not page.locator('#delivered-total').count()
                assert page.get_by_role('alert').is_visible()
                capture('invalid-destination','Postcode')
                for k,v in fields.items():page.locator('[name="'+k+'"]').fill(v)
                page.get_by_role('button',name='Calculate quote',exact=True).click()
                assert page.locator('#delivered-total').inner_text()==money(rt.quote(offer['offer_id'])['total_minor'])
                capture('valid-destination','Total')
                # Re-entering a new invalid location must not retain a stale valid total.
                page.locator('[name="destination_country"]').fill('US')
                page.get_by_role('button',name='Calculate quote',exact=True).click()
                assert not page.locator('#delivered-total').count()
                report['checks']+=['no_quote_before_location','partial_or_wrong_address_feedback','native_correction_exact_canonical_total','wrong_country_clears_previous_quote']
            assert not errors,errors
            assert not rt.snapshot()['commerce_mutations']
            report.update(passed=True,provenance=rt.provenance)
        except Exception:report['error']=traceback.format_exc()
        finally:env.close()
    report['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    (out/'report.json').write_text(json.dumps(report,indent=2));return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    from environments.connected_shopping.__main__ import source_hashes
    before=source_hashes()
    for p in [Path(__file__),*(Path('intent_browser')/name for name in ('ax_context.py','ax_explorer.py','standard_profile.py'))]:before[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    with ProcessPoolExecutor(max_workers=2) as pool:reports=list(pool.map(run,[(name,str(a.output)) for name in ('discovery','split-destination','single-destination','retailer-home')]))
    after={k:hashlib.sha256(Path(k).read_bytes()).hexdigest() for k in before};drift=[k for k,v in before.items() if after.get(k)!=v]
    result={'schema':'shopping-interaction-browser-v1','sources':before,'source_drift':drift,'cases':reports,'model_calls':0}
    (a.output/'report.json').write_text(json.dumps(result,indent=2));print(json.dumps({'cases':[{k:r.get(k) for k in ('case','passed','error')} for r in reports],'source_drift':drift}))
    if drift or not all(r['passed'] for r in reports):raise SystemExit(1)

if __name__=='__main__':main()
