"""BrowserGym AX projection for local gate designs; no model/user-LLM calls."""
import argparse,json,hashlib,os,sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor


def case(args):
    style,out=args
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from environments.site_verification import sample,Gate
    from environments.connected_shopping.http import Site
    from scripts.inspect_retail_ax import capture
    import intent_browser.ax_context as ax
    root=Path(out)/style;root.mkdir();spec=sample(['comparison'],probability=1)['sites'][0];spec.update(style=style,trigger='entry');gate=Gate(spec)
    with Site(lambda *a:(200,'<html><body><h1>Product offers</h1><p>Price 123 SEK</p></body></html>'),verification=gate) as site:
        env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':site.origin,'goal':'Scripted verification presentation acceptance'},headless=True)
        try:
            env.reset();before=capture(env,root,'blocked');text=(root/'blocked.outline.txt').read_text()
            assert 'Verify you are human' in text and 'Verification pending' in text and 'Price 123' not in text
            sid,state=next(iter(gate.snapshot()['sessions'].items()));assert gate.resolve(sid,state['challenge_id'])
            env.unwrapped.page.reload();after=capture(env,root,'resumed');text=(root/'resumed.outline.txt').read_text()
            assert 'Product offers' in text and 'Price 123 SEK' in text and 'Verification pending' not in text
            return {'style':style,'passed':True,'blocked_nodes':before['semantic_nodes'],'resumed_nodes':after['semantic_nodes'],'tokenizer':before['tokenizer'],'blocked_projection_tokens':before['full_nonverbose_projection_tokens'],'scope':'Complete nonverbose AX audit reconstruction, not one policy message','ax_module':ax.__file__,'ax_sha256':hashlib.sha256(Path(ax.__file__).read_bytes()).hexdigest()}
        finally:env.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--harness-source',type=Path,required=True);a=p.parse_args();sys.path.insert(0,str(a.harness_source.resolve()));a.output.mkdir(parents=True,exist_ok=False)
    with ProcessPoolExecutor(max_workers=2) as pool:rows=list(pool.map(case,[(s,str(a.output)) for s in ('interstitial','embedded')]))
    report={'passed':True,'model_calls':0,'cases':rows,'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path('scripts/inspect_retail_ax.py'),Path('environments/site_verification/runtime.py'),Path('environments/connected_shopping/http.py')]},'artifacts_sha256':{str(p.relative_to(a.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.rglob('*') if p.is_file()}}
    (a.output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':True,'cases':rows}))

if __name__=='__main__':main()
