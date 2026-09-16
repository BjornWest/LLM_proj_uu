#!/usr/bin/env python3
"""Actual Axolotl NF4 GPU SFT probe; called by modal_training.py in a subprocess."""
import argparse
import gc
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot', required=True)
    p.add_argument('--sequence-len', type=int, choices=[1024, 2048], default=1024)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    import torch
    import yaml
    from transformers import AutoTokenizer
    from axolotl.cli.config import load_cfg
    from axolotl.common.datasets import load_datasets
    from axolotl.train import train
    from browser_training.dataset import convert_trajectory
    from browser_training.precision import inspect_dtypes, inspect_nf4, inspect_optimizer
    from check_adapter_dtypes import check

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    tokenizer = AutoTokenizer.from_pretrained(args.snapshot, local_files_only=True)
    rows = []
    for i in range(8):
        # Real conversation converter; ~512 tokens to qualify kernels before
        # spending the short debugging allowance on longer contexts.
        repeats = 24 if args.sequence_len == 1024 else 132
        observation = ('[1] button Continue. [2] checkbox optional addon unchecked. ' * repeats)
        rows.extend(convert_trajectory({'task': f'Click Continue, leave addon unchecked. Trial {i}.',
            'success': True, 'steps': [{'observation': observation, 'action': "click('1')"}]}))
    data = output / 'data.jsonl'
    data.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    cfg = yaml.safe_load(Path('configs/sft_qwen38_27b_nf4_qlora.yml').read_text())
    cfg.update(base_model=args.snapshot, revision_of_model=None, output_dir=str(output),
        dataset_prepared_path=str(output / 'prepared'), sequence_len=args.sequence_len,
        max_steps=2, save_steps=1, gradient_accumulation_steps=1,
        dataset_num_proc=1, dataloader_num_workers=0,
        use_wandb=False, use_mlflow=False, use_tensorboard=False)
    cfg['datasets'][0]['path'] = str(data)
    resolved = output / 'resolved.yml'
    resolved.write_text(yaml.safe_dump(cfg, sort_keys=False))
    cfg = load_cfg(str(resolved))
    dataset = load_datasets(cfg=cfg)
    lengths = [len(row['input_ids']) for row in dataset.train_dataset]
    assert len(lengths) == 8 and min(lengths) > 256
    assert all(any(v != -100 for v in row['labels']) and any(v == -100 for v in row['labels'])
        for row in dataset.train_dataset)
    del tokenizer
    torch.cuda.reset_peak_memory_stats()
    model, tokenizer, trainer = train(cfg, dataset)
    assert trainer.state.global_step == 2
    assert all(not p.requires_grad for n, p in model.named_parameters() if '.visual.' in n)
    report = dict(status='PASS', scope='27B NF4 Axolotl GPU SFT; no RL server/synchronization',
        gpu=torch.cuda.get_device_name(), capability=torch.cuda.get_device_capability(),
        torch_cuda=torch.version.cuda, sequence_lengths=lengths,
        last_allocator_interval_peak_gib=torch.cuda.max_memory_allocated()/2**30,
        peak_reserved_gib=torch.cuda.max_memory_reserved()/2**30,
        dtypes=inspect_dtypes(model), nf4=inspect_nf4(model),
        fp32_moment_tensors=inspect_optimizer(trainer.optimizer),
        checkpoint=check(output / 'checkpoint-2'), history=trainer.state.log_history,
        packages={n: metadata.version(n) for n in ['axolotl','torch','transformers','peft','bitsandbytes','flash-linear-attention']},
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    for name in ['trainer_state.json', 'optimizer.pt', 'scheduler.pt', 'rng_state.pth']:
        assert (output / 'checkpoint-2' / name).is_file(), name
    (output / 'sft-report.json').write_text(json.dumps(report, indent=2))
    # Re-use the model but reload all Trainer checkpoint state and the adapter.
    # A cold base reload is separately covered by local CPU validation.
    from safetensors import safe_open
    with safe_open(output / 'checkpoint-1/adapter_model.safetensors', framework='pt', device='cpu') as saved:
        key = next(k for k in saved.keys() if 'lora_B' in k)
        before = saved.get_tensor(key).clone()
    # Resume an INTERMEDIATE checkpoint: the original two-step schedule still
    # has a nonzero learning rate. Resuming its final checkpoint tests a no-op.
    trainer.train(resume_from_checkpoint=str(output / 'checkpoint-1'))
    assert trainer.state.global_step == 2
    with safe_open(output / 'checkpoint-2/adapter_model.safetensors', framework='pt', device='cpu') as saved:
        delta = (saved.get_tensor(key).float() - before.float()).abs().max().item()
    assert delta > 0, 'Resume failed to change the adapter'
    report['resume'] = dict(step=2, from_checkpoint=1, adapter_max_abs_change=delta,
        checked_adapter_tensor=key, dtypes=inspect_dtypes(model),
        fp32_moment_tensors=inspect_optimizer(trainer.optimizer),
        checkpoint=check(output / 'checkpoint-2'), history=trainer.state.log_history)
    report['max_logged_allocated_gib'] = max(row.get('memory/max_allocated (GiB)', 0)
        for row in report['history'] + report['resume']['history'])
    report['elapsed_seconds'] = time.monotonic() - started
    (output / 'sft-report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
    del model, trainer, tokenizer
    gc.collect()


if __name__ == '__main__':
    main()
