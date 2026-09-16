#!/usr/bin/env python3
"""Exercise GPU probe control flow against a deterministic fake HTTP engine."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import torch
from safetensors.torch import save_file,load_file
from modal_inference_probe import exercise,padded_adapter

class Response:
    def __init__(self,data):self.data=data
    def raise_for_status(self):pass
    def json(self):return self.data
    def iter_lines(self):return iter([b'data: first token',b'data: [DONE]'])
    def close(self):pass

class Session:
    def __init__(self):self.adapters={};self.counter=0;self.signatures={};self.trace_id=None
    def get(self,url,**kwargs):return Response({'data':[{'id':n} for n in self.adapters]})
    def post(self,url,json,**kwargs):
        if url.endswith('/collective_rpc'):
            if json['method']=='training_lora_fingerprint':
                adapter_id=json['args'][0]
                return Response({'results':[dict(sha256=self.signatures[adapter_id],cpu_reconstruction_matches=True)]})
            if json['method']=='training_lora_trace':
                if json.get('args'):
                    self.trace_id=json['args'][0]
                    return Response({'results':[dict(armed=True)]})
                assert self.trace_id is not None
                self.trace_id=None
                return Response({'results':[dict(calls={'fake/lora_shrink':1},missing_calls=[])]})
            ids=list(self.adapters.values())
            return Response({'results':[dict(registered=ids,active=ids,capacity=4,slots=4,allocated=1,reserved=2,rss=3)]})
        if url.endswith('/load_lora_adapter'):
            self.counter+=1;self.adapters[json['lora_name']]=self.counter
            from browser_training.vllm_probe_worker import tensor_digest
            tensors=load_file(Path(json['lora_path'])/'adapter_model.safetensors')
            self.signatures[self.counter]=tensor_digest(tensors['model.lora_B.weight'])
            assert len(self.adapters)<=4
        elif url.endswith('/unload_lora_adapter'):del self.adapters[json['lora_name']]
        elif url.endswith('/completions'):
            assert json['model'] in self.adapters
            is_b=self.signatures[self.adapters[json['model']]]!=self.signatures[1]
            return Response({'choices':[dict(text='click(8)' if is_b else 'click(7)',logprobs={'token_logprobs':[-0.1],'tokens':['8' if is_b else '7']})]})
        else:raise AssertionError(url)
        return Response({})

def main():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);source=root/'source';source.mkdir()
        (source/'adapter_config.json').write_text(json.dumps(dict(r=16,lora_alpha=32)))
        a=torch.randn(16,8,dtype=torch.bfloat16);b=torch.randn(8,16,dtype=torch.bfloat16)
        save_file({'model.lora_A.weight':a,'model.lora_B.weight':b},source/'adapter_model.safetensors')
        padded_adapter(source,root/'padded',32)
        t=load_file(root/'padded/adapter_model.safetensors')
        assert torch.equal(b@a,t['model.lora_B.weight']@t['model.lora_A.weight'])
        output=root/'output';output.mkdir()
        with patch('requests.Session',Session):report=exercise('http://mock',source,output)
        assert report['status']=='PASS' and report['versions_loaded']==10
        output=root/'identity';output.mkdir()
        with patch('requests.Session',Session):report=exercise('http://mock',source,output,16,True)
        assert report['status']=='PASS' and report['identity']['behaviorally_distinct']
        assert set(report['identity']['traces'])=={'a_before','b_control','a_after','churn-5','churn-10'}
    print('PASS: rank padding, identity and lifecycle control flow; simulated HTTP engine, no GPU')

if __name__=='__main__':main()
