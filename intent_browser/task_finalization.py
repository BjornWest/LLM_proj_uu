"""One explicit final-grade boundary for local suites and hosted execution.

The ordinary runner keeps its original pre-close evaluation/episode unchanged.
Adapters declaring post-close grading must return Evaluation after HAR flush.
This module has no model/backend, registry, setup or site-specific verifier logic.
"""
from copy import deepcopy
from dataclasses import fields
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from .evaluation import Evaluation


def finalize_task_run(task, trace_directory, summary):
    directory = Path(trace_directory)
    target = directory / 'authoritative-evaluation.json'
    if target.exists() or target.is_symlink():
        raise FileExistsError('Authoritative result already recorded; do not rerun grading')
    phase = getattr(task, 'grading_phase', 'before_browser_close')
    if phase not in ('before_browser_close', 'after_browser_close'):
        raise ValueError('Unknown authoritative grading phase')
    started = datetime.now(timezone.utc).isoformat()
    runtime_file = directory / 'evaluation.json'
    runtime_raw = runtime_file.read_bytes()
    runtime = json.loads(runtime_raw)
    try:
        if phase == 'after_browser_close':
            events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
            if not any(row.get('event') == 'environment_close_completed' for row in events):
                raise ValueError('No recorded browser-close boundary; post-close grading refused')
            value = task.finalize_after_close(directory, deepcopy(summary))
            if not isinstance(value, Evaluation):
                raise TypeError('Post-close verifier must return Evaluation')
        else:
            value = Evaluation(**{field.name: runtime[field.name] for field in fields(Evaluation) if field.name in runtime})
        value.technical_error = summary.get('error') or value.technical_error
        result = value.to_dict()
    except Exception as error:
        result = Evaluation('authoritative-grading-error', '1', technical_error=f'{type(error).__name__}: {error}',
                            evidence=['evaluation.json'], limitations=['No fallback to a pre-close or declared success label.']).to_dict()
    record = {'schema': 'task-authoritative-result-v1', 'grading_phase': phase,
              'runtime_evaluation_file': 'evaluation.json',
              'runtime_evaluation_sha256': hashlib.sha256(runtime_raw).hexdigest(),
              'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
              'evaluation': result}
    # Never silently replace a historical result, including a dangling symlink.
    with target.open('x') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return record
