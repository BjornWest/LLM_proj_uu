"""Thin saved-answer adapter; reuse native pages, matching and shared lifecycle."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from . import saved_answer_lifecycle as lifecycle, saved_answer_publication as publication
from .catalog_unit_price_execution import CatalogUnitPriceEpisode
from .catalog_unit_price_grading import CatalogUnitPriceGrader

VERSION = 'website-unit-price-saved-answer-v1'
RECIPE = 'website-catalog-unit-price-publication-v2'
TASK, REFERENCE = 'catalog-unit-price-task.private.json', 'catalog-unit-price-reference.private.json'


def prepare_saved(saved, output, *, expected_manifest_sha256, user_message):
    snapshot = publication.read_recipe(saved, expected_manifest_sha256=expected_manifest_sha256)
    _, manifest, buffers = snapshot
    if manifest['recipe'] != RECIPE:
        raise ValueError('Wrong saved offer recipe kind')
    read = lambda name: json.loads(buffers[name])
    task = read(TASK)
    world, surrounding = read('pin/world.private.json'), read('surrounding.private.json')
    from .feature_offer_task import FieldInventory
    from .catalog_unit_price_task import reference
    expected = reference(world, task, inventory=FieldInventory(task['concept_id']), surrounding=surrounding)
    if expected != read(REFERENCE):
        raise ValueError('Saved native offer reference changed')
    setup = {'schema': publication.VERSION, 'task_id': task['task_id'],
        'user_message': user_message, 'memories': deepcopy(task['memories']),
        'start': deepcopy(read('episode.json')['start'])}
    return publication.prepare_saved(snapshot, output, expected_manifest_sha256=expected_manifest_sha256,
        setup=setup, task_filename=TASK, adapter_file=__file__)


def checked_setup(raw, manifest, task, original_start):
    if (manifest.get('saved_answer_recipe') != publication.VERSION
            or sha256(raw).hexdigest() != manifest['files']['saved-answer-setup.private.json']):
        raise ValueError('Saved offer setup differs from frozen recipe')
    setup = json.loads(raw)
    if (type(setup) is not dict or set(setup) != {'schema','task_id','user_message','memories','start'}
            or setup['schema'] != publication.VERSION or setup['task_id'] != task['task_id']
            or setup['memories'] != task['memories'] or setup['start'] != original_start
            or type(setup['user_message']) is not str or not setup['user_message'].strip()):
        raise ValueError('Saved offer public identity, memories or start changed')
    return setup


class SavedUnitPriceEpisode(CatalogUnitPriceEpisode):
    def __init__(self, output, *, lazy_publication=True):
        output = Path(output).resolve()
        super().__init__(output, lazy_publication=lazy_publication)
        try:
            from intent_browser.connected_world_task import public_projection
            from .comparison_sku_task import episode_task
            setup_path = output/'saved-answer-setup.private.json'
            setup = checked_setup(setup_path.read_bytes(), self.manifest, self.answer_grader.task,
                json.loads((output/'episode.json').read_bytes())['start'])
            self.public = public_projection({**self.public, 'user_message': setup['user_message']})
            files = deepcopy(self.task.files)
            files[str(setup_path)] = self.manifest['files']['saved-answer-setup.private.json']
            self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                                    attachments=deepcopy(self.task.attachments))
            self.task.site_discovery_callback = self.site_discovery
        except BaseException:
            self.runtime.close()
            raise


def native_inputs(output, runtime_directory):
    return {'world': output/'pin/world.private.json',
        'task': output/TASK, 'reference': output/REFERENCE,
        'bindings': runtime_directory/'bindings.private.json',
        'surrounding': output/'surrounding.private.json'}


def run(output, run_directory, **options):
    return lifecycle.run(output, run_directory, episode_factory=SavedUnitPriceEpisode,
        inputs_factory=native_inputs, grader_factory=CatalogUnitPriceGrader,
        contract_id=VERSION, verifier='catalog-unit-price-native', **options)
