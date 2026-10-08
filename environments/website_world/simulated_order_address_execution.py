"""Order-capable address-only setup/capture; Evaluation owns grade and run.

No policy runner is exposed here: dispatch must attach the separately accepted
address-only automatic grader and viewer. Full-order execution stays separate.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from . import generation as shared, short_task_setup as setup
from . import simulated_order_task as native
from . import simulated_order_capture as capture_api
from .simulated_order_address_capture import AddressOrderCapture
from .simulated_order_address_publication import VERSION as RECIPE, SCOPE
from .simulated_order_execution import checked_union
from .adapter import digest
from .catalog_cart_execution import save_new

VERSION = 'website-simulated-order-address-execution-v1'


class AddressOnlyOrderEpisode(shared.GeneratedEpisode):
    """Actual ordinary cart setup, default ordering and bound raw address evidence."""
    def __init__(self, output, *, lazy_publication=None, additional_source_files=None):
        manifest = shared.load(output)
        if (manifest.get('order_address_recipe') != RECIPE
                or manifest.get('scoring_scope') != SCOPE
                or manifest.get('simulated_order_recipe') is not None
                or manifest.get('automatic_grader_supported') is not False):
            raise ValueError('Require a separate address-only recipe and external grader')
        if lazy_publication is None:
            lazy_publication = manifest['execution_policy']['runtime_options']['lazy_publication']
        sources = checked_union(manifest, additional_source_files)
        own = str(Path(__file__).resolve())
        if sources.get(own) != sha256(Path(own).read_bytes()).hexdigest():
            raise ValueError('Address episode implementation absent from frozen source union')
        super().__init__(output, lazy_publication=lazy_publication)
        try:
            read = lambda name: json.loads((self.output/name).read_bytes())
            self.native_task = read('simulated-order-task.private.json')
            if self.native_task != native.make(self.runtime.baskets, self.native_task['spec']):
                raise ValueError('Original ordering task, address or basket context changed')
            self.reference = read('order-address-reference.private.json')
            expected_reference = {'schema_version': RECIPE,
                'task_id': self.native_task['task_id'], 'task_sha256': digest(self.native_task),
                'retailer_id': self.native_task['retailer_id'],
                'expected_address': deepcopy(self.native_task['delivery_address']),
                'implicit_country': 'SE', 'scoring_scope': SCOPE,
                'full_effects': 'unknown', 'order_outcome_scored': False}
            if self.reference != expected_reference:
                raise ValueError('Address-only reference differs from unchanged native address')
            episode = read('episode.json')
            expected_public = {'user_message': self.native_task['user_message'],
                               'memories': self.native_task['memories']}
            rid = self.native_task['retailer_id']
            if (episode['task_id'] != self.native_task['task_id']
                    or episode['manual_task'] != expected_public
                    or episode['start'] != {'kind': 'retailer_home', 'retailer_id': rid}):
                raise ValueError('Original natural request/memories or retailer start changed')
            declaration = read('simulated-order-setup.private.json')
            if (self.native_task['coupon_code'] is not None or declaration != {
                    'start': {'kind': 'cart'}, 'prepared_cart': [{
                        'offer_id': self.native_task['spec']['offer_id'],
                        'quantity': self.native_task['spec']['quantity']}]}):
                raise ValueError('Use the unchanged explicit preloaded cart')
            self.setup_plan = setup.make_plan(self.runtime, retailer_id=rid, **declaration)
            if not self.runtime.public_catalogs[rid].get('simulatedOrders'):
                raise ValueError('Runtime does not offer actual simulated ordering')
            self.public = {**self.public, **deepcopy(expected_public),
                'task_id': self.native_task['task_id'], 'start_url': self.setup_plan['start_url']}
            files = deepcopy(self.task.files)
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            files.update(sources)
            self.task = type(self.task)(self.public, origins=self.runtime.navigation_origins,
                files=files, attachments=self.task.attachments, headless=self.task.headless,
                profile_name=self.profile.name)
            self.capture = AddressOrderCapture(self.runtime, self.native_task, source_files=sources)
            self.task = capture_api.prepared_task(self.task, self.capture, self.setup_plan, self.runtime)
            self.source_union = sources
        except BaseException:
            self.runtime.close()
            raise

    def export_private_runtime(self, output):
        manifest = super().export_private_runtime(output)
        output = Path(output).resolve()
        for name, value in (
                ('simulated-order-task.private.json', self.native_task),
                ('order-address-reference.private.json', self.reference),
                ('simulated-order-setup.private.json', self.setup_plan),
                ('order-address-source-union.private.json', self.source_union),
                ('order-ledger-before-setup.private.json', self.runtime.orders.snapshot())):
            save_new(output/name, value)
            manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
        manifest['scoring_scope'] = SCOPE
        manifest['full_effects'] = 'unknown'
        manifest['order_outcome_scored'] = False
        (output/'manifest.json').write_text(json.dumps(manifest, indent=2,
            ensure_ascii=False, allow_nan=False)+'\n')
        return manifest
