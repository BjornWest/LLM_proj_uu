"""Family-level bindings for configurable tasks; native semantics stay native."""
from copy import deepcopy
from dataclasses import dataclass

from . import feature_offer_task, catalog_priority_task, catalog_shortlist_task
from . import catalog_statistics_task, catalog_review_task
from . import feature_saved_answer, statistics_saved_answer, saved_answer_registry
from . import review_saved_runner
from .review_saved_inputs import target_setup
from .task_instance_navigation import BasicOfferAdapter, VariantLinkAdapter
from .task_instance_atomic import AtomicAdapter
from .task_instance_cart import CartAdapter


@dataclass(frozen=True)
class Adapter:
    stem: str
    native: object
    inventory_file: str

    @property
    def recipe(self):
        return 'website-' + self.stem + '-publication-v1'

    @property
    def task_file(self):
        return self.stem + '-task.private.json'

    @property
    def reference_file(self):
        return self.stem + '-reference.private.json'

    def construct(self, world, surrounding, parameters, *, snapshot=None):
        concept = parameters.get('concept_id')
        if self.stem == 'catalog-review':
            inventory = catalog_review_task.ReviewInventory(concept)
            task = self.native.make(world, parameters, inventory=inventory)
            reference = self.native.reference(world, task, inventory=inventory)
            record = {k: deepcopy(getattr(inventory, k)) for k in
                      ('concept_id', 'topics', 'legacy', 'source_hashes')}
            record['field_inventory'] = inventory_record(inventory.fields)
        else:
            inventory = feature_offer_task.FieldInventory(concept)
            if self.stem == 'catalog-statistics':
                task = self.native.make(world, surrounding, parameters, inventory=inventory)
                reference = self.native.reference(world, surrounding, task, inventory=inventory)
            else:
                task = self.native.make(world, parameters, inventory=inventory, surrounding=surrounding)
                reference = self.native.reference(world, task, inventory=inventory, surrounding=surrounding)
            record = inventory_record(inventory)
        return task, reference, record

    def records(self, world, surrounding, task, reference, inventory, episode,
                start, user_message, *, snapshot=None, instance=None):
        """Bind one native instance to the existing episode/setup schemas."""
        episode = deepcopy(episode)
        episode.update(task_id=task['task_id'], manual_task={
            'user_message': task['user_message'], 'memories': deepcopy(task['memories'])})
        # Old fixture labels can name an entirely different product/site.
        episode.pop('shopping_scope', None)
        records = {self.task_file: task, self.reference_file: reference,
                   self.inventory_file: inventory}
        if self.stem == 'catalog-review':
            coverage = [s['site_id'] for s in surrounding['sites']
                        if s['kind'] == 'product_reviews'
                        and task['subject']['product_id'] in s['product_ids']]
            binding = {'status': 'bound', 'publication_ids': coverage, 'world_repaired': False}
            if start.get('kind') != 'review_product' or set(start) - {'kind', 'site_id', 'query'}:
                raise ValueError('Review tasks require a review_product start with site_id and optional query')
            setup = target_setup(world, task, surrounding, binding,
                                 review_site_id=start.get('site_id'), start_query=start.get('query'))
            episode['start'] = {'kind': 'directory'}
            episode['readable_origins'] = True
            episode['manual_task']['user_message'] = user_message
            records['catalog-review-binding.private.json'] = binding
            records['saved-review-setup.private.json'] = setup
            public_start = setup['start']
        elif self.stem == 'catalog-statistics':
            public_start = {'kind': 'comparison_catalog', 'comparison_site_id': task['comparison_site_id']}
            if start != public_start:
                raise ValueError('Statistics start must name the task comparison_catalog')
            episode['start'] = {'kind': 'directory'}
            records['catalog-statistics-binding.private.json'] = {
                'status': 'bound', 'world_repaired': False, 'comparison_site_id': task['comparison_site_id']}
        else:
            if start not in ({'kind': 'directory'}, {'kind': 'tool_discovery'}):
                expected = {'kind': 'comparison_home', 'comparison_site_id': task.get('comparison_site_id')}
                if start != expected or expected['comparison_site_id'] is None:
                    raise ValueError('Offer start must be directory, tool_discovery or its comparison_home')
            episode['start'] = deepcopy(start)
            public_start = start
            if self.stem != 'feature-offer':
                records[self.stem + '-binding.private.json'] = {'status': 'bound', 'world_repaired': False}
        records['episode.json'] = episode
        return records, public_start

    def run(self, recipe, destination, **options):
        if self.stem == 'feature-offer':
            return feature_saved_answer.run(recipe, destination, **options)
        if self.stem == 'catalog-statistics':
            return statistics_saved_answer.run(recipe, destination, **options)
        if self.stem == 'catalog-review':
            return review_saved_runner.run(recipe, destination, **options)
        kind = self.stem.replace('-', '_')
        return saved_answer_registry.run(recipe, destination, kind=kind, **options)


def inventory_record(inventory):
    return {k: deepcopy(getattr(inventory, k)) for k in
            ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}


ADAPTERS = {
    'catalog_cart': CartAdapter(),
    'checkout_details': CartAdapter(checkout=True),
    'atomic_product': AtomicAdapter(),
    'basic_offer': BasicOfferAdapter(),
    'variant_link': VariantLinkAdapter(),
    'feature_offer': Adapter('feature-offer', feature_offer_task, 'feature-field-inventory.private.json'),
    'catalog_priority': Adapter('catalog-priority', catalog_priority_task, 'priority-field-inventory.private.json'),
    'catalog_shortlist': Adapter('catalog-shortlist', catalog_shortlist_task, 'shortlist-field-inventory.private.json'),
    'catalog_statistics': Adapter('catalog-statistics', catalog_statistics_task, 'statistics-field-inventory.private.json'),
    'catalog_review': Adapter('catalog-review', catalog_review_task, 'review-topic-inventory.private.json'),
}
