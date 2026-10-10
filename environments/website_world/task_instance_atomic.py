"""Saved atomic task permutations retain native catalog and recorder bindings.

The adapter does not select fixtures, sample worlds or infer effect authority.
Whole-run remains the native default; scoped state grading must be explicit.
"""
from copy import deepcopy
import json

from . import atomic_product_task as native
from . import atomic_product_publication as publication
from . import atomic_product_execution_consumer as consumer


class AtomicAdapter:
    stem = 'atomic-product'
    recipe = publication.CAPTURE_CONTAINER
    task_file = 'atomic-product-task.private.json'
    reference_file = 'atomic-product-reference.private.json'
    inventory_file = 'atomic-product-catalog.private.json'

    @staticmethod
    def recipe_matches(manifest):
        return all(manifest.get(k) == value for k, value in publication.recipe_marker().items())

    @staticmethod
    def _read(snapshot, name):
        if snapshot is None:
            raise ValueError('Atomic permutations require manifest-bound saved runtime inputs')
        return json.loads(snapshot[2][name])

    def construct(self, world, surrounding, parameters, *, snapshot=None):
        parameters = deepcopy(parameters)
        scope = publication.checked_scope(parameters.pop('scoring_scope', 'whole_run'))
        parameters.pop('prepared_cart', None)
        parameters.pop('product_details_open', None)
        parameters.pop('product_details_heading', None)
        catalog = self._read(snapshot, self.inventory_file)
        args = {'catalog': catalog,
                'bindings': self._read(snapshot, 'atomic-product-bindings.private.json'),
                'checkout_domain': self._read(snapshot, 'checkout-domain.private.json')}
        runtime_options = assets = None
        if scope == 'observed_atomic_state':
            runtime_options = self._recorder(snapshot, parameters)
            assets = self._read(snapshot, 'atomic-product-assets.private.json')
        packet = publication.compile_packet(world, parameters, scoring_scope=scope,
            runtime_options=runtime_options, asset_sha256=assets, **args)
        return packet['task'], packet['reference'], packet['catalog']

    def _recorder(self, snapshot, spec):
        # The served recorder settings are asset-bound. Tuple and quantity
        # permutations remain on that exact saved page; page changes require
        # a separately prepared native source recipe with its actual assets.
        options = self._read(snapshot, 'atomic-product-runtime-options.private.json')
        catalog = self._read(snapshot, self.inventory_file)
        pages = [p for p in catalog['products']
                 if any(v['offerId'] == spec['offer_id'] for v in p['variants'])]
        if len(pages) != 1 or catalog['siteId'] != spec['retailer_id']:
            raise ValueError('Atomic target must belong to the saved merchant catalog')
        rid = spec['retailer_id']
        if set(options) != {'selector_capture'} or set(options['selector_capture']) != {rid}:
            raise ValueError('Require the saved exact merchant recorder')
        if options['selector_capture'][rid]['page_id'] != pages[0]['id']:
            raise ValueError('Use a native source recipe whose bound recorder targets this page')
        return options

    def records(self, world, surrounding, task, reference, inventory, episode,
                start, user_message, *, snapshot=None, instance=None):
        if start != {'kind': 'product', 'offer_id': task['offer_id']}:
            raise ValueError('Atomic start must name the exact target product offer')
        if type(instance) is not dict:
            raise ValueError('Atomic records require the validated instance context')
        parameters = instance['parameters']
        scope = publication.checked_scope(parameters.get('scoring_scope', 'whole_run'))
        cart = deepcopy(parameters.get('prepared_cart', []))
        if type(cart) is not list:
            raise ValueError('Prepared cart must be explicit rows')
        setup = {'start': deepcopy(start),
                 'selected_offer_id': task['setup']['selected_offer_id'], 'prepared_cart': cart}
        if 'product_details_open' in parameters:
            if type(parameters['product_details_open']) is not bool:
                raise ValueError('Product details exposure must be boolean')
            setup['product_details_open'] = parameters['product_details_open']
        if 'product_details_heading' in parameters:
            heading = parameters['product_details_heading']
            if ('product_details_open' not in parameters or task['kind'] != 'read_public_fact'
                    or type(heading) is not str or heading != task['public_fact']['heading']):
                raise ValueError('Details heading must name the actual native public fact panel')
            setup['product_details_heading'] = heading
        records = {self.task_file: task, self.reference_file: reference,
                   self.inventory_file: inventory, 'atomic-product-setup.private.json': setup,
                   'atomic-product-scoring-scope.private.json': scope,
                   'episode.json': {'task_id': task['task_id'], 'readable_origins': True,
                       'start': deepcopy(task['start']), 'manual_task': {
                           'user_message': user_message, 'memories': deepcopy(task['memories'])}}}
        if scope == 'observed_atomic_state':
            records['atomic-product-runtime-options.private.json'] = self._recorder(snapshot, task['spec'])
            records['atomic-product-assets.private.json'] = self._read(snapshot, 'atomic-product-assets.private.json')
        elif any(name in snapshot[2] for name in (
                'atomic-product-runtime-options.private.json', 'atomic-product-assets.private.json')):
            raise ValueError('Use a whole-run source recipe for strict whole-run permutations')
        return records, deepcopy(start)

    @staticmethod
    def metrics(reference):
        return {'status': 'ready', 'population': 1}

    @staticmethod
    def manifest_updates(prepared):
        return {'atomic_product_recipe': publication.VERSION}

    @staticmethod
    def execution_overrides(prepared):
        execution = json.loads(prepared['snapshot'][2]['execution.private.json'])
        grading = execution.get('answer_grading', {'mode': 'off'})
        if prepared['task']['kind'].startswith('read_') and grading.get('mode') != 'subscription-post-run':
            raise ValueError('Atomic read source requires automatic post-run extraction')
        return {'answer_grading': deepcopy(grading)}

    @staticmethod
    def run(recipe, destination, **options):
        return consumer.run(recipe, destination, **options)


ADAPTER = AtomicAdapter()
