"""Sequential foreground test: native OS focus is a shared desktop resource.

No model, external websites, synthetic OS keystrokes or clicks in user windows.
"""
import argparse
import base64
import json
import subprocess
import time
import threading
from playwright.sync_api import sync_playwright
from intent_browser.human_handover import HumanHandoverController
from intent_browser.human_handover_ui import HumanHandoverUI
from pathlib import Path
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.windows_browser import WindowsChrome
from intent_browser.windows_layout import load_layout

MONITOR = r'''
$ProgressPreference='SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;using System.Collections.Generic;using System.Runtime.InteropServices;
public class FocusMonitor {
 public delegate void Callback(IntPtr hook,uint evt,IntPtr hwnd,int id,int child,uint tid,uint time);
 [DllImport("user32.dll")] static extern IntPtr SetWinEventHook(uint lo,uint hi,IntPtr lib,Callback cb,uint pid,uint tid,uint flags);
 [DllImport("user32.dll")] static extern bool UnhookWinEvent(IntPtr hook);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 public static List<long> Events=new List<long>();
 public static Callback Handler=(hook,evt,hwnd,id,child,tid,time)=>{Events.Add(hwnd.ToInt64());};
 public static IntPtr Start(){return SetWinEventHook(3,3,IntPtr.Zero,Handler,0,0,0);}
 public static void Stop(IntPtr h){UnhookWinEvent(h);}
}
'@
$hook=[FocusMonitor]::Start()
if($hook -eq [IntPtr]::Zero) {throw 'Focus monitor failed'}
@{ready=$true;initial=[FocusMonitor]::GetForegroundWindow().ToInt64()} | ConvertTo-Json -Compress
$timer=[Diagnostics.Stopwatch]::StartNew()
while($timer.Elapsed.TotalSeconds -lt 40) {[System.Windows.Forms.Application]::DoEvents();Start-Sleep -Milliseconds 10}
[FocusMonitor]::Stop($hook)
@{events=@([FocusMonitor]::Events);final=[FocusMonitor]::GetForegroundWindow().ToInt64()} | ConvertTo-Json -Compress
'''

class Fixture(OpenEndedTask):
 def setup(self,page):
  page.set_content('<title>Quiet launch fixture</title><label>Name<input autofocus></label><button onclick="document.querySelector(\'p\').textContent=\'Saved\'">Save</button><p>Ready</p>')
  return 'Local focus fixture',{}

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--port',type=int,required=True);args=p.parse_args()
 out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
 encoded=base64.b64encode(MONITOR.encode('utf-16-le')).decode()
 monitor=subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 ready=json.loads(monitor.stdout.readline().lstrip('\ufeff'));assert ready['ready']
 chrome=None;env=None
 try:
  chrome=WindowsChrome(out,args.port,layout=load_layout())
  with chrome.bind_environment():
   env=BrowserEnv(task_entrypoint=Fixture,task_kwargs={'start_url':'about:blank','goal':'Fixture'},headless=False,wait_for_user_message=False)
   obs,_=env.reset()
   assert chrome.startup_cleanup.pages==[],chrome.startup_cleanup.results
   assert chrome.chat_chrome.startup_cleanup.pages==[]
   assert env.chat.browser is not env.browser
   env.page.get_by_role('textbox',name='Name').fill('Agent input')
   env.page.get_by_role('button',name='Save').click()
   assert env.page.locator('p').inner_text()=='Saved'
   assert env.page.locator('input').input_value()=='Agent input'
   assert env.page.screenshot()
   env.chat.page.evaluate("send_user_message('Local callback check')")
   assert env.chat.messages[-1]['message']=='Local callback check'
   controller=HumanHandoverController()
   controller.register('fixture',title='Local verification',url='about:blank')
   controller.handover('fixture','Local UI test')
   with HumanHandoverUI(controller) as ui:
    ui.attach_chat(env.chat.page)
    env.chat.page.get_by_role('button',name='Start helping',exact=True).wait_for(timeout=10000)
    done=threading.Event();errors=[]
    def human():
     try:
      with sync_playwright() as pw:
       client=pw.chromium.connect_over_cdp(chrome.chat_chrome.endpoint)
       try:
        pages=[page for ctx in client.contexts for page in ctx.pages]
        assert len(pages)==1
        pages[0].get_by_role('button',name='Start helping',exact=True).click()
        pages[0].get_by_role('button',name='Finished',exact=True).click()
        pages[0].get_by_text('Waiting for fresh inspection by the agent.',exact=True).wait_for()
       finally:client.close()
     except Exception as exc:errors.append(str(exc))
     finally:done.set()
    thread=threading.Thread(target=human,daemon=True);thread.start()
    assert done.wait(20),'Handover controls require owner-thread callbacks'
    thread.join();assert not errors,errors
    assert controller.snapshot()['tabs'][0]['state']=='returned'
    assert env.chat.messages[-1]['message']=='Local callback check'
   # A second page uses the same background creation path. No bring_to_front.
   tab=env.context.new_page();tab.set_content('<title>Second local tab</title><input>')
   tab.locator('input').fill('second');assert tab.locator('input').input_value()=='second';tab.close()
   assert len(chrome.layout_results)==2 and all(r['placed'] for r in chrome.layout_results),chrome.layout_results
   handles={r['hwnd'] for r in chrome.layout_results}
   assert len(handles)==2
   assert 'BrowserAgentLayout-' not in json.dumps(obs.get('axtree_object',{}))
   # Monitor stays live through close too; collect afterward. No polling the page.
   env.close();env=None
   chrome.close()
   stdout,stderr=monitor.communicate(timeout=45)
   assert monitor.returncode==0,stderr
   observed=json.loads(stdout.strip());assert not handles.intersection(observed['events']),observed
   report={'passed':True,'model_calls':0,'initial_focus':ready['initial'],'monitor':observed,
           'owned_window_handles':sorted(handles),'layout':chrome.layout_results,
           'checks':['no_startup_windows','no_owned_foreground_events','fill_click_autofocus','screenshot','separate_native_chat_browser','chat_callback','handover_controls_while_owner_blocked','new_background_tab','layout','no_marker_in_AX']}
   (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
 finally:
  if env is not None:env.close()
  if chrome is not None:chrome.close()
  if monitor.poll() is None:monitor.terminate();monitor.wait()

if __name__=='__main__':main()
