"""New footwear preview: native type discovery and retailer variant reachability.

Privileged scripted acceptance; no model calls, purchasing or outcome grading.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
import hashlib,json
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode


def read(p):return json.loads(Path(p).read_text())


def journey(args):
    kind,model,runtime,output=args
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    root=Path(output)/kind.replace(' ','-');root.mkdir()
    manifest=read(Path(runtime)/'manifest.json')
    env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':manifest['index_url'],
        'goal':'Scripted public footwear type discovery'},headless=True,timeout=10000)
    try:
        env.reset();page=env.unwrapped.page
        page.get_by_role('searchbox',name='Search sites and products',exact=True).fill(model['name'])
        page.get_by_role('combobox',name='Site type',exact=True).select_option('retailer')
        page.get_by_role('button',name='Search',exact=True).click()
        target=page.locator('main article h3 a').first
        assert target.count(),'No indexed retailer for offered model'
        target.click()
        manage=page.get_by_role('button',name='Manage preferences',exact=True)
        if manage.count() and manage.is_visible():
            manage.click()
            page.get_by_role('button',name='Reject optional cookies',exact=True).or_(
                page.get_by_role('button',name='Use necessary cookies only',exact=True)).click()
        product_url=page.url
        details=page.get_by_role('link',name='Read full product details',exact=True)
        if details.count():details.click()
        # Check the selected product's fact row, not matching text in related items.
        fact=page.locator('table.fact-table tr').filter(has=page.get_by_role('rowheader',name='Shoe type',exact=True))
        assert fact.count()==1
        assert fact.locator('td').inner_text()==kind
        metrics=capture(env,root,'retailer')
        result={'type':kind,'model_id':model['group_id'],'product_url':product_url,'url':page.url,
                'ax_semantic_nodes':metrics['semantic_nodes'],'passed':True,'model_calls':0}
        (root/'report.json').write_text(json.dumps(result,indent=2));return result
    finally:env.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scenario',required=True,type=Path)
    p.add_argument('--runtime',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    scenario=read(a.scenario);world=scenario['bundle']['public'];products={p['product_id']:p for p in world['products']}
    groups=[g for g in world['product_groups'] if g['family']=='footwear']
    examples={};counts=Counter();offered={o['product_id'] for o in world['offers']}
    for g in groups:
        kinds={products[v['product_id']]['attributes']['shoe_type'] for v in g['variants']}
        assert len(kinds)==1;kind=next(iter(kinds));counts[kind]+=1
        assert all(axis['field']!='shoe_type' for axis in g['axes'])
        if any(v['product_id'] in offered for v in g['variants']):examples.setdefault(kind,g)
    assert set(examples)==set(counts),'A shoe type has no reachable retailer offer'
    # Compare type-filter HTTP results against the site's actual membership, not the full world.
    manifest=read(a.runtime/'manifest.json');coverage=read(a.runtime/'comparison-coverage.json')
    comparisons={g['group_id']:products[g['variants'][0]['product_id']]['attributes']['shoe_type'] for g in groups}
    by_id={s['site_id']:s for s in manifest['sites']};checks=[]
    for site in coverage['sites']:
        if 'footwear' not in site['families']:continue
        members=[i for i in site['comparison_ids'] if i in comparisons]
        profile=read(a.runtime/'comparison-profiles.json')[site['site_id']]
        if 'shoe_type' not in profile['filters']['attributes'].get('footwear',[]):continue
        values=sorted({comparisons[i] for i in members})
        for ix,value in enumerate(values):
            expected=[i for i in members if comparisons[i]==value]
            query=urlencode({'category':'footwear',f'f_shoe_type_{ix}':'1'})
            with urlopen(by_id[site['site_id']]['origin']+'/search?'+query,timeout=20) as response:
                html=response.read().decode()
            assert 'Shoe type' in html and f'{len(expected)} comparison products' in html
            checks.append({'site':site['site_id'],'type':value,'count':len(expected)})
    with ProcessPoolExecutor(max_workers=2) as pool:
        rows=list(pool.map(journey,[(k,g,str(a.runtime),str(a.output)) for k,g in examples.items()]))
    result={'passed':True,'models':len(groups),'models_by_type':dict(counts),'native_journeys':rows,
            'comparison_type_counts':checks,'model_calls':0,
            'scenario_sha256':hashlib.sha256(a.scenario.read_bytes()).hexdigest(),
            'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (a.output/'report.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
