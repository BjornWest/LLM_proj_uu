#!/usr/bin/env python3
"""Add generic replay on top of the browser SFT set, with exact Axolotl token accounting.

Replay is ADDED: every browser row is kept unchanged and exactly once; replay rows are whole
conversations, chosen without replacement in the pool's frozen (seeded) order.

  --unit docs  --fraction RHO   replay share of training DOCUMENTS (Kotha & Liang 2026):
                                n_replay = round(n_browser * RHO / (1 - RHO)); first n of the pool.
  --unit loss  --fraction F     replay share of LOSS-BEARING tokens (training-recipe.md §3): the recipe's
                                greedy whole-example rule (browser_training.sft_mixture.mix), tolerance 0.5 pp.

  --render nothink   replay rendered in Qwen's NON-thinking mode: dataset-level template
                     templates/qwen38_nothink.jinja = official template with enable_thinking forced
                     false (no "Reasoning effort" system text, empty <think>\\n\\n</think>\\n\\n block,
                     which Axolotl masks). Axolotl 0.19's chat_template_kwargs are global, so this needs
                     a SECOND dataset entry: the output is a directory with replay.jsonl + an Axolotl
                     config listing both datasets (the browser entry is unchanged).
  --render think     replay rendered exactly like the browser rows (self-generated rows with
                     reasoning_content); also writes a single combined JSONL.

Every row is measured with the installed Axolotl 0.19.0 ChatTemplateStrategy (CPU, offline, cached and
hash-checked Qwen3.8 tokenizer): Axolotl input_ids must equal the template rendering; loss tokens =
labels != -100. Outputs a manifest reporting documents, processed tokens and loss tokens side by side.
"""
import argparse
import copy
import hashlib
import json
import os
import random
import sys

os.environ.update(HF_HUB_OFFLINE='1', CUDA_VISIBLE_DEVICES='', AXOLOTL_DO_NOT_TRACK='1', TOKENIZERS_PARALLELISM='false')
HERE = os.path.dirname(os.path.abspath(__file__))
SFT = os.path.dirname(HERE)
TOK_DIR = '/home/bjorn/code/LLM_proj_uu/training/.cache/qwen38-tokenizer'
EXPECTED = {'tokenizer.json': '0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3',
            'chat_template.jinja': 'c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041'}
KW = dict(enable_thinking=True, preserve_thinking=True)  # = the browser config's chat_template_kwargs
NOTHINK_HEADER = '{#- SFT replay: Qwen3.8 official template, NON-thinking mode forced for this dataset only. -#}\n{%- set enable_thinking = false %}\n'
GRAD_ACC, MICRO = 8, 1


