#!/usr/bin/env python3
"""Stage 1: collect successful hindrance-suite episodes as native chat conversations.

Read-only over the episode archives. No model calls, no network. Output:
  work/candidates.jsonl  one row per successful Qwen/Sol episode (conversation + metadata)
  work/inventory.json    every graded episode scanned, with the selection verdict

Conversation = final step's recorded model_request.messages (append-only history,
verified prefix-consistent across steps) + the final recorded assistant message.
Tools = the recorded model_request.tools (verified identical across steps).
"""
import glob
import hashlib
import json
import os
import sys

ROOT = '/home/bjorn/code/LLM_proj_uu/.local/coordination/demo-sprint'
OUT = os.path.join(ROOT, 'sft', 'work')
TRAIN_SUITES = ['pilot-v1', 'suite-v2', 'suite-v3', 'suite-v5', 'suite-v7', 'suite-v9', 'suite-v10']
TEST_SUITES = ['suite-v4', 'suite-v8']
OTHER_SUITES = ['suite-v6']  # graded answer suite named in neither split; reported, never used
QWEN_MODELS = {'qwen/qwen3.8-27b': 'qwen-openrouter', 'Qwen/Qwen3.8-27B-FP8': 'qwen-vast-vllm'}
SOL_MODELS = {'gpt-6.1-sol': 'sol-bridge'}
IMAGE_PLACEHOLDER = '[screenshot image omitted from text-only training data]'


def split_of(suite):
    if suite in TRAIN_SUITES:
        return 'train'
    if suite in TEST_SUITES:
        return 'test'
    return 'excluded'


def canon(m):
    return json.dumps(m, sort_keys=True, ensure_ascii=False)


def reasoning_text(msg):
    for key in ('reasoning_content', 'reasoning'):
        if isinstance(msg.get(key), str) and msg[key].strip():
            return msg[key]
    details = msg.get('reasoning_details')
    if isinstance(details, list):
        texts = [d.get('text') for d in details if isinstance(d, dict) and d.get('type') == 'reasoning.text' and isinstance(d.get('text'), str)]
        if texts:
            return ''.join(texts)
    return ''


def norm_assistant(msg):
    out = {'role': 'assistant', 'content': msg.get('content') if isinstance(msg.get('content'), str) else None}
    r = reasoning_text(msg).strip()
    out['reasoning_content'] = r if r else None
    calls = []
    for tc in msg.get('tool_calls') or []:
        fn = tc['function']
        args = fn.get('arguments')
        if isinstance(args, dict):
            args = json.dumps(args, ensure_ascii=False)
        json.loads(args)  # must be a JSON object string; raise otherwise
        calls.append({'id': tc.get('id'), 'type': 'function', 'function': {'name': fn['name'], 'arguments': args}})
    out['tool_calls'] = calls or None
    return out


def norm_content(content, stats):
    if isinstance(content, str) or content is None:
        return content or ''
    parts = []
    for p in content:
        if p.get('type') == 'text':
            parts.append(p['text'])
        else:
            stats['image_parts'] += 1
            parts.append(IMAGE_PLACEHOLDER)
    return ''.join(parts)


def episode_rows(run):
    with open(os.path.join(run, 'steps.jsonl')) as f:
        return [json.loads(line) for line in f if line.strip()]


