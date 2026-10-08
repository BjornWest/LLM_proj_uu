"""Separate address-only recipe around an unchanged saved ordering instance.

Full-order sources/references remain available, but are not the scoring contract.
No manufacture, truth repair or complete-effect authority is supplied here.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from . import generation as shared, simulated_order_publication as ordering
from .adapter import digest

VERSION = 'website-simulated-order-address-publication-v1'
SCOPE = 'observed_checkout_or_submitted_address_only'


def prepare_saved(saved, output, *, spec, expected_world_sha256):
    """Freeze once through the existing native maker; preserve request/memories."""
    manifest = ordering.prepare_saved(saved, output, spec=spec,
                                     expected_world_sha256=expected_world_sha256)
    output = Path(output).resolve()
    task = json.loads((output/'simulated-order-task.private.json').read_bytes())
    reference = {'schema_version': VERSION, 'task_id': task['task_id'],
        'task_sha256': digest(task), 'retailer_id': task['retailer_id'],
        'expected_address': deepcopy(task['delivery_address']),
        'implicit_country': 'SE', 'scoring_scope': SCOPE,
        'full_effects': 'unknown', 'order_outcome_scored': False}
    shared.save(output/'order-address-reference.private.json', reference)
    execution = json.loads((output/'execution.private.json').read_bytes())
    execution['state_grading'] = 'evaluation_owned_address_only_wrapper_required'
    execution['address_only'] = {'recipe': VERSION, 'scoring_scope': SCOPE,
        'full_effects': 'unknown', 'order_outcome_scored': False}
    shared.save(output/'execution.private.json', execution)
    config = json.loads((output/'generation-config.private.json').read_bytes())
    config['recipe'] = VERSION
    config['address_only'] = deepcopy(execution['address_only'])
    shared.save(output/'generation-config.private.json', config)
    manifest.update(recipe=VERSION, order_address_recipe=VERSION,
        task_kind='simulated_order_address_only', scoring_scope=SCOPE,
        automatic_grader_supported=False,
        automatic_grader_requirement='evaluation_address_only_grade_and_viewer_wrapper',
        effect_authority='unknown_not_required_for_address_only_score',
        execution_policy=execution)
    # Reject accidental dispatch through the full-order recipe consumer.
    manifest['native_ordering_recipe'] = manifest.pop('simulated_order_recipe')
    for name in ('order-address-reference.private.json', 'execution.private.json',
                 'generation-config.private.json'):
        manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    shared.save(output/'manifest.json', manifest)
    return manifest
