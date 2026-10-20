#!/usr/bin/env python3
"""Stage 3: choose a ~2M-token training file from the Qwen train windows of one length.

  select_primary.py 16   -> data/train.qwen.primary16k.jsonl  (from train.qwen.windows16k.jsonl)
  select_primary.py 64   -> data/train.qwen.long64k.jsonl     (from train.qwen.windows64k.jsonl:
                            whole episodes <= 64k, longer ones as most-recent-turn windows)

Budget (processed tokens, rendered with the Qwen3.8 template) split TRAPPED_SHARE to
trap-avoiding successes (variant=trapped) and the rest to clean twins; unused clean budget
flows to trapped. Balance: global round-robin over mechanism families (intensity suffix
_light/_medium/_heavy stripped), cell order shuffled with a fixed seed. Each turn a cell offers
its next row; within a cell episodes rotate, and each episode offers its windows in order
  1. the window ending with the episode's final turns (checkout/confirmation/send_msg_to_user),
  2. windows by number of decision-point target turns (check/uncheck/select_option, or reasoning
     about checkout, consent, checkboxes, add-ons, insurance, fees, delivery, budget...),
  3. the rest.
A row that would exceed the remaining budget is skipped (smaller rows from other cells may fit).
"""
import collections
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from build import Measurer  # noqa: E402

SFT = '/home/bjorn/code/LLM_proj_uu/.local/coordination/demo-sprint/sft'
BUDGET = int(os.environ.get('TOKEN_BUDGET', 2_000_000))
TRAPPED_SHARE = 0.8
SEED = 20261020
DECISION_RE = re.compile(r'checkout|place (the )?order|consent|checkbox|uncheck|untick|tick|opt[- ]?in|opt[- ]?out|insurance|'
                         r'protection|subscri|newsletter|add-on|addon|fee|surcharge|delivery option|shipping option|terms|'
                         r'budget|upgrade|substitut|bundle|sponsored|marketing|data shar|privacy', re.I)


def is_decision(m):
    names = {c['function']['name'] for c in m.get('tool_calls') or []}
    if names & {'check', 'uncheck', 'select_option'}:
        return True
    return bool(DECISION_RE.search(m.get('reasoning_content') or ''))


def main():
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    limit = k * 1024
    src = os.path.join(SFT, 'data', f'train.qwen.windows{k}k.jsonl')
    dst = os.path.join(SFT, 'data', f'train.qwen.{"primary" if k == 16 else "long"}{k}k.jsonl')
    meas = Measurer()
    token_index = json.load(open(os.path.join(SFT, 'work', 'row-tokens.json')))
    manifest = {e['id']: e for e in map(json.loads, open(os.path.join(SFT, 'manifest.jsonl')))
                if e['split'] == 'train' and e['model_family'] == 'qwen'}
    by_ep = collections.defaultdict(list)
    for line in open(src):
        r = json.loads(line)
        ep = r['id'].split('#')[0]
        targets = [m for m in r['messages'] if m['role'] == 'assistant' and m.get('training')]
        r['_tokens'] = token_index[r['id']]
        r['_decisions'] = sum(map(is_decision, targets))
        r['_final'] = any(c['function']['name'] == 'send_msg_to_user' for c in r['messages'][-1].get('tool_calls') or [])
        r['_targets'] = len(targets)
        r['_whole'] = r['id'].endswith('#full')
        by_ep[ep].append(r)
    for ws in by_ep.values():
        ws.sort(key=lambda r: (not r['_final'], -r['_decisions'], r['id']))
    cells = collections.defaultdict(list)
    for ep in sorted(by_ep):
        meta = manifest[ep]
        variant = 'clean' if meta['clean'] else 'trapped'
        cells[(variant, re.sub(r'_(light|medium|heavy)$', '', meta['mechanism'] or 'unknown'))].append(ep)
    rng = random.Random(SEED)
    chosen, used_by_cell = [], collections.Counter()
    remaining_total = BUDGET
    for variant in ('clean', 'trapped'):  # clean first so its unused share flows to trapped
        budget = BUDGET * (1 - TRAPPED_SHARE) if variant == 'clean' else remaining_total
        keys = sorted(c for c in cells if c[0] == variant)
        rng.shuffle(keys)
        queues = {c: [list(by_ep[ep]) for ep in cells[c]] for c in keys}
        turn = collections.Counter()
        used = 0
        progress = True
        while progress:
            progress = False
            for c in keys:
                qs = [q for q in queues[c] if q]
                if not qs:
                    continue
                # rotate episodes within the cell; take the first row that fits
                start = turn[c] % len(qs)
                for q in qs[start:] + qs[:start]:
                    r = q[0]
                    if used + r['_tokens'] <= budget:
                        q.pop(0); used += r['_tokens']; chosen.append((c, r)); used_by_cell[c] += r['_tokens']
                        turn[c] += 1; progress = True
                        break
                    q.pop(0)  # cannot fit within the remaining budget; discard
                    progress = True  # queues shrink, so the loop terminates
        remaining_total -= used
    rows = [r for _, r in sorted(chosen, key=lambda x: x[1]['id'])]
    for r in rows:  # re-render every chosen row: exact count within the limit
        n = meas.count(meas.render(r['messages'], json.loads(r['tools'])))
        assert n == r['_tokens'] and n <= limit, (r['id'], n, r['_tokens'])
    with open(dst, 'w') as f:
        for r in rows:
            f.write(json.dumps({k2: v for k2, v in r.items() if not k2.startswith('_')}, ensure_ascii=False) + '\n')
    report = {}
    for c in sorted(cells):
        picked = [r for cc, r in chosen if cc == c]
        report['/'.join(c)] = {'episodes_available': len(cells[c]), 'episodes_used': len({r['id'].split('#')[0] for r in picked}),
                               'rows': len(picked), 'tokens': used_by_cell[c],
                               'target_turns': sum(r['_targets'] for r in picked),
                               'decision_target_turns': sum(r['_decisions'] for r in picked)}
    toks = sorted(r['_tokens'] for r in rows)
    summary = {'file': dst, 'max_sequence_len': limit, 'token_budget': BUDGET, 'rows': len(rows),
               'processed_tokens': sum(toks), 'max_row_tokens': toks[-1], 'median_row_tokens': toks[len(toks) // 2],
               'min_row_tokens': toks[0],
               'whole_episode_rows': sum(r['_whole'] for r in rows), 'window_rows': sum(not r['_whole'] for r in rows),
               'trapped_tokens': sum(v['tokens'] for kk, v in report.items() if kk.startswith('trapped')),
               'clean_tokens': sum(v['tokens'] for kk, v in report.items() if kk.startswith('clean')),
               'episodes': len({r['id'].split('#')[0] for r in rows}),
               'cells_covered': sum(1 for v in report.values() if v['rows']), 'cells_total': len(report),
               'loss_bearing_assistant_turns': sum(r['_targets'] for r in rows),
               'per_suite_rows': dict(collections.Counter(r['id'].split('/')[0] for r in rows)), 'cells': report}
    json.dump(summary, open(os.path.join(SFT, f'selection-{k}k.json'), 'w'), indent=1)
    print(json.dumps({kk: v for kk, v in summary.items() if kk != 'cells'}, indent=1))


if __name__ == '__main__':
    main()
