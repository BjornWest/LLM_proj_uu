"""Scripted live-browser boundaries for opt-in capture; no model/server calls."""
import argparse
from collections import Counter
from pathlib import Path
import sys
import json
import hashlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from browsergym.core.observation import _pre_extract,_post_extract,extract_merged_axtree
from intent_browser.actions import make_action_set
from intent_browser.trace import Trace,write_json
from intent_browser.observation_pipeline import ObservationPipeline,ObservationPipelineConfig,ax_node_signature,ObservationChanged
from intent_browser.readiness import ReadinessSpec

ORIGIN='http://boundaries.invalid'
HTML='''<!doctype html><title>Readiness</title><main id=app aria-busy=false>
<label>Note <input></label><button id=go>Update</button><p id=status>Initial</p>
<a href=/next>Next page</a></main>'''
SCRIPT='''<script>document.querySelector('#go').onclick=()=>{
 const op=__intentReadinessV1.app.begin('fixture-update');window.calls=(window.calls||0)+1;
 document.querySelector('#app').setAttribute('aria-busy','true');
 setTimeout(()=>{document.querySelector('#status').textContent='Updated';
 document.querySelector('#app').setAttribute('aria-busy','false');__intentReadinessV1.app.end(op);},300);
};</script>'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    source_paths=[*Path('intent_browser').glob('*.py'),Path('intent_browser/observation_revision.js'),Path(__file__)]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    checks=[]
    def check(name,ok,**evidence):
        checks.append(dict(name=name,passed=bool(ok),**evidence));write_json(args.output/'checks.json',checks)
        assert ok,name
    class Task(OpenEndedTask):
        mode='static'
        def setup(self,page):
            def route(r):
                body=HTML+(SCRIPT if self.mode=='script' else '')
                if self.mode=='iframe':body+='<iframe srcdoc="<p>Inside</p>"></iframe>'
                headers={} if self.mode in ('script','iframe') else {'Content-Security-Policy':"script-src 'none'"}
                if self.mode=='override':headers={'Content-Security-Policy':"script-src 'none'; script-src-elem 'unsafe-inline'"}
                r.fulfill(content_type='text/html',body=body,headers=headers)
            page.route(ORIGIN+'/**',route);return super().setup(page)
    trace=Trace(args.output,{})
    env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN+'/'},headless=True,
        action_mapping=make_action_set().to_python_code)
    pipeline=ObservationPipeline(env,ObservationPipelineConfig((ORIGIN,),trace_screenshots=False,
        readiness_by_action={'click':ReadinessSpec(scope='#app',signal_scope='fixture-update',timeout_ms=1500)},
        readiness_contract='scripted-fixture-operation'),trace)
    try:
        observation,_=env.reset(seed=0)
        check('initial partial',observation['observation_capture']['coverage']=='partial')
        pipeline.prefetch();full=pipeline.full_after_completion()
        _pre_extract(env.page)
        try:native=extract_merged_axtree(env.page)
        finally:_post_extract(env.page)
        check('all full nodes and BIDs match native BrowserGym',
            Counter(map(ax_node_signature,native['nodes']))==Counter(map(ax_node_signature,full['axtree_object']['nodes'])),nodes=len(native['nodes']))
        original=env.page.locator('input').get_attribute('bid')
        env.page.locator('input').fill('New value')
        changed=pipeline.capture(complete=True)
        node=next(n for n in changed['axtree_object']['nodes'] if n.get('browsergym_id')==original)
        check('property change forces fresh tree',node['value']['value']=='New value')
        pipeline.cache=None;pipeline.capture()
        env.page.evaluate("document.querySelector('#status').textContent='Changed after preview'")
        try:pipeline.prefetch();rejected=False
        except ObservationChanged:rejected=True
        check('change between shallow and full rejected',rejected)
        for mode in ('override','script','iframe','static'):
            env.task.mode=mode;env.page.reload();obs=pipeline.capture()
            check('same URL current headers/mode '+mode,
                obs['observation_capture']['coverage']=='partial' if mode=='static' else obs['observation_capture'].get('mode')=='native_fallback')
        env.task.mode='script';env.page.reload();obs=pipeline.capture()
        bid=env.page.locator('#go').get_attribute('bid')
        obs,reward,done,truncated,info=env.step(f'click({bid!r})')
        check('application readiness awaited',pipeline.last_readiness['status']=='ready',readiness=pipeline.last_readiness)
        check('async action exactly once',env.page.evaluate('window.calls')==1)
        check('updated text at observation',env.page.locator('#status').inner_text()=='Updated')
        check('no fixed post-action delay with explicit contract',info['wait_for_page_loading_stop']-info['wait_for_page_loading_start']<.5)
        # A held operation must remain pending; never repair it to completion.
        env.page.evaluate("()=>{document.querySelector('#go').onclick=()=>{window.calls++;__intentReadinessV1.app.begin('fixture-update');};}")
        pipeline.config=ObservationPipelineConfig((ORIGIN,),trace_screenshots=False,
            readiness_by_action={'click':ReadinessSpec(scope='#app',signal_scope='fixture-update',timeout_ms=40)},
            readiness_contract='scripted-pending-operation')
        env.step(f'click({bid!r})')
        check('pending completion becomes uncertain action feedback',pipeline.last_readiness['status']=='pending' and 'No action was replayed' in env.last_action_error)
        check('pending action never retried',env.page.evaluate('window.calls')==2)
    finally:
        pipeline.close();env.close();trace.finish({'stop_reason':'scripted_validation'})
    unchanged=hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    write_json(args.output/'report.json',{'passed':all(c['passed'] for c in checks),'checks':checks,
        'source_sha256':hashes,'sources_unchanged':unchanged,'model_calls':0})
    assert unchanged

if __name__=='__main__':main()
