"""Gate newly used unmodified controls before defining tasks; no inference."""
import argparse,hashlib,json,os
from pathlib import Path
from playwright.sync_api import sync_playwright
from data.curation.expansion.runtime_snapshot import activate
activate()
from intent_browser.tricky import FixtureServer
ROOT=Path(__file__).resolve().parents[5]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','');server=FixtureServer(ROOT/'.local/tricky-full-v1');results=[]
 try:
  with sync_playwright() as pw:
   b=pw.chromium.launch(headless=True)
   for site in ['shop','health','news','spotify']:
    c=b.new_context();c.route('**/*',lambda r:r.continue_() if r.request.url.startswith(server.origin+'/') else r.abort());page=c.new_page();page.set_default_timeout(4000);error=None;data={}
    try:
     page.goto(server.origin+'/sites/tricky/'+site);page.get_by_text('Scratchpad',exact=True).wait_for()
     if site=='shop':
      page.locator('input[placeholder="Search for products"]').fill('Bluff');page.locator('#add_to_cart_1').click();page.locator('a[href="/sites/tricky/shop/cart"]').click();i=page.locator('.ant-list-item input').first;i.fill('3');i.press('Tab');page.wait_for_timeout(100);data['input_value']=i.input_value();data['cart']=page.evaluate('()=>window.__fullSnapshot().cart');assert data['cart'][0]['quantity']==3
      page.reload();page.get_by_text('Scratchpad',exact=True).wait_for();assert page.locator('.ant-list-item input').first.input_value()=='3';data['reload_quantity']=3
     elif site=='health':
      page.locator('a[href$="/messages"]').last.click();page.locator('#new-message-input').fill('Draft only');data['draft']=page.locator('#new-message-input').input_value();data['sent_you_messages']=page.locator('#messages-content .ant-list-item-meta-title').filter(has_text='You').count();assert data['draft']=='Draft only' and data['sent_you_messages']==0
     elif site=='news':
      links=page.locator('a').evaluate_all('(xs)=>xs.map(x=>({text:x.innerText,href:x.getAttribute("href")}))');data['links']=links
      page.locator('button').filter(has_text='Set Up News Alerts').click();page.locator('input[placeholder="your.email@example.com"]').fill('reader@example.com');combo=page.get_by_role('combobox');combo.press('ArrowDown');combo.press('Home');combo.press('ArrowDown');combo.press('Enter');data['form_text']=page.locator('body').inner_text();data['email']=page.locator('input[placeholder="your.email@example.com"]').input_value();assert 'Weekly' in data['form_text']
     else:
      page.locator('a[href$="/spotify/playlists"]').click();data['titles']=page.locator('.spotify-playlists .ant-card-head-title').all_inner_texts();assert len(data['titles'])==4
     (a.output/(site+'.txt')).write_text(page.locator('body').inner_text());page.screenshot(path=str(a.output/(site+'.png')),full_page=True)
    except Exception as e:error=repr(e)
    finally:c.close()
    results.append({'site':site,'data':data,'error':error,'passed':error is None})
   b.close()
 finally:server.close()
 report={'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'model_calls':0,'site_revision':server.build['site_revision'],'results':results,'passed':all(r['passed'] for r in results)}
 (a.output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(results));raise SystemExit(0 if report['passed'] else 1)
if __name__=='__main__':main()
