"""Assert actual Chromium replies use the fast path; no model or external calls."""
import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.cdp_json import send_json, _STATE_ATTRIBUTE
from intent_browser.trace import write_json


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    paths=[*Path('intent_browser').glob('*.py'),Path(__file__)]
    hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before=hashes()
    class Fixture(OpenEndedTask):
        def setup(self,page):
            page.route('**/*',lambda r:r.fulfill(content_type='text/html',body='<h1>Test</h1><input aria-label="Name"><button>Commit</button>'))
            return super().setup(page)
    env=BrowserEnv(task_entrypoint=Fixture,task_kwargs={'start_url':'http://fixture.invalid/','goal':'Inspect'},headless=True)
    rows=[]
    try:
        env.reset();page=env.page;cdp=page.context.new_cdp_session(page)
        connection=page._impl_obj._connection
        original=connection._replace_guids_with_channels
        for variant in ('public','conversion_only','optimized'):
            roots=[]
            def observe(payload):
                if type(payload) is dict and set(payload)=={'result'}:
                    value=payload['result']
                    if type(value) is dict and ('nodes' in value or ('strings' in value and 'documents' in value)):
                        roots.append(sorted(value))
                return original(payload)
            path=(patch('intent_browser.cdp_json._raw_reply_scope',lambda *a:nullcontext())
                  if variant=='conversion_only' else nullcontext())
            with patch('intent_browser.cdp_json._reviewed_version',return_value=variant!='public'),path,patch.object(connection,'_replace_guids_with_channels',observe):
                ax=send_json(cdp,'Accessibility.getFullAXTree',{})
                dom=send_json(cdp,'DOMSnapshot.captureSnapshot',{'computedStyles':[]})
            assert ax['nodes'] and dom['documents']
            assert len(roots)==(0 if variant=='optimized' else 2),(variant,roots)
            assert not hasattr(connection,_STATE_ATTRIBUTE)
            # Verify ordinary Playwright handle conversion and actions still work.
            handle=page.query_selector('input');handle.fill(variant);assert handle.input_value()==variant;handle.dispose()
            rows.append({'variant':variant,'large_reply_reference_scans':len(roots),'normal_handle_action':True})
        try:send_json(cdp,'Accessibility.getFullAXTree',{'frameId':'nonexistent-frame'})
        except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
        else:raise AssertionError('Expected CDP error')
        assert not hasattr(connection,_STATE_ATTRIBUTE)
        assert send_json(cdp,'Accessibility.getFullAXTree',{})['nodes']
        cdp.detach()
    finally:env.close()
    assert hashes()==before
    write_json(a.output/'report.json',{'passed':True,'cases':rows,'cdp_error':error,'usable_after_error':True,'model_calls':0,'source_sha256':before})
    print(json.dumps({'passed':True,'cases':rows}))

if __name__=='__main__':main()
