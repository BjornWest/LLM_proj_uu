#!/usr/bin/env python3
"""Freeze the fixed regression item subsets (run once; base and SFT then see identical items).

Writes data/{gsm8k,ifeval,mmlu_pro}.jsonl and data/MANIFEST.json (dataset, Hub revision at
fetch time, license, split, row indices, seed, file sha256). Only the sampled rows are fetched.
"""
import argparse
import hashlib
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hf_fetch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20261020
SPECS = {
    'gsm8k': ('openai/gsm8k', 'main', 'test', 100),
    'ifeval': ('google/IFEval', 'default', 'train', 100),
    'mmlu_pro': ('TIGER-Lab/MMLU-Pro', 'default', 'test', 200),
}


def gsm8k_item(idx, row):
    final = row['answer'].split('####')[-1].strip().replace(',', '')
    return {'id': f'gsm8k-test-{idx}', 'row_idx': idx, 'question': row['question'], 'answer': final}


def ifeval_item(idx, row):
    return {'id': f'ifeval-{row["key"]}', 'row_idx': idx, 'key': row['key'], 'prompt': row['prompt'],
            'instruction_id_list': row['instruction_id_list'], 'kwargs': row['kwargs']}


def mmlu_item(idx, row):
    return {'id': f'mmlupro-{row["question_id"]}', 'row_idx': idx, 'question': row['question'],
            'options': row['options'], 'answer': row['answer'], 'category': row['category'], 'src': row['src']}


MAKERS = {'gsm8k': gsm8k_item, 'ifeval': ifeval_item, 'mmlu_pro': mmlu_item}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default=os.path.join(HERE, 'data'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    manifest = {'seed': SEED, 'source_api': hf_fetch.API, 'benchmarks': {}}
    for name, (ds, cfg, split, n) in SPECS.items():
        total = hf_fetch.num_rows(ds, cfg, split)
        idxs = sorted(random.Random(f'{SEED}-{name}').sample(range(total), n))
        got = hf_fetch.rows_at(ds, cfg, split, idxs)
        items = [MAKERS[name](i, row) for i, row in got]
        path = os.path.join(a.out, f'{name}.jsonl')
        with open(path, 'w') as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + '\n')
        manifest['benchmarks'][name] = {**hf_fetch.dataset_info(ds), 'config': cfg, 'split': split,
                                        'split_rows': total, 'n': n, 'row_indices': idxs,
                                        'file': os.path.basename(path),
                                        'sha256': hashlib.sha256(open(path, 'rb').read()).hexdigest()}
        if name == 'mmlu_pro':
            cats = {}
            for it in items:
                cats[it['category']] = cats.get(it['category'], 0) + 1
            manifest['benchmarks'][name]['category_counts'] = dict(sorted(cats.items()))
        print(name, n, 'items from', total, flush=True)
    json.dump(manifest, open(os.path.join(a.out, 'MANIFEST.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
