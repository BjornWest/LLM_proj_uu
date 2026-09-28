"""Two-tab synthetic verification/cookie scope; no model or harness invocation."""
import argparse,json,hashlib
from pathlib import Path
from environments.connected_shopping.http import Site
from environments.site_verification import sample,Gate
from playwright.sync_api import sync_playwright


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    spec=sample(['comparator'],probability=1)['sites'][0];spec['trigger']='entry';gate=Gate(spec)
    renderer=lambda *a:(200,'<html><body><h1>Comparison offers</h1></body></html>')
    retailer=lambda *a:(200,'<html><body><h1>Retailer</h1><label>Notes<input aria-label="Notes"></label></body></html>')
    with Site(renderer,verification=gate) as cmp,Site(retailer) as shop,sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);ctx=browser.new_context();held=ctx.new_page();held.goto(cmp.origin+'/search?q=shoes');held_url=held.url
        assert held.get_by_role('heading',name='Verify you are human').is_visible()
        working=ctx.new_page();working.goto(shop.origin);working.bring_to_front();working.get_by_role('textbox',name='Notes').fill('research continues')
        sid,state=next(iter(gate.snapshot()['sessions'].items()));cid=state['challenge_id']
        assert gate.resolve(sid,cid)
        # Clearance alone does not navigate either browser page or pretend the
        # model received a fresh observation. The old gate remains until reload.
        assert held.get_by_role('heading',name='Verify you are human').is_visible()
        assert working.get_by_role('textbox',name='Notes').input_value()=='research continues'
        held.reload();assert held.url==held_url
        assert held.get_by_role('heading',name='Comparison offers').is_visible()
        assert working.get_by_role('textbox',name='Notes').input_value()=='research continues'
        held.screenshot(path=str(args.output/'cleared.png'));working.screenshot(path=str(args.output/'independent-tab.png'))
        gate.reset();held.reload();assert held.get_by_role('heading',name='Verify you are human').is_visible()
        assert not gate.resolve(sid,cid)
        (args.output/'journal.private.json').write_text(json.dumps(gate.snapshot(),indent=2));browser.close()
    files=[Path(__file__),Path('environments/connected_shopping/http.py'),Path('environments/site_verification/runtime.py')]
    report={'passed':True,'model_calls':0,'scope':'Two native Chromium tabs; trusted scripted clearance while unrelated tab retains typed state; no harness custody or user-LLM claim','source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'artifact_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}}
    (args.output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':True,'model_calls':0}))

if __name__=='__main__':main()
