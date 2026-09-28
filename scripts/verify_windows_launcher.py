"""Local Windows/WSLg fixture only; no model or external site calls."""
import argparse
import json
from unittest.mock import patch
from contextlib import nullcontext
from pathlib import Path
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.windows_browser import WindowsChrome, StartupCleanup
from intent_browser.windows_layout import load_layout

class Fixture(OpenEndedTask):
    def setup(self,page):
        page.set_content('<title>Launcher local fixture</title><label>Name<input></label><button onclick="document.querySelector(\'p\').textContent=\'Saved\'">Save</button><p>Ready</p>')
        return 'Local fixture',{}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--port',type=int,required=True);parser.add_argument('--layout',action='store_true');parser.add_argument('--preserve-startup',action='store_true')
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    chrome=WindowsChrome(out,args.port,headless=not args.layout,layout=load_layout() if args.layout else {})
    env=None
    class ModifiedStartup(StartupCleanup):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.pages[0].set_content('<title>User note</title><p>Keep this page</p>')
    test_patch = patch('intent_browser.windows_browser.StartupCleanup', ModifiedStartup) if args.preserve_startup else nullcontext()
    try:
        with test_patch, chrome.bind_environment():
            env=BrowserEnv(task_entrypoint=Fixture,task_kwargs={'start_url':'about:blank','goal':'Fixture'},headless=not args.layout,wait_for_user_message=False)
            obs,info=env.reset()
            assert chrome.startup_cleanup.attempted
            expected='retained_content' if args.preserve_startup else 'closed_unused_startup'
            assert all(r['outcome']==expected for r in chrome.startup_cleanup.results),chrome.startup_cleanup.results
            if args.preserve_startup:
                assert chrome.startup_cleanup.pages[0].locator('p').inner_text()=='Keep this page'
            assert not env.page.is_closed() and not env.chat.page.is_closed()
            assert env.page.context != env.chat.context
            env.page.get_by_role('textbox',name='Name').fill('Test')
            env.page.get_by_role('button',name='Save').click()
            assert env.page.locator('p').inner_text()=='Saved'
            assert env.page.title()=='Launcher local fixture'
            assert 'BrowserAgentLayout-' not in env.chat.page.title()
            assert 'BrowserAgentLayout-' not in json.dumps(obs.get('axtree_object',{}))
            assert env.page.screenshot()
            if args.layout:
                assert len(chrome.layout_results)==2,chrome.layout_results
                assert all(r['placed'] for r in chrome.layout_results),chrome.layout_results
                assert all(r['actual']==r['requested'] for r in chrome.layout_results),chrome.layout_results
            (out/'report.json').write_text(json.dumps({'passed':True,'model_calls':0,'layout':chrome.layout_results,'cleanup':chrome.startup_cleanup.results,'checks':[expected,'task_and_chat_open','distinct_contexts','fill_click','screenshot','titles_restored','no_layout_marker_in_AX']},indent=2))
    finally:
        if env is not None:env.close()
        chrome.close()

if __name__=='__main__':main()
