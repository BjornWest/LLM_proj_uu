"""Native stock disclosure and quantity checks; separate worlds, no model calls."""
import argparse,json,hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright
from environments.product_world.test_branch_shipping import fixture
from environments.connected_shopping.runtime import Runtime


def case(enabled,out):
    out.mkdir();scenario=fixture(enabled=enabled,stockout=1)
    (out/'scenario.private.json').write_text(json.dumps(scenario,indent=2))
    with Runtime(scenario,consent=False) as rt,sync_playwright() as pw:
        o=next(iter(rt.offers.values()));sid=o['retailer_id']
        browser=pw.chromium.launch(headless=True)
        try:
            page=browser.new_page();cdp=page.context.new_cdp_session(page);page.goto(rt.origins[sid]+'/products/'+o['product_id'])
            section=page.locator('#store-stock')
            assert not section.locator('article').first.is_visible()
            (out/'collapsed.ax.json').write_text(json.dumps(cdp.send('Accessibility.getFullAXTree'),indent=2))
            section.locator('summary').click()
            assert section.locator('article').first.is_visible()
            (out/'expanded.ax.json').write_text(json.dumps(cdp.send('Accessibility.getFullAXTree'),indent=2))
            page.screenshot(path=str(out/'expanded.png'))
            assert section.get_by_text('Ships online orders: '+('Yes' if enabled else 'No'),exact=False).count()>0
            section.get_by_role('link',name='Check pickup at',exact=False).first.click()
            assert page.locator('#offer-quote strong').inner_text()=='Available'
            page.get_by_label('Quantity',exact=True).fill('100')
            page.get_by_role('button',name='Calculate quote',exact=True).click()
            assert page.locator('#offer-quote strong').inner_text()=='Unavailable'
            (out/'quantity.ax.json').write_text(json.dumps(cdp.send('Accessibility.getFullAXTree'),indent=2))
            row={'passed':True,'branch_shipping':bool(enabled),'offer_id':o['offer_id'],'model_calls':0}
            (out/'journal.private.json').write_text(json.dumps(rt.snapshot(),indent=2))
        finally:browser.close()
    return row


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    files=[Path(__file__),*Path('environments/connected_shopping').glob('*.py'),*Path('environments/product_world').glob('*.py')]
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(lambda e:case(e,a.output/str(e)),[0,1]))
    changed=[str(p) for p in files if before[str(p)]!=hashlib.sha256(p.read_bytes()).hexdigest()]
    report={'passed':all(r['passed'] for r in rows),'cases':rows,'model_calls':0,'source_sha256':before,'source_changes_during_validation':changed,'scope':'Native Chromium/Playwright AX, not harness policy delivery'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':report['passed'],'source_changes':changed}))
if __name__=='__main__':main()
