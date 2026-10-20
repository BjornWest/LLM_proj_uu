"""Synthetic multi-turn SFT rows near a target token length (observation-heavy, like browser episodes)."""
import json, random, sys
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained(sys.argv[1])
target, count, out = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
rng = random.Random(target)
words = [w for w in "page button cart checkout delivery address size colour price product filter search \
order confirm consent terms checkbox shipping option total quantity review navigation link heading list \
item region dialog banner label textbox combobox selected expanded collapsed stock available".split()]
def text(n): return ' '.join(rng.choice(words) for _ in range(n))
def tokens(msgs):
    ids = tok.apply_chat_template(msgs, tokenize=True, enable_thinking=True, return_dict=False)
    ids = ids['input_ids'] if isinstance(ids, dict) or hasattr(ids, 'keys') else ids
    if ids and isinstance(ids[0], list):
        ids = ids[0]
    return len(ids)
with open(out, 'w') as f:
    for _ in range(count):
        msgs = [{'role': 'system', 'content': 'You are a careful shopping agent. ' + text(200)},
                {'role': 'user', 'content': 'Task: ' + text(80)}]
        # Estimate the turn size once, then add whole turns and check the final length.
        turn = lambda: [{'role': 'assistant', 'reasoning_content': text(150), 'content': 'Action: ' + text(60)},
                        {'role': 'user', 'content': 'Observation: ' + text(1100)}]
        per = tokens(msgs + turn()) - tokens(msgs)
        while tokens(msgs) + per * 8 < target * 0.985:
            for _ in range(8):
                msgs += turn()
        while tokens(msgs) + per < target * 0.985:
            msgs += turn()
        msgs.append({'role': 'assistant', 'reasoning_content': text(150), 'content': 'Action: ' + text(60)})
        f.write(json.dumps({'messages': msgs}) + '\n')
        print(out, tokens(msgs), file=sys.stderr)
