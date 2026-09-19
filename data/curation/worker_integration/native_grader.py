"""Offline native HAR grading; run in the pinned WebArena evaluator environment.

This process consumes privileged files. It never starts a browser or model call.
"""
import argparse
from importlib.metadata import version
import json
import hashlib
from pathlib import Path


def evaluate(task_id, response, har_path, origins):
    if version('webarena-verified') != '1.2.3':
        raise ValueError('Expected webarena-verified 1.2.3')
    from webarena_verified.api import WebArenaVerified
    from webarena_verified.types.config import WebArenaVerifiedConfig
    envs = {'__' + key.upper() + '__': {'urls': [value]} for key, value in origins.items()}
    config = WebArenaVerifiedConfig(environments=envs)
    expected = 'd65275660814663375028e9017e1f929e3c38321041b125795e2713b52243d30'
    if hashlib.sha256(config.test_data_file.read_bytes()).hexdigest() != expected:
        raise ValueError('Native evaluator dataset differs from reviewed source')
    api = WebArenaVerified(config=config)
    return api.evaluate_task(task_id=task_id, agent_response=response, network_trace=Path(har_path)).model_dump(mode='json')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() or a.output.is_symlink():
        raise FileExistsError(a.output)
    request = json.loads(a.input.read_text())
    result = evaluate(request['task_id'], request['response'], request['har_path'], request['origins'])
    with a.output.open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')


if __name__ == '__main__':
    main()
