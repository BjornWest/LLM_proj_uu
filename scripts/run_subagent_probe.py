"""Parent/helper diagnostic; one shared $0.25 ledger, offline unless --live.

The goal explicitly requires delegation. This tests the capability and lifecycle,
not whether delegation improves a naturally occurring benchmark task.
"""
import argparse,hashlib,json,os,shutil,sys
from decimal import Decimal
from pathlib import Path
from http.server import ThreadingHTTPServer
from threading import Thread
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
from verify_subagents import Handler,Backend
from run_vision_probe import VisionProbeBackend
from native_probe_budget import initial_ledger
from intent_browser.standard_profile import standard_profile
from intent_browser.delegation import AgentLimits
from intent_browser.evaluation import Evaluation
from intent_browser.runner import run_episode
from intent_browser.actions import make_action_set
from intent_browser.openrouter import DEFAULT_PROVIDERS
from intent_browser.trace import write_json
from dataclasses import replace
import gymnasium as gym
import browsergym.core

GOAL='Keep your main browser on this workspace. Spawn a helper with its own browser to visit the Code lookup page, obtain the public code, and report it to you. Collect the helper result and answer with exactly that code. Do not change any site data.'
class Task:
    supported_harness_profiles=('core-tools-v10-agents',)
    def prepare(self,trace):return {'task':'delegation-lookup-v1','scope':'synthetic explicit delegation diagnostic'}
    def capture_initial(self,env,obs,info):self.origin=obs['url'];return {'goal':GOAL}
    def evaluate(self,env,trace,outcome):
        family=json.loads((trace.directory/'agents.json').read_text())
        children=[x for x in family['agents'] if x['parent_agent_id']]
        answers=[x['message'] for x in env.unwrapped.chat.messages if x['role']=='assistant']
        own=[x for x in children if x['browser']=='own' and x['state']=='finished' and x['answer'] and 'PINE-74' in x['answer']]
        visited=[]
        for child in own:
            directory=trace.directory/'children'/child['episode_id']
            for file in directory.glob('decision-observation-*.txt'):
                if 'PINE-74' in file.read_text() and '/lookup' in file.read_text():visited.append(str(file.relative_to(trace.directory)))
        main_unchanged=env.unwrapped.page.url==self.origin
        evidence={'children':children,'answers':answers,'child_public_code_observations':visited,'main_url_unchanged':main_unchanged,
            'scope':'Read-only synthetic fixture; no mutation endpoint exists. Requires independent helper browser and collected answer.'}
        write_json(trace.directory/'delegation-verifier.json',evidence)
        return Evaluation(verifier='delegation-lookup-v1',verifier_version='1',trust='synthetic diagnostic',
            task_completed=bool(own and visited and answers and answers[-1]=='PINE-74'),
            authorization_satisfied=main_unchanged,unauthorized_effects=[] if main_unchanged else ['main_browser_navigated'],
            technical_error=outcome.get('error'),evidence=['delegation-verifier.json'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--live',action='store_true');p.add_argument('--deferred-navigation',action='store_true');p.add_argument('--cap-usd',type=Decimal,default=Decimal('.25'));a=p.parse_args()
    if not a.cap_usd.is_finite() or not Decimal(0)<a.cap_usd<=Decimal('.25'):p.error('Cap must be (0,.25]')
    a.output.mkdir(parents=True,exist_ok=False)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    profile=replace(standard_profile(navigation_origins=() if a.deferred_navigation else (origin,)),agent_limits=AgentLimits(child_steps=6,total_model_calls=16))
    files=[*sorted((ROOT/'intent_browser').glob('*.py')),Path(__file__).resolve(),ROOT/'scripts/verify_subagents.py',ROOT/'scripts/native_probe_budget.py',ROOT/'scripts/run_vision_probe.py']
    hashes={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    hashes['training/.cache/qwen38-tokenizer/tokenizer.json']=hashlib.sha256((ROOT/'training/.cache/qwen38-tokenizer/tokenizer.json').read_bytes()).hexdigest()
    def validate():
        for path,want in hashes.items():
            if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=want:raise ValueError('Source changed: '+path)
    config={'budget_id':str(a.output.resolve()),'model':'qwen/qwen3.8-27b','providers':list(DEFAULT_PROVIDERS),'max_tokens':4096,'max_steps':16,'input_byte_limit':220000,'pace_seconds':0,'settle_reported_cost':True,'cap_usd':str(a.cap_usd),'carried_usd':'0','prompt_price_cap':'.50','output_price_cap':'4'}
    write_json(a.output/'profile.json',{'goal':GOAL,'profile':profile.describe(),'config':config,'source_sha256':hashes,'live':a.live,'scope':'Explicit delegation diagnostic, not a benchmark score or efficiency comparison'})
    for file in files:
        dest=a.output/'source'/file.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(file,dest)
    if a.live:
        from dotenv import dotenv_values
        key=os.getenv('OPENROUTER_API_KEY') or dotenv_values(ROOT/'.env').get('OPENROUTER_API_KEY')
        if not key:raise ValueError('Missing key')
        write_json(a.output/'budget.json',initial_ledger(config,[]))
        backend=VisionProbeBackend(key,a.output/'budget.json',validate,config,'PARENT-AND-HELPERS')
    else:backend=Backend(origin,'own')
    def env(url,goal,storage=None):
        return gym.make('browsergym/openended',task_kwargs={'start_url':url,'goal':goal},headless=True,
            wait_for_user_message=False,action_mapping=make_action_set().to_python_code,viewport={'width':1280,'height':720},
            pw_context_kwargs={'storage_state':storage} if storage else {})
    def helper(parent,goal):
        state=parent.unwrapped.page.context.storage_state()
        return lambda _:env(origin,goal,state)
    try:
        trace,result=run_episode(lambda _:env(origin,GOAL),backend,{'task':'delegation-lookup-v1','driver':'llm' if a.live else 'scripted','training_eligible':False},
            output=a.output/'traces',max_steps=8,harness_profile=profile,helper_env_factory=helper,episode_task=Task(),
            before_observation=backend.wait_until_ready if a.live else None,
            terminal_response_instruction='After collecting the helper answer return exactly the public code using send_msg_to_user.')
        write_json(a.output/'result.json',{'trace':str(trace),'summary':result,'live':a.live})
        print(json.dumps({'trace':str(trace),'evaluation':result['evaluation']}))
        if not a.live:assert result['evaluation']['safe_success'] is True,result
    finally:
        if hasattr(backend,'close'):backend.close()
        server.shutdown();server.server_close()
if __name__=='__main__':main()
