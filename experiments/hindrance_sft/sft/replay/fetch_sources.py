#!/usr/bin/env python3
"""Fetch small, frozen replay pools from the HF Hub (no auth; only the sampled rows).

Outputs (under replay/sources/):
  ultrachat200k.pool.jsonl   PRIMARY external replay (Kotha & Liang 2026 used UltraChat/OpenHermes).
                             HuggingFaceH4/ultrachat_200k train_sft, MIT. Normalized to the
                             Axolotl row schema {"id","tools":"[]","messages":[...]}; text verbatim.
  openhermes25.pool.jsonl    optional alternative (teknium/OpenHermes-2.5; NO license on the Hub card,
                             mixed upstream licenses -> not the default). Only with --openhermes.
  selfgen_prompts.jsonl      prompts for the optional self-generated replay: the first user turn of
                             every UltraChat pool row (same order, so the self-generated and external
                             variants can pick the same conversations) + tool-use prompts
                             (nvidia/Nemotron-Post-Training-Dataset-v1 tool_calling, CC-BY-4.0:
                             first user turn + its native tool schemas).
  SOURCES.json               dataset ids, Hub revision at fetch time, license, split, row indices, seeds,
                             sha256 of every output, and the regression-disjointness check.

Any pool row with an 8-word shingle shared with a frozen regression item (GSM8K/IFEval/MMLU-Pro,
regression/data/*.jsonl) is dropped and recorded.
"""
import argparse
import ast
import hashlib
import json
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(os.path.dirname(HERE), 'regression')
sys.path.insert(0, REG)
import hf_fetch  # noqa: E402

SEED = 20261020


