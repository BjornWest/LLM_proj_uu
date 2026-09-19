"""Isolated browser checks: no shared state or upstream build changes."""
import argparse,json,os,hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright
from intent_browser.tricky import FixtureServer
ROOT=Path(__file__).resolve().parents[4]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
 server=FixtureServer(ROOT/'.local/tricky-full-v1');evidence={};contexts=[]
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True)
   def page_for(site):
    ctx=browser.new_context();contexts.append(ctx);ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(server.origin+'/') else r.abort());page=ctx.new_page();page.goto(server.origin+'/sites/tricky/'+site);page.wait_for_function("document.querySelector('#root').innerText.length>50");return page
   def save(name,page):
    text=page.locator('body').inner_text();(args.output/(name+'.txt')).write_text(text);page.screenshot(path=str(args.output/(name+'.png')),full_page=True);return text
   for site in ['shop','health','spotify','news']:
    page=page_for(site);text=save(site+'-home',page);evidence[site]={'home_loaded':len(text)>50,'full_site_revision':page.locator('meta[name="intent-site-revision"]').get_attribute('content'),'links':[r for r in page.locator('a').evaluate_all('(es)=>es.map(e=>({text:e.innerText,href:e.getAttribute("href")}))')]}
   page=page_for('health');page.locator('a[href$="/appointments"]').click();before=save('health-before-cancel',page)
   page.locator('#cancel-appointment-app1').click();after=save('health-after-cancel',page)
   page.locator('a[href$="/dashboard"]').click();dashboard=save('health-dashboard-after-cancel',page)
   fresh=page_for('health');fresh.locator('a[href$="/appointments"]').click();fresh_text=save('health-fresh-context',fresh)
   evidence['health']['cancellation_defect']={'precondition_app1': '10:00 AM' in before,'appointments_removed_app1':'10:00 AM' not in after,'dashboard_still_shows_app1':'10:00 AM' in dashboard,'fresh_context_restores_app1':'10:00 AM' in fresh_text,'status':'confirmed_cross_page_inconsistency'}
   # The original clean cancellation flow has no privacy drawer. Do not invent one.
   evidence['health']['clean_privacy_dialog_present']=page.get_by_text('Data Privacy & Settings',exact=True).count()>0
   response=page.request.get(server.origin+'/downloads/blood_test.pdf');evidence['health']['missing_pdf_status']=response.status
   music=page_for('spotify');media_responses=[];media_failures=[];music.on('response',lambda r:media_responses.append({'url':r.url,'status':r.status,'resource_type':r.request.resource_type}) if r.request.resource_type=='media' else None);music.on('requestfailed',lambda r:media_failures.append({'url':r.url,'failure':r.failure,'resource_type':r.resource_type}) if r.resource_type=='media' else None);music.locator('a[href$="/spotify/search"]').click();music.locator('#play-button-3').click();music.wait_for_timeout(500);save('music-after-play-request',music)
   evidence['spotify']['audio_after_play_request']=music.locator('audio').evaluate_all('(es)=>es.map(a=>({src:a.currentSrc,paused:a.paused,readyState:a.readyState,error:a.error?{code:a.error.code,message:a.error.message}:null}))')
   evidence['spotify']['media_responses']=media_responses
   evidence['spotify']['media_failures']=media_failures
   evidence['spotify']['audio_available']=None # Audio objects are detached; absence of DOM audio is not playback evidence.
   evidence['spotify']['requested_media_unavailable']=any(r['status']==404 and r['url'].endswith('.missing') for r in media_responses)
   shop=page_for('shop');shop.get_by_placeholder('Search for products').fill('Dell Inspiron 15');shop.locator('#add_to_cart_24').click();shop.wait_for_timeout(100);draft=shop.evaluate("()=>JSON.parse(localStorage.getItem('cart'))")
   fresh_shop=page_for('shop');fresh_cart=fresh_shop.evaluate("()=>JSON.parse(localStorage.getItem('cart'))")
   evidence['shop']['fresh_context_isolation']={'first_cart_items':len(draft),'fresh_cart_items':len(fresh_cart),'passed':len(draft)>0 and fresh_cart==[]}
   for ctx in contexts:ctx.close()
   browser.close()
 finally:server.close()
 checks={'all_four_homepages_loaded':all(evidence[s]['home_loaded'] for s in ['shop','health','spotify','news']),'one_pinned_site_revision':len({evidence[s]['full_site_revision'] for s in ['shop','health','spotify','news']})==1,'health_state_mismatch_reproduced':all(evidence['health']['cancellation_defect'][k] for k in ['precondition_app1','appointments_removed_app1','dashboard_still_shows_app1','fresh_context_restores_app1']),'shop_context_reset_verified':evidence['shop']['fresh_context_isolation']['passed'],'missing_pdf_confirmed':evidence['health']['missing_pdf_status']==404,'missing_audio_confirmed':evidence['spotify']['requested_media_unavailable']}
 report={'schema_version':1,'checks':checks,'all_diagnostic_checks_pass':all(checks.values()),'site_ready_for_all_original_tasks':False,'model_calls':0,'evidence':evidence,'source_sha256':{str(Path(__file__).relative_to(ROOT)):sha(Path(__file__)), 'environments/tricky_full/build-record.json':sha(ROOT/'environments/tricky_full/build-record.json')},'artifact_sha256':{f.name:sha(f) for f in args.output.iterdir() if f.is_file()}}
 (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(checks,indent=2))
 if not all(checks.values()):raise SystemExit(1)
if __name__=='__main__':main()
