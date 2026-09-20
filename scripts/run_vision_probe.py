"""Two parallel fresh Qwen vision episodes with separate bounded ledgers.

Requires explicit --live --total-cap-usd authorization; no default paid execution.
Uses the synthetic public canvas task and independent before-close verifier.
"""
import argparse
import base64
from copy import deepcopy
from io import BytesIO
from PIL import Image
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Thread
from http.server import ThreadingHTTPServer
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from verify_vision import Handler,Task,GOAL
import gymnasium as gym
from dotenv import dotenv_values
from intent_browser.actions import make_action_set
from intent_browser.ax_explorer import AXConfig
from intent_browser.harness import native_tools_profile
from intent_browser.openrouter import DEFAULT_PROVIDERS
from intent_browser.runner import run_episode
from intent_browser.retry_policy import DecisionRetryPolicy
from intent_browser.trace import write_json
from intent_browser.vision import VisionConfig
from native_probe_budget import NativeProbeBackend,initial_ledger

class VisionProbeBackend(NativeProbeBackend):
    supports_native_tools=True
    def validate_messages(self,messages):
        validated=deepcopy(messages)
        for message in validated:
            content=message.get('content')
            if not isinstance(content,list):continue
            for part in content:
                if part.get('type')=='text' and isinstance(part.get('text'),str):continue
                if part.get('type')!='image_url':raise ValueError('Unsupported image-probe content')
                url=part['image_url']['url']
                if not url.startswith('data:image/png;base64,'):raise ValueError('Only local PNG input allowed')
                encoded=url.split(',',1)[1]
                image=Image.open(BytesIO(base64.b64decode(encoded,validate=True)))
                # This probe freezes viewport resolution. Base64 reservation
                # alone exceeds the 880 image positions (+2 boundaries).
                if image.size!=(1280,720) or len(encoded)<1024:
                    raise ValueError('Image outside reviewed resolution/byte reservation bound')
            message['content']=''
        super().validate_messages(validated)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.supports_images=True


def case(directory,mode,cap,retry=False):
    directory.mkdir(parents=True,exist_ok=False)
    files=[*sorted((ROOT/'intent_browser').glob('*.py')),Path(__file__).resolve(),
        ROOT/'scripts/verify_vision.py',ROOT/'scripts/native_probe_budget.py',
        ROOT/'training/.cache/qwen38-tokenizer/tokenizer.json']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    def validate():
        for p,want in hashes.items():
            if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=want:raise ValueError('Frozen source changed: '+p)
    config={'budget_id':str(directory),'model':'qwen/qwen3.8-27b','providers':list(DEFAULT_PROVIDERS),
        'max_tokens':4096,'max_steps':16,'input_byte_limit':200000,'pace_seconds':0,
        'settle_reported_cost':True,'cap_usd':str(cap),'carried_usd':'0',
        'prompt_price_cap':'0.50','output_price_cap':'4'}
    profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,timeout_feedback=True,
        ax_config=AXConfig(str(ROOT/'training/.cache/qwen38-tokenizer/tokenizer.json'),incremental=True),
        vision_config=VisionConfig(mode))
    write_json(directory/'profile.json',{'task':GOAL,'config':config,'mode':mode,'harness':profile.describe(),
        'source_sha256':hashes,'scope':'Synthetic visual diagnostic; fresh episodes, not paired performance evidence.',
        'budget':'Conservative complete JSON bytes (including image base64) +2048 reservation; settled verified actual costs. Separate per-case caps sum to user total.',
        'retry_policy':DecisionRetryPolicy().describe() if retry else None,
        'retry_budget_scope':'Recovery uses the same request/ledger caps. This probe budget wrapper still stops on transport/HTTP/usage-audit failures; only completed-response protocol recovery can proceed.',
        'image_transport':'Explicit tool message image parts. Unsupported provider behavior must fail visibly; no transport fallback.'})
    for p in files:
        if p.name=='tokenizer.json':continue
        dest=directory/'source'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    write_json(directory/'budget.json',initial_ledger(config,[]))
    key=os.getenv('OPENROUTER_API_KEY') or dotenv_values(ROOT/'.env').get('OPENROUTER_API_KEY')
    if not key:raise ValueError('Missing API credential')
    backend=VisionProbeBackend(key,directory/'budget.json',validate,config,'VISION-'+mode)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    def factory(_):
        return gym.make('browsergym/openended',task_kwargs={'start_url':origin,'goal':GOAL},headless=True,
            wait_for_user_message=False,action_mapping=make_action_set().to_python_code,viewport={'width':1280,'height':720})
    try:
        trace,summary=run_episode(factory,backend,{'task':'visual-inspection-v1','model':config['model'],
            'retention':mode,'training_eligible':False,'profile':str(directory/'profile.json')},
            output=directory/'traces',max_steps=config['max_steps'],harness_profile=profile,
            before_observation=backend.wait_until_ready,episode_task=Task(),
            retry_policy=DecisionRetryPolicy() if retry else None,
            terminal_response_instruction='After inspection return exactly the requested count/digit as your final answer.')
        write_json(directory/'case.json',{'trace':str(trace),'summary':summary})
    finally:backend.close();server.shutdown();server.server_close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--live',action='store_true');p.add_argument('--total-cap-usd',type=Decimal)
    p.add_argument('--case',choices=['retain','agent']);p.add_argument('--retry-policy',choices=['none','bounded-v1'],default='none');a=p.parse_args()
    if not a.live or a.total_cap_usd is None or not a.total_cap_usd.is_finite() or not Decimal('0')<a.total_cap_usd<=Decimal('0.25'):
        p.error('Explicit --live and --total-cap-usd (0,0.25] required; obtain spending authorization first')
    output=a.directory.resolve()
    if a.case:return case(output,a.case,a.total_cap_usd/2,a.retry_policy=='bounded-v1')
    output.mkdir(parents=True,exist_ok=False)
    def launch(mode):
        with (output/f'{mode}.log').open('x') as log:
            r=subprocess.run([sys.executable,__file__,'--directory',str(output/mode),'--case',mode,
                '--live','--total-cap-usd',str(a.total_cap_usd),'--retry-policy',a.retry_policy],stdout=log,stderr=subprocess.STDOUT,timeout=900)
        return {'mode':mode,'returncode':r.returncode}
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(launch,['retain','agent']))
    write_json(output/'suite.json',{'parallel':True,'total_cap_usd':str(a.total_cap_usd),'cases':results})
    print(json.dumps(results))
if __name__=='__main__':main()
