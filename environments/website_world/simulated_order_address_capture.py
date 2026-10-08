"""Actual address evidence and complete retained store snapshots, no authority.

Evaluation selects/grades the observed addresses. This module never grades an
order count, price, delivery selection or the completeness of external effects.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from intent_browser.connected_world_task import checked_files
from .adapter import digest
from .catalog_cart_execution import save_new
from .simulated_order_capture import OrderCapture

VERSION = 'website-simulated-order-address-capture-v1'


class AddressOrderCapture(OrderCapture):
    def __init__(self, runtime, task, *, source_files):
        super().__init__(runtime, task, source_files=source_files)
        self.capture_sha256 = sha256(Path(__file__).read_bytes()).hexdigest()
        if source_files.get(str(Path(__file__).resolve())) != self.capture_sha256:
            raise ValueError('Address capture implementation absent from source union')
        self.storage_artifacts = {}

    def _storage(self, env, trace, phase):
        self._check()
        if self.trace is not trace or phase in self.storage_artifacts:
            raise ValueError('Capture exactly one storage snapshot per actual phase')
        page = env.unwrapped.page
        try:
            storage = page.context.storage_state()
        finally:
            env.unwrapped._active_page_check()
        if env.unwrapped.page is not page:
            raise ValueError('Address capture changed the active task page')
        rid = self.task['retailer_id']
        row = {'schema_version': VERSION, 'phase': phase,
            'episode_id': trace.episode_id, 'binding': deepcopy(self.binding),
            'retailer_id': rid, 'origin': self.runtime.origins[rid],
            'storage_key': 'website-drafts.state.' + rid,
            'implicit_country': 'SE', 'active_url': page.url,
            'storage_state': deepcopy(storage), 'full_effects': 'unknown'}
        path = trace.directory/'manual-review-private'/('order-address-'+phase+'.private.json')
        save_new(path, row)
        self.storage_artifacts[phase] = {'path': str(path.resolve()),
                                       'sha256': sha256(path.read_bytes()).hexdigest()}
        return deepcopy(self.storage_artifacts[phase])

    def before(self, env, trace):
        ledger = super().before(env, trace)
        return {'ledger': ledger, 'address_storage': self._storage(env, trace, 'before')}

    def after(self, env, trace, outcome):
        ledger = super().after(env, trace, outcome)
        return {'ledger': ledger, 'address_storage': self._storage(env, trace, 'after')}

    def seal(self, returned_trace, summary):
        """After cleanup, bind actual artifacts for the external limited grader.

        Inherited seal only closes the store/checks actual ledger drift. Its raw
        capsule keeps effect_journal null; it is not a full-order authority.
        """
        root = Path(returned_trace).resolve()
        if set(self.storage_artifacts) != {'before', 'after'}:
            raise ValueError('Missing actual baseline/terminal address observations')
        storage = {}
        for phase, artifact in self.storage_artifacts.items():
            path = Path(artifact['path'])
            if (not path.is_relative_to(root)
                    or sha256(path.read_bytes()).hexdigest() != artifact['sha256']):
                raise ValueError('Observed address artifact changed')
            storage[phase] = json.loads(path.read_bytes())
            if (storage[phase]['phase'] != phase
                    or storage[phase]['binding'] != self.binding
                    or storage[phase]['episode_id'] != self.trace.episode_id):
                raise ValueError('Observed address belongs to another lifecycle')
        capsule, completed = super().seal(returned_trace, summary)
        # Retain every native record; no deduplication or winner selection here.
        evidence = {'schema_version': VERSION, 'task_id': self.task['task_id'],
            'task_sha256': digest(self.task), 'binding': deepcopy(self.binding),
            'episode_id': capsule['episode_id'],
            'main_trace_sha256': capsule['main_trace_sha256'],
            'ledger': deepcopy(capsule), 'checkout_storage': storage,
            'artifacts': {'orders': deepcopy(self.artifacts),
                          'checkout_storage': deepcopy(self.storage_artifacts)},
            'full_effects': 'unknown', 'complete_effect_envelope': None,
            'order_outcome_scored': False}
        save_new(root/'manual-review-private/order-address-evidence.private.json', evidence)
        return evidence, completed
