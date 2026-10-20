#!/usr/bin/env python3
"""Tokenize sample rows through the installed Axolotl 0.19.0 chat_template strategy (CPU, offline).

Loads each JSONL through HF `datasets` (the same Arrow path Axolotl uses), tokenizes sampled
rows with ChatTemplateStrategy, and checks:
  * Axolotl input_ids == our apply_chat_template rendering (no truncation / template drift)
  * supervised text contains every loss-bearing assistant turn's tool call, and no context turn's
  * no tool/user/system text is supervised
No model weights, no GPU, no training.
"""
import json
import os
import random
import sys

os.environ.update(HF_HUB_OFFLINE='1', CUDA_VISIBLE_DEVICES='', AXOLOTL_DO_NOT_TRACK='1', TOKENIZERS_PARALLELISM='false')
sys.path.insert(0, os.path.dirname(__file__))
from build import Measurer, for_template, TEMPLATE_KW  # noqa: E402
import datasets  # noqa: E402
from axolotl.prompt_strategies.chat_template import ChatTemplatePrompter, ChatTemplateStrategy  # noqa: E402
import importlib.metadata  # noqa: E402

SFT = '/home/bjorn/code/LLM_proj_uu/.local/coordination/demo-sprint/sft'


def main():
    files = sys.argv[1:] or ['data/train.qwen.windows32k.jsonl', 'data/train.qwen.windows16k.jsonl']
    per_file = int(os.environ.get('SAMPLES', '6'))
    meas = Measurer()
    tok = meas.tok
    out = {'axolotl_version': importlib.metadata.version('axolotl'), 'chat_template_kwargs': TEMPLATE_KW, 'files': {}}
    for fname in files:
        path = os.path.join(SFT, fname)
        seq = 65536 if '64k' in fname else 32768 if '32k' in fname else 16384 if '16k' in fname else 300000
        ds = datasets.load_dataset('json', data_files=path, split='train')
        prompter = ChatTemplatePrompter(tokenizer=tok, chat_template=tok.chat_template, max_length=seq + 1,
                                        chat_template_kwargs=TEMPLATE_KW,
                                        message_field_training='training')
        strategy = ChatTemplateStrategy(prompter, tok, train_on_inputs=False, sequence_len=seq,
                                        roles_to_train=['assistant'], train_on_eos='turn')
        rng = random.Random(0)
        # include rows with context-only turns (windows) and short full rows
        idx = list(range(len(ds)))
        ctx_rows = [i for i in idx if any(m.get('training') is False for m in ds[i]['messages'])]
        pick = sorted(set(rng.sample(ctx_rows, min(per_file // 2, len(ctx_rows))) + rng.sample(idx, min(per_file - per_file // 2, len(idx)))))
        results = []
        for i in pick:
            row = ds[i]
            # Arrow round-trip check: messages must survive without injected keys/values
            raw = json.loads(open(path).readlines()[i])
            assert row['id'] == raw['id']
            enc = strategy.tokenize_prompt(row)
            ids = tok.apply_chat_template(for_template(raw['messages']), tools=json.loads(raw['tools']), tokenize=True,
                                          return_dict=False, **TEMPLATE_KW)
            assert list(enc['input_ids']) == list(ids), (fname, raw['id'], len(enc['input_ids']), len(ids))
            labels = enc['labels']
            # contiguous supervised spans, decoded separately
            spans, cur = [], []
            for t in labels:
                if t != -100:
                    cur.append(t)
                elif cur:
                    spans.append(cur); cur = []
            if cur:
                spans.append(cur)
            got = [tok.decode(sp) for sp in spans]
            # expected: for each loss-bearing assistant turn, its rendered body after '<think>\n' through '<|im_end|>'
            text = tok.apply_chat_template(for_template(raw['messages']), tools=json.loads(raw['tools']), tokenize=False, **TEMPLATE_KW)
            units = text.split('<|im_start|>assistant\n')[1:]
            asst = [m for m in raw['messages'] if m['role'] == 'assistant']
            assert len(units) == len(asst)
            expected = []
            for m, u in zip(asst, units):
                if m.get('training', True):
                    assert u.startswith('<think>\n')
                    expected.append(u[len('<think>\n'):u.index('<|im_end|>') + len('<|im_end|>')])
            # adjacent trained turns are separated by masked text, so spans map 1:1 to trained turns
            assert got == expected, (raw['id'], len(got), len(expected), [g[:60] for g in got][:3], [e[:60] for e in expected][:3])
            n_target = len(expected); n_ctx = len(asst) - n_target
            results.append({'id': raw['id'], 'tokens': len(ids), 'supervised_tokens': sum(t != -100 for t in labels),
                            'target_turns': n_target, 'context_turns': n_ctx})
        out['files'][fname] = {'rows': len(ds), 'checked': results}
        print(fname, json.dumps(results))
    out['passed'] = True
    json.dump(out, open(os.path.join(SFT, 'axolotl-validation.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
