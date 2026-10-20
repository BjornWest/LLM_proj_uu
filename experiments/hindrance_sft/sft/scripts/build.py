#!/usr/bin/env python3
"""Stage 2: dedup, cap, split, tokenize and write Axolotl chat_template datasets.

Run with the SFT env (transformers installed, offline):
  HF_HUB_OFFLINE=1 /home/bjorn/code/LLM_proj_uu/training/envs/sft/.venv/bin/python scripts/build.py

Tokenizer: Qwen/Qwen3.8-27B tokenizer.json + chat_template.jinja (sha256-checked; identical to
hindrance-run8 assets and training/.cache/qwen38-tokenizer). Rendering uses
enable_thinking=True, preserve_thinking=True, tools=<recorded tools>, i.e. the run_sft.py
--enable-thinking path with the NF4 config's preserve_thinking.

Row format (Axolotl `type: chat_template`, field_messages=messages, roles_to_train=[assistant]):
  {"id": str, "tools": <JSON string of the recorded tool list>, "messages": [...]}
  assistant messages: content (str|null), reasoning_content (str|null),
                      tool_calls [{id,type,function:{name, arguments:<JSON string>}}] (Axolotl json.loads them)
  window rows additionally carry per-message "training": true/false (message_field_training: training)
Tools and tool arguments are JSON strings on purpose: Arrow would otherwise union the
heterogeneous argument/parameter schemas and inject nulls.
"""
import collections
import hashlib
import json
import os
import random
import statistics
import sys

os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
from transformers import AutoTokenizer  # noqa: E402

SFT = '/home/bjorn/code/LLM_proj_uu/.local/coordination/demo-sprint/sft'
TOK_DIR = '/home/bjorn/code/LLM_proj_uu/training/.cache/qwen38-tokenizer'
SPEC_TOKENIZER = ('/home/bjorn/code/LLM_proj_uu-worktrees/hindrance-run8-20261020/.local/'
                  'website-38-concept-world-20261006-v1/assets/tokenizer.json')
EXPECTED = {'tokenizer.json': '0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3',
            'chat_template.jinja': 'c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041'}
TEMPLATE_KW = dict(enable_thinking=True, preserve_thinking=True)
CAP_SHARE = 0.15
WINDOW_LENS = (65536, 32768, 16384)
TARGET_FRACTION = 0.5  # max share of a window's budget spanned by loss-bearing turns (rest = history)
NEAR_DUP_JACCARD = 0.9
SEED = 20261020


def sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def for_template(messages):
    """Copy with tool-call arguments parsed (the Qwen template iterates arguments|items)."""
    out = []
    for m in messages:
        m = {k: v for k, v in m.items() if k != 'training'}
        if m.get('tool_calls'):
            m['tool_calls'] = [{**c, 'function': {**c['function'], 'arguments': json.loads(c['function']['arguments'])}}
                               for c in m['tool_calls']]
        out.append(m)
    return out


class Measurer:
    def __init__(self):
        for name, digest in EXPECTED.items():
            assert sha(os.path.join(TOK_DIR, name)) == digest, name
        assert sha(SPEC_TOKENIZER) == EXPECTED['tokenizer.json']
        self.tok = AutoTokenizer.from_pretrained(TOK_DIR, local_files_only=True)

    def render(self, messages, tools, **kw):
        return self.tok.apply_chat_template(for_template(messages), tools=tools, tokenize=False, **TEMPLATE_KW, **kw)

    def count(self, text):
        return len(self.tok(text, add_special_tokens=False)['input_ids'])

    def segments(self, messages, tools):
        """Token counts: prefix (system+user) and per assistant unit (assistant + following tool results)."""
        text = self.render(messages, tools)
        marker = '<|im_start|>assistant\n'
        pieces = text.split(marker)
        prefix = pieces[0]
        units = [marker + p for p in pieces[1:]]
        n_asst = sum(m['role'] == 'assistant' for m in messages)
        assert len(units) == n_asst, (len(units), n_asst)
        counts = [self.count(prefix)] + [self.count(u) for u in units]
        total = self.count(text)
        # BPE never merges across the <|im_start|> special token, so segment counts are additive
        assert sum(counts) == total, (sum(counts), total)
        asst_counts = []
        for u in units:
            a_end = u.index('<|im_end|>') + len('<|im_end|>\n')  # template emits '<|im_end|>\n'
            asst_counts.append(self.count(u[:a_end]))
        return total, counts, asst_counts


