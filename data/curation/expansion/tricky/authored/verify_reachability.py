"""Fresh-context site rehearsals only. Not BrowserGym/native profile acceptance."""
import argparse,hashlib,json,os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from intent_browser.tricky import FixtureServer
from data.curation.expansion.tricky.authored.solver import plan
from data.curation.expansion.tricky.authored.grader import grade
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def snapshot(page):
 page.evaluate('()=>window.__fullDrain()')
 state=page.evaluate('()=>({...window.__fullSnapshot(),personalizedArticles:JSON.parse(localStorage.getItem("personalizedArticles")||"[]")})');state['path']=urlparse(page.url).path;return state

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--task',action='append');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
 data=json.loads((HERE/'contracts.json').read_text());source={str(p.relative_to(ROOT)):sha(p) for p in HERE.glob('*.py')};source[str((HERE/'contracts.json').relative_to(ROOT))]=sha(HERE/'contracts.json')
 for name,pin in data['source_sha256'].items():assert sha(ROOT/'.local/tricky-full-v1/upstream'/name)==pin
 server=FixtureServer(ROOT/'.local/tricky-full-v1');rows=[]
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True)
   for task in data['tasks']:
    if a.task and task['id'] not in a.task:continue
    for negative in [False,True]:
     case='negative' if negative else 'positive';out=a.output/(task['id']+'-'+case);out.mkdir();context=browser.new_context();events=[];page=None;error=None;answer=None;actions=[];evaluation=None
     try:
      context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(server.origin+'/') else r.abort())
      context.expose_binding('__authoredCapture',lambda source,event:events.append(event));context.add_init_script('window.__intentEmit=(kind,payload)=>window.__authoredCapture({kind,payload,url:location.href});')
      page=context.new_page();page.set_default_timeout(4000);page.goto(server.origin+'/sites/tricky/'+task['site']);page.get_by_text('Scratchpad',exact=True).wait_for(timeout=5000)
      initial=snapshot(page);(out/'initial-state.json').write_text(json.dumps(initial,indent=2))
      for i,action in enumerate(plan(task,page,negative)):
       actions.append(action);(out/f'observed-{i:03}.txt').write_text(page.locator('body').inner_text())
       if action['action']=='finish':answer=action['answer'];break
       locator=page.locator(action['selector']).last
       if action['action']=='click':locator.click(timeout=4000)
       elif action['action']=='fill':locator.fill(action['text'],timeout=4000)
       elif action['action']=='press':locator.press(action['text'],timeout=4000)
       page.wait_for_timeout(100)
      final=snapshot(page);evaluation=grade(task,answer,final,events)
      if task['kind'] in ['cart','bookmarks']:
       # Persistence is part of site gate, not an extra instruction to the model.
       page.reload();page.get_by_text('Scratchpad',exact=True).wait_for(timeout=5000);reloaded=snapshot(page);after_reload=grade(task,answer,reloaded,events)
       assert evaluation['task_completed']==after_reload['task_completed'],'reload changed outcome'
       (out/'reload-state.json').write_text(json.dumps(reloaded,indent=2))
      page.screenshot(path=str(out/'final.png'),full_page=True)
     except Exception as exc:error=f'{type(exc).__name__}: {exc}'
     finally:context.close()
     passed=error is None and evaluation['task_completed'] is (not negative)
     result={'task_id':task['id'],'template_id':task['template_id'],'site':task['site'],'case':case,'passed':passed,'error':error,'evaluation':evaluation,'answer':answer,'actions':actions,'events':events,'native_profile_validated':False,'model_calls':0}
     (out/'case.json').write_text(json.dumps(result,indent=2)+'\n');result['artifact_sha256']={f.name:sha(f) for f in out.iterdir() if f.is_file()};rows.append(result)
     report={'schema_version':1,'scope':'Playwright site reachability and derived outcome checks; not BrowserGym/native acceptance','model_calls':0,'native_profile_validated':False,'independent_review':False,'source_sha256':source,'source_unchanged':all(sha(ROOT/k)==v for k,v in source.items()),'passed':all(r['passed'] for r in rows),'rows':rows}
     (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(task['id'],case,passed,error,flush=True)
   browser.close()
 finally:server.close()
 if not all(r['passed'] for r in rows):raise SystemExit(1)
if __name__=='__main__':main()
