"""Capture current renderers against a saved immutable public review corpus."""
import argparse,hashlib,json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor


def run(spec):
    name,settings,path,export,root=spec
    from environments.product_review_sites.runtime import Runtime
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    public=json.loads(Path(export).read_text())['public'];out=Path(root)/name;out.mkdir()
    with Runtime(public,**settings) as rt:
        env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':rt.origin+path,'goal':'Read-only page audit'},headless=True,viewport={'width':1440,'height':1000},slow_mo=0,timeout=10000)
        try:
            env.reset();page=env.unwrapped.page
            report={'name':name,'captures':[capture(env,out,'page')],'settings':settings,'path':path,'model_calls':0}
            (out/'body.txt').write_text(page.locator('body').inner_text())
            page.set_viewport_size({'width':390,'height':844});report['mobile_no_overflow']=page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(out/'mobile.png'))
        finally:env.close()
    report['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return {k:report[k] for k in ('name','mobile_no_overflow')}


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--export',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads(a.manifest.read_text());specs=[]
    for s in manifest['sites']:
        settings={'families':s['families'],'layout':s['layout'],'name':s['name'],'page_size':12,'seed':42,'site_id':s['site_id']}
        path=s['example'][len(s['origin']):]
        specs.append((s['site_id'],settings,path,str(a.export),str(a.output)))
        specs.append((s['site_id']+'-catalog',settings,'/catalog',str(a.export),str(a.output)))
        if s['site_id']=='pets':specs.append(('dog-food',settings,'/reviews/dog_food-model-0003',str(a.export),str(a.output)))
        if s['site_id']=='computing':
            for part in ('specifications','readers'):specs.append(('computing-'+part,settings,path+'?part='+part,str(a.export),str(a.output)))
    sources={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path(__file__),*Path('environments/product_review_sites').glob('*.py')]}
    (a.output/'driver.py').write_bytes(Path(__file__).read_bytes())
    with ProcessPoolExecutor(max_workers=2) as pool:rows=list(pool.map(run,specs))
    report={'schema':'product-review-page-audit-v1','export_sha256':hashlib.sha256(a.export.read_bytes()).hexdigest(),'sources':sources,'cases':rows,'model_calls':0}
    (a.output/'suite.json').write_text(json.dumps(report,indent=2));print(json.dumps(rows,indent=2))
    if not all(r['mobile_no_overflow'] for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
