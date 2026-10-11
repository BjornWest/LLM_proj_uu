#!/usr/bin/env python3
"""CPU allocator regression for the Qwen FP8 target/BF16 DFlash page ratio.

Uses synthetic cache specs matching observed layer counts/page budget. This is
not a model load or a substitute for checking the realised GPU cache specs.
"""
import json
import math
from types import SimpleNamespace as NS


def verify():
    import torch
    from importlib.metadata import version
    from vllm.v1.kv_cache_interface import FullAttentionSpec, SlidingWindowSpec, MambaSpec, KVCacheConfig
    from vllm.v1.core.kv_cache_utils import get_kv_cache_groups, get_max_concurrency_for_kv_cache_config
    from vllm.v1.attention.backends.flash_attn import FlashAttentionBackend
    assert version('vllm')=='0.28.0'
    cfg=NS(model_config=NS(max_model_len=61040),
        parallel_config=NS(decode_context_parallel_size=1,prefill_context_parallel_size=1),
        scheduler_config=NS(disable_hybrid_kv_cache_manager=False),
        cache_config=NS(mamba_cache_mode='align'),max_in_flight_tokens=16384)
    records=[]
    for block_size in (1648,1664):
        page=block_size*2048
        full=FullAttentionSpec(block_size=block_size,num_kv_heads=4,head_size=256,dtype=torch.float8_e4m3fn)
        mamba=MambaSpec(block_size=block_size,shapes=((1,),),dtypes=(torch.float32,),
            page_size_padded=page,mamba_type='gdn',mamba_cache_mode='align',num_speculative_blocks=7)
        sw=SlidingWindowSpec(block_size=16,num_kv_heads=8,head_size=128,dtype=torch.bfloat16,
            sliding_window=2048,indexes_kv_by_block_stride=True)
        specs={**{f'm{i}':mamba for i in range(48)},**{f'f{i}':full for i in range(16)},
               **{f'd{i}':sw for i in range(5)}}
        groups=get_kv_cache_groups(cfg,specs)
        draft=next(g.kv_cache_spec for g in groups if g.layer_names[0].startswith('d'))
        stride=page*max(len(g.layer_names) for g in groups)
        # Fixed measured pool bytes from the original GPU attempt; future GPU
        # profiling will choose its own available-memory budget.
        pool_blocks=52769751040//stride
        cache=KVCacheConfig(num_blocks=pool_blocks,kv_cache_tensors=[],kv_cache_groups=groups)
        nominal=get_max_concurrency_for_kv_cache_config(cfg,cache)
        blocks=sum(math.ceil(g.kv_cache_spec.max_memory_usage_bytes(cfg)/g.kv_cache_spec.page_size_bytes) for g in groups)
        assert FlashAttentionBackend.supports_block_size(draft.block_size)
        shape=FlashAttentionBackend.get_kv_cache_shape(2,draft.block_size,8,128)
        records.append(dict(primary_block_size=block_size,draft_block_size=draft.block_size,
            draft_page_bytes=draft.page_size_bytes,draft_natural_page_bytes=draft.real_page_size_bytes,
            draft_padding_factor=draft.page_size_bytes/draft.real_page_size_bytes,
            prefix_alignment_tokens=math.lcm(*(g.kv_cache_spec.block_size for g in groups)),
            pool_blocks=pool_blocks,blocks_per_request=blocks,nominal_capacity=nominal,
            integer_capacity=(pool_blocks-1)//blocks,draft_shape=list(shape)))
    before,after=records
    assert before['blocks_per_request']==1395 and before['integer_capacity']==2
    assert after['draft_block_size']==832 and after['draft_padding_factor']==1
    assert after['prefix_alignment_tokens']==1664 and after['integer_capacity']>=10
    return dict(status='PASS',kind='CPU synthetic-spec allocator regression',cases=records,
        caveat='Actual GPU budget, attention kernels and prefix-cache reuse still require the bounded GPU test')

if __name__=='__main__':print(json.dumps(verify(),indent=2))
