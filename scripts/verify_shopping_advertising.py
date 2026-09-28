"""Privileged scripted ad AX/link acceptance; no model calls or purchasing."""
import argparse,json,hashlib
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from urllib.request import urlopen


def journey(args):
    site,ads,runtime,out=args
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    root=Path(out)/site['site_id'];root.mkdir()
    env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':site['origin'],'goal':'Scripted ad display/link acceptance'},headless=True)
    try:
        env.reset();page=env.unwrapped.page
        page.get_by_role('button',name='Manage preferences',exact=True).click()
        page.get_by_role('button',name='Reject optional cookies',exact=True).or_(page.get_by_role('button',name='Use necessary cookies only',exact=True)).click()
        metrics=capture(env,root,'ads')
        ax=(root/'ads.outline.txt').read_text()
        assert 'Advertisement' in ax
        for ad in ads:
            card=page.locator('[data-ad-id="'+ad['ad_id']+'"]')
            assert card.is_visible() and card.get_by_text('Advertisement',exact=True).is_visible()
            assert ad['headline'] in ax
        # Both layouts also remain usable at a narrow viewport.
        page.set_viewport_size({'width':390,'height':844})
        assert page.locator('body').evaluate('e=>e.scrollWidth')<=410
        page.screenshot(path=str(root/'mobile.png'),full_page=False)
        first=page.locator('[data-ad-id="'+ads[0]['ad_id']+'"] a')
        expected=first.get_attribute('href');first.click()
        assert page.url==expected
        assert page.locator('#selected-sku').inner_text()==ads[0]['product_id']
        capture(env,root,'destination')
        return {'site_id':site['site_id'],'passed':True,'ads':len(ads),'ax_semantic_nodes':metrics['semantic_nodes'],'destination':expected}
    finally:env.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((a.runtime/'manifest.json').read_text());ad=json.loads((a.runtime/'advertising.public.json').read_text())
    lookup={s['site_id']:s for s in manifest['sites']};selected=[]
    for kind in ('aggregator','product_review'):
        s=next(s for s in ad['sites'] if s['kind']==kind and s['ads']);selected.append((lookup[s['site_id']],s['ads'],str(a.runtime),str(a.output)))
    with ProcessPoolExecutor(max_workers=2) as pool:rows=list(pool.map(journey,selected))
    result={'passed':True,'cases':rows,'model_calls':0,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'manifest_sha256':hashlib.sha256((a.runtime/'manifest.json').read_bytes()).hexdigest(),
      'advertising_file_sha256':hashlib.sha256((a.runtime/'advertising.public.json').read_bytes()).hexdigest()}
    (a.output/'report.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
