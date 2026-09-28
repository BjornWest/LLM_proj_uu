"""Launch a fixed, fictional review world for local browsing or BrowserGym."""
import argparse,hashlib,json,os,signal,threading
from pathlib import Path
from .runtime import Runtime
from .identity import sample_identity


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=0);p.add_argument('--seed',type=int,default=42);p.add_argument('--site-name');p.add_argument('--site-id',default='merchant-reviews');p.add_argument('--reviews-per-store',type=int,default=48);p.add_argument('--export',type=Path);p.add_argument('--bindings',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    if a.export:bundle=json.loads(a.export.read_text())
    else:
        from environments.product_world.stores import generate_store_world
        from environments.product_world.reviews import generate_reviews
        world=generate_store_world(seed=a.seed,store_count=8,focus_families=['footwear','laptops'],models_per_store=3)
        # Authored demonstration priors, not inferred real merchant safety.
        ids=[s['retailer_id'] for s in world['public']['retailers']]
        profiles=[{'1':1,'2':1,'3':2,'4':5,'5':8},{'1':8,'2':5,'3':2,'4':1,'5':1},{str(n):1 for n in range(1,6)}]
        bundle=generate_reviews(world,seed=a.seed,reviews_per_store=a.reviews_per_store,config={'company_star_weights':{id:profiles[i%3] for i,id in enumerate(ids)}})
        (a.output/'world.json').write_text(json.dumps(world,ensure_ascii=False,indent=2))
    if bundle.get('schema_version')!='merchant-review-export-v1':raise ValueError('Unsupported review export')
    (a.output/'reviews.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2))
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    bindings=json.loads(a.bindings.read_text()) if a.bindings else None
    identity=sample_identity(a.seed,a.site_id)
    if a.site_name:identity['name']=a.site_name
    with Runtime(bundle['public'],a.port,bindings,site_name=identity['name']) as runtime:
        manifest={'schema_version':'merchant-reviews-preview-v1','identity':identity,'origin':runtime.origin,'pid':os.getpid(),'companies':len(runtime.catalog.companies),'reviews':len(runtime.catalog.by_review),'public_sha256':hashlib.sha256(json.dumps(bundle['public'],sort_keys=True).encode()).hexdigest(),'sources':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [*Path('environments/merchant_reviews').glob('*.py'),Path('environments/product_world/reviews.py')]}}
        (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({k:v for k,v in manifest.items() if k!='sources'}),flush=True)
        try:stop.wait()
        finally:(a.output/'access-log.json').write_text(json.dumps(runtime.access_log(),indent=2))


if __name__=='__main__':main()
