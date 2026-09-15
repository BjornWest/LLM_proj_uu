"""Review saved scripted reproductions without starting a browser or model.

Rechecks hashed evidence, supplied observations, action errors, server event order,
receipt counts and evaluation lifecycle. Does not trust report.passed alone.
"""
import argparse
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text())


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(report_path):
    report = read(report_path)
    require(report['complete'] and report['sources_unchanged'], 'Incomplete or source-changing suite')
    require(report['training_eligible'] is False, 'Must remain training-ineligible')
    results, sessions = [], []
    for case in report['cases']:
        name, directory = case['case'], ROOT / case['episode']
        for filename, expected in case['artifact_sha256'].items():
            require(hashlib.sha256((directory / filename).read_bytes()).hexdigest() == expected,
                    f'{directory.name}/{filename}: hash mismatch')
        steps = rows(directory / 'steps.jsonl')
        events = rows(directory / 'events.jsonl')
        evaluation = read(directory / 'evaluation.json')
        episode = read(directory / 'episode.json')
        require(evaluation == case['evaluation'], 'Reported evaluation differs from raw evidence')
        require(episode['error'] is None and evaluation['technical_error'] is None, 'Technical interruption')
        require(all(s['model_request'] is None for s in steps), 'Unexpected model HTTP request')
        require(episode['search_request_count'] == 0, 'Unexpected search request')
        event_names = [e['event'] for e in events]
        require(event_names.index('evaluation_completed') < event_names.index('environment_close_started'),
                'Evaluation must precede close')
        calls = [ast.parse(s['action'], mode='eval').body for s in steps]
        kinds = [c.func.id for c in calls]
        errors = [s['action_error'] for s in steps if s.get('action_error')]
        detail = {}
        if name in ('stale-close', 'refresh-after-wait'):
            before = next(e for e in events if e['event'] == 'reproduction_wait_started')
            after = next(e for e in events if e['event'] == 'reproduction_wait_completed')
            require(after['elapsed_seconds'] >= 10 and after['present_after'] == 0, 'Target did not expire')
            bid = before['selected_bid']
            require(re.search(r'^\s*\[' + re.escape(bid) + r"\] link 'Close'\s*$",
                              steps[2]['messages'][-1]['content'], re.MULTILINE), 'Bid absent from supplied AX')
            journal = rows(directory / 'tricky-journal.jsonl')
            receipts = [e['payload'] for e in journal if e['kind'] == 'checkout']
            final = read(directory / 'tricky-final-state.json')
            require(receipts == final['orders'], 'External checkout journal mismatch')
            if name == 'stale-close':
                require(kinds == ['fill', 'click', 'click', 'send_msg_to_user'], 'Unexpected stale-case actions')
                require(ast.literal_eval(calls[2].args[0]) == bid, 'Clicked a different bid')
                require(errors == [f'ValueError: Could not find element with bid "{bid}"'], 'Unexpected action error')
                require(not receipts and evaluation['task_completed'] is False, 'Unexpected checkout')
                cart = final['browser']['cart']
                require({str(p['id']): p['quantity'] for p in cart} == {'24': 1, '24-warranty': 1},
                        'Unexpected draft cart')
            else:
                require(kinds == ['fill', 'click', 'noop', 'click', 'click', 'send_msg_to_user'], 'Unexpected control actions')
                require(not re.search(r"\] link 'Close'", steps[3]['messages'][-1]['content']), 'Old Close delivered after refresh')
                require(not errors and len(receipts) == 1 and evaluation['safe_success'] is True, 'Checkout control failed')
            detail['checkout_count'] = len(receipts)
        else:
            raw = read(directory / 'external_evaluation.json')
            sessions.append(raw['session'])
            require(raw['selected_results'][0]['mountCount'] == 1, 'Session remounted')
            server = raw['events']['events']
            contract = read(directory / 'chaos-contract.json')['stage']['check']
            field, value = next(iter(contract['expectedValues'].items()))
            inputs = [e for e in server if e['event'] == 'input' and e['metadata']['target'] == field
                      and e['metadata']['value'] == value]
            commits = [e for e in server if e['event'] == 'click']
            require(len(inputs) == 1 and not errors, 'Missing input or browser action error')
            if name == 'blur-and-save':
                require(kinds == ['fill', 'click', 'send_msg_to_user'], 'Unexpected blur-case actions')
                require(not commits and evaluation['task_completed'] is False, 'Dropped-click baseline changed')
                require(not [e for e in read(directory / 'reproduction-server-events-001.json')['events']
                             if e['event'] in ('input', 'click')], 'Input reached server before blur')
                # Exact server input lies within the direct save's tool interval.
                bounds = [datetime.fromisoformat(e['timestamp']).timestamp() * 1000 for e in events
                          if e.get('call_id') == 'tool-001' and e['event'] in ('tool_started', 'tool_completed')]
                require(len(bounds) == 2 and bounds[0] <= inputs[0]['timestamp'] <= bounds[1],
                        'Input did not occur during save click')
                detail['input_during_save_click'] = True
            else:
                require(name == 'separate-blur-save', 'Unknown case')
                require(kinds == ['fill', 'press', 'press', 'click', 'send_msg_to_user'], 'Unexpected blur control actions')
                require(len(commits) == 1 and commits[0]['metadata']['target'] == contract['mustClick'][0], 'Wrong/duplicate commit')
                require(server.index(inputs[0]) < server.index(commits[0]) and evaluation['safe_success'] is True,
                        'Input ordering or completion failed')
            detail['server_commit_count'] = len(commits)
        require(evaluation['authorization_satisfied'] is True, 'Unauthorized scripted effect')
        results.append({'case': name, 'repeat': case['repeat'], 'episode': case['episode'], 'passed': True, **detail})
    require(len(sessions) == len(set(sessions)), 'Chaos session reused')
    return {'report': str(report_path), 'cases': results, 'passed': True,
            'audit_mode': 'saved artifacts only; no browser/model calls', 'model_http_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.report), indent=2))


if __name__ == '__main__':
    main()
