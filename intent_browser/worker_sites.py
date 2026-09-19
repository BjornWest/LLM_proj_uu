"""Private worker lease client shared by hosted and local task execution.

Only registry identities and fixed state operations cross this boundary. Browser
proxy credentials are transient configuration, never task metadata or tool input.
"""
from copy import deepcopy
from urllib.parse import urlsplit

import httpx


class WorkerSites:
    def __init__(self, origin, token, *, transport=None):
        parsed = urlsplit(origin)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('Expected a private worker service origin')
        if not isinstance(token, str) or len(token) < 43:
            raise ValueError('Missing private worker service credential')
        self.client = httpx.Client(base_url=origin.rstrip('/'), headers={'Authorization': 'Bearer ' + token},
                                   timeout=60, trust_env=False, follow_redirects=False, transport=transport)

    def post(self, operation, value):
        response = self.client.post('/_control/' + operation, json=value)
        if response.status_code != 200:
            raise RuntimeError(f'Worker site {operation} returned HTTP {response.status_code}; no retry')
        return response.json()

    def acquire(self, task_id, revision, session_id):
        return WorkerLease(self, self.post('acquire', dict(task_id=task_id, revision=revision, session_id=session_id)))

    def close(self):
        self.client.close()


class WorkerLease:
    def __init__(self, service, record):
        self.service = service
        self._record = deepcopy(record)
        self._identity = deepcopy(record['identity'])
        self._baseline = None
        self._released = False
        if not self._identity.get('instance_id') or not self._identity.get('reset_id'):
            raise ValueError('Missing isolated worker instance identity')

    @property
    def browser_proxy(self):
        return deepcopy(self._record['browser_proxy'])

    @property
    def origin(self):
        return self._record['origin']

    def _post(self, command, **value):
        if self._released:
            raise RuntimeError('Worker lease already released')
        result = self.service.post(command, {'lease_token': self._record['lease_token'], **value})
        if result.get('identity') != self._identity:
            raise RuntimeError('Worker instance/reset changed; result refused')
        return result

    def attest(self):
        return deepcopy(self._post('renew')['identity'])

    def state_read(self, operation, arguments):
        # Adapter arguments are checked locally; no caller-chosen baseline,
        # target, SQL or container is ever forwarded to the host.
        if operation == 'forum.posts_since':
            if arguments != {'baseline_ids': self._baseline} or self._baseline is None:
                raise ValueError('Submission baseline differs from this lease')
        elif arguments:
            # A fixed vote target is selected from the admitted contract.
            if operation != 'forum.vote_state' or arguments != {'target_id': self._record.get('target_id')}:
                raise ValueError('State arguments differ from admitted task')
        result = self._post('state', operation=operation)
        if result.get('operation') != operation:
            raise RuntimeError('Unexpected state operation response')
        if operation == 'forum.submission_ids' and self._baseline is None:
            self._baseline = deepcopy(result['value'])
        return result['value']

    def close(self):
        if not self._released:
            # Do not automatically replay a failed release. The host deadline
            # still revokes the lease and quarantines/reset its clone.
            self._released = True
            self.service.post('release', {'lease_token': self._record['lease_token']})
