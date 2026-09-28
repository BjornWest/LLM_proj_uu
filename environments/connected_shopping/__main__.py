"""Launch a new local connected-world preview from an immutable product pin."""
import argparse,hashlib,json,os,signal,threading
from pathlib import Path
from .runtime import Runtime
from .pins import load_pin


def source_hashes():
    paths=[]
    for package in ['connected_shopping','procedural_commerce','product_review_sites','merchant_reviews','site_consent','site_verification','travel_planner','product_world']:
        paths.extend(p for p in (Path('environments')/package).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.css','.json') and '__pycache__' not in p.parts)
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pin',type=Path,default=Path('.local/coordination/connected-shopping-world/product-pin-v1'));p.add_argument('--comparison-coverage',type=Path);p.add_argument('--advertising',type=Path);p.add_argument('--interaction-patterns',type=Path);p.add_argument('--storefront-content',type=Path);p.add_argument('--verification-probability',type=float);p.add_argument('--verification-seed',type=int,default=0);p.add_argument('--comparison-profiles',type=Path);p.add_argument('--product-review-evidence',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--no-consent',action='store_true');p.add_argument('--product-review-seed',type=int,default=42);p.add_argument('--opinions-per-review',type=int,default=24);a=p.parse_args()
    scenario,pins=load_pin(a.pin)
    if a.product_review_evidence:
        scenario['product_review_evidence']=json.loads(a.product_review_evidence.read_text())
        from environments.product_review_sites.evidence import validate_evidence
        validate_evidence(scenario['bundle'],scenario['product_review_evidence'])
    coverage=json.loads(a.comparison_coverage.read_text()) if a.comparison_coverage else None
    verification=None
    if a.verification_probability is not None:
        from environments.site_verification import sample
        verification=sample([c['site_id'] for c in coverage['sites']] if coverage else ['aggregator'],seed=a.verification_seed,probability=a.verification_probability)
    a.output.mkdir(parents=True,exist_ok=False)
    def save(name,obj):(a.output/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2))
    save('source-pins.json',pins);save('sources.json',source_hashes());stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    with Runtime(scenario,storefront_content=json.loads(a.storefront_content.read_text()) if a.storefront_content else None,interaction_patterns=json.loads(a.interaction_patterns.read_text()) if a.interaction_patterns else None,verification=verification,advertising=json.loads(a.advertising.read_text()) if a.advertising else None,comparison_coverage=coverage,comparison_profiles=json.loads(a.comparison_profiles.read_text()) if a.comparison_profiles else None,product_review_seed=a.product_review_seed,opinions_per_review=a.opinions_per_review,consent=not a.no_consent) as rt:
        if rt.interaction_patterns is not None:save('interaction-patterns.public.json',rt.interaction_patterns)
        if rt.storefront_content is not None:save('storefront-content.public.json',rt.storefront_content)
        if rt.account_pages is not None:save('accounts.private.json',scenario['accounts'])
        if verification is not None:save('verification.private.json',verification)
        if rt.advertising is not None:save('advertising.public.json',rt.advertising.public)
        if rt.comparison_coverage is not None:save('comparison-coverage.json',rt.comparison_coverage);save('comparison-profiles.json',rt.comparison_profiles)
        if rt.product_review_evidence is not None:save('product-review-evidence.private.json',rt.product_review_evidence)
        save('manifest.json',rt.public_manifest);save('bindings.json',rt.bindings);save('provenance.json',rt.provenance);save('product-reviews.private.json',rt.product_reviews);save('index-documents.public.json',rt.documents)
        save('process.json',{'pid':os.getpid(),'input_pin':str(a.pin),'index':rt.index_origin,'source_scenario_sha256':hashlib.sha256((a.pin/'scenario.private.json').read_bytes()).hexdigest()})
        print(json.dumps({'index':rt.index_origin.replace('127.0.0.1','localhost'),'sites':len(rt.site_records),'documents':len(rt.documents),'pid':os.getpid()},ensure_ascii=False),flush=True)
        try:stop.wait()
        finally:save('journal.private.json',rt.snapshot())


if __name__=='__main__':main()
