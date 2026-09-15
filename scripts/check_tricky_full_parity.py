"""Compare actual BrowserGym page content/state with authenticated client rendering."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
from intent_browser.runner import run_episode
from intent_browser.backend import Completion
from intent_browser.actions import make_action_set
from intent_browser.tricky import TrickyTask
from intent_browser.tricky_privacy import PrivacyTask
from intent_browser.tricky_membership import MembershipTask
ROOT=Path(__file__).resolve().parents[1]
class Driver:
 def __init__(self,t,env,page,base,paths,checks):self.t=t;self.env=env;self.page=None;self.base=base;self.paths=list(paths);self.checks=checks
 def complete(self,messages):
  if not self.paths:return Completion("send_msg_to_user('Scripted parity check complete')",{'source':'privileged-parity'})
  route=self.paths.pop(0);native=self.env['env'].unwrapped.page
  if self.page is None:
   ctx=native.context.browser.new_context(viewport={'width':1280,'height':720});assert ctx.request.post(self.base+'/login',headers={'Origin':self.base},data={'code':'offline-interactive-code-'*3}).ok;self.page=ctx.new_page()
  self.t.trace.event('fixture_control',operation='paired-native-and-client-navigation',route=route)
  native.goto(self.t.server.origin+'/sites/tricky'+route);self.page.goto(self.base+'/sites/tricky'+route)
  for p in (native,self.page):p.wait_for_function('!!window.__fullSnapshot');p.wait_for_timeout(250)
  a=native.locator('#root').inner_text();b=self.page.locator('#root').inner_text()
  sa=native.evaluate('window.__fullSnapshot()');sb=self.page.evaluate('window.__fullSnapshot()');sa.pop('url');sb.pop('url')
  record={'route':route,'same_visible_text':a==b,'same_public_state':sa==sb,'site_revision':sa['site_revision'],'native_text_sha256':hashlib.sha256(a.encode()).hexdigest(),'client_text_sha256':hashlib.sha256(b.encode()).hexdigest()}
  self.checks.append(record);assert a==b and sa==sb,record
  return Completion('noop()',{'source':'privileged-parity'})
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 server=subprocess.Popen(['node','tests/interactive-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True);origin='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port']);checks=[];rows=[]
 try:
  for cls,paths in [(PrivacyTask,['/health','/health/medical-records','/health/appointments','/health/dashboard','/health/lab-results','/health/messages','/health/doctor/d1']), (MembershipTask,['/spotify','/spotify/search','/spotify/artists','/spotify/artist/1','/spotify/playlists','/spotify/podcasts','/spotify/membership']), (TrickyTask,['/shop','/shop/cart'])]:
   t=cls(condition='no_added_injection',build_dir=ROOT/'.local/tricky-full-v1');env={}
   def factory(video):env['env']=t.make_env(video,action_mapping=make_action_set().to_python_code,headless=True);return env['env']
   try:
    folder,result=run_episode(factory,Driver(t,env,None,origin,paths,checks),{'task':'complete-site-native-client-parity','driver':'privileged-parity','model':None},output=ROOT/'runs',max_steps=10,episode_task=t)
    rows.append({'trace':str(folder.relative_to(ROOT)),'error':result['error'],'checks':checks.copy()});assert result['error'] is None
   finally:t.close()
  (a.output/'report.json').write_text(json.dumps({'passed':all(c['same_visible_text'] and c['same_public_state'] for c in checks),'checks':checks,'traces':rows,'model_calls':0},indent=2))
 finally:server.terminate();server.wait(timeout=10)
if __name__=='__main__':main()
