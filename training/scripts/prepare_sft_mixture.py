#!/usr/bin/env python3
"""Prepare token-accounted replay mix with cached Qwen tokenizer + installed Axolotl.

No weights, downloads, model execution or training. Inputs are converter-style
messages JSONL. Output is a fresh directory containing mixed.jsonl + manifest.
"""
import os
os.environ['HF_HUB_OFFLINE']='1'
os.environ['CUDA_VISIBLE_DEVICES']=''
os.environ['AXOLOTL_DO_NOT_TRACK']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from browser_training.sft_mixture import mix
from browser_training.outcomes import require
from browser_training.monitoring_files import atomic_json


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--browser',required=True,type=Path)
    p.add_argument('--replay',type=Path)
    p.add_argument('--protected',type=Path,action='append',default=[],help='Normalized SFT validation/dev/generic holdout files')
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--replay-fraction',type=float,default=0.05)
    p.add_argument('--tolerance',type=float,default=0.005)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--sequence-len',type=int,default=16384)
    p.add_argument('--reasoning',action='store_true')
    a=p.parse_args()
    if a.output.exists(): p.error('Use a fresh output directory')
    if a.replay_fraction and not a.replay: p.error('A replay input is required for nonzero replay share')
    require(a.sequence_len > 0,'Positive sequence length required')
    from validate_tokenization import ASSETS, REVISION
    cache=ROOT/'.cache/qwen38-tokenizer'
    for name,expected in ASSETS.items():
        require(hashlib.sha256((cache/name).read_bytes()).hexdigest()==expected, f'Cached tokenizer hash mismatch: {name}')
    from transformers import AutoTokenizer
    from axolotl.prompt_strategies.chat_template import ChatTemplatePrompter, ChatTemplateStrategy
    require(importlib.metadata.version('axolotl')=='0.19.0','Requalify token masks for changed Axolotl version')
    tokenizer=AutoTokenizer.from_pretrained(cache,local_files_only=True)
    options=dict(enable_thinking=a.reasoning,preserve_thinking=True)
    prompter=ChatTemplatePrompter(tokenizer=tokenizer,chat_template=tokenizer.chat_template,
                                max_length=a.sequence_len+1,chat_template_kwargs=options)
    strategy=ChatTemplateStrategy(prompter,tokenizer,train_on_inputs=False,sequence_len=a.sequence_len,
                                  roles_to_train=['assistant'],train_on_eos='turn')
    def measure(row):
        ids=tokenizer.apply_chat_template(row['messages'],tokenize=True,return_dict=False,add_generation_prompt=False,**options)
        require(len(ids)<=a.sequence_len, f'Example exceeds {a.sequence_len} tokens; choose a reviewed chunking/context policy')
        encoded=strategy.tokenize_prompt(row)
        require(list(encoded['input_ids'])==list(ids),'Axolotl/rendered token mismatch; no silent truncation permitted')
        labels=encoded['labels']
        require(len(labels)==len(ids),'Token/label length mismatch')
        return dict(processed_tokens=len(ids),loss_tokens=sum(label!=-100 for label in labels[1:]))
    sources=[a.browser,*([a.replay] if a.replay else []),*a.protected]
    source_hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    rows,report=mix(read(a.browser),read(a.replay) if a.replay else [],measure,
                    replay_fraction=a.replay_fraction,tolerance=a.tolerance,seed=a.seed,
                    protected=[row for path in a.protected for row in read(path)])
    require(all(hashlib.sha256(path.read_bytes()).hexdigest()==source_hashes[str(path)] for path in sources),
            'Input changed during preparation')
    raw=''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows)
    report.update(model='Qwen/Qwen3.8-27B',model_revision=REVISION,tokenizer_assets=ASSETS,
                  axolotl_version=importlib.metadata.version('axolotl'),source_sha256=source_hashes,
                  sequence_len=a.sequence_len,chat_template_kwargs=options,roles_to_train=['assistant'],train_on_eos='turn',
                  output_sha256=hashlib.sha256(raw.encode()).hexdigest(),training_performed=False)
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'mixed.jsonl').write_text(raw)
    atomic_json(a.output/'manifest.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in {'examples','tokenizer_assets','source_sha256'}},indent=2))


if __name__=='__main__': main()
