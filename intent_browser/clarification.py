"""Trusted user callback boundary. Stores evidence, never interprets preferences."""
from datetime import datetime, timezone
from .trace import write_json

VERSION = 'user-clarification-v1'


def execute_clarification(trace, index, question, callback, *, audit_id=None):
    """Return (policy feedback, artifact); callback errors are retained and re-raised.

    Callback-owned matched-field/audit state is never inspected or exposed here.
    The runner supplies a unique execution index, including within action batches.
    """
    if not callable(callback): raise ValueError('Clarification callback is required')
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise ValueError('Invalid clarification question')
    if audit_id is not None and (not isinstance(audit_id, str) or not audit_id.strip()):
        raise ValueError('Invalid clarification audit ID')
    artifact = f'clarification-{index:03d}.json'
    path = trace.directory / artifact
    if path.exists(): raise ValueError('Clarification evidence already exists')
    record = {'schema_version': VERSION, 'question': question, 'reply': None,
              'audit_id': audit_id, 'started_at': datetime.now(timezone.utc).isoformat(),
              'completed_at': None, 'error': None}
    # Retain attempted question even if callback is interrupted; no fabricated reply.
    write_json(path, record)
    try:
        reply = callback(question)
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError('Clarification callback must return a nonempty string')
        record['reply'] = reply
    except BaseException as exc:
        record['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        record['completed_at'] = datetime.now(timezone.utc).isoformat()
        write_json(path, record)
    return {'tool': 'ask_user', 'user_reply': reply}, artifact
