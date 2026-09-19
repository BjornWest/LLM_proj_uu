"""Private process boundary for the current expanded runtime, never a web API."""
import json
import os
from pathlib import Path
import sys


def main():
    from .expanded_tasks import certified_tasks
    operation = sys.argv[1] if len(sys.argv) == 2 else None
    value = json.load(sys.stdin)
    env = dict(os.environ)
    if operation == 'capabilities':
        rows, _ = certified_tasks(env)
        print(json.dumps([{'id': row['id'], 'revision': row['revision']} for row in rows]))
    elif operation == 'execute' and set(value) == {'job', 'data_dir'}:
        from .team_worker import Broker, execute_job
        if not value['job']['task'].startswith(('tricky:', 'webarena:')):
            raise ValueError('Only expanded tasks use this runtime')
        broker = Broker(env['HARNESS_URL'], env['HARNESS_WORKER_TOKEN'])
        try: execute_job(broker, value['job'], Path(value['data_dir']), env)
        finally: broker.client.close()
    else:
        raise ValueError('Unknown private runtime operation')


if __name__ == '__main__': main()
