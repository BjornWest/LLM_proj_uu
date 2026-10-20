#!/usr/bin/env python3
"""Compare two regression runs (e.g. base vs qwen-sft): per-benchmark scores with bootstrap 95% CIs.

    compare.py BASE_DIR SFT_DIR [--out comparison.md]

Per-model CIs: percentile bootstrap over items. Delta CI: paired bootstrap over items
present (status ok) in both runs. IFEval instruction-level accuracy resamples prompts
(cluster bootstrap). Truncated answers count as wrong; truncation counts are shown.
"""
import argparse
import json
import os

import numpy as np

METRICS = [  # (bench, label, per-row value function)
    ('gsm8k', 'GSM8K accuracy', lambda r: [float(r['correct'])]),
    ('ifeval', 'IFEval prompt-strict', lambda r: [float(r['prompt_strict'] and not r['truncated'])]),
    ('ifeval', 'IFEval inst-strict', lambda r: [0.0] * len(r['inst_strict']) if r['truncated'] else [float(x) for x in r['inst_strict']]),
    ('mmlu_pro', 'MMLU-Pro accuracy', lambda r: [float(r['correct'])]),
]


def load(d, bench):
    p = os.path.join(d, f'{bench}.jsonl')
    if not os.path.exists(p):
        return {}
    return {r['id']: r for r in map(json.loads, open(p)) if r.get('status') == 'ok'}


def stat(vals):  # vals: list of per-item lists -> pooled mean
    tot = sum(len(v) for v in vals)
    return sum(sum(v) for v in vals) / tot if tot else float('nan')


def boot(vals_a, vals_b, n_boot, rng):
    n = len(vals_a)
    sa = np.array([sum(v) for v in vals_a]); ca = np.array([len(v) for v in vals_a])
    sb = np.array([sum(v) for v in vals_b]); cb = np.array([len(v) for v in vals_b])
    idx = rng.integers(0, n, size=(n_boot, n))
    ma = sa[idx].sum(1) / ca[idx].sum(1)
    mb = sb[idx].sum(1) / cb[idx].sum(1)
    q = lambda x: (float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5)))  # noqa: E731
    return q(ma), q(mb), q(mb - ma)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('base')
    ap.add_argument('sft')
    ap.add_argument('--out')
    ap.add_argument('--boot', type=int, default=10000)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    names = []
    for d in (a.base, a.sft):
        s = os.path.join(d, 'summary.json')
        names.append(json.load(open(s))['model'] if os.path.exists(s) else os.path.basename(d.rstrip('/')))
    lines = [f'# Generic regression: {names[0]} (A) vs {names[1]} (B)', '',
             f'Paired percentile bootstrap, {a.boot} resamples over items; 95% CIs. Truncated = wrong.', '',
             '| metric | n paired | A | B | B − A | A trunc | B trunc | A mean out tok | B mean out tok |',
             '|---|---|---|---|---|---|---|---|---|']
    result = {'a': names[0], 'b': names[1], 'metrics': {}}
    for bench, label, fn in METRICS:
        A, B = load(a.base, bench), load(a.sft, bench)
        ids = sorted(set(A) & set(B))
        if not ids:
            continue
        va, vb = [fn(A[i]) for i in ids], [fn(B[i]) for i in ids]
        ca, cb, cd = boot(va, vb, a.boot, rng)
        ma, mb = stat(va), stat(vb)
        ta, tb = sum(A[i]['truncated'] for i in ids), sum(B[i]['truncated'] for i in ids)
        oa = np.mean([A[i]['completion_tokens'] or 0 for i in ids]); ob = np.mean([B[i]['completion_tokens'] or 0 for i in ids])
        lines.append(f'| {label} | {len(ids)} | {ma:.3f} [{ca[0]:.3f}, {ca[1]:.3f}] | {mb:.3f} [{cb[0]:.3f}, {cb[1]:.3f}] | '
                     f'{mb - ma:+.3f} [{cd[0]:+.3f}, {cd[1]:+.3f}] | {ta} | {tb} | {oa:.0f} | {ob:.0f} |')
        result['metrics'][label] = {'n': len(ids), 'a': ma, 'a_ci': ca, 'b': mb, 'b_ci': cb, 'delta': mb - ma,
                                    'delta_ci': cd, 'a_truncated': ta, 'b_truncated': tb,
                                    'a_mean_out_tokens': float(oa), 'b_mean_out_tokens': float(ob),
                                    'unpaired_a_only': len(set(A) - set(B)), 'unpaired_b_only': len(set(B) - set(A))}
    lines += ['', 'A delta CI that excludes 0 is a detectable change at this sample size; n=100-200 only detects '
              'large regressions (roughly 8-12 points).']
    text = '\n'.join(lines)
    print(text)
    if a.out:
        open(a.out, 'w').write(text + '\n')
        json.dump(result, open(os.path.splitext(a.out)[0] + '.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
