#!/usr/bin/env python3
"""Exact loss-token count per file: for each loss-bearing assistant turn, tokens of its rendered
body after '<think>\\n' through '<|im_end|>' (what Axolotl supervises; validated in validate_axolotl.py)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from build import Measurer, for_template, TEMPLATE_KW
meas = Measurer(); out = {}
for f in sys.argv[1:]:
    rows = loss = proc = 0
    for line in open(f):
        r = json.loads(line); rows += 1
        text = meas.render(r['messages'], json.loads(r['tools'])); proc += meas.count(text)
        units = text.split('<|im_start|>assistant\n')[1:]
        asst = [m for m in r['messages'] if m['role'] == 'assistant']
        for m, u in zip(asst, units):
            if m.get('training', True):
                loss += meas.count(u[len('<think>\n'):u.index('<|im_end|>') + len('<|im_end|>')])
    out[os.path.basename(f)] = {'rows': rows, 'processed_tokens': proc, 'loss_tokens': loss}
    print(os.path.basename(f), out[os.path.basename(f)], flush=True)
json.dump(out, open('/home/bjorn/code/LLM_proj_uu/.local/coordination/demo-sprint/sft/loss-tokens.json', 'w'), indent=1)
