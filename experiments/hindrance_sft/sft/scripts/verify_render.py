#!/usr/bin/env python3
"""Check that our rendering reproduces the exact prompt the self-hosted vLLM Qwen saw.

For vast (Qwen/Qwen3.8-27B-FP8 on vLLM) steps, vLLM reports exact usage.prompt_tokens.
We render the recorded request messages + tools with add_generation_prompt=True under
several reasoning representations and compare. No model calls.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from build import Measurer  # noqa: E402
from collect import norm_assistant, norm_content  # noqa: E402

ROOT = '/home/bjorn/code/LLM_proj_uu/.local/coordination/demo-sprint'


def convert(messages, keep_reasoning):
    stats = {'image_parts': 0}
    out = []
    for m in messages:
        if m['role'] == 'assistant':
            a = norm_assistant(m)
            if not keep_reasoning:
                a['reasoning_content'] = None
            out.append(a)
        else:
            out.append({**{k: v for k, v in m.items() if k != 'content'}, 'content': norm_content(m.get('content'), stats)})
    return out, stats['image_parts']


def main():
    meas = Measurer()
    results = []
    eps = sorted(glob.glob(f'{ROOT}/suite-v*/vast-*/episode-*/runs/*/steps.jsonl'))[:: max(1, len(glob.glob(f'{ROOT}/suite-v*/vast-*/episode-*/runs/*/steps.jsonl')) // 12)]
    for path in eps[:12]:
        rows = [json.loads(l) for l in open(path)]
        for idx in (1, len(rows) // 2, len(rows) - 1):
            x = rows[idx]
            req = x['model_request']
            reported = ((x.get('model_response') or {}).get('usage') or {}).get('prompt_tokens')
            res = {'steps': path, 'step': idx, 'reported_prompt_tokens': reported}
            for label, keep in (('with_reasoning', True), ('without_reasoning', False)):
                msgs, images = convert(req['messages'], keep)
                text = meas.render(msgs, req.get('tools'), add_generation_prompt=True)
                res[label] = meas.count(text)
                res['image_parts'] = images
            results.append(res)
    exact = [r for r in results if not r['image_parts']]
    summary = {'checked_requests': len(results), 'without_images': len(exact),
               'exact_match_with_reasoning': sum(r['with_reasoning'] == r['reported_prompt_tokens'] for r in exact),
               'exact_match_without_reasoning': sum(r['without_reasoning'] == r['reported_prompt_tokens'] for r in exact)}
    json.dump({'summary': summary, 'results': results}, open(os.path.join(ROOT, 'sft', 'render-verification.json'), 'w'), indent=1)
    print(json.dumps(summary, indent=1))
    for r in results[:12]:
        print(r['step'], r['reported_prompt_tokens'], r['with_reasoning'], r['without_reasoning'], r['image_parts'])


if __name__ == '__main__':
    main()
