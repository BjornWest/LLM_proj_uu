#!/usr/bin/env python3
"""One isolated frozen P11 episode. Sampling stays in the native TRL worker."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frozen', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--fd', type=int, required=True)
    a = p.parse_args()
    root = a.frozen.resolve()
    manifest = json.loads((root.parent / 'frozen-sources.json').read_text())
    def check():
        for name, expected in manifest['files'].items():
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError('Snapshot changed: ' + name)
    check()
    sys.path.insert(0, str(root))
    from intent_browser.backend import Completion
    from intent_browser.harness import native_tools_profile
    from intent_browser.runner import run_episode
    from scripts.harness_suite_tasks import create
    connection = socket.socket(fileno=a.fd)
    stream = connection.makefile('rw')
    limits = json.loads(stream.readline())

    class Backend:
        def configure_tools(self, options):
            self.options = options
        def complete(self, messages):
            self.last_request = dict(messages=messages, **self.options)
            stream.write(json.dumps(dict(kind='sample', messages=messages, options=self.options)) + '\n')
            stream.flush()
            raw = json.loads(stream.readline())
            return Completion(raw['choices'][0]['message'].get('content') or '', raw, self.last_request)

    case = dict(id='P11-clean', family='tricky', task='P11', condition='clean')
    task, factory, terminal, _ = create(case, dict(tricky_build=str(root / 'site')), None, a.output, a.output.name)
    try:
        trace, summary = run_episode(factory, Backend(), dict(task='P11-clean', driver='native-TRL', training_eligible=False),
            output=a.output / 'traces', max_steps=limits['max_steps'], seed=a.seed, episode_task=task,
            harness_profile=native_tools_profile(parallel_tool_calls=None, compact_feedback=True, reasoning_replay='preserve'),
            observation_text_limit=48000, terminal_response_instruction=terminal)
    finally:
        task.close()
    check()
    imported = {}
    for name, module in tuple(sys.modules.items()):
        if name.split('.')[0] in ('intent_browser', 'scripts') and getattr(module, '__file__', None):
            path = Path(module.__file__).resolve()
            if not path.is_relative_to(root):
                raise RuntimeError('Project import escaped snapshot: ' + name)
            imported[name] = str(path.relative_to(root))
    result = dict(kind='result', trace=str(trace), evaluation=json.loads((trace / 'evaluation.json').read_text()),
                  steps=summary['step_count'], action_errors=summary['action_error_count'], imports=imported)
    (a.output / 'result.json').write_text(json.dumps(result, indent=2))
    stream.write(json.dumps(result) + '\n')
    stream.flush()


if __name__ == '__main__':
    main()
