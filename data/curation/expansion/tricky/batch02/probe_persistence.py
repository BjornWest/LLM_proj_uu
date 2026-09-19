"""Full-site native control diagnostics; no persistence fixes or invented pages."""
import argparse,hashlib,json,os
from pathlib import Path
from playwright.sync_api import sync_playwright
from intent_browser.tricky import FixtureServer
ROOT=Path(__file__).resolve().parents[5]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','');server=FixtureServer(ROOT/'.local/tricky-full-v1');report={}
 def save(page,name):
  text=page.locator('body').inner_text();(a.output/(name+'.txt')).write_text(text);page.screenshot(path=str(a.output/(name+'.png')),full_page=True);return text
 try:
  with sync_playwright() as p:
   b=p.chromium.launch(headless=True)
   c=b.new_context();page=c.new_page();page.goto(server.origin+'/sites/tricky/shop');page.get_by_placeholder('Search for products').fill('Dell Inspiron 15');page.locator('a[href$="/product/24"]').last.click();page.locator('#review-star-2').check();page.locator('#review-textbox').fill('Disappointing performance and poor value.');page.locator('#submit-review-button').click();before=save(page,'review-submitted');page.reload();after=save(page,'review-reloaded');report['review']={'submitted_review_visible':'Disappointing performance and poor value.' in before,'review_survives_reload':'Disappointing performance and poor value.' in after,'source_behavior':'ProductDetail.newReviews React component state only'};c.close()
   c=b.new_context();page=c.new_page();page.goto(server.origin+'/sites/tricky/spotify/search');page.locator('#add-to-playlist-6').click();page.locator('#playlist-select').click();page.get_by_text('My Favorites',exact=True).last.click();page.locator('#add-song-ok-button').click();page.locator('a[href$="/spotify/playlists"]').click();before=save(page,'playlist-added');page.reload();after=save(page,'playlist-reloaded');report['playlist']={'radioactive_visible_after_add':'Radioactive - Imagine Dragons' in before,'radioactive_survives_reload':'Radioactive - Imagine Dragons' in after,'source_behavior':'SpotifyClone.playlists React state only'};c.close();b.close()
 finally:server.close()
 sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
 report={'schema_version':1,'model_calls':0,'scripted_only':True,'task_acceptance':False,'findings':report,'source_sha256':{str(Path(__file__).relative_to(ROOT)):sha(Path(__file__))},'artifacts':{f.name:sha(f) for f in a.output.iterdir() if f.is_file()}}
 (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report['findings'],indent=2))
if __name__=='__main__':main()
