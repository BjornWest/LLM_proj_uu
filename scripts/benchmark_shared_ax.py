"""Local/shared AX and request-count latency/parity, synthetic capture only."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import select
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tokenizer',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--nodes',type=int,default=128)
    args=parser.parse_args()
    if not 16<=args.nodes<=4096:parser.error('nodes must be between 16 and 4096')
    from intent_browser.ax_explorer import AXConfig
    from intent_browser.ax_context import AXContext
    from intent_browser.input_budget import QwenInputCounter
    from intent_browser.shared_tokenizer import SharedTokenizerConfig,asset_digest
    def node(i,role,name,children=()):
        return {'nodeId':str(i),'role':{'value':role},'name':{'value':name},
                'childIds':list(map(str,children)),'browsergym_id':str(i),'backendDOMNodeId':i+100}
    nodes=[node(0,'RootWebArea','Retail offers',range(1,args.nodes))]+[
           node(i,'button',f'Offer {i}: '+('Product details price delivery warranty '*12)) for i in range(1,args.nodes)]
    observation={'url':'http://synthetic.invalid/','last_action_error':'','axtree_object':{'nodes':nodes}}
    rows=[];digests=[]
    with tempfile.TemporaryDirectory() as folder:
        socket=str(Path(folder)/'tokens.sock');manifest=Path(folder)/'assets.json'
        manifest.write_text(json.dumps([{'path':str(Path(args.tokenizer).resolve()),
            'sha256':asset_digest(args.tokenizer),'normalization':'raw'}]))
        service=subprocess.Popen([sys.executable,'-B','-m','intent_browser.tokenizer_service',
            '--socket',socket,'--manifest',str(manifest)],cwd=ROOT,stdout=subprocess.PIPE,text=True)
        try:
            readable,_,_=select.select([service.stdout],[],[],30)
            if not readable or json.loads(service.stdout.readline()).get('ready') is not True:
                raise RuntimeError('Service startup did not report readiness')
            for mode in ('local','shared'):
                samples=[]
                for _ in range(3):
                    config=SharedTokenizerConfig(socket) if mode=='shared' else None
                    explorer=AXContext(AXConfig(args.tokenizer,incremental=True,shared_tokenizer=config))
                    counter=QwenInputCounter(args.tokenizer,shared_tokenizer=config)
                    rpc_count=[0]
                    if config:
                        for client in [explorer.tokenizer,counter.tokenizer]:
                            original=client._rpc
                            def wrapped(*a,_original=original,**kw):
                                rpc_count[0]+=1
                                return _original(*a,**kw)
                            client._rpc=wrapped
                    timings={};outputs=[]
                    def timed(name,operation):
                        start=time.perf_counter();result=operation();timings[name]=time.perf_counter()-start
                        outputs.append(result);return result
                    timed('initial_ax',lambda:explorer.prepare_observation(observation));explorer.acknowledge()
                    timed('search',lambda:explorer.search(['price','delivery'],limit=5));explorer.acknowledge()
                    timed('node_read',lambda:explorer.read(explorer.ref(args.nodes-1),view='node'));explorer.acknowledge()
                    timed('unchanged_ax',lambda:explorer.prepare_observation(observation));explorer.acknowledge()
                    measured=timed('complete_request',lambda:counter([{'role':'user','content':'Compare the offers.'}],[]))
                    measured.pop('tokenizer_service',None)
                    digest=hashlib.sha256(json.dumps(outputs,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                    digests.append(digest)
                    samples.append({'seconds':timings,'rpc_requests':rpc_count[0],'output_sha256':digest})
                rows.append({'mode':mode,'samples':samples,'median_seconds':{
                    name:statistics.median(sample['seconds'][name] for sample in samples) for name in samples[0]['seconds']}})
        finally:
            if service.poll() is None:service.terminate()
            try:service.wait(timeout=5)
            except subprocess.TimeoutExpired:service.kill();service.wait(timeout=5)
    if len(set(digests))!=1:raise AssertionError('Local/shared AX or complete-request output mismatch')
    report={'scope':'Synthetic raw AX capture; no rendering/browser/navigation/model/world. Three fresh explorers per mode.',
            'semantic_nodes':args.nodes,'tokenizer_sha256':asset_digest(args.tokenizer),
            'results':rows,'complete_output_parity':True,'model_dispatches':0}
    with Path(args.output).open('x') as f:json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps({'output':args.output,'complete_output_parity':True}))


if __name__=='__main__':main()