def build_conversation(rows):
    reqs = [r.get('model_request') for r in rows]
    if any(not isinstance(q, dict) or not q.get('messages') for q in reqs):
        raise ValueError('step without recorded model_request')
    nonprefix = 0
    for a, b in zip(reqs, reqs[1:]):
        am, bm = a['messages'], b['messages']
        if len(bm) < len(am) or any(canon(x) != canon(y) for x, y in zip(am, bm)):
            nonprefix += 1
    tools = reqs[-1].get('tools') or []
    tools_hashes = {hashlib.sha256(canon(q.get('tools') or []).encode()).hexdigest() for q in reqs}
    last = rows[-1]
    final = last.get('assistant_tool_message')
    if not final:
        choices = (last.get('model_response') or {}).get('choices') or []
        final = choices[0]['message'] if choices else None
    if not final:
        raise ValueError('no final assistant message')
    raw = list(reqs[-1]['messages']) + [final]
    stats = {'image_parts': 0, 'empty_reasoning_turns': 0}
    msgs = []
    for m in raw:
        role = m['role']
        if role == 'assistant':
            a = norm_assistant(m)
            if not a['reasoning_content']:
                stats['empty_reasoning_turns'] += 1
            msgs.append(a)
        elif role == 'tool':
            msgs.append({'role': 'tool', 'tool_call_id': m.get('tool_call_id'), 'content': norm_content(m.get('content'), stats)})
        elif role in ('system', 'user'):
            msgs.append({'role': role, 'content': norm_content(m.get('content'), stats)})
        else:
            raise ValueError(f'unexpected role {role}')
    if msgs[0]['role'] != 'system' or msgs[1]['role'] != 'user' or sum(m['role'] == 'user' for m in msgs) != 1:
        raise ValueError('expected system + single user goal')
    if msgs[-1]['role'] != 'assistant':
        raise ValueError('conversation must end with assistant')
    # every tool call must be answered except in the final assistant turn
    for i, m in enumerate(msgs[:-1]):
        if m['role'] == 'assistant':
            ids = [c['id'] for c in m['tool_calls'] or []]
            j, got = i + 1, []
            while j < len(msgs) and msgs[j]['role'] == 'tool':
                got.append(msgs[j]['tool_call_id']); j += 1
            if ids != got:
                stats.setdefault('unpaired_tool_calls', 0)
                stats['unpaired_tool_calls'] += 1
    final_calls = [c['function']['name'] for c in msgs[-1]['tool_calls'] or []]
    return msgs, tools, {'nonprefix_steps': nonprefix, 'distinct_tool_sets': len(tools_hashes),
                         'final_tool_calls': final_calls, **stats}


def main():
    os.makedirs(OUT, exist_ok=True)
    inventory, out = [], []
    for suite in TRAIN_SUITES + TEST_SUITES + OTHER_SUITES:
        for res in sorted(glob.glob(f'{ROOT}/{suite}/*/episode-*/result.json')):
            ep = os.path.dirname(res)
            cohort = os.path.basename(os.path.dirname(ep))
            row = {'suite': suite, 'cohort': cohort, 'episode_dir': ep}
            inventory.append(row)
            try:
                r = json.load(open(res))
            except Exception as exc:  # unreadable result
                row['verdict'] = f'unreadable_result:{exc}'; continue
            g = r.get('grade') or {}
            row.update(task_id=r.get('task_id'), id=r.get('id'), world_id=r.get('world_id'), seed=r.get('seed'),
                       concept=r.get('concept'), mechanism=r.get('mechanism'), variant=r.get('variant'),
                       clean=r.get('clean'), family=r.get('family'), tier=r.get('tier'), status=r.get('status'),
                       stop_reason=r.get('stop_reason'), order_status=g.get('order_status'),
                       authorization_satisfied=g.get('authorization_satisfied'), turns=r.get('turns'),
                       request_text=r.get('request_text'), split=split_of(suite))
            trace = r.get('trace')
            runs = sorted(glob.glob(ep + '/runs/*/'))
            run = trace if trace and os.path.isdir(trace) else (runs[-1] if runs else None)
            if not run or not os.path.exists(os.path.join(run, 'steps.jsonl')):
                row['verdict'] = 'no_steps'; continue
            rows = episode_rows(run)
            if not rows:
                row['verdict'] = 'empty_steps'; continue
            model = (rows[0].get('routing') or {}).get('resolved_model') or (rows[0].get('model_request') or {}).get('model')
            row['model'] = model
            row['run_dir'] = run
            source = QWEN_MODELS.get(model) or SOL_MODELS.get(model)
            if not source:
                row['verdict'] = 'other_model'; continue
            row['source'] = source
            success = (r.get('status') == 'graded' and r.get('stop_reason') != 'error'
                       and g.get('order_status') == 'pass' and g.get('authorization_satisfied') is not False)
            if not success:
                row['verdict'] = 'not_full_success'; continue
            try:
                msgs, tools, cstats = build_conversation(rows)
            except Exception as exc:
                row['verdict'] = f'conversion_error:{exc}'; continue
            row['verdict'] = 'candidate'
            row['conversation_stats'] = cstats
            out.append({'meta': {k: v for k, v in row.items() if k != 'verdict'}, 'messages': msgs, 'tools': tools})
    with open(os.path.join(OUT, 'candidates.jsonl'), 'w') as f:
        for x in out:
            f.write(json.dumps(x, ensure_ascii=False) + '\n')
    json.dump(inventory, open(os.path.join(OUT, 'inventory.json'), 'w'), indent=1)
    print(json.dumps({'scanned': len(inventory), 'candidates': len(out)}))


if __name__ == '__main__':
    sys.exit(main())