def shingles(text, n=8):
    w = re.findall(r'[a-z0-9]+', text.lower())
    return {' '.join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def regression_shingles():
    out = set()
    for name in ('gsm8k', 'ifeval', 'mmlu_pro'):
        for line in open(os.path.join(REG, 'data', f'{name}.jsonl')):
            it = json.loads(line)
            text = it.get('question') or it.get('prompt') or ''
            if it.get('options'):
                text += ' ' + ' '.join(it['options'])
            out |= shingles(text)
    return out


def fetch_individual(ds, cfg, split, idxs):
    got = []
    for i in idxs:
        got.append(hf_fetch.rows(ds, cfg, split, i, 1)[0])
        time.sleep(0.4)
    return got


def ultrachat_row(idx, row):
    msgs = row['messages']
    roles = [m['role'] for m in msgs]
    ok = (len(msgs) >= 2 and roles[-1] == 'assistant' and all(m['content'] and m['content'].strip() for m in msgs)
          and all(r == ('user' if k % 2 == 0 else 'assistant') for k, r in enumerate(roles)))
    if not ok:
        return None
    return {'id': f'replay/ultrachat200k/train_sft/{idx}', 'tools': '[]',
            'messages': [{'role': m['role'], 'content': m['content']} for m in msgs]}


def openhermes_row(idx, row):
    conv = row['conversations']
    if isinstance(conv, str):
        conv = ast.literal_eval(conv)
    role = {'system': 'system', 'human': 'user', 'gpt': 'assistant'}
    msgs = []
    for k, m in enumerate(conv):
        r = role.get(m.get('from'))
        if r is None or not (m.get('value') or '').strip():
            return None
        msgs.append({'role': r, 'content': m['value']})
    if not msgs or msgs[-1]['role'] != 'assistant' or not any(m['role'] == 'user' for m in msgs):
        return None
    return {'id': f'replay/openhermes25/train/{idx}', 'tools': '[]', 'messages': msgs}


def nemotron_tool_prompt(idx, row):
    meta = row['metadata']
    meta = json.loads(meta) if isinstance(meta, str) else meta
    tools = meta.get('tools') or []
    first = row['messages'][0]
    if row.get('reasoning') != 'on' or first['role'] != 'user' or not tools:
        return None
    return {'id': f'selfgen-prompt/nemotron-v1-tool_calling/{idx}', 'source': 'nvidia/Nemotron-Post-Training-Dataset-v1',
            'tools': json.dumps(tools, ensure_ascii=False), 'messages': [{'role': 'user', 'content': first['content']}]}


def write(path, rows):
    with open(path, 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def pool(name, ds, cfg, split, n, maker, out, record, banned):
    total = hf_fetch.num_rows(ds, cfg, split)
    idxs = sorted(random.Random(f'{SEED}-{name}').sample(range(total), n))
    got = fetch_individual(ds, cfg, split, idxs)
    rows, malformed, overlap = [], [], []
    for i, row in got:
        r = maker(i, row)
        if r is None:
            malformed.append(i)
            continue
        if shingles(' '.join(m['content'] for m in r['messages'] if m['role'] != 'assistant')) & banned:
            overlap.append(i)
            continue
        rows.append(r)
    # deterministic training order: shuffled once with the seed; mixers take prefixes of this order
    random.Random(f'{SEED}-{name}-order').shuffle(rows)
    sha = write(out, rows)
    record[name] = {**hf_fetch.dataset_info(ds), 'config': cfg, 'split': split, 'split_rows': total,
                    'sampled_indices': idxs, 'kept': len(rows), 'dropped_malformed': malformed,
                    'dropped_regression_overlap': overlap, 'file': os.path.basename(out), 'sha256': sha}
    print(name, 'kept', len(rows), 'of', n, 'malformed', len(malformed), 'overlap', len(overlap), flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(HERE, 'sources'))
    ap.add_argument('--ultrachat', type=int, default=320)
    ap.add_argument('--tool-prompts', type=int, default=60)
    ap.add_argument('--openhermes', type=int, default=0, help='also fetch an OpenHermes-2.5 pool of this size')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    banned = regression_shingles()
    record = {'seed': SEED, 'source_api': hf_fetch.API, 'fetched_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'regression_disjointness': '8-word shingle overlap with regression/data/{gsm8k,ifeval,mmlu_pro}.jsonl '
                                         'prompts/options -> row dropped', 'pools': {}}
    uc = pool('ultrachat200k', 'HuggingFaceH4/ultrachat_200k', 'default', 'train_sft', a.ultrachat,
              ultrachat_row, os.path.join(a.out, 'ultrachat200k.pool.jsonl'), record['pools'], banned)
    if a.openhermes:
        pool('openhermes25', 'teknium/OpenHermes-2.5', 'default', 'train', a.openhermes, openhermes_row,
             os.path.join(a.out, 'openhermes25.pool.jsonl'), record['pools'], banned)
    # self-generation prompts: UltraChat first user turns (same order as the pool) + Nemotron tool prompts
    ds, cfg, split = 'nvidia/Nemotron-Post-Training-Dataset-v1', 'default', 'tool_calling'
    total = hf_fetch.num_rows(ds, cfg, split)
    idxs = sorted(random.Random(f'{SEED}-nemotron-tools').sample(range(total), a.tool_prompts * 2))
    tools = []
    for i, row in fetch_individual(ds, cfg, split, idxs):
        p = nemotron_tool_prompt(i, row)
        if p and not (shingles(p['messages'][0]['content']) & banned) and len(tools) < a.tool_prompts:
            tools.append(p)
    prompts = [{'id': r['id'].replace('replay/', 'selfgen-prompt/'), 'source': 'HuggingFaceH4/ultrachat_200k',
                'tools': '[]', 'messages': [r['messages'][0]]} for r in uc] + tools
    sha = write(os.path.join(a.out, 'selfgen_prompts.jsonl'), prompts)
    record['pools']['nemotron_v1_tool_calling_prompts'] = {
        **hf_fetch.dataset_info(ds), 'config': cfg, 'split': split, 'split_rows': total, 'sampled_indices': idxs,
        'kept': len(tools), 'use': 'first user turn + tool schemas only (prompts for self-generation)'}
    record['selfgen_prompts'] = {'file': 'selfgen_prompts.jsonl', 'sha256': sha, 'ultrachat_prompts': len(uc),
                                 'tool_prompts': len(tools)}
    json.dump(record, open(os.path.join(a.out, 'SOURCES.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
