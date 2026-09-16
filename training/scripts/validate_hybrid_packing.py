#!/usr/bin/env python3
"""CPU negative control: position resets alone must not qualify hybrid packing."""
import os
os.environ['CUDA_VISIBLE_DEVICES']=''
os.environ['USE_HUB_KERNELS']='NO'
os.environ['HF_HUB_OFFLINE']='1'
import inspect
import json
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
import torch
from transformers import AutoConfig
from transformers.models.qwen3_5 import modeling_qwen3_5 as m

def main():
    torch.set_num_threads(2);torch.manual_seed(42)
    cfg=AutoConfig.from_pretrained('.cache/qwen38-tokenizer',local_files_only=True).text_config
    cfg.update(dict(vocab_size=64,hidden_size=64,intermediate_size=128,num_hidden_layers=1,
        num_attention_heads=4,num_key_value_heads=2,head_dim=16,layer_types=['linear_attention'],
        linear_key_head_dim=16,linear_value_head_dim=16,linear_num_key_heads=2,linear_num_value_heads=4,
        max_position_embeddings=128))
    cfg._attn_implementation='eager'
    model=m.Qwen3_5TextModel(cfg).eval()
    ids=torch.randint(0,64,(1,16));other=ids.clone();other[:,:8]=(other[:,:8]+1)%64
    positions=torch.arange(8).repeat(2).unsqueeze(0)
    calls=[]
    reference=inspect.unwrap(m.torch_chunk_gated_delta_rule)
    def recorded(*args,**kwargs):
        calls.append({'cu_seqlens':None if kwargs.get('cu_seqlens') is None else kwargs['cu_seqlens'].tolist()})
        return reference(*args,**kwargs)
    with ExitStack() as stack,torch.no_grad():
        for name in ('causal_conv1d_fn','causal_conv1d_update','torch_recurrent_gated_delta_rule'):
            stack.enter_context(patch.object(m,name,inspect.unwrap(getattr(m,name))))
        stack.enter_context(patch.object(m,'torch_chunk_gated_delta_rule',recorded))
        first=model(input_ids=ids,position_ids=positions,use_cache=False).last_hidden_state
        changed=model(input_ids=other,position_ids=positions,use_cache=False).last_hidden_state
        alone=model(input_ids=ids[:,8:],position_ids=positions[:,:8],use_cache=False).last_hidden_state
    leakage=(first[:,8:]-changed[:,8:]).abs().max().item()
    independent_error=(first[:,8:]-alone).abs().max().item()
    assert leakage>1e-4 and all(c['cu_seqlens'] is None for c in calls)
    report=dict(status='BLOCKED_PACKED_HYBRID_TRAINING',gpu_used=False,reference_functions=True,
        modified_prefix_changes_next_sequence=leakage,packed_vs_independent_max_error=independent_error,
        kernel_calls=calls,scope='actual Transformers text model; one linear-attention layer; CPU reference kernels',
        conclusion='TRL position_ids resets alone do not supply DeltaNet/conv boundaries. FA2 only fixes full attention.')
    Path('research/hybrid-packing-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
