"""Publish additive design previews bound to an existing connected world.

No second catalog, retailer, task card or geography publisher is created.
"""
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import argparse,json,hashlib,os,signal,threading
from .pins import load_pin
from .comparison import build
from .comparison_designs import Design
from .http import Site


def bound_owner(pin,published):
    scenario,_=load_pin(pin);root=Path(published)
    manifest=json.loads((root/'manifest.json').read_text());provenance=json.loads((root/'provenance.json').read_text())
    if provenance['world_sha256']!=scenario['bundle']['world_sha256']:raise ValueError('Published world does not match pin')
    p=scenario['bundle']['public']
    return SimpleNamespace(comparisons=build(scenario['bundle']),offers={o['offer_id']:o for o in p['offers']},stores={s['retailer_id']:s for s in p['retailers']},group_for={v['product_id']:g for g in p['product_groups'] for v in g['variants']},families=sorted({p['category'] for p in p['products']}),origins={s['site_id']:s['origin'] for s in manifest['sites']},index_origin=manifest['index_url'])


class Preview:
    def __init__(self,pin,published):
        self.owner=bound_owner(pin,published);self.stack=ExitStack();self.sites={};self.designs={}
        try:
            specs=[('directory',None,'Prislyktan'),('specialist','footwear','Stegvis'),('specialist','laptops','Datorval')]
            for layout,family,name in specs:
                d=Design(self.owner,layout=layout,family=family,name=name);site=self.stack.enter_context(Site(d.render,consent_design='bottom-banner'))
                key=layout+('-'+family if family else '');self.designs[key]=d;self.sites[key]=site
            self.manifest={'schema':'comparison-design-preview-v1','published_world':str(published),'sites':[{'id':key,'layout':self.designs[key].layout,'family':self.designs[key].family,'name':self.designs[key].name,'url':site.origin} for key,site in self.sites.items()]}
        except BaseException:self.stack.close();raise
    def close(self):self.stack.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--pin',type=Path,default=Path('.local/coordination/connected-shopping-world/product-pin-v2'));p.add_argument('--published',type=Path,default=Path('.local/connected-shopping/preview-v2'));p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    with Preview(a.pin,a.published) as preview:
        (a.output/'manifest.json').write_text(json.dumps(preview.manifest,indent=2))
        (a.output/'process.json').write_text(json.dumps({'pid':os.getpid(),'manifest':str(a.output/'manifest.json')},indent=2))
        (a.output/'sources.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},indent=2))
        print(json.dumps(preview.manifest),flush=True);stop.wait()


if __name__=='__main__':main()
