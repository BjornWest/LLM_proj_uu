"""Native account/coupon/tracking/cancellation journeys; no model calls."""
import argparse,json,hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright
from environments.connected_shopping.test_accounts import account_scenario
from environments.connected_shopping.runtime import Runtime
from environments.product_world.accounts import generate_accounts
from environments.product_world.account_tasks import sample_account_task,reference_account_task,check_account_task


def case(kind,out):
    out.mkdir();scenario=account_scenario();sid='store-001'
    if kind=='shipped':
        scenario['accounts']=generate_accounts(scenario['bundle'],config={'signed_in_probability':1,'order_status_weights':{'processing':0,'shipped':1,'delivered':0,'cancelled':0}})
    if kind=='signed-out':scenario['accounts']['accounts'][0]['signed_in']=False
    (out/'scenario.private.json').write_text(json.dumps(scenario,indent=2))
    account=scenario['accounts']['accounts'][0];oid=account['orders'][0]['order_id']
    task=sample_account_task(scenario['bundle'],scenario['accounts'],operation='cancel' if kind=='processing' else 'track',retailer_id=sid,order_id=oid)
    with Runtime(scenario,consent=False) as rt,sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);page=browser.new_page();cdp=page.context.new_cdp_session(page)
        page.set_default_timeout(10000)
        def capture(name):
            (out/(name+'.ax.json')).write_text(json.dumps(cdp.send('Accessibility.getFullAXTree'),indent=2))
            (out/(name+'.html')).write_text(page.content());page.screenshot(path=str(out/(name+'.png')))
        try:
            page.goto(rt.origins[sid]);page.get_by_role('link',name='Account (signed out)' if kind=='signed-out' else 'My account',exact=True).click()
            if kind=='signed-out':
                assert page.get_by_text('You are not signed in',exact=False).is_visible()
                assert oid not in page.content()
                page.goto(rt.origins[sid]+'/account/orders/'+oid)
                assert oid not in page.locator('body').inner_text()
                capture('signed-out');assert not rt.snapshot()['commerce_mutations']
            else:
                page.get_by_role('link',name='Orders',exact=True).click()
                page.get_by_role('link',name='Order '+oid,exact=True).click()
                assert page.locator('#order-status').inner_text()=='Status: '+kind
                capture('tracking')
                if kind=='processing':
                    page.get_by_role('link',name='Cancel order',exact=True).click()
                    assert not rt.snapshot()['commerce_mutations']
                    page.get_by_role('link',name='Keep order',exact=True).click()
                    assert page.locator('#order-status').inner_text()=='Status: processing'
                    page.get_by_role('link',name='Cancel order',exact=True).click()
                    page.get_by_role('button',name='Confirm cancellation',exact=True).click()
                    assert page.locator('#order-status').inner_text()=='Status: cancelled'
                    capture('cancelled');assert len(rt.snapshot()['commerce_mutations'])==1
                    page.reload();assert len(rt.snapshot()['commerce_mutations'])==1
                    # Discover a coupon then apply it through public quote controls.
                    page.get_by_role('link',name='My account',exact=True).click()
                    page.get_by_role('link',name='Coupons',exact=True).click()
                    code=page.locator('main article h2').first.inner_text();capture('coupons')
                    offer=next(o for o in rt.offers.values() if o['retailer_id']==sid)
                    page.goto(rt.origins[sid]+'/products/'+offer['product_id'])
                    page.get_by_role('link',name='Check delivery total and arrival',exact=True).click()
                    page.get_by_label('Coupon code',exact=True).fill(code)
                    page.get_by_role('button',name='Calculate quote',exact=True).click()
                    expected=rt.account_pages.session.quote(rt.quote(offer['offer_id']),code)
                    assert page.locator('#delivered-total').inner_text()==f"{expected['total_minor']/100:.2f} SEK"
                    assert expected['discount_minor']>0;capture('discounted-quote')
                else:
                    assert page.get_by_role('link',name='Cancel order',exact=True).count()==0
                    assert 'Parcel dispatched' in page.locator('body').inner_text()
                    assert not rt.snapshot()['commerce_mutations']
            (out/'journal.private.json').write_text(json.dumps(rt.snapshot(),indent=2))
            reference=reference_account_task(scenario['bundle'],scenario['accounts'],task)
            grade=check_account_task(scenario['bundle'],scenario['accounts'],task,reference['answer'],rt.account_pages.session.snapshot())
            assert grade['success']
            (out/'scripted-task-check.private.json').write_text(json.dumps({'task':task,'reference_answer':reference['answer'],'evaluation':grade,'scope':'Reference structured answer supplied by driver, not a model-extracted natural response; checks native resulting state'},indent=2))
            return {'case':kind,'passed':True,'model_calls':0,'scripted_state_and_answer_check':grade}
        except Exception as exc:
            capture('failure');(out/'error.txt').write_text(repr(exc));raise
        finally:browser.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    files=[Path(__file__),*Path('environments/connected_shopping').glob('*.py'),*Path('environments/product_world').glob('*.py')]
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(lambda k:case(k,a.output/k),['processing','shipped','signed-out']))
    changed=[str(p) for p in files if before[str(p)]!=hashlib.sha256(p.read_bytes()).hexdigest()]
    report={'passed':all(r['passed'] for r in rows),'cases':rows,'model_calls':0,'source_sha256':before,'source_changes_during_validation':changed,'scope':'Native Chromium actions and raw AX; no model policy-delivery or grading claim'}
    report['artifact_sha256']={str(p.relative_to(a.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.rglob('*') if p.is_file()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':report['passed'],'source_changes':changed}))
if __name__=='__main__':main()
