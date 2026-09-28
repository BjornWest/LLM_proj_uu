"""Serve five specialist publications from one immutable generated product world."""
import argparse
from contextlib import ExitStack
import hashlib,json,os,signal,threading
from urllib.parse import urlsplit
from pathlib import Path
from .generate import generate_reviews,FAMILIES
from .runtime import Runtime
from environments.site_consent.runtime import DESIGNS,design_for,ROOT as CONSENT_ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ports-from',type=Path,help='Reuse local site ports from a previous preview manifest after stopping it');p.add_argument('--world',type=Path);p.add_argument('--seed',type=int,default=42)
    p.add_argument('--models-per-family',type=int,default=6);p.add_argument('--opinions-per-review',type=int,default=24)
    p.add_argument('--consent-design',choices=('sampled','none')+DESIGNS,default='sampled');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not 1<=a.models_per_family<=30:raise ValueError('1..30 models per family')
    a.output.mkdir(parents=True,exist_ok=False)
    if a.world:world=json.loads(a.world.read_text())
    else:
        from environments.product_world.generator import generate_catalog
        families=list(FAMILIES)*a.models_per_family
        world=generate_catalog(seed=a.seed,model_count=len(families),model_families=families)
    export=generate_reviews(world,seed=a.seed,opinions_per_review=a.opinions_per_review)
    (a.output/'world.json').write_text(json.dumps(world,ensure_ascii=False,indent=2))
    (a.output/'reviews.json').write_text(json.dumps(export,ensure_ascii=False,indent=2))
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    designs=[('footwear',('footwear',),'lab-directory'),('computing',('laptops',),'editorial-magazine'),('pets',('dog_food','cat_food'),'lab-directory'),('beer',('beer',),'community-feed'),('wine',('wine',),'community-feed')]
    ports={}
    if a.ports_from:
        for row in json.loads(a.ports_from.read_text())['sites']:
            parsed=urlsplit(row['origin'])
            if parsed.scheme!='http' or parsed.hostname not in ('localhost','127.0.0.1') or not parsed.port:
                raise ValueError('Expected local preview origins')
            ports[row['site_id']]=parsed.port
    with ExitStack() as stack:
        sites=[]
        for sid,families,layout in designs:
            rt=stack.enter_context(Runtime(export['public'],port=ports.get(sid,0),families=families,layout=layout,seed=a.seed,site_id=sid,consent_design=(design_for(a.seed,sid) if a.consent_design=='sampled' else None if a.consent_design=='none' else a.consent_design)))
            sites.append((sid,rt))
        manifest={'schema':'product-review-preview-v1','pid':os.getpid(),'public_sha256':export['private_provenance']['public_sha256'],
                  'sites':[{'site_id':sid,'name':rt.name,'families':rt.db.families,'layout':rt.layout,'consent_design':rt.consent.design if rt.consent else None,'origin':rt.origin,'article_count':len(rt.db.articles),
                            'example':rt.origin+'/reviews/'+next(iter(rt.db.by_id)) if rt.db.by_id else rt.origin+'/catalog'} for sid,rt in sites],
                  'sources':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [*Path('environments/product_review_sites').glob('*.py'),*CONSENT_ROOT.glob('*.py'),CONSENT_ROOT/'ui.js',CONSENT_ROOT/'style.css']}}
        (a.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        print(json.dumps({k:v for k,v in manifest.items() if k!='sources'},ensure_ascii=False),flush=True)
        try:stop.wait()
        finally:
            for sid,rt in sites:
                (a.output/(sid+'-access.json')).write_text(json.dumps(rt.access_log(),indent=2))
                if rt.consent:(a.output/(sid+'-consent.json')).write_text(json.dumps(rt.consent.snapshot(),indent=2))


if __name__=='__main__':main()
