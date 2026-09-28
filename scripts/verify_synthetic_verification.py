"""Offline native-browser verification gates; private scripted user, no model/API.

Each case gets an isolated server, gate, browser and session. Cases run bounded
parallel. Captures are Chromium AX trees (not harness-delivered model inputs).
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path


def run_case(args):
    style,trigger,out=args
    from playwright.sync_api import sync_playwright
    from environments.site_verification import sample,Gate
    from environments.connected_shopping.http import Site
    root=Path(out)/f'{style}-{trigger}';root.mkdir()
    spec=sample(['comparison-test'],probability=1)['sites'][0]
    spec.update(style=style,trigger=trigger)
    gate=Gate(spec)
    def render(path,q,raw):
        return 200,'<html><body><h1>Comparison catalog</h1><form action="/search"><label>Search<input name="q"></label><button>Search</button></form><p>Offer 123 SEK</p></body></html>'
    with Site(render,verification=gate) as site,sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context();page=context.new_page()
        page.goto(site.origin+'/')
        if trigger=='discovery':
            assert page.get_by_role('heading',name='Comparison catalog').is_visible()
            page.get_by_role('textbox',name='Search').fill('shoes')
            page.get_by_role('button',name='Search',exact=True).click()
        assert page.get_by_role('heading',name='Verify you are human').is_visible()
        assert 'Offer 123' not in page.content()
        original=page.url
        cdp=context.new_cdp_session(page)
        (root/'pending.ax.json').write_text(json.dumps(cdp.send('Accessibility.getFullAXTree'),indent=2))
        page.screenshot(path=str(root/'pending.png'))
        page.get_by_role('link',name='Check verification status').click()
        assert page.url==original
        assert page.get_by_role('heading',name='Verify you are human').is_visible()
        states=gate.snapshot()['sessions'];sid=next(iter(states));cid=states[sid]['challenge_id']
        assert gate.resolve(sid,cid) # trusted user fixture, not a browser action
        page.get_by_role('link',name='Check verification status').click()
        assert page.url==original
        assert page.get_by_role('heading',name='Comparison catalog').is_visible()
        (root/'resumed.ax.json').write_text(json.dumps(cdp.send('Accessibility.getFullAXTree'),indent=2))
        page.screenshot(path=str(root/'resumed.png'))
        other=browser.new_context();otherpage=other.new_page()
        otherpage.goto(original)
        if trigger=='discovery' and original==site.origin+'/':raise AssertionError('Missing discovery')
        assert otherpage.get_by_role('heading',name='Verify you are human').is_visible()
        (root/'journal.private.json').write_text(json.dumps(gate.snapshot(),indent=2))
        browser.close()
    return {'style':style,'trigger':trigger,'passed':True,'model_calls':0,'capture':'Chromium full AX; not harness delivery'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    cases=[(s,t,str(args.output)) for s in ('interstitial','embedded') for t in ('entry','discovery')]
    with ProcessPoolExecutor(max_workers=2) as pool:rows=list(pool.map(run_case,cases))
    paths=list(Path('environments/site_verification').glob('*.py'))+[Path('environments/connected_shopping/http.py'),Path(__file__)]
    result={'passed':all(r['passed'] for r in rows),'cases':rows,'model_calls':0,'scope':'local simulation; no external Turnstile widget or user LLM',
            'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            'artifact_sha256':{str(p.relative_to(args.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.rglob('*') if p.is_file()}}
    (args.output/'report.json').write_text(json.dumps(result,indent=2));print(json.dumps({'passed':result['passed'],'cases':len(rows)}))

if __name__=='__main__':main()
