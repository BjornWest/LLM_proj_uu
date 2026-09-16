"""Offline native grading of the scripted control smoke. Use the isolated WAV venv.

Never called by the policy. Expected results stay on the evaluator side.
The explicit task-type/status response is a scripted fixture, not model output.
"""
import argparse
import hashlib
import json
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--task-id', type=int, required=True, choices=[118, 399])
    args = parser.parse_args()
    har = args.trace / 'network.har'
    target = args.trace / 'native-evaluation.json'
    if target.exists():
        raise FileExistsError(target)
    api = WebArenaVerified(config=WebArenaVerifiedConfig(environments={
        '__SHOPPING__': {'urls': ['http://localhost:7770']},
        '__REDDIT__': {'urls': ['http://localhost:9999']},
    }))
    response = {'task_type': 'mutate' if args.task_id == 399 else 'navigate',
                'status': 'SUCCESS', 'retrieved_data': None}
    result = api.evaluate_task(task_id=args.task_id, agent_response=response, network_trace=har)
    # Keep a valid HAR but remove the class of event needed to satisfy the task.
    # This checks a failed criterion, rather than merely a malformed input error.
    reduced = json.loads(har.read_text())
    def excluded(entry):
        request = entry['request']
        return (request['method'] == 'POST' if args.task_id == 399 else
                urlsplit(request['url']).path.endswith('.html'))
    reduced['log']['entries'] = [e for e in reduced['log']['entries'] if not excluded(e)]
    negative_har = args.trace / 'negative-control.har'
    with negative_har.open('x') as f:
        json.dump(reduced, f)
    negative = api.evaluate_task(task_id=args.task_id, agent_response=response, network_trace=negative_har)
    report = {'scope': 'Scripted control integration, native task criteria only',
              'model_calls': 0, 'grader_recomputed': True,
              'evaluation_timing': 'offline after browser close/HAR flush',
              'authorization_preserved': None, 'safe_success': None,
              'task_id': args.task_id, 'webarena_verified_version': version('webarena-verified'),
              'scripted_agent_response': response,
              'har_sha256': hashlib.sha256(har.read_bytes()).hexdigest(),
              'task': api.get_task(args.task_id).model_dump(mode='json'),
              'result': result.model_dump(mode='json'),
              'removed_required_traffic_negative_control': negative.model_dump(mode='json'),
              'negative_har_sha256': hashlib.sha256(negative_har.read_bytes()).hexdigest()}
    with target.open('x') as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    if (result.score != 1 or negative.score != 0 or
            result.model_dump(mode='json')['status'] != 'success' or
            negative.model_dump(mode='json')['status'] != 'failure'):
        raise SystemExit('Native pass/negative-control assertion failed; inspect retained report')


if __name__ == '__main__':
    main()
