#!/usr/bin/env python3
"""Check an `axolotl preprocess` output for a replay mix against its manifest.json.

    check_prepared.py PREPARED_DIR MANIFEST_JSON

Asserts: row count = browser + replay documents; total processed and loss tokens equal the
manifest; non-thinking replay rows (no tool schema) contain no "Reasoning effort" system text,
contain the empty think block, and never supervise <think>/</think>; browser rows keep the
thinking-mode system text. Run with the training env python (CPU).
"""
import glob
import json
import os
import sys

os.environ.update(HF_HUB_OFFLINE='1', CUDA_VISIBLE_DEVICES='')
import datasets  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

TOK_DIR = '/home/bjorn/code/LLM_proj_uu/training/.cache/qwen38-tokenizer'


def main():
    prep, man = sys.argv[1], json.load(open(sys.argv[2]))
    paths = [os.path.dirname(p) for p in glob.glob(os.path.join(prep, '**', 'dataset_info.json'), recursive=True)]
    assert paths, f'no saved dataset under {prep}'
    ds = datasets.concatenate_datasets([datasets.load_from_disk(p) for p in paths])
    tok = AutoTokenizer.from_pretrained(TOK_DIR, local_files_only=True)
    think_open, think_close = tok.convert_tokens_to_ids('<think>'), tok.convert_tokens_to_ids('</think>')
    s = man['side_by_side']
    n_b, n_r = s['documents']['browser'], s['documents']['replay']
    proc = loss = 0
    counts = {'browser': 0, 'replay_nothink': 0, 'replay_think': 0}
    for row in ds:
        ids, labels = row['input_ids'], row['labels']
        proc += len(ids)
        loss += sum(t != -100 for t in labels[1:])
        text = tok.decode(ids)
        if '<tools>' in text and 'USER GOAL' in text:
            counts['browser'] += 1
            assert 'Reasoning effort is set to xhigh' in text
        elif man['render'] == 'nothink':
            counts['replay_nothink'] += 1
            assert 'Reasoning effort' not in text, 'non-thinking replay row carries the thinking system text'
            assert '<think>\n\n</think>\n\n' in text
            sup = [t for t, l in zip(ids, labels) if l != -100]
            assert think_open not in sup and think_close not in sup, 'think block is supervised'
        else:
            counts['replay_think'] += 1
    assert len(ds) == n_b + n_r, (len(ds), n_b, n_r)
    assert counts['browser'] == n_b, counts
    assert proc == s['processed_tokens']['browser'] + s['processed_tokens']['replay'], proc
    assert loss == s['loss_tokens']['browser'] + s['loss_tokens']['replay'], loss
    print(json.dumps({'rows': len(ds), **counts, 'processed_tokens': proc, 'loss_tokens': loss, 'passed': True}))


if __name__ == '__main__':
    main()
