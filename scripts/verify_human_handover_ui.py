"""Local panel controls only; does not certify shared-runner tab concurrency."""
import argparse,json,hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright
from intent_browser.human_handover import HumanHandoverController
from intent_browser.human_handover_ui import HumanHandoverUI


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    c=HumanHandoverController(journal_path=a.output/'human-transitions.jsonl')
    c.register('tab-challenge',title='Store verification',url='https://shop.example/challenge')
    c.register('tab-research',title='Other retailer',url='https://other.example/search?q=headphones')
    c.handover('tab-challenge','Please complete the verification in this tab. Research can continue in the other tab.')
    with HumanHandoverUI(c) as ui,sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1200,'height':900});page.goto(ui.origin)
        page.get_by_role('button',name='Start helping',exact=True).click()
        page.get_by_role('button',name='Finished',exact=True).wait_for()
        assert c.snapshot()['tabs'][0]['state']=='human_active'
        c.register('tab-research',title='Other retailer results',url='https://other.example/results')
        assert c.snapshot()['tabs'][1]['state']=='agent_controlled'
        page.get_by_role('heading',name='Other retailer results',exact=True).wait_for()
        page.screenshot(path=str(a.output/'human-active.png'),full_page=True)
        page.get_by_role('button',name='Finished',exact=True).click()
        page.get_by_text('Waiting for the agent to inspect fresh page state.',exact=True).wait_for()
        assert c.snapshot()['tabs'][0]['state']=='returned'
        c.resume('tab-challenge');c.handover('tab-challenge','Second explicit help request')
        page.get_by_role('button',name='Cancel handover',exact=True).wait_for();page.get_by_role('button',name='Cancel handover',exact=True).click()
        page.get_by_text('Waiting for the agent to inspect fresh page state.',exact=True).wait_for()
        assert c.snapshot()['tabs'][0]['state']=='returned'
        browser.close()
    events=c.drain();assert len([x for x in events if x['event']=='complete'])==1
    sources=['intent_browser/human_handover.py','intent_browser/human_handover_ui.py',__file__]
    result={'passed':True,'scope':'native panel clicks and pure controller transitions; no agent browser concurrency claim',
        'model_calls':0,'transitions':len(events),'sources':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources}}
    (a.output/'report.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
