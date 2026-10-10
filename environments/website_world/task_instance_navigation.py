"""Saved task bindings for accepted variant links and ordinary listed offers.

These adapters preserve the native constructors and browser consumers. Link
capability comes from the authenticated parent recipe, never from parameters.
"""
from copy import deepcopy
import json

from . import basic_offer_task, basic_offer_saved_answer
from . import variant_link_publication, variant_link_execution


def _read(snapshot, name):
    if snapshot is None:
        raise ValueError('This adapter requires an authenticated saved recipe')
    return json.loads(snapshot[2][name])


class VariantLinkAdapter:
    stem = 'variant-link'
    recipe = variant_link_publication.VERSION
    task_file = 'variant-link-task.private.json'
    reference_file = 'variant-link-reference.private.json'
    inventory_file = 'variant-link-capability.private.json'

    def construct(self, world, surrounding, parameters, *, snapshot=None):
        packet = variant_link_publication.compile_packet(world=world,
            spec=parameters, catalog=_read(snapshot, 'variant-link-catalog.private.json'),
            bindings=_read(snapshot, 'variant-link-bindings.private.json'),
            asset_sha256=_read(snapshot, 'variant-link-assets.private.json'),
            acceptance=_read(snapshot, 'variant-link-acceptance.private.json'))
        return packet['task'], packet['reference'], packet['navigation_capability']

    def records(self, world, surrounding, task, reference, inventory, episode,
                start, user_message, *, snapshot=None, instance=None):
        if start != task['start']:
            raise ValueError('Link start must be the accepted native product page')
        episode = {'task_id': task['task_id'], 'readable_origins': True,
            'start': deepcopy(task['start']), 'manual_task': {
                'user_message': user_message, 'memories': deepcopy(task['memories'])}}
        variant_link_publication.public_request(task, episode)
        return {self.task_file: task, self.reference_file: reference,
                self.inventory_file: inventory, 'episode.json': episode}, deepcopy(start)

    def metrics(self, reference):
        return {'status': 'ready', 'population': 1}

    def execution_overrides(self, prepared):
        grading = _read(prepared['snapshot'], 'execution.private.json')['answer_grading']
        if grading.get('mode') != 'subscription-post-run':
            raise ValueError('Accepted link recipe requires its attached grading configuration')
        return {'answer_grading': deepcopy(grading)}

    def run(self, recipe, destination, **options):
        return variant_link_execution.run(recipe, destination, **options)


class BasicOfferAdapter:
    stem = 'basic-offer'
    recipe = basic_offer_saved_answer.VERSION
    task_file = 'basic-offer-task.private.json'
    reference_file = 'basic-offer-reference.private.json'
    inventory_file = 'basic-offer-inventory.private.json'

    def construct(self, world, surrounding, parameters, *, snapshot=None):
        task = basic_offer_task.make(world, parameters, surrounding=surrounding)
        reference = basic_offer_task.reference(world, task, surrounding=surrounding)
        inventory = {'concept_ids': deepcopy(world['config']['concept_ids']),
                     'price_basis': task['price_basis']}
        return task, reference, inventory

    def records(self, world, surrounding, task, reference, inventory, episode,
                start, user_message, *, snapshot=None, instance=None):
        expected = ({'kind': 'comparison_home', 'comparison_site_id': task['comparison_site_id']}
                    if 'comparison_site_id' in task else {'kind': 'directory'})
        if start != expected:
            raise ValueError('Listed-offer start must match its native comparison scope')
        episode = {'task_id': task['task_id'], 'readable_origins': True,
            'start': deepcopy(expected), 'manual_task': {
                'user_message': task['user_message'], 'memories': deepcopy(task['memories'])}}
        return {self.task_file: task, self.reference_file: reference,
                self.inventory_file: inventory, 'episode.json': episode}, expected

    def metrics(self, reference):
        return {'status': reference['status'], 'population': len(reference['candidates'])}

    def run(self, recipe, destination, **options):
        return basic_offer_saved_answer.run(recipe, destination, **options)
