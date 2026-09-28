"""Local-browser targeted-ID lifecycle acceptance; no model or network calls."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.cdp_json import send_json,extract_json
from intent_browser.preview_bids import assign_preview_bids
from intent_browser.native_capture import CaptureBudget,capture_native
from intent_browser.trace import Trace,write_json


def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 sources=[*Path('intent_browser').glob('*.py'),Path(__file__)];hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};before=hashes()
 env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':'about:blank','goal':'Inspect only'},headless=True)
 trace=Trace(a.output/'traces',{'driver':'preview_bid_acceptance','model_calls':0});checks=[]
 def check(name,value):
  assert value,name;checks.append(name)
 def tree_and_bids():
  cdp=env.page.context.new_cdp_session(env.page)
  try:
   nodes=send_json(cdp,'Accessibility.getFullAXTree',{})['nodes']
   return nodes,assign_preview_bids(env.page,cdp,nodes)
  finally:cdp.detach()
 def full():
  budget=CaptureBudget(env.page,trace,enforce=False)
  with budget.rpc_deadline():return capture_native(env,budget,screenshots=False)
 try:
  env.reset(seed=0)
  body='''<button id="a">First</button><input aria-label="Search"><div id="shadow"></div><button id="hidden" style="visibility:hidden">Hidden</button><button id="off" style="position:absolute;top:4000px">Offscreen</button><iframe src="/child"></iframe><script>document.querySelector('#shadow').attachShadow({mode:'open'}).innerHTML='<button>Shadow</button>'</script>'''
  env.page.route('**/*',lambda r:r.fulfill(content_type='text/html',body='<button>Child</button>' if r.request.url.endswith('child') else body))
  env.page.goto('http://fixture.invalid/main')
  env.page.evaluate("let host=document.createElement('div');document.body.append(host);window.closedButton=document.createElement('button');closedButton.textContent='Closed shadow';host.attachShadow({mode:'closed'}).append(closedButton)")
  nodes,bids=tree_and_bids()
  check('fresh_document_allocates',bool(bids))
  first=env.page.locator('#a').get_attribute('bid');counter=env.page.evaluate('window.browsergym_elem_counter')
  check('offscreen_not_assigned',env.page.locator('#off').get_attribute('bid') is None)
  check('hidden_not_assigned',env.page.locator('#hidden').get_attribute('bid') is None)
  check('iframe_not_assigned',env.page.locator('iframe').get_attribute('bid') is None)
  check('child_not_touched',env.page.frames[1].locator('button').get_attribute('bid') is None)
  check('shadow_assigned',env.page.locator('#shadow button').get_attribute('bid') is not None)
  check('closed_shadow_not_assigned',env.page.evaluate("closedButton.getAttribute('bid')") is None)
  _,again=tree_and_bids();check('unchanged_reuses',bids==again and counter==env.page.evaluate('window.browsergym_elem_counter'))
  env.page.locator('input').fill('new value');tree_and_bids();check('fill_preserves_identity',first==env.page.locator('#a').get_attribute('bid'))
  env.page.evaluate("document.querySelector('#a').insertAdjacentHTML('afterend','<button id=new>New</button>')")
  tree_and_bids();new=env.page.locator('#new').get_attribute('bid');check('new_unique_id',new is not None and new!=first)
  obs=full();check('native_preserves_preview_bid',any(n.get('browsergym_id')==first and n.get('name',{}).get('value')=='First' for n in obs['axtree_object']['nodes']))
  native_ids={n.get('backendDOMNodeId'):n.get('browsergym_id') for n in obs['axtree_object']['nodes'] if n.get('browsergym_id') is not None}
  check('all_preview_ids_survive_native_including_input_and_shadow',all(native_ids.get(node)==bid for node,bid in bids.items()))
  check('native_allocates_iframe',env.page.locator('iframe').get_attribute('bid') is not None)
  check('native_child_namespaced',env.page.frames[1].locator('button').get_attribute('bid').startswith(env.page.locator('iframe').get_attribute('bid')))
  env.page.locator('#new').evaluate("e=>{const n=document.createElement('button');n.id='new';n.textContent='Replacement';e.replaceWith(n)}")
  tree_and_bids();check('replacement_new_bid',env.page.locator('#new').get_attribute('bid')!=new)
  # Preview leaves duplicates for the full-capture fence, never claims uniqueness.
  env.page.locator('#a').evaluate("e=>e.before(e.cloneNode(true))")
  full();check('native_repairs_duplicate',len(set(env.page.locator('#a').evaluate_all("es=>es.map(e=>e.getAttribute('bid'))")))==2)
  env.page.reload();check('navigation_discards_old_allocator',env.page.evaluate("typeof window.browsergym_elem_counter")=='undefined')
  tree_and_bids();check('navigation_new_document_prepares',env.page.locator('#a').get_attribute('bid') is not None)
  env.page.reload();env.page.locator('#a').evaluate("e=>e.setAttribute('bid','site-owned')")
  tree_and_bids();check('foreign_candidate_bid_not_adopted',env.page.locator('#a').get_attribute('bid')=='site-owned')
 finally:env.close();trace.finish({'stop_reason':'scripted_acceptance'})
 assert hashes()==before
 write_json(a.output/'report.json',{'passed':True,'checks':checks,'source_sha256':before,'model_calls':0})
if __name__=='__main__':main()
