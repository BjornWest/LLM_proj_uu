"""Per-turn latency breakdown of one saved browser trace (read-only).

Segments follow the 2026-10-14 B14 analysis so local scripted runs and the live
trace are comparable: model request span, harness gap (response to next
request), response to first tool, decision observation, per-tool execution and
inter-tool gaps, plus capture counts by phase and env-step phase medians.
Spans are taken from events.jsonl timestamps; nested diagnostics are reported
separately and must not be summed with the exclusive per-turn segments.
"""
import argparse
import collections
import glob
import json
import re
import statistics
from datetime import datetime
from pathlib import Path


def ts(event):
    return datetime.fromisoformat(event['timestamp']).timestamp()


def stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {'n': len(values), 'sum': round(sum(values), 3), 'mean': round(statistics.mean(values), 3),
            'median': round(statistics.median(values), 3), 'max': round(max(values), 3)}


def analyze(trace):
    trace = Path(trace)
    events = [json.loads(line) for line in (trace / 'events.jsonl').open()]
    steps = [json.loads(line) for line in (trace / 'steps.jsonl').open()]
    model = {}
    for e in events:
        if e['event'] in ('model_started', 'model_completed'):
            model.setdefault(e['call_id'], {})[e['event']] = ts(e)
    turns = []
    order = sorted(model.items(), key=lambda kv: kv[1].get('model_started', 0))
    tools = [e for e in events if e['event'] in ('tool_started', 'tool_completed')]
    decisions = {str(e['step']): e for e in events if e['event'] == 'decision_observation_completed'}
    tool_spans = collections.defaultdict(list)
    open_tools = {}
    for e in tools:
        if e['event'] == 'tool_started':
            open_tools[e['call_id']] = (e['tool'], ts(e))
        elif e['call_id'] in open_tools:
            name, start = open_tools.pop(e['call_id'])
            tool_spans[name].append((start, ts(e)))
    all_spans = sorted((s, f, n) for n, spans in tool_spans.items() for s, f in spans)
    for index, (call, span) in enumerate(order):
        start, end = span.get('model_started'), span.get('model_completed')
        if end is None:
            continue
        nxt = order[index + 1][1].get('model_started') if index + 1 < len(order) else None
        in_turn = [(s, f, n) for s, f, n in all_spans if s >= end and (nxt is None or f <= nxt)]
        row = {'call': call, 'model_seconds': end - start,
               'harness_gap_seconds': (nxt - end) if nxt else None,
               'response_to_first_tool_seconds': (in_turn[0][0] - end) if in_turn else None,
               'tool_seconds': sum(f - s for s, f, _ in in_turn) if in_turn else 0.0,
               'between_tools_seconds': sum(in_turn[i + 1][0] - in_turn[i][1] for i in range(len(in_turn) - 1)) if in_turn else 0.0,
               'tools': [n for _, _, n in in_turn]}
        step_no = str(int(call.split('-')[1]) + 1)
        if step_no in decisions:
            row['next_decision_observation_seconds'] = float(decisions[step_no].get('seconds') or 0)
        turns.append(row)
    pipeline = [s.get('observation_pipeline') for s in steps if s.get('observation_pipeline')]
    residual = [p['barrier_seconds'] - p['backend_completion_seconds'] for p in pipeline
                if p.get('barrier_seconds') is not None and p.get('backend_completion_seconds') is not None]
    phases = collections.Counter()
    for path in trace.glob('*.json.gz'):
        m = re.match(r'(?:(decision|batch_guard|background)-)?observation-\d+\.json\.gz', path.name)
        if m:
            phases[m.group(1) or 'transition'] += 1
    telemetry = collections.defaultdict(list)
    path = trace / 'env-step-telemetry.jsonl'
    if path.exists():
        starts = {}
        for line in path.open():
            e = json.loads(line)
            if e.get('event') == 'phase_started':
                starts[(e['step'], e['phase_id'])] = (e['phase'], e['seconds'], e.get('tool'))
            elif e.get('event') == 'phase_finished' and (e['step'], e['phase_id']) in starts:
                phase, began, tool = starts.pop((e['step'], e['phase_id']))
                telemetry[phase].append(e['seconds'] - began)
    readiness = [e for e in events if e['event'] == 'observation_readiness']
    selection = json.loads((trace / 'metadata.json').read_text()).get('runtime_selection')
    per_tool = {name: stats([f - s for s, f in spans]) for name, spans in tool_spans.items()}
    capture_events = collections.Counter(e['event'] for e in events if 'capture' in e['event'])
    return {
        'trace': str(trace), 'runtime_selection': selection, 'turns': len(turns),
        'segments': {key: stats([t.get(key) for t in turns]) for key in (
            'model_seconds', 'harness_gap_seconds', 'response_to_first_tool_seconds', 'tool_seconds',
            'between_tools_seconds', 'next_decision_observation_seconds')},
        'per_tool': per_tool,
        'pipeline_residual_wait_seconds': stats(residual),
        'pipeline_overlapped_turns': sum(1 for p in pipeline if p.get('overlapped')),
        'observation_artifacts_by_phase': dict(phases),
        'fact_capture_files': len(glob.glob(str(trace / 'fact-capture-*.json'))),
        'capture_events': dict(capture_events),
        'env_step_phases': {k: stats(v) for k, v in telemetry.items()},
        'readiness_events': len(readiness),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('trace')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    result = analyze(args.trace)
    if args.json:
        print(json.dumps(result, indent=1))
        return
    print('runtime_selection:', result['runtime_selection'])
    print('turns:', result['turns'])
    for key, value in result['segments'].items():
        print(f'  {key:42s}', value)
    print('  residual post-inference wait          ', result['pipeline_residual_wait_seconds'])
    print('per tool:')
    for key, value in sorted(result['per_tool'].items()):
        print(f'  {key:14s}', value)
    print('observation artifacts:', result['observation_artifacts_by_phase'], 'fact captures:', result['fact_capture_files'])
    print('env-step phases:')
    for key, value in sorted(result['env_step_phases'].items()):
        print(f'  {key:22s}', value)


if __name__ == '__main__':
    main()
