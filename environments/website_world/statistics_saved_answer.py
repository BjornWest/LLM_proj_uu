"""Thin statistics adapter for the common saved-answer lifecycle."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from . import saved_answer_lifecycle as lifecycle, saved_answer_publication as publication
from .catalog_statistics_execution import CatalogStatisticsEpisode
from .catalog_statistics_grading import CatalogStatisticsGrader

VERSION = 'website-statistics-saved-answer-v1'


def comparison_start(runtime, task):
    sites = [site for site in runtime.site_registry
             if site['site_id'] == task['comparison_site_id']]
    if (len(sites) != 1 or sites[0]['kind'] != 'aggregator'
            or sites[0]['name'] != task['comparison_site_name']):
        raise ValueError('Actual comparison-catalog identity changed')
    return sites[0]['origin'].rstrip('/')+'/search'


def prepare_saved(saved, output, *, expected_manifest_sha256, user_message):
    snapshot = publication.read_recipe(saved, expected_manifest_sha256=expected_manifest_sha256)
    saved, manifest, buffers = snapshot
    if manifest['recipe'] != 'website-catalog-statistics-publication-v1':
        raise ValueError('Not a saved statistics recipe')
    read = lambda name: json.loads(buffers[name])
    task = read('catalog-statistics-task.private.json')
    # Native validation precedes the ordinary prose/start override.
    from .catalog_statistics_task import reference
    if reference(read('pin/world.private.json'), read('surrounding.private.json'), task) != read('catalog-statistics-reference.private.json'):
        raise ValueError('Saved native statistics reference changed')
    setup = {'schema': publication.VERSION, 'task_id': task['task_id'],
        'user_message': user_message, 'memories': deepcopy(task['memories']),
        'start': {'kind': 'comparison_catalog', 'comparison_site_id': task['comparison_site_id']}}
    return publication.prepare_saved(snapshot, output, expected_manifest_sha256=expected_manifest_sha256,
        setup=setup, task_filename='catalog-statistics-task.private.json', adapter_file=__file__)


def checked_setup(setup_bytes, manifest, task):
    if manifest.get('saved_answer_recipe') != publication.VERSION:
        raise ValueError('Not a saved-answer statistics extension')
    if sha256(setup_bytes).hexdigest() != manifest['files']['saved-answer-setup.private.json']:
        raise ValueError('Saved setup differs from the checked recipe')
    setup = json.loads(setup_bytes)
    if (type(setup) is not dict or set(setup) != {'schema', 'task_id', 'user_message', 'memories', 'start'}
            or setup['schema'] != publication.VERSION or setup['task_id'] != task['task_id']
            or setup['memories'] != task['memories']
            or type(setup['user_message']) is not str or not setup['user_message'].strip()
            or setup['start'] != {'kind': 'comparison_catalog', 'comparison_site_id': task['comparison_site_id']}):
        raise ValueError('Saved statistics public setup changed')
    return setup


class SavedStatisticsEpisode(CatalogStatisticsEpisode):
    def __init__(self, output, *, lazy_publication=True):
        output = Path(output).resolve()
        setup_path = output/'saved-answer-setup.private.json'
        setup_bytes = setup_path.read_bytes()
        def saved_start(runtime, native):
            checked_setup(setup_bytes, self.manifest, native)
            return comparison_start(runtime, native)
        super().__init__(output, lazy_publication=lazy_publication, start_url_factory=saved_start)
        try:
            from intent_browser.standard_profile import standard_profile
            from intent_browser.connected_world_task import public_projection
            from .comparison_sku_task import episode_task
            task = self.answer_grader.task
            setup = checked_setup(setup_bytes, self.manifest, task)
            self.public = public_projection({**self.public, 'user_message': setup['user_message'],
                'start_url': comparison_start(self.runtime, task)})
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins,
                                            helpers=False, data_tools=False)
            self.site_discovery = None
            files = deepcopy(self.task.files)
            files[str(setup_path)] = self.manifest['files']['saved-answer-setup.private.json']
            self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                                     attachments=deepcopy(self.task.attachments))
            self.task.site_discovery_callback = None
        except BaseException:
            self.runtime.close()
            raise


def native_inputs(output, runtime_directory):
    return {'world': output/'pin/world.private.json',
        'task': output/'catalog-statistics-task.private.json',
        'reference': output/'catalog-statistics-reference.private.json',
        'site_registry': runtime_directory/'site-registry.private.json',
        'surrounding': output/'surrounding.private.json'}


def run(output, run_directory, **options):
    return lifecycle.run(output, run_directory, episode_factory=SavedStatisticsEpisode,
        inputs_factory=native_inputs, grader_factory=CatalogStatisticsGrader,
        contract_id=VERSION, verifier='catalog-statistics-native', **options)
