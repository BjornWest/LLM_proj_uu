"""Episode capture of the host-produced session journal.

Modelled on `simulated_order_capture.OrderCapture`: the store is bound to the
episode before any request, a baseline is taken when the policy starts, and
the journal is sealed only after browser and Runtime cleanup. The sealed
journal is written unchanged into the trace; nothing here grades or repairs.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic

from environments.website_world.catalog_cart_execution import save_new
from .store import SessionStore

VERSION = 'website-commerce-session-capture-v1'
JOURNAL_FILE = 'manual-review-private/commerce-session-journal.private.json'


class SessionCapture:
    def __init__(self, runtime):
        if type(getattr(runtime, 'session', None)) is not SessionStore:
            raise ValueError('Capture needs a Runtime with a mounted commerce scenario')
        self.runtime, self.store = runtime, runtime.session
        self.trace = None
        self.artifacts = {}
        self.sealed = None

    def bind(self, trace, binding):
        """In the task's `prepare`: give the store the trace's episode id and bound binding."""
        if self.trace is not None:
            raise ValueError('Session capture is already bound to an episode')
        self.store.bind_episode(trace.episode_id, binding)
        self.trace = trace

    def _save(self, trace, name, value):
        if self.trace is not trace or name in self.artifacts:
            raise ValueError('Capture each session phase once, for the bound trace')
        private = trace.directory/'manual-review-private'
        private.mkdir(exist_ok=True)
        path = private/('commerce-session-' + name + '.private.json')
        save_new(path, value)
        self.artifacts[name] = {'path': str(path.resolve()), 'sha256': sha256(path.read_bytes()).hexdigest()}
        return deepcopy(self.artifacts[name])

    def before(self, env, trace):
        """When the policy starts: let a loaded shop page settle, then begin the journal."""
        page = env.unwrapped.page
        origin = self.runtime.origins[self.store.journal()['retailer_id']]
        if page.url.startswith(origin):
            deadline = monotonic() + 10
            while page.evaluate('document.documentElement.dataset.commerceScenario') != 'ready':
                if monotonic() >= deadline:
                    raise ValueError('Scenario page did not settle before the policy started')
                page.wait_for_timeout(25)
        baseline = self.store.begin()
        return self._save(trace, 'before', {'schema': VERSION, 'phase': 'before_policy',
                                            'before': baseline, 'store': self.store.snapshot()})

    def after(self, env, trace, outcome):
        """In the task's `evaluate`, before the browser context closes: a retained, unsealed view."""
        return self._save(trace, 'after', {
            'schema': VERSION, 'phase': 'after_policy_before_context_close',
            'outcome': {key: outcome.get(key) for key in ('stop_reason', 'terminated', 'truncated', 'error')},
            'store': self.store.snapshot()})

    def seal(self, returned_trace):
        """After browser and Runtime cleanup: seal the store and write the journal into the trace."""
        directory = Path(returned_trace).resolve()
        if self.sealed is not None:
            raise ValueError('Session journal is already sealed')
        if not self.runtime.closed:
            raise ValueError('Seal the session journal after browser and Runtime cleanup')
        if self.trace is not None and directory != self.trace.directory.resolve():
            raise ValueError('Returned trace differs from the bound episode')
        metadata = json.loads((directory/'metadata.json').read_bytes())
        journal = self.store.seal(episode_id=metadata['episode_id'])
        (directory/JOURNAL_FILE).parent.mkdir(exist_ok=True)
        save_new(directory/JOURNAL_FILE, journal)
        self.sealed = {'path': str(directory/JOURNAL_FILE),
                       'sha256': sha256((directory/JOURNAL_FILE).read_bytes()).hexdigest(),
                       'journal': journal}
        return deepcopy(journal)

    def journal(self, env, trace, outcome):
        """Callback for the automatic adapter: `(env, trace, outcome) -> sealed journal`."""
        if self.sealed is None:
            return self.seal(trace.directory)
        path = Path(self.sealed['path'])
        if (Path(trace.directory).resolve() != path.parents[1]
                or sha256(path.read_bytes()).hexdigest() != self.sealed['sha256']):
            raise ValueError('Sealed session journal changed or belongs to another trace')
        return deepcopy(self.sealed['journal'])