def action_signature(messages):
    sig = []
    for m in messages:
        if m['role'] == 'assistant':
            for c in m.get('tool_calls') or []:
                sig.append(c['function']['name'] + ':' + c['function']['arguments'])
    return sig


def jaccard(a, b):
    a, b = set(zip(a, a[1:])), set(zip(b, b[1:]))
    return len(a & b) / max(1, len(a | b))


def cell_of(meta):
    return meta.get('mechanism') or 'unknown'


def units_of(messages):
    """Indices: [system, user] prefix, then units starting at each assistant message."""
    starts = [i for i, m in enumerate(messages) if m['role'] == 'assistant']
    bounds = starts + [len(messages)]
    return [(bounds[k], bounds[k + 1]) for k in range(len(starts))]


def make_windows(ex, seg, limit):
    messages = ex['messages']
    prefix_tokens, unit_tokens = seg['counts'][0], seg['counts'][1:]
    asst_tokens = seg['asst_counts']
    units = units_of(messages)
    n = len(units)
    budget = limit - prefix_tokens
    target_budget = int(budget * TARGET_FRACTION)
    windows, t, dropped = [], 0, 0
    while t < n:
        # window ends on assistant e; its trailing tool results are cut (no loss after it)
        def cost(s, e):
            return sum(unit_tokens[s:e]) + asst_tokens[e]
        if cost(t, t) > budget:
            dropped += 1; t += 1; continue
        e = t
        # targets t..e: the loss-bearing span (assistant turns + their tool results) is capped
        # at TARGET_FRACTION of the window, so the rest holds the most recent history
        while e + 1 < n and cost(t, e + 1) <= target_budget:
            e += 1
        s = t
        while s > 0 and cost(s - 1, e) <= budget:
            s -= 1
        msgs = list(messages[:2])
        for k in range(s, e + 1):
            a, b = units[k]
            if k == e:
                b = a + 1
            for i in range(a, b):
                m = dict(messages[i])
                if m['role'] == 'assistant':
                    m['training'] = k >= t
                msgs.append(m)
        windows.append({'messages': msgs, 'context_from_turn': s, 'target_turns': [t, e],
                        'expected_tokens': prefix_tokens + cost(s, e)})
        t = e + 1
    return windows, dropped


def dump(path, rows):
    with open(path, 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def row_of(ex_id, messages, tools):
    return {'id': ex_id, 'tools': json.dumps(tools, ensure_ascii=False), 'messages': messages}


def dist(xs):
    if not xs:
        return {}
    xs = sorted(xs)
    q = lambda p: xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))]
    return {'n': len(xs), 'min': xs[0], 'p10': q(.1), 'p25': q(.25), 'median': q(.5), 'p75': q(.75),
            'p90': q(.9), 'max': xs[-1], 'mean': round(statistics.mean(xs)), 'sum': sum(xs),
            'over_16k': sum(x > 16384 for x in xs), 'over_32k': sum(x > 32768 for x in xs),
            'over_64k': sum(x > 65536 for x in xs), 'over_128k': sum(x > 131072 for x in xs)}


