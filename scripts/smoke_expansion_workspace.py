"""Frozen 203-objective catalog in actual workspace; no jobs, model calls or setup."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--origin',help='Read-only verification of an authenticated deployed workspace');args=parser.parse_args()
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
 out=ROOT/'.local/vercel-demo'/('expansion-ui-'+uuid4().hex[:8]);out.mkdir(parents=True)
 source=ROOT/'data/curation/expansion/hosted-review-catalog.json';catalog=json.loads(source.read_text());checks=[]
 def check(name,value):
  assert value,name
  checks.append(name);print('PASS',name,flush=True)
 process=None
 if args.origin:
  origin=args.origin.rstrip('/');invitation=json.loads((ROOT/'.local/vercel-demo/invitation-codes.json').read_text())['bjorn'];code=invitation if isinstance(invitation,str) else invitation['code']
 else:
  process=subprocess.Popen(['node','tests/catalog-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True)
  origin='http://127.0.0.1:'+str(json.loads(process.stdout.readline())['port']);code='offline-catalog-code-'*3
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch();context=browser.new_context(viewport={'width':1512,'height':1040});page=context.new_page();errors=[];writes=[]
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:writes.append(r.url) if r.method not in ['GET','HEAD','OPTIONS'] else None)
   check('Catalog requires an invitation',page.request.get(origin+'/api/task-catalog').status==401)
   page.goto(origin);page.get_by_label('Your invitation code').fill(code);page.get_by_role('button',name='Open demo').click();expect(page.locator('#site-count')).to_have_text('9',timeout=30000);writes.clear()
   check('Served contract exactly matches frozen 203-task catalog',page.request.get(origin+'/api/task-catalog').json()==catalog and len(catalog['tasks'])==203)
   rendered={}
   for site in catalog['sites']:
    expected={task['id']:task['goal'] for task in catalog['tasks'] if task['site_id']==site['id']}
    badge=page.locator('.site-choice[data-site="'+site['id']+'"] .site-task-count');expect(badge).to_have_text(str(len(expected))+' tasks')
    page.locator('.site-choice[data-site="'+site['id']+'"]').click();page.locator('#research-tab').click();expect(page.locator('#catalog-heading')).to_contain_text(str(len(expected)))
    while page.locator('#catalog-more').is_visible():page.locator('#catalog-more').click()
    cards=page.locator('#catalog-cards [data-catalog-task]');actual={card.get_attribute('data-catalog-task'):card.locator('.catalog-goal').text_content() for card in cards.all()};rendered.update(actual)
    check(site['id']+' displays exact objectives and expected count',actual==expected)
    first=next(task for task in catalog['tasks'] if task['site_id']==site['id']);page.locator('#catalog-search').fill(first['id']);expect(cards).to_have_count(1);cards.locator('button').click();expect(page.locator('#catalog-dialog-goal')).to_have_text(first['goal']);check(site['id']+' review has no agent launch control',page.locator('#catalog-dialog #try-task').count()==0 and 'launch unavailable' in page.locator('#catalog-dialog').inner_text())
    if site['client_url']:check(site['id']+' offers exact complete-site link',page.locator('#catalog-dialog-browse a').get_attribute('href')==site['client_url'])
    else:
     browse=page.locator('#catalog-dialog-browse button');check(site['id']+' bridge status is separate from objective visibility',browse.inner_text()==('Remote browsing unavailable' if browse.is_disabled() else 'Open remote site controls →'))
    page.get_by_role('button',name='Close review objective').click();page.locator('#catalog-search').fill('')
   check('All 203 distinct exact IDs/goals are reachable',rendered=={task['id']:task['goal'] for task in catalog['tasks']})
   page.locator('.site-choice[data-site=webarena-shopping]').click();page.locator('#research-tab').click();page.locator('#catalog-search').fill('webarena:516');page.locator('#catalog-cards button').click()
   deictic=next(task for task in catalog['tasks'] if task['id']=='webarena:516');check('Product-specific starting path preserved without claiming setup',deictic['start_path'] in page.locator('#catalog-dialog-facts').inner_text() and 'does not apply' in page.locator('#catalog-dialog-scope').inner_text());page.get_by_role('button',name='Close review objective').click()
   page.locator('.site-choice[data-site=tricky-shop]').click();page.locator('#research-tab').click();expect(page.locator('.site-choice[data-site=tricky-shop] .site-worker-count')).to_have_text('+ 2 worker tasks');expect(page.locator('#task-cards button')).to_have_count(2);check('Original worker selectors remain separate from 42 review tasks',True)
   page.locator('#catalog-origin').select_option('project_authored');page.locator('#catalog-kind').select_option('answer');expected=[task for task in catalog['tasks'] if task['site_id']=='tricky-shop' and task['origin']=='project_authored' and task['kind']=='answer'];expect(page.locator('#catalog-cards article')).to_have_count(min(len(expected),24));check('Origin and kind filters combine over full catalog',True)
   page.locator('#catalog-origin').select_option('all');page.locator('#catalog-kind').select_option('all');page.screenshot(path=str(out/'desktop.png'),full_page=True)
   page.set_viewport_size({'width':390,'height':844});check('Nine-site catalog fits mobile width',page.evaluate('document.documentElement.scrollWidth<=innerWidth'));page.screenshot(path=str(out/'mobile.png'),full_page=True)
   page.goto(origin+'/workspace?site=tricky-news&view=research');expect(page.locator('#catalog-heading')).to_contain_text('20 review objectives');check('Catalog-only site restores from direct link',page.locator('#site-name').inner_text()=='Tricky news')
   news=context.new_page();news.goto(origin+'/sites/tricky/news');expect(news.locator('#inspection-toolbar strong')).to_contain_text('News');check('News toolbar and workspace link identify news',news.locator('#inspection-toolbar a').get_attribute('href')=='/workspace?site=tricky-news');news.get_by_role('button',name='Start fresh',exact=True).click();news.wait_for_url('**/sites/tricky/news');expect(news.locator('#inspection-toolbar strong')).to_contain_text('News');news.close()
   if not args.origin:
    page.route('**/api/task-catalog',lambda route:route.fulfill(status=503,json={'error':'Fixture catalog offline'}),times=1);page.reload();expect(page.locator('#catalog-retry')).to_be_visible();page.locator('#catalog-retry').click();expect(page.locator('#catalog-heading')).to_contain_text('20 review objectives');check('Catalog outage has explicit retry without losing existing task flow',True)
    stats=page.request.get(origin+'/__fixture/stats').json();check('Fixture records no jobs, actions or model calls',stats=={'writes':0,'model_calls':0})
   check('Review issues no job, action or model requests',not writes);check('No browser script errors',not errors);browser.close()
  (out/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'origin':origin,'catalog_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'paid_calls':0,'scope':('Deployed authenticated UI' if args.origin else 'Actual workspace and invitation handler, frozen catalog endpoint fixture')+'; remote WebArena bridge not exercised','sources':{name:hashlib.sha256((ROOT/'deploy/daylight/client'/name).read_bytes()).hexdigest() for name in ['workspace.js','workspace.html','workspace.css','inspection.js']}},indent=2));print(json.dumps({'checks':len(checks),'report':str(out/'report.json')}))
 finally:
  if process:process.terminate();process.wait(timeout=10)
if __name__=='__main__':main()
