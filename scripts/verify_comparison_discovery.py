"""Read-only native checks against additive merchandising previews; no model calls."""
import argparse,json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from urllib.request import urlopen
from urllib.parse import urljoin


def check(args):
    site,output=args
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    from environments.connected_shopping.comparison_discovery import LABELS
    out=Path(output)/site['mode'];out.mkdir()
    env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':site['origin'],'goal':'Scripted discovery-section acceptance'},headless=True,viewport={'width':1440,'height':1000},timeout=10000)
    try:
        env.reset();page=env.unwrapped.page
        page.get_by_role('button',name='Use necessary cookies only',exact=True).click();page.locator('#consent-ui').wait_for(state='hidden')
        region=page.get_by_role('region',name=LABELS[site['mode']],exact=True)
        assert region.is_visible()
        assert region.locator('article').count()==12
        families=region.locator('article > small').all_text_contents()
        assert set(families)=={'Footwear','Laptops','Cat food','Dog food','Beer','Wine'}
        links=region.locator('h3 a');hrefs=links.evaluate_all('(xs)=>xs.map(x=>x.getAttribute("href"))')
        assert len(set(hrefs))==12
        assert all(urlopen(urljoin(site['origin'],href)).status==200 for href in hrefs)
        metrics=capture(env,out,'home')
        name=links.first.inner_text();links.first.click();assert page.get_by_role('heading',name=name,exact=True).is_visible()
        page.goto(site['origin']);assert region.locator('h3 a').evaluate_all('(xs)=>xs.map(x=>x.getAttribute("href"))')==hrefs
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        result={'passed':True,'mode':site['mode'],'origin':site['origin'],'families':families,'links':hrefs,'home_ax_nodes':metrics['semantic_nodes'],'model_calls':0}
        (out/'report.json').write_text(json.dumps(result,indent=2));return result
    finally:env.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    data=json.loads(a.manifest.read_text())
    with ProcessPoolExecutor(max_workers=2) as pool:results=list(pool.map(check,[(site,str(a.output)) for site in data['sites']]))
    report={'passed':all(x['passed'] for x in results),'cases':results,'manifest':str(a.manifest),'model_calls':0}
    (a.output/'suite.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':main()