def main():
    meas = Measurer()
    cands = [json.loads(l) for l in open(os.path.join(SFT, 'work', 'candidates.jsonl'))]
    report = {'tokenizer': {'name': 'Qwen/Qwen3.8-27B (revision 1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0)',
                            'tokenizer_json': SPEC_TOKENIZER, 'tokenizer_sha256': EXPECTED['tokenizer.json'],
                            'chat_template_sha256': EXPECTED['chat_template.jinja'],
                            'render_kwargs': TEMPLATE_KW, 'tools_rendered_in_system': True}}
    # --- measure everything
    for ex in cands:
        total, counts, asst = meas.segments(ex['messages'], ex['tools'])
        ex['seg'] = {'total': total, 'counts': counts, 'asst_counts': asst}
        ex['meta']['tokens_full'] = total
        ex['meta']['loss_tokens_full_approx'] = sum(asst)  # assistant turn incl. header; Axolotl masks header
        ex['meta']['assistant_turns'] = len(asst)
    # --- screenshot episodes: the model saw image tokens that a text-only SFT run cannot feed;
    # its later reasoning may describe the picture. Excluded from all output files.
    image_log = [c['meta']['episode_dir'] for c in cands if c['meta']['conversation_stats']['image_parts']]
    cands = [c for c in cands if not c['meta']['conversation_stats']['image_parts']]
    report['image_exclusion'] = {'rule': 'episodes containing screenshot image parts are excluded', 'dropped': len(image_log), 'episodes': image_log}
    # --- dedup (within split+source, same task_id: identical or near-identical action sequences)
    dedup_log = []
    groups = collections.defaultdict(list)
    for ex in cands:
        m = ex['meta']
        groups[(m['source'].split('-')[0], m['task_id'])].append(ex)
    kept = []
    for key, exs in groups.items():
        exs.sort(key=lambda e: (e['meta']['tokens_full'], e['meta']['episode_dir']))
        chosen = []
        for ex in exs:
            sig = action_signature(ex['messages'])
            dup = None
            for c in chosen:
                csig = action_signature(c['messages'])
                if sig == csig or jaccard(sig, csig) >= NEAR_DUP_JACCARD:
                    dup = c; break
            if dup:
                dedup_log.append({'dropped': ex['meta']['episode_dir'], 'kept': dup['meta']['episode_dir'],
                                  'task_id': key[1], 'jaccard_bigram': round(jaccard(sig, action_signature(dup['messages'])), 3)})
            else:
                chosen.append(ex)
        kept.extend(chosen)
    report['dedup'] = {'rule': f'same model family + task_id, action-bigram Jaccard >= {NEAR_DUP_JACCARD} or identical',
                       'dropped': len(dedup_log), 'log': dedup_log}
    # --- partition
    by = collections.defaultdict(list)
    for ex in kept:
        fam = 'qwen' if ex['meta']['source'].startswith('qwen') else 'sol'
        by[(fam, ex['meta']['split'])].append(ex)
    # --- per-cell cap on Qwen train (cell = mechanism; trapped and clean twins counted together)
    rng = random.Random(SEED)
    cap_log = {}
    def cap(exs, label):
        exs = sorted(exs, key=lambda e: e['meta']['episode_dir'])
        for _ in range(100):
            cnt = collections.Counter(cell_of(e['meta']) for e in exs)
            n = len(exs)
            limit = max(1, int(CAP_SHARE * n))
            over = [c for c, k in cnt.items() if k > limit]
            if not over:
                break
            c = max(over, key=lambda c: cnt[c])
            members = [e for e in exs if cell_of(e['meta']) == c]
            rng.shuffle(members)
            # drop one at a time (dropping changes n); prefer dropping longest-duplicate-world first
            members.sort(key=lambda e: -sum(1 for x in exs if x['meta']['world_id'] == e['meta']['world_id']))
            victim = members[0]
            exs.remove(victim)
            cap_log.setdefault(label, []).append({'cell': c, 'dropped': victim['meta']['episode_dir']})
        return exs
    by[('qwen', 'train')] = cap(by[('qwen', 'train')], 'qwen-train')
    by[('sol', 'train')] = cap(by[('sol', 'train')], 'sol-train')
    report['cap'] = {'rule': f'cell = mechanism; no cell above {int(CAP_SHARE * 100)}% of the split (iteratively drops, seed {SEED})',
                     'dropped': {k: len(v) for k, v in cap_log.items()}, 'log': cap_log}
    # --- leakage check
    def ids(exs, key):
        return {e['meta'][key] for e in exs}
    train_all = by[('qwen', 'train')] + by[('sol', 'train')]
    test_all = by[('qwen', 'test')] + by[('sol', 'test')]
    report['leakage'] = {
        'task_id_overlap_train_vs_test': sorted(ids(train_all, 'task_id') & ids(test_all, 'task_id')),
        'world_id_overlap_train_vs_test_selected': sorted(ids(train_all, 'world_id') & ids(test_all, 'world_id')),
        'mechanism_overlap_train_vs_test_selected': sorted(ids(train_all, 'mechanism') & ids(test_all, 'mechanism')),
    }
    # all test-suite tasks/worlds regardless of success (what a later eval reruns)
    inv = json.load(open(os.path.join(SFT, 'work', 'inventory.json')))
    test_inv = [r for r in inv if r.get('split') == 'test' and r.get('task_id')]
    train_inv = [r for r in inv if r.get('split') == 'train' and r.get('task_id')]
    report['leakage']['task_id_overlap_all_train_vs_all_test_suites'] = sorted(ids_all := ({r['task_id'] for r in train_inv} & {r['task_id'] for r in test_inv}))
    wshared = sorted({r['world_id'] for r in train_inv} & {r['world_id'] for r in test_inv})
    report['leakage']['world_id_overlap_all_train_vs_all_test_suites'] = [
        {'world_id': w, 'seed_concept': sorted({f"{r['seed']}-{r['concept']}" for r in inv if r.get('world_id') == w}),
         'train_suites': sorted({r['suite'] for r in train_inv if r['world_id'] == w}),
         'test_suites': sorted({r['suite'] for r in test_inv if r['world_id'] == w}),
         'selected_train_examples': sum(1 for e in train_all if e['meta']['world_id'] == w)} for w in wshared]
    # test task list for re-running
    test_tasks = {}
    for r in test_inv:
        t = test_tasks.setdefault(r['task_id'], {'task_id': r['task_id'], 'suite': r['suite'], 'mechanism': r.get('mechanism'),
                                                  'variant': r.get('variant'), 'clean': r.get('clean'), 'world_id': r.get('world_id'),
                                                  'seed': r.get('seed'), 'concept': r.get('concept'), 'family': r.get('family'),
                                                  'request_text': r.get('request_text'), 'episodes': []})
        t['episodes'].append({'cohort': r['cohort'], 'episode_dir': r['episode_dir'], 'model': r.get('model'),
                              'order_status': r.get('order_status'), 'authorization_satisfied': r.get('authorization_satisfied'),
                              'stop_reason': r.get('stop_reason'), 'verdict': r.get('verdict')})
    # --- write datasets
    data = os.path.join(SFT, 'data'); os.makedirs(data, exist_ok=True)
    splits = os.path.join(SFT, 'splits'); os.makedirs(splits, exist_ok=True)
    manifest, stats, token_index = [], {}, {}
    for (fam, split), exs in sorted(by.items()):
        exs.sort(key=lambda e: e['meta']['episode_dir'])
        full_rows, win_rows = [], {L: [] for L in WINDOW_LENS}
        win_dropped = {L: 0 for L in WINDOW_LENS}
        win_tokens = {L: [] for L in WINDOW_LENS}
        for ex in exs:
            m = ex['meta']
            ex_id = f"{m['suite']}/{m['cohort']}/{os.path.basename(m['episode_dir'])}"
            full_rows.append(row_of(ex_id, ex['messages'], ex['tools']))
            entry = {'id': ex_id, **{k: m.get(k) for k in ('suite', 'cohort', 'source', 'model', 'task_id', 'world_id', 'seed',
                     'concept', 'mechanism', 'variant', 'clean', 'family', 'tier', 'turns', 'tokens_full', 'assistant_turns',
                     'loss_tokens_full_approx', 'episode_dir', 'run_dir', 'conversation_stats')}}
            for L in WINDOW_LENS:
                if ex['seg']['total'] <= L:
                    msgs = [dict(x, training=True) if x['role'] == 'assistant' else x for x in ex['messages']]
                    win_rows[L].append(row_of(ex_id + '#full', msgs, ex['tools']))
                    token_index[ex_id + '#full'] = ex['seg']['total']
                    entry[f'windows_{L}'] = 0
                    win_tokens[L].append(ex['seg']['total'])
                    continue
                ws, dropped = make_windows(ex, ex['seg'], L)
                win_dropped[L] += dropped
                entry[f'windows_{L}'] = len(ws)
                for k, w in enumerate(ws):
                    wid = f'{ex_id}#w{k}:{w["target_turns"][0]}-{w["target_turns"][1]}'
                    win_rows[L].append(row_of(wid, w['messages'], ex['tools']))
                    token_index[wid] = w['expected_tokens']
                    win_tokens[L].append(w['expected_tokens'])
            manifest.append({'model_family': fam, 'split': split, **entry})
        base = f'{split}.{fam}'
        dump(os.path.join(data, f'{base}.full.jsonl'), full_rows)
        if split != 'excluded':
            for L in WINDOW_LENS:
                dump(os.path.join(data, f'{base}.windows{L // 1024}k.jsonl'), win_rows[L])
        stats[base] = {'episodes': len(exs), 'full_tokens': dist([e['seg']['total'] for e in exs]),
                       'assistant_turns': sum(len(e['seg']['asst_counts']) for e in exs),
                       **{f'windows{L // 1024}k_examples': len(win_rows[L]) for L in WINDOW_LENS},
                       **{f'windows{L // 1024}k_tokens': dist(win_tokens[L]) for L in WINDOW_LENS},
                       **{f'windows{L // 1024}k_untrainable_turns_dropped': win_dropped[L] for L in WINDOW_LENS}}
    # --- verify window lengths by actual rendering (random sample per file; additivity asserted per episode above)
    verify = {}
    vrng = random.Random(SEED)
    for fname in sorted(os.listdir(data)):
        if 'windows' not in fname:
            continue
        L = 65536 if '64k' in fname else 32768 if '32k' in fname else 16384
        lines = open(os.path.join(data, fname)).readlines()
        mism, lens = 0, []
        for line in vrng.sample(lines, min(150, len(lines))):
            r = json.loads(line)
            n = meas.count(meas.render(r['messages'], json.loads(r['tools'])))
            assert n <= L, (fname, r['id'], n)
            exp = token_index.get(r['id'])
            mism += exp is not None and exp != n
            lens.append(n)
        verify[fname] = {'rows': len(lines), 'sampled': len(lens), 'expected_vs_rendered_mismatches': mism, 'sampled_tokens': dist(lens)}
    json.dump(token_index, open(os.path.join(SFT, 'work', 'row-tokens.json'), 'w'))
    report['stats'] = stats
    report['window_verification'] = verify
    # per suite / mechanism counts
    tab = collections.defaultdict(lambda: collections.Counter())
    for e in manifest:
        tab[f"{e['split']}.{e['model_family']}"][(e['suite'], e['mechanism'], 'clean' if e['clean'] else 'trapped')] += 1
    report['per_suite_mechanism'] = {k: [{'suite': s, 'mechanism': mm, 'variant': v, 'episodes': c} for (s, mm, v), c in sorted(v.items())]
                                     for k, v in tab.items()}
    dump(os.path.join(SFT, 'manifest.jsonl'), manifest)
    json.dump(sorted(test_tasks.values(), key=lambda t: (t['suite'], t['task_id'])),
              open(os.path.join(splits, 'test_tasks.json'), 'w'), indent=1)
    train_tasks = {}
    for r in train_inv:
        train_tasks.setdefault(r['task_id'], {'task_id': r['task_id'], 'suite': r['suite'], 'mechanism': r.get('mechanism'),
                                              'variant': r.get('variant'), 'world_id': r.get('world_id'), 'seed': r.get('seed'),
                                              'concept': r.get('concept')})
    json.dump(sorted(train_tasks.values(), key=lambda t: (t['suite'], t['task_id'])),
              open(os.path.join(splits, 'train_tasks.json'), 'w'), indent=1)
    json.dump(report, open(os.path.join(SFT, 'report.json'), 'w'), indent=1, default=str)
    print(json.dumps({k: report[k] for k in ('stats', 'leakage')}, indent=1, default=str)[:6000])


if __name__ == '__main__':
    sys.exit(main())
