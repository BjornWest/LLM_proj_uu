"""Per-step model and tool timings of a Korp run, from its saved trace.

    python apps/raven/timings.py            # latest run
    python apps/raven/timings.py RUN_DIR    # a run id, attempt or episode directory

Requests are not streamed, so the trace has no time-to-first-token: "ms/out tok" is the whole
call divided by output tokens (prefill included, an upper bound on TPOT). The least-squares fit
latency = a + b*input_k + c*output splits it into fixed overhead, prefill and decode (TPOT = c)
when the run has enough steps with varied sizes.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

RUNS = Path(__file__).resolve().parents[2] / '.local/raven-runs'


def episode_dirs(arg):
    root = Path(arg) if arg else max(RUNS.glob('*/attempt-*'), key=lambda p: p.stat().st_mtime)
    if not root.exists():
        root = RUNS / arg
    return sorted(p.parent for p in root.rglob('events.jsonl'))


def stamp(event):
    value = event['timestamp']
    return float(value) if isinstance(value, (int, float)) else datetime.fromisoformat(value).timestamp()


def report(directory):
    events = [json.loads(line) for line in (directory / 'events.jsonl').open()]
    model, tools, open_calls = [], [], {}
    for e in events:
        kind = e.get('event')
        if kind in ('model_started', 'tool_started'):
            open_calls[e['call_id']] = e
        elif kind in ('model_completed', 'tool_completed', 'tool_failed') and e.get('call_id') in open_calls:
            start = open_calls.pop(e['call_id'])
            seconds = stamp(e) - stamp(start)
            if kind == 'model_completed':
                usage = (e.get('model_response') or {}).get('usage') or {}
                details = usage.get('prompt_tokens_details') or {}
                model.append(dict(start=stamp(start), end=stamp(e), seconds=seconds,
                                  input=usage.get('prompt_tokens') or 0, output=usage.get('completion_tokens') or 0,
                                  cached=details.get('cached_tokens') or 0, cost=usage.get('cost')))
            else:
                tools.append(dict(start=stamp(start), end=stamp(e), seconds=seconds, tool=e.get('tool'),
                                  error=bool(e.get('error')) or kind == 'tool_failed'))
    # A call that never completed (provider error, timeout, crash) lasts until the first later event
    # that reports an error or ends the episode (background guards keep logging meanwhile).
    stamps = sorted(stamp(e) for e in events if e.get('timestamp'))
    endings = sorted(stamp(e) for e in events if e.get('timestamp') and (
        e.get('error') or e.get('event') in ('episode_finished', 'model_started', 'tool_started')))
    for start in open_calls.values():
        begun = stamp(start)
        end = next((t for t in endings if t > begun), stamps[-1] if stamps else begun)
        if start['event'] == 'model_started':
            model.append(dict(start=begun, end=end, seconds=end - begun, input=0, output=0, cached=0, cost=None,
                              failed=True))
        else:
            tools.append(dict(start=begun, end=end, seconds=end - begun, tool=start.get('tool'), error=True))
    model.sort(key=lambda m: m['start'])
    tools.sort(key=lambda t: t['start'])
    metadata = json.loads((directory / 'metadata.json').read_text()) if (directory / 'metadata.json').exists() else {}
    print(f"\n{directory}\nmodel {metadata.get('model')}  backend {metadata.get('model_backend')}  "
          f"goal {str(metadata.get('goal'))[:80]!r}")
    if not model:
        print('no completed model calls')
        return
    print(f"{'#':>3} {'in tok':>7} {'cached':>7} {'out':>5} {'model s':>8} {'ms/out':>7} "
          f"{'tools s':>8} {'other s':>8}  tools")
    for i, call in enumerate(model):
        nxt = model[i + 1]['start'] if i + 1 < len(model) else max([call['end']] + [t['end'] for t in tools] + stamps[-1:])
        batch = [t for t in tools if call['end'] <= t['start'] < nxt]
        tool_s = sum(t['seconds'] for t in batch)
        other = (nxt - call['end']) - tool_s
        names = ', '.join(f"{t['tool']} {t['seconds']:.1f}" + ('!' if t['error'] else '') for t in batch)
        per = 1000 * call['seconds'] / call['output'] if call['output'] else float('nan')
        print(f"{i:>3} {call['input']:>7} {call['cached']:>7} {call['output']:>5} {call['seconds']:>8.2f} "
              f"{per:>7.0f} {tool_s:>8.2f} {other:>8.2f}  {names}" + ('  [model call failed]' if call.get('failed') else ''))
    wall = max([m['end'] for m in model] + [t['end'] for t in tools] + stamps[-1:]) - model[0]['start']
    model_s = sum(m['seconds'] for m in model)
    tool_s = sum(t['seconds'] for t in tools)
    out = sum(m['output'] for m in model)
    failed = [m for m in model if m.get('failed')]
    if failed:
        print(f"{len(failed)} model call(s) failed without a response ({sum(m['seconds'] for m in failed):.1f}s); "
              "the fit and per-token figures use completed calls only")
    model_ok = [m for m in model if not m.get('failed')]
    cost = [m['cost'] for m in model if m['cost'] is not None]
    print(f"wall {wall:.1f}s = model {model_s:.1f}s ({100 * model_s / wall:.0f}%) + tools {tool_s:.1f}s "
          f"({100 * tool_s / wall:.0f}%) + other {wall - model_s - tool_s:.1f}s (observation, guards, pacing)")
    print(f"{len(model)} model calls, mean {model_s / len(model):.2f}s; input {sum(m['input'] for m in model)} tok "
          f"(cached {sum(m['cached'] for m in model)}), output {out} tok; "
          f"whole-call ms per output token {1000 * model_s / out:.0f}" if out else '')
    if cost:
        print(f"provider-reported cost ${sum(cost):.4f}")
    by_tool = {}
    for t in tools:
        by_tool.setdefault(t['tool'], []).append(t['seconds'])
    print('tool latency: ' + '; '.join(f"{name} n={len(v)} mean {sum(v) / len(v):.2f}s max {max(v):.2f}s"
                                         for name, v in sorted(by_tool.items(), key=lambda kv: -sum(kv[1]))))
    if len(model_ok) >= 5:
        fit(model_ok)


def fit(model):
    """Least squares latency = a + b*input_k + c*output, via normal equations (no numpy needed)."""
    rows = [(1.0, m['input'] / 1000, float(m['output'])) for m in model]
    ys = [m['seconds'] for m in model]
    n = 3
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(n)] for i in range(n)]
    aty = [sum(r[i] * y for r, y in zip(rows, ys)) for i in range(n)]
    try:
        for col in range(n):  # Gauss-Jordan with partial pivoting
            pivot = max(range(col, n), key=lambda r: abs(ata[r][col]))
            ata[col], ata[pivot], aty[col], aty[pivot] = ata[pivot], ata[col], aty[pivot], aty[col]
            if abs(ata[col][col]) < 1e-12:
                raise ZeroDivisionError
            for r in range(n):
                if r != col:
                    f = ata[r][col] / ata[col][col]
                    ata[r] = [x - f * y for x, y in zip(ata[r], ata[col])]
                    aty[r] -= f * aty[col]
        a, b, c = (aty[i] / ata[i][i] for i in range(n))
    except ZeroDivisionError:
        print('fit: not enough variation in sizes')
        return
    print(f"fit: latency ≈ {a:.2f}s + {b * 1000:.1f}ms per 1k input + {c * 1000:.1f}ms per output token "
          f"(TPOT estimate {c * 1000:.1f}ms; rough with few steps)")


if __name__ == '__main__':
    for directory in episode_dirs(sys.argv[1] if len(sys.argv) > 1 else None):
        report(directory)
