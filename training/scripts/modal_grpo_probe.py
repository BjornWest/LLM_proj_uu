#!/usr/bin/env python3
"""Isolated 27B NF4 native AsyncGRPO loss/backward probe, no rollout process."""
import argparse
import json
from pathlib import Path
import queue
import time
from types import SimpleNamespace


def reject_packed_inputs(module, positional, kwargs):
    positions=kwargs.get('position_ids')
    if positions is None or positions.ndim!=2 or positions.shape[0]!=1:
        raise ValueError('Isolated hybrid probe requires one explicit unpadded sequence')
    import torch
    expected=torch.arange(positions.shape[1],device=positions.device).unsqueeze(0)
    if not torch.equal(positions,expected):
        raise ValueError('Hybrid packed trajectory boundaries are not qualified; refusing this forward')


def main():
    p=argparse.ArgumentParser();p.add_argument('--snapshot',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    import torch
    import yaml
    from transformers import AutoTokenizer
    from peft import LoraConfig
    from datasets import Dataset
    from safetensors.torch import load_file
    from browser_training.qlora_compat import candidate_module
    from browser_training.precision import enforce_bf16_lora,inspect_dtypes,inspect_nf4,make_optimizer,inspect_optimizer
    from check_adapter_dtypes import check
    torch.manual_seed(42);started=time.monotonic()
    _,candidate,evidence=candidate_module()
    tokenizer=AutoTokenizer.from_pretrained(a.snapshot,local_files_only=True)
    targets=yaml.safe_load(Path('configs/sft_qwen38_27b_nf4_qlora.yml').read_text())['lora_target_modules']
    args=candidate.AsyncGRPOConfig(output_dir=str(a.output),bf16=True,dtype='bfloat16',report_to='none',
        max_steps=2,per_device_train_batch_size=1,num_generations=2,token_budget=0,
        gradient_checkpointing=True,gradient_checkpointing_kwargs={'use_reentrant':False},
        model_init_kwargs={'attn_implementation':'sdpa','local_files_only':True})
    trainer=candidate.AsyncGRPOTrainer(model=a.snapshot,args=args,processing_class=tokenizer,
        train_dataset=Dataset.from_dict({'prompt':[[{'role':'user','content':'Click Continue.'}]]}),
        peft_config=LoraConfig(r=16,lora_alpha=32,lora_dropout=0,target_modules=targets,task_type='CAUSAL_LM'),
        rollout_worker=SimpleNamespace(rollout_buffer=queue.Queue(),metrics_queue=queue.Queue()),weight_transfer=object())
    model=trainer.model
    evidence['dtypes_before_explicit_cast']=inspect_dtypes(model)
    enforce_bf16_lora(model);evidence['nf4']=inspect_nf4(model)
    assert next(model.parameters()).device.type=='cuda'
    assert all(not p.requires_grad for n,p in model.named_parameters() if '.visual.' in n)
    model.train();model.config.use_cache=False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
    model.register_forward_pre_hook(reject_packed_inputs,with_kwargs=True)
    trainer.current_gradient_accumulation_steps=1
    optimizer=make_optimizer(model,5e-5)
    ids=tokenizer('Task: click Continue without choosing the addon. Observation: [1] Continue [2] Addon unchecked. '*16,
        return_tensors='pt')['input_ids'].to('cuda')[:,:384]
    n=ids.shape[1];assert n>=128
    positions=torch.arange(n,device='cuda').unsqueeze(0)
    mask=torch.zeros_like(ids);mask[:,-32:]=1
    with torch.no_grad(),torch.autocast('cuda',dtype=torch.bfloat16):
        behavior=model(input_ids=ids,position_ids=positions,labels=ids,completion_mask=mask,use_cache=False)['log_probs']
    inputs=dict(input_ids=ids,attention_mask=torch.ones_like(ids),completion_mask=mask,position_ids=positions,
        old_log_probs=torch.cat([torch.zeros(1,1,device='cuda'),behavior],dim=1),advantages=torch.ones_like(ids),
        global_n_tokens=torch.tensor([32],device='cuda'),global_n_forward_tokens=torch.tensor([n],device='cuda'),
        mean_seq_len=torch.tensor([float(n)],device='cuda'))
    # Small samples prove selected frozen weights remain unchanged without copying a 27B base.
    frozen={name:p.detach().flatten()[:32].clone() for name,p in model.named_parameters() if not p.requires_grad}
    trainable_name,trainable=next((name,p) for name,p in model.named_parameters() if p.requires_grad and 'lora_B' in name)
    before=trainable.detach().clone();losses=[];steps=[]
    torch.cuda.reset_peak_memory_stats()
    for step in range(2):
        tick=time.monotonic();optimizer.zero_grad(set_to_none=True)
        with torch.autocast('cuda',dtype=torch.bfloat16):loss=trainer.compute_loss(model,inputs)
        assert torch.isfinite(loss);loss.backward()
        evidence['gradients']=inspect_dtypes(model,check_grads=True)
        optimizer.step();evidence['fp32_moment_tensors']=inspect_optimizer(optimizer)
        losses.append(loss.item());torch.cuda.synchronize();steps.append(time.monotonic()-tick)
    delta=(trainable.detach().float()-before.float()).abs().max().item();assert delta>0
    assert all(torch.equal(p.detach().flatten()[:32],frozen[name]) for name,p in model.named_parameters() if name in frozen)
    checkpoint=a.output/'checkpoint-2';model.save_pretrained(checkpoint);torch.save(optimizer.state_dict(),checkpoint/'optimizer.pt')
    (checkpoint/'probe_state.json').write_text(json.dumps(dict(step=2,sequence_length=n,seed=42)))
    evidence['checkpoint']=check(checkpoint)
    restored=make_optimizer(model,5e-5);restored.load_state_dict(torch.load(checkpoint/'optimizer.pt',map_location='cuda',weights_only=True))
    inspect_optimizer(restored)
    evidence.update(status='PASS',losses=losses,step_seconds=steps,sequence_length=n,
        peak_allocated_gib=torch.cuda.max_memory_allocated()/2**30,peak_reserved_gib=torch.cuda.max_memory_reserved()/2**30,
        adapter_max_change=delta,checked_tensor=trainable_name,frozen_parameter_samples_unchanged=True,
        optimizer_reload=True,elapsed_seconds=time.monotonic()-started,gpu=torch.cuda.get_device_name(),
        attention='SDPA; single trajectory; packed inputs rejected',
        scope='native AsyncGRPO constructor/compute_loss + two optimizer steps; synthetic old logprobs/advantages; no Trainer.train, vLLM or rollout worker')
    (a.output/'grpo-report.json').write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence,indent=2))

if __name__=='__main__':main()
