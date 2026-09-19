"""Read-only fresh-context probe of the complete pinned existing site build."""
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from intent_browser.tricky import FixtureServer
ROOT=Path(__file__).resolve().parents[4]
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
server=FixtureServer(ROOT/'.local/tricky-full-v1')
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  for site in ['shop','health','spotify','news']:
   ctx=browser.new_context();page=ctx.new_page();page.goto(server.origin+'/sites/tricky/'+site);page.wait_for_timeout(900)
   (out/(site+'.txt')).write_text(page.locator('body').inner_text())
   (out/(site+'-links.json')).write_text(json.dumps(page.locator('a').evaluate_all('(els)=>els.map(e=>({text:e.innerText,href:e.getAttribute("href"),id:e.id}))'),indent=2))
   page.screenshot(path=str(out/(site+'.png')),full_page=True);ctx.close()
  browser.close()
finally:server.close()
