"""Three merchandising variations bound to a published world's canonical retailers."""
import argparse,json,os,signal,threading
from pathlib import Path
from contextlib import ExitStack
from .comparison_preview import bound_owner
from .comparison_profiles import create
from .http import Site
from .__main__ import source_hashes


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pin',type=Path,default=Path('.local/coordination/connected-shopping-world/product-pin-v2'))
    p.add_argument('--published',type=Path,default=Path('.local/connected-shopping/preview-v4-coverage'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,default=42)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    owner=bound_owner(a.pin,a.published)
    profiles=json.loads((a.published/'comparison-profiles.json').read_text())
    coverage=json.loads((a.published/'comparison-coverage.json').read_text())
    scope=next(x for x in coverage['sites'] if x['site_id']=='comparison-general-a')
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    with ExitStack() as stack:
        rows=[]
        for mode in ['trending','popular','new']:
            profile={**profiles['comparison-general-a'],'discovery':{'mode':mode,'seed':a.seed,'limit':12}}
            d=create(owner,profile,scope);site=stack.enter_context(Site(d.render,consent_design='bottom-banner'))
            rows.append({'mode':mode,'origin':site.origin,'profile':profile})
        manifest={'schema':'comparison-discovery-preview-v1','published_world':str(a.published),'pid':os.getpid(),'sites':rows,'coverage':scope}
        (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
        (a.output/'sources.json').write_text(json.dumps(source_hashes(),indent=2))
        print(json.dumps(manifest),flush=True);stop.wait()


if __name__=='__main__':main()
