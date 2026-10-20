#!/usr/bin/env python3
"""Generic capability-regression check against an OpenAI-compatible endpoint (vLLM).

Benchmarks (frozen items in data/, see data/MANIFEST.json): GSM8K (100), IFEval (100),
MMLU-Pro (200). Every request uses the agent-run sampling (temperature 0.6, top_p 0.95,
top_k 20, thinking on by default) and a per-item seed, so base and SFT see identical
prompts and seeds. Answers are extracted from the final `content` only; the reasoning
(vLLM `reasoning` / `reasoning_content`) is saved but never scored.

Truncated generations (finish_reason == "length") count as wrong and are reported
separately. Endpoint errors after retries are recorded as `error` and excluded from the
score (an infrastructure failure, not a model verdict); the summary reports them.
Per-item results are appended to OUT/<bench>.jsonl and a rerun resumes (skips done items).
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault('NLTK_DATA', os.path.join(HERE, 'nltk_data'))
sys.path.insert(0, HERE)

LETTERS = 'ABCDEFGHIJ'
DEFAULT_MAX_TOKENS = {'gsm8k': 3072, 'ifeval': 4096, 'mmlu_pro': 3072}


# ---------------------------------------------------------------- prompts / scoring
def gsm8k_prompt(it):
    return (it['question'] + '\n\nSolve the problem. Give the final answer as a number on the last line, '
            'in the form "#### <number>".')


def _num(s):
    s = s.replace(',', '').replace('$', '').strip().rstrip('.')
    try:
        v = float(s)
    except ValueError:
        return None
    return v


def gsm8k_extract(text):
    m = re.findall(r'####\s*\$?\s*(-?[\d,]*\.?\d+)', text)
    if m:
        return m[-1]
    m = re.findall(r'\\boxed\{\s*\$?(-?[\d,]*\.?\d+)', text)
    if m:
        return m[-1]
    m = re.findall(r'-?[\d,]*\.?\d+', text)
    return m[-1] if m else None


def gsm8k_score(it, content):
    pred = gsm8k_extract(content or '')
    p, g = (_num(pred) if pred else None), _num(it['answer'])
    return {'pred': pred, 'correct': p is not None and g is not None and abs(p - g) < 1e-6}


def ifeval_prompt(it):
    return it['prompt']


def ifeval_score(it, content):
    from ifeval_lm_eval import utils as ifu
    kwargs = [{k: v for k, v in kw.items() if v is not None} for kw in it['kwargs']]
    r = ifu.process_results({'key': it['key'], 'instruction_id_list': it['instruction_id_list'],
                             'prompt': it['prompt'], 'kwargs': kwargs}, [content or ''])
    return {'correct': bool(r['prompt_level_strict_acc']), 'prompt_strict': bool(r['prompt_level_strict_acc']),
            'prompt_loose': bool(r['prompt_level_loose_acc']), 'inst_strict': [bool(x) for x in r['inst_level_strict_acc']],
            'inst_loose': [bool(x) for x in r['inst_level_loose_acc']]}


def mmlu_prompt(it):
    opts = '\n'.join(f'{LETTERS[i]}. {o}' for i, o in enumerate(it['options']))
    return (f'The following is a multiple choice question about {it["category"]}.\n\n{it["question"]}\n\n{opts}\n\n'
            f'Choose the single best option. End your reply with a final line of the form "Answer: X", '
            f'where X is one of {", ".join(LETTERS[:len(it["options"])])}.')


def mmlu_extract(text):
    for pat in (r'Answer:\s*\**\s*\(?([A-J])\b', r'answer is\s*\**\s*\(?([A-J])\b', r'\\boxed\{\s*\(?([A-J])\b'):
        m = re.findall(pat, text, flags=re.I)
        if m:
            return m[-1].upper()
    m = re.findall(r'^\s*\(?([A-J])[\).:]?\s*$', text, flags=re.M)
    return m[-1] if m else None


def mmlu_score(it, content):
    pred = mmlu_extract(content or '')
    return {'pred': pred, 'correct': pred == it['answer']}


BENCH = {'gsm8k': (gsm8k_prompt, gsm8k_score), 'ifeval': (ifeval_prompt, ifeval_score),
         'mmlu_pro': (mmlu_prompt, mmlu_score)}


def check_scoring(benches):
    """Score one trivial response per benchmark before any generation is dispatched.

    IFEval needs the vendored ifeval_lm_eval checker plus nltk (punkt_tab), langdetect and
    immutabledict; without them every generated response would end as an unscored error.
    """
    probes = {'ifeval': ({'key': 0, 'prompt': 'probe', 'instruction_id_list':
                          ['punctuation:no_comma', 'length_constraints:number_sentences'],
                          'kwargs': [{}, {'num_sentences': 1, 'relation': 'at least'}]},
                         'One sentence. Another one.'),
              'gsm8k': ({'answer': '4'}, '#### 4'), 'mmlu_pro': ({'answer': 'A'}, 'Answer: A')}
    for b in benches:
        it, content = probes[b]
        try:
            ok = BENCH[b][1](it, content)['correct']
        except Exception as e:  # noqa: BLE001 - reported as an actionable setup error
            sys.exit(f'{b} scoring is unavailable ({type(e).__name__}: {e}). Nothing was sent. '
                     f'See README.md: install nltk>=3.9.1, langdetect and immutabledict into .venv and '
                     f'download punkt_tab into NLTK_DATA (now {os.environ["NLTK_DATA"]}).')
        if ok is not True:
            sys.exit(f'{b} scoring self-check returned {ok!r} for a known-correct response; nothing was sent.')


# ---------------------------------------------------------------- endpoint
def http_json(url, body=None, timeout=1800, api_key=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json',
                                                          **({'Authorization': 'Bearer ' + api_key} if api_key else {})})
    # no proxies: the endpoint is a local SSH tunnel
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read())


def chat(a, messages, max_tokens, seed, think):
    body = {'model': a.model, 'messages': messages, 'max_tokens': max_tokens, 'temperature': a.temperature,
            'top_p': a.top_p, 'top_k': a.top_k, 'seed': seed}
    if not think:
        body['chat_template_kwargs'] = {'enable_thinking': False}
    delay, t0 = 5.0, time.monotonic()
    while True:
        try:
            return http_json(a.base_url.rstrip('/') + '/chat/completions', body, api_key=a.api_key)
        except urllib.error.HTTPError as e:
            if e.code not in (408, 429, 500, 502, 503, 504) or time.monotonic() - t0 > a.retry_seconds:
                raise RuntimeError(f'HTTP {e.code}: {e.read()[:300]!r}') from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if time.monotonic() - t0 > a.retry_seconds:
                raise RuntimeError(repr(e)[:300]) from e
        time.sleep(delay)
        delay = min(delay * 2, 60)


def item_seed(base_seed, item_id):
    return (base_seed + int(hashlib.sha256(item_id.encode()).hexdigest()[:8], 16)) % (2 ** 31)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base-url', default='http://127.0.0.1:18000/v1')
    ap.add_argument('--model', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--api-key', default=os.environ.get('SELF_HOSTED_API_KEY'))
    ap.add_argument('--benchmarks', default='gsm8k,ifeval,mmlu_pro')
    ap.add_argument('--limit', type=int, default=0, help='first N items per benchmark (smoke tests); 0 = all')
    ap.add_argument('--concurrency', type=int, default=16)
    ap.add_argument('--temperature', type=float, default=0.6)
    ap.add_argument('--top-p', type=float, default=0.95)
    ap.add_argument('--top-k', type=int, default=20)
    ap.add_argument('--seed', type=int, default=20261020)
    ap.add_argument('--max-tokens', default='', help='per-benchmark overrides, e.g. gsm8k=3072,mmlu_pro=2048')
    ap.add_argument('--no-think', default='', help='comma list of benchmarks to run with enable_thinking=false')
    ap.add_argument('--retry-seconds', type=float, default=600)
    ap.add_argument('--data', default=os.path.join(HERE, 'data'))
    a = ap.parse_args()
    benches = [b for b in a.benchmarks.split(',') if b]
    max_tokens = dict(DEFAULT_MAX_TOKENS)
    for kv in filter(None, a.max_tokens.split(',')):
        k, v = kv.split('=')
        max_tokens[k] = int(v)
    no_think = set(filter(None, a.no_think.split(',')))
    unknown = [b for b in benches if b not in BENCH]
    if unknown:
        sys.exit(f'Unknown benchmarks: {unknown}')
    check_scoring(benches)
    os.makedirs(a.out, exist_ok=True)

    models = http_json(a.base_url.rstrip('/') + '/models', timeout=30, api_key=a.api_key)
    served = [m.get('id') for m in models.get('data', [])]
    if a.model not in served:
        sys.exit(f'Endpoint does not serve {a.model!r}; it serves {served}')

    items, done = [], {}
    for b in benches:
        path = os.path.join(a.data, f'{b}.jsonl')
        its = [json.loads(line) for line in open(path)]
        if a.limit:
            its = its[:a.limit]
        out = os.path.join(a.out, f'{b}.jsonl')
        if os.path.exists(out):
            for line in open(out):
                r = json.loads(line)
                if r.get('status') == 'ok':
                    done[(b, r['id'])] = r
            # keep only successful rows; errored items are retried
            with open(out, 'w') as f:
                for (bb, _), r in done.items():
                    if bb == b:
                        f.write(json.dumps(r, ensure_ascii=False) + '\n')
        items += [(b, it) for it in its if (b, it['id']) not in done]
    random.Random(a.seed).shuffle(items)  # interleave benchmarks so the batch stays mixed
    print(f'{a.model}: {len(items)} items to run, {len(done)} already done; concurrency {a.concurrency}', flush=True)

    lock = threading.Lock()
    files = {b: open(os.path.join(a.out, f'{b}.jsonl'), 'a') for b in benches}
    stats = {'n': 0, 'out_tokens': 0, 'errors': 0}
    t0 = time.monotonic()

    def run(b, it):
        make_prompt, score = BENCH[b]
        messages = [{'role': 'user', 'content': make_prompt(it)}]
        seed = item_seed(a.seed, it['id'])
        rec = {'id': it['id'], 'bench': b, 'model': a.model, 'seed': seed, 'think': b not in no_think,
               'max_tokens': max_tokens[b]}
        t = time.monotonic()
        try:
            resp = chat(a, messages, max_tokens[b], seed, b not in no_think)
            ch = resp['choices'][0]
            msg = ch.get('message') or {}
            content = msg.get('content') or ''
            reasoning = msg.get('reasoning') or msg.get('reasoning_content') or ''
            usage = resp.get('usage') or {}
            rec.update(status='ok', finish_reason=ch.get('finish_reason'), truncated=ch.get('finish_reason') == 'length',
                       completion_tokens=usage.get('completion_tokens'), prompt_tokens=usage.get('prompt_tokens'),
                       latency_s=round(time.monotonic() - t, 2), content=content, reasoning=reasoning,
                       **score(it, content))
            if rec['truncated']:
                rec['correct'] = False
        except Exception as e:  # noqa: BLE001 - recorded as infrastructure error, not a model verdict
            rec.update(status='error', error=str(e)[:500], latency_s=round(time.monotonic() - t, 2))
        with lock:
            files[b].write(json.dumps(rec, ensure_ascii=False) + '\n')
            files[b].flush()
            stats['n'] += 1
            stats['out_tokens'] += rec.get('completion_tokens') or 0
            stats['errors'] += rec['status'] == 'error'
            if stats['n'] % 20 == 0 or stats['n'] == len(items):
                el = time.monotonic() - t0
                eta = el / stats['n'] * (len(items) - stats['n'])
                print(f'  {stats["n"]}/{len(items)}  {el:.0f}s elapsed  ~{eta:.0f}s left  '
                      f'{stats["out_tokens"] / max(el, 1e-9):.0f} out tok/s  errors {stats["errors"]}', flush=True)

    with ThreadPoolExecutor(a.concurrency) as ex:
        for f in as_completed([ex.submit(run, b, it) for b, it in items]):
            f.result()
    for f in files.values():
        f.close()
    wall = time.monotonic() - t0

    summary = {'model': a.model, 'base_url': a.base_url, 'served_models': served, 'wall_seconds_this_run': round(wall, 1),
               'sampling': {'temperature': a.temperature, 'top_p': a.top_p, 'top_k': a.top_k, 'seed': a.seed},
               'max_tokens': {b: max_tokens[b] for b in benches}, 'no_think': sorted(no_think), 'limit': a.limit,
               'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'benchmarks': {}}
    for b in benches:
        rows = [json.loads(line) for line in open(os.path.join(a.out, f'{b}.jsonl'))]
        ok = [r for r in rows if r['status'] == 'ok']
        s = {'items': len(rows), 'scored': len(ok), 'errors': len(rows) - len(ok),
             'accuracy': sum(r['correct'] for r in ok) / len(ok) if ok else None,
             'truncated': sum(r['truncated'] for r in ok),
             'mean_completion_tokens': sum(r['completion_tokens'] or 0 for r in ok) / len(ok) if ok else None,
             'data_sha256': hashlib.sha256(open(os.path.join(a.data, f'{b}.jsonl'), 'rb').read()).hexdigest()}
        if b == 'ifeval' and ok:
            s['prompt_loose'] = sum(r['prompt_loose'] for r in ok) / len(ok)
            inst = [x for r in ok for x in r['inst_strict']]
            s['inst_strict'] = sum(inst) / len(inst)
        summary['benchmarks'][b] = s
        print(f'{b:9s} acc {s["accuracy"]}  scored {s["scored"]}/{s["items"]}  truncated {s["truncated"]}  '
              f'mean out tok {s["mean_completion_tokens"]}', flush=True)
    json.dump(summary, open(os.path.join(a.out, 'summary.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