def sha_file(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def row_hash(row):
    return hashlib.sha256(json.dumps(row['messages'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--browser', default=os.path.join(SFT, 'data', 'train.qwen.primary16k.jsonl'))
    ap.add_argument('--browser-config', default=os.path.join(SFT, 'axolotl', 'sft_qwen38_27b_nf4_qlora_hindrance16k.yml'))
    ap.add_argument('--replay', required=True, help='pool JSONL in the {"id","tools","messages"} schema, frozen order')
    ap.add_argument('--unit', choices=['docs', 'loss'], required=True)
    ap.add_argument('--fraction', type=float, required=True)
    ap.add_argument('--render', choices=['nothink', 'think'], required=True)
    ap.add_argument('--name', required=True, help='e.g. replay25 -> train.qwen.primary16k+replay25')
    ap.add_argument('--out-dir', default=os.path.join(HERE, 'mixes'))
    ap.add_argument('--sequence-len', type=int, default=16384)
    ap.add_argument('--tolerance', type=float, default=0.005)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--host-data-dir', default='/opt/sft/data',
                    help='also write a *.host.yml whose dataset/template paths point here (copy the files there)')
    ap.add_argument('--protected', action='append', default=[],
                    help='JSONL whose prompts must not appear in replay (exact text); default: regression items')
    a = ap.parse_args()
    assert 0 < a.fraction < 1
    for name, digest in EXPECTED.items():
        assert sha_file(os.path.join(TOK_DIR, name)) == digest, f'tokenizer asset hash mismatch: {name}'

    import datasets
    import importlib.metadata
    import yaml
    from transformers import AutoTokenizer
    from axolotl.prompt_strategies.chat_template import ChatTemplatePrompter, ChatTemplateStrategy
    assert importlib.metadata.version('axolotl') == '0.19.0', 'requalify masks for a different Axolotl'
    tok = AutoTokenizer.from_pretrained(TOK_DIR, local_files_only=True)
    official = tok.chat_template
    tdir = os.path.join(HERE, 'templates')
    os.makedirs(tdir, exist_ok=True)
    nothink_path = os.path.join(tdir, 'qwen38_nothink.jinja')
    nothink = NOTHINK_HEADER + official
    if not os.path.exists(nothink_path) or open(nothink_path).read() != nothink:
        open(nothink_path, 'w').write(nothink)

    def strategy(template, with_training_field):
        p = ChatTemplatePrompter(tokenizer=tok, chat_template=template, max_length=a.sequence_len + 1,
                                 chat_template_kwargs=KW, field_tools='tools',
                                 message_field_training='training' if with_training_field else None)
        return ChatTemplateStrategy(p, tok, train_on_inputs=False, sequence_len=a.sequence_len,
                                    roles_to_train=['assistant'], train_on_eos='turn')

    def for_template(messages):
        out = []
        for m in messages:
            m = {k: v for k, v in m.items() if k != 'training'}
            if m.get('tool_calls'):
                m['tool_calls'] = [{**c, 'function': {**c['function'], 'arguments': json.loads(c['function']['arguments'])}}
                                   for c in m['tool_calls']]
            out.append(m)
        return out

    def measure(path, template, with_training_field):
        """Load through HF datasets (Axolotl's Arrow path) and tokenize with Axolotl; compare to template render."""
        ds = datasets.load_dataset('json', data_files=path, split='train')
        raws = [json.loads(line) for line in open(path)]
        st = strategy(template, with_training_field)
        out = []
        for row, raw in zip(ds, raws):
            assert row['id'] == raw['id']
            enc = st.tokenize_prompt(row)
            ids = tok.apply_chat_template(for_template(raw['messages']), tools=json.loads(raw['tools']) or None,
                                          tokenize=True, return_dict=False, chat_template=template, **KW)
            ok = list(enc['input_ids']) == list(ids)
            out.append({'id': raw['id'], 'processed_tokens': len(ids),
                        'loss_tokens': int(sum(t != -100 for t in enc['labels'][1:])), 'render_match': ok,
                        'fits': len(ids) <= a.sequence_len, 'raw': raw})
        return out

    browser = measure(a.browser, official, True)
    assert all(b['render_match'] and b['fits'] for b in browser), 'browser rows: Axolotl/render mismatch or overflow'
    replay_template = nothink if a.render == 'nothink' else official
    pool = measure(a.replay, replay_template, False)
    bad = [r['id'] for r in pool if not r['render_match']]
    assert not bad, f'replay Axolotl/render mismatch: {bad[:5]}'
    too_long = [r['id'] for r in pool if not r['fits']]
    pool = [r for r in pool if r['fits'] and r['loss_tokens'] > 0]

    # exact-content checks (as the recipe's mixer): no browser/replay overlap, no duplicate replay, no protected text
    bh = {row_hash(b['raw']) for b in browser}
    seen, uniq = set(), []
    for r in pool:
        h = row_hash(r['raw'])
        if h not in seen and h not in bh:
            seen.add(h)
            uniq.append(r)
    dup_removed = len(pool) - len(uniq)
    pool = uniq
    protected = a.protected or [os.path.join(SFT, 'regression', 'data', f) for f in ('gsm8k.jsonl', 'ifeval.jsonl', 'mmlu_pro.jsonl')]
    ptexts = set()
    for p in protected:
        for line in open(p):
            it = json.loads(line)
            for k in ('question', 'prompt'):
                if it.get(k):
                    ptexts.add(' '.join(it[k].split()))
    leaked = [r['id'] for r in pool if any(' '.join(m['content'].split()) in ptexts for m in r['raw']['messages']
                                           if m['role'] != 'assistant' and isinstance(m.get('content'), str))]
    assert not leaked, f'replay contains protected regression prompts: {leaked[:5]}'

    nb = len(browser)
    b_loss = sum(b['loss_tokens'] for b in browser)
    b_proc = sum(b['processed_tokens'] for b in browser)
    if a.unit == 'docs':
        n = round(nb * a.fraction / (1 - a.fraction))
        assert n <= len(pool), f'pool has {len(pool)} usable rows, need {n}'
        selected = pool[:n]
    else:
        target = b_loss * a.fraction / (1 - a.fraction)
        selected, total = [], 0
        for r in pool:  # browser_training.sft_mixture.mix greedy rule, in frozen pool order
            if abs(total + r['loss_tokens'] - target) < abs(total - target):
                selected.append(r)
                total += r['loss_tokens']
        achieved = total / (b_loss + total)
        assert abs(achieved - a.fraction) <= a.tolerance + 1e-12, \
            f'whole-example replay loss share {achieved:.4f} misses {a.fraction} by > {a.tolerance}'
    r_loss = sum(r['loss_tokens'] for r in selected)
    r_proc = sum(r['processed_tokens'] for r in selected)
    nr = len(selected)

    stem = f'train.qwen.primary16k+{a.name}'
    od = os.path.join(a.out_dir, stem)
    os.makedirs(od, exist_ok=True)
    rpath = os.path.join(od, 'replay.jsonl')
    with open(rpath, 'w') as f:
        for r in selected:
            f.write(json.dumps(r['raw'], ensure_ascii=False) + '\n')
    cfg = yaml.safe_load(open(a.browser_config))
    bentry = cfg['datasets'][0]
    assert bentry['path'].endswith('train.qwen.primary16k.jsonl') and bentry.get('message_field_training') == 'training'
    rentry = copy.deepcopy({k: v for k, v in bentry.items() if k not in ('path', 'message_field_training')})
    rentry['path'] = rpath
    combined = None
    if a.render == 'nothink':
        rentry['chat_template'] = 'jinja'
        rentry['chat_template_jinja'] = nothink_path
        cfg['datasets'] = [bentry, rentry]
    else:
        # thinking-mode replay renders like browser rows: one combined file, one dataset entry
        combined = os.path.join(od, stem + '.jsonl')
        rows = [b['raw'] for b in browser] + [r['raw'] for r in selected]
        random.Random(a.seed).shuffle(rows)
        with open(combined, 'w') as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
        cfg['datasets'] = [{**bentry, 'path': combined}]
    cfg['output_dir'] = f'outputs/sft-qwen38-nf4-hindrance16k-{a.name}'
    cfg['dataset_prepared_path'] = f'data/prepared-qwen38-nf4-hindrance16k-{a.name}'
    cfg_path = os.path.join(od, f'sft_qwen38_27b_nf4_qlora_hindrance16k_{a.name}.yml')
    header = (f'# Derived from {os.path.basename(a.browser_config)} by replay/mix_replay.py ({a.name}).\n'
              f'# Browser dataset entry unchanged; replay ADDED ({nr} rows, unit={a.unit}, fraction={a.fraction}, '
              f'render={a.render}).\n'
              '# On the GPU host, replace the absolute dataset/template paths.\n')
    with open(cfg_path, 'w') as f:
        f.write(header + yaml.safe_dump(cfg, sort_keys=False))
    host = copy.deepcopy(cfg)
    hd = a.host_data_dir.rstrip('/')
    host_files = {}
    for d in host['datasets']:
        local = d['path']
        d['path'] = f'{hd}/{os.path.basename(a.browser)}' if local == bentry['path'] else f'{hd}/{stem}.replay.jsonl' \
            if local == rpath else f'{hd}/{os.path.basename(local)}'
        host_files[d['path']] = local
        if d.get('chat_template_jinja'):
            host_files[f'{hd}/qwen38_nothink.jinja'] = d['chat_template_jinja']
            d['chat_template_jinja'] = f'{hd}/qwen38_nothink.jinja'
    host_cfg_path = cfg_path[:-4] + '.host.yml'
    with open(host_cfg_path, 'w') as f:
        f.write(header.replace('# On the GPU host, replace the absolute dataset/template paths.\n',
                               '# GPU-host copy: copy each local file to the path below (see manifest host_files).\n')
                + yaml.safe_dump(host, sort_keys=False))

    def share(r, b):
        return round(r / (r + b), 4)
    manifest = {
        'name': stem, 'replay_added_not_replacing': True, 'unit': a.unit, 'requested_fraction': a.fraction,
        'render': a.render, 'sequence_len': a.sequence_len, 'seed': a.seed,
        'side_by_side': {
            'documents': {'browser': nb, 'replay': nr, 'replay_share': share(nr, nb)},
            'processed_tokens': {'browser': b_proc, 'replay': r_proc, 'replay_share': share(r_proc, b_proc)},
            'loss_tokens': {'browser': b_loss, 'replay': r_loss, 'replay_share': share(r_loss, b_loss)},
            'optimizer_steps': {'browser_only': -(-nb // (GRAD_ACC * MICRO)), 'with_replay': -(-(nb + nr) // (GRAD_ACC * MICRO)),
                                'note': f'micro_batch {MICRO} x grad_accum {GRAD_ACC}, 1 epoch, unpacked'}},
        'replay_pool': {'path': os.path.abspath(a.replay), 'sha256': sha_file(a.replay), 'usable_rows': len(pool),
                        'over_sequence_len': too_long, 'exact_duplicates_or_browser_overlap_removed': dup_removed,
                        'selection': 'first N in frozen pool order' if a.unit == 'docs' else
                                     'recipe greedy whole-example rule in frozen pool order'},
        'replay_rows': [{'id': r['id'], 'processed_tokens': r['processed_tokens'], 'loss_tokens': r['loss_tokens']} for r in selected],
        'browser': {'path': os.path.abspath(a.browser), 'sha256': sha_file(a.browser)},
        'outputs': {'replay_jsonl': rpath, 'replay_sha256': sha_file(rpath), 'axolotl_config': cfg_path,
                    'host_axolotl_config': host_cfg_path, 'host_files': host_files,
                    'combined_jsonl': combined, 'combined_sha256': sha_file(combined) if combined else None},
        'template': {'official_sha256': EXPECTED['chat_template.jinja'],
                     'replay_template': nothink_path if a.render == 'nothink' else 'tokenizer_default',
                     'replay_template_sha256': sha_file(nothink_path) if a.render == 'nothink' else EXPECTED['chat_template.jinja'],
                     'global_chat_template_kwargs': KW},
        'checks': {'axolotl_version': importlib.metadata.version('axolotl'),
                   'axolotl_ids_equal_template_render': True, 'protected_files': protected,
                   'protected_exact_prompt_overlap': 0},
    }
    json.dump(manifest, open(os.path.join(od, 'manifest.json'), 'w'), indent=1)
    s = manifest['side_by_side']
    print(f'{stem}: docs {nb}+{nr} ({s["documents"]["replay_share"]:.1%}) | processed {b_proc}+{r_proc} '
          f'({s["processed_tokens"]["replay_share"]:.1%}) | loss {b_loss}+{r_loss} ({s["loss_tokens"]["replay_share"]:.1%}) | '
          f'steps {s["optimizer_steps"]["browser_only"]}->{s["optimizer_steps"]["with_replay"]}')


if __name__ == '__main__':
    main()
