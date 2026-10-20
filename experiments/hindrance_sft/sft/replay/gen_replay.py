#!/usr/bin/env python3
"""OPTIONAL secondary replay: the base model answers generic prompts itself (own distribution).

Reads sources/selfgen_prompts.jsonl (UltraChat first user turns + Nemotron-v1 tool-use prompts
with native tool schemas) and asks the served base model, thinking ON, with the agent sampling
(temperature 0.6, top_p 0.95, top_k 20, per-prompt seed). Writes rows in the browser SFT schema:

  {"id": "replay/selfgen/...", "tools": "<JSON string>", "messages": [
     {"role": "user", "content": ...},
     {"role": "assistant", "content": str|null, "reasoning_content": str, "tool_calls": [...]}]}

Tool-call arguments stay JSON strings (as in train.qwen.primary16k.jsonl). Rejected (not written,
logged to OUT.rejects.jsonl): finish_reason=length, empty reasoning, neither content nor tool calls,
unparseable tool arguments, endpoint errors. Generation metadata goes to OUT.meta.jsonl.
Resumable: ids already in OUT are skipped.
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'regression'))
from regress import http_json  # noqa: E402
import urllib.error  # noqa: E402


def call(a, body):
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base-url', default='http://127.0.0.1:18000/v1')
    ap.add_argument('--model', default='Qwen/Qwen3.8-27B-FP8')
    ap.add_argument('--api-key', default=os.environ.get('SELF_HOSTED_API_KEY'))
    ap.add_argument('--prompts', default=os.path.join(HERE, 'sources', 'selfgen_prompts.jsonl'))
    ap.add_argument('--out', default=os.path.join(HERE, 'selfgen', 'replay.selfgen.jsonl'))
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--concurrency', type=int, default=16)
    ap.add_argument('--max-tokens', type=int, default=8192)
    ap.add_argument('--seed', type=int, default=20261020)
    ap.add_argument('--retry-seconds', type=float, default=600)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    prompts = [json.loads(line) for line in open(a.prompts)]
    if a.limit:
        prompts = prompts[:a.limit]
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(line)['id'] for line in open(a.out)}
    todo = [p for p in prompts if p['id'].replace('selfgen-prompt/', 'replay/selfgen/') not in done]
    models = http_json(a.base_url.rstrip('/') + '/models', timeout=30, api_key=a.api_key)
    if a.model not in [m.get('id') for m in models.get('data', [])]:
        sys.exit(f'Endpoint does not serve {a.model}')
    print(f'{len(todo)} prompts to generate ({len(done)} done)', flush=True)
    lock = threading.Lock()
    out, meta, rej = (open(a.out, 'a'), open(a.out + '.meta.jsonl', 'a'), open(a.out + '.rejects.jsonl', 'a'))
    counts = {'kept': 0, 'rejected': 0}
    t0 = time.monotonic()

    def run(p):
        rid = p['id'].replace('selfgen-prompt/', 'replay/selfgen/')
        tools = json.loads(p['tools'])
        seed = (a.seed + int(hashlib.sha256(rid.encode()).hexdigest()[:8], 16)) % (2 ** 31)
        body = {'model': a.model, 'messages': p['messages'], 'max_tokens': a.max_tokens, 'temperature': 0.6,
                'top_p': 0.95, 'top_k': 20, 'seed': seed}
        if tools:
            body['tools'] = tools
        reason, row = None, None
        try:
            resp = call(a, body)
            ch = resp['choices'][0]
            msg = ch.get('message') or {}
            reasoning = (msg.get('reasoning') or msg.get('reasoning_content') or '').strip()
            content = msg.get('content')
            calls = []
            for c in msg.get('tool_calls') or []:
                args = c['function'].get('arguments') or '{}'
                json.loads(args)  # must parse; kept as the JSON string
                calls.append({'id': c.get('id'), 'type': 'function',
                              'function': {'name': c['function']['name'], 'arguments': args}})
            if ch.get('finish_reason') == 'length':
                reason = 'truncated'
            elif not reasoning:
                reason = 'empty_reasoning'
            elif not (content and content.strip()) and not calls:
                reason = 'empty_answer'
            else:
                asst = {'role': 'assistant', 'content': content if (content and content.strip()) else None,
                        'reasoning_content': reasoning}
                if calls:
                    asst['tool_calls'] = calls
                row = {'id': rid, 'tools': p['tools'], 'messages': [*p['messages'], asst]}
            info = {'id': rid, 'seed': seed, 'model': a.model, 'finish_reason': ch.get('finish_reason'),
                    'usage': resp.get('usage'), 'response_id': resp.get('id'), 'kept': row is not None, 'reason': reason}
        except (RuntimeError, ValueError, KeyError) as e:
            reason = 'error: ' + str(e)[:300]
            info = {'id': rid, 'seed': seed, 'kept': False, 'reason': reason}
        with lock:
            meta.write(json.dumps(info) + '\n')
            meta.flush()
            if row:
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
                out.flush()
                counts['kept'] += 1
            else:
                rej.write(json.dumps(info) + '\n')
                rej.flush()
                counts['rejected'] += 1
            n = counts['kept'] + counts['rejected']
            if n % 20 == 0 or n == len(todo):
                print(f'  {n}/{len(todo)} kept {counts["kept"]} rejected {counts["rejected"]} '
                      f'{time.monotonic() - t0:.0f}s', flush=True)

    with ThreadPoolExecutor(a.concurrency) as ex:
        for f in as_completed([ex.submit(run, p) for p in todo]):
            f.result()
    for f in (out, meta, rej):
        f.close()


if __name__ == '__main__':
    main()
