"""Offline BrowserGym delegation checks. Model transport is scripted; no credentials."""
import argparse,json,os,sys,tempfile,re
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
import gymnasium as gym
import browsergym.core
from intent_browser.backend import Completion
from intent_browser.harness import native_tools_profile,with_subagents
from intent_browser.ax_explorer import AXConfig
from intent_browser.delegation import AgentLimits
from intent_browser.runner import run_episode
from intent_browser.actions import make_action_set
from intent_browser.trace import write_json

class Backend:
    supports_images=True
    def __init__(self,origin,mode):self.origin,self.mode=origin,mode;self.request_options={};self.session_id=None;self.counters={};self.serial=0;self.records=[]
    def configure_tools(self,options):self.request_options.update(options)
    def begin_episode(self,ident):self.session_id=ident;return {'session_id':ident}
    def complete(self,messages):
        self.serial+=1;n=self.counters.get(self.session_id,0);self.counters[self.session_id]=n+1
        names=[t['function']['name'] for t in self.request_options['tools']];parent='spawn_agent' in names
        context=json.dumps(messages,ensure_ascii=False)
        if parent:
            if n==0:name,args='spawn_agent',{'task':'Find the public lookup code and report it.','browser':self.mode,'context':('For the reasoning-only check the supplied code is PINE-74.' if self.mode=='none' else 'Open the public /lookup page in your own browser.')}
            elif n==1:
                ident=re.findall(r'(?<![a-z_])agent_id[^a-z0-9]+([a-f0-9]{32})',context)[-1]
                name,args='wait_agent',{'agent_id':ident,'timeout_seconds':30}
            else:name,args='send_msg_to_user',{'text':'PINE-74'}
        elif self.mode=='own' and n==0:name,args='goto',{'url':self.origin+'/lookup'}
        else:
            assert 'PINE-74' in context,'Script must read code from supplied/public evidence'
            name,args='send_msg_to_user',{'text':'PINE-74'}
        raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'reasoning':'Offline test decision','tool_calls':[{'id':'call-'+str(self.serial),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}]}
        req={'model':'scripted','messages':messages,'session_id':self.session_id,**self.request_options};self.last_request=req;self.records.append(req)
        return Completion('',raw,req)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        html='<h1>Lookup</h1><p>Public code: PINE-74</p>' if self.path=='/lookup' else '<h1>Main workspace</h1><a href="/lookup">Code lookup</a><p>Keep this page open.</p>'
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(html.encode())
    def log_message(self,*args):pass

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--mode',choices=['none','own'],required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    profile=with_subagents(native_tools_profile(parallel_tool_calls=None,compact_feedback=True,timeout_feedback=True,navigation_origins=(origin,),
        ax_config=AXConfig(str(ROOT/'training/.cache/qwen38-tokenizer/tokenizer.json'),incremental=True),batch_size=8),AgentLimits(child_steps=4,total_model_calls=8))
    def env(url,goal,storage=None):
        return gym.make('browsergym/openended',task_kwargs={'start_url':url,'goal':goal},headless=True,wait_for_user_message=False,
            action_mapping=make_action_set().to_python_code,pw_context_kwargs={'storage_state':storage} if storage else {})
    def factory(_):return env(origin,'Delegate the code lookup to a helper, collect its answer, and report the code.')
    def helper(parent,goal):
        storage=parent.unwrapped.page.context.storage_state()
        return lambda _:env(origin,goal,storage)
    b=Backend(origin,a.mode)
    try:
        trace,result=run_episode(factory,b,{'task':'offline-helper-'+a.mode},output=a.output/'traces',max_steps=4,harness_profile=profile,helper_env_factory=helper)
        agents=json.loads((trace/'agents.json').read_text());children=[x for x in agents['agents'] if x['parent_agent_id']]
        assert len(children)==1 and children[0]['state']=='finished',children
        assert children[0]['answer']=='PINE-74',children
        assert result['error'] is None,result
        childdir=trace/'children'/children[0]['episode_id'];metadata=json.loads((childdir/'metadata.json').read_text())
        assert metadata['agent_lineage']['parent_episode_id']==trace.name
        childrows=[json.loads(x) for x in (childdir/'steps.jsonl').read_text().splitlines()]
        assert all('spawn_agent' not in [t['function']['name'] for t in row['model_request']['tools']] for row in childrows)
        assert all(row['model_request']['session_id']==childdir.name for row in childrows)
        report={'passed':True,'mode':a.mode,'model_calls':0,'mock_requests':len(b.records),'root':str(trace),'child':str(childdir),'shared_calls':agents['total_model_calls']}
        write_json(a.output/'report.json',report);print(json.dumps(report))
    finally:server.shutdown();server.server_close()
if __name__=='__main__':main()
