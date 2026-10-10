"""Saved listed-offer tasks over the common prospective answer lifecycle.

No world draw, new predicate, page modification or native grader is introduced.
The supplied native task/reference are replayed against the complete saved world.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import Execution, _bind
from experiments.answer_grading.listed_offer import SYSTEM
from . import basic_offer_task as native, generation as shared
from . import saved_answer_lifecycle as lifecycle, saved_answer_publication as publication
from . import unified_generation as unified
from .listed_offer_grading import ListedOfferGrader
from .comparison_stock_execution import ComparisonStockEpisode

VERSION = 'website-basic-offer-saved-answer-v1'
INPUTS = ('world.private.json', 'presentation.private.json', 'compositions.private.json',
          'surrounding.private.json', 'basket-plan.private.json', 'checkout-domain.private.json')


def _pinned(record):
    if type(record) is not dict or set(record) != {'path', 'sha256'}:
        raise ValueError('Declare exact saved native file pins')
    path = Path(record['path']).resolve()
    data = path.read_bytes()
    if sha256(data).hexdigest() != record['sha256']:
        raise ValueError('Saved native file changed: '+str(path))
    return data


def _reference(world, task, surrounding):
    if task.get('kind') != native.KIND:
        raise ValueError('Expected ordinary cheapest-available listed-offer task')
    return native.reference(world, task, surrounding=surrounding)


def prepare_saved(saved, output, *, expected_input_sha256, task_file, reference_file,
                  user_message=None):
    """Freeze explicit saved inputs and a native task into a fresh lazy recipe.

    Input hashes cover every required saved sidecar and the optional delivery
    menu when present. Task/reference pins identify literal Product-owned files.
    Nothing is repaired, sampled, or written into the original input directory.
    """
    saved, output = Path(saved).resolve(), Path(output).resolve()
    if output == saved or output.is_relative_to(saved) or saved.is_relative_to(output):
        raise ValueError('Use a fresh output separate from saved inputs')
    names = INPUTS + (('delivery-plan.private.json',) if (saved/'delivery-plan.private.json').exists() else ())
    if type(expected_input_sha256) is not dict or set(expected_input_sha256) != set(names):
        raise ValueError('Pin the complete saved world and sidecar input set')
    buffers = {}
    for name in names:
        path = saved/name
        if path.is_symlink(): raise ValueError('Saved input must be a regular file')
        buffers[name] = _pinned({'path': str(path), 'sha256': expected_input_sha256[name]})
    task_bytes, reference_bytes = _pinned(task_file), _pinned(reference_file)
    task, reference = json.loads(task_bytes), json.loads(reference_bytes)
    world, surrounding = json.loads(buffers['world.private.json']), json.loads(buffers['surrounding.private.json'])
    if _reference(world, task, surrounding) != reference:
        raise ValueError('Saved native listed-offer reference changed')
    message = task['user_message'] if user_message is None else user_message
    if type(message) is not str or not message.strip():
        raise ValueError('Require a nonempty public request')
    start = ({'kind': 'comparison_home', 'comparison_site_id': task['comparison_site_id']}
             if 'comparison_site_id' in task else {'kind': 'directory'})
    setup = {'schema': publication.VERSION, 'task_id': task['task_id'],
        'user_message': message, 'memories': deepcopy(task['memories']), 'start': start}
    sources = _bind(shared.source_files, __file__=__file__)()
    from scripts import trace_grades
    source = Path(trace_grades.__file__).resolve()
    sources[str(source.relative_to(shared.ROOT))] = sha256(source.read_bytes()).hexdigest()
    for name, h in publication.declared_sources(task, reference).items():
        if sha256((shared.ROOT/name).read_bytes()).hexdigest() != h or (name in sources and sources[name] != h):
            raise ValueError('Native dependency changed: '+name)
        sources[name] = h
    output.mkdir(parents=True, exist_ok=False)
    producer = Execution(validation='off').freeze(world, output/'pin')
    (output/'pin/world.private.json').write_bytes(buffers['world.private.json'])
    producer['files']['world.private.json'] = expected_input_sha256['world.private.json']
    (output/'pin/manifest.json').write_text(json.dumps(producer, indent=2)+'\n')
    for name, h in producer['source_sha256'].items():
        if name in sources and sources[name] != h: raise ValueError('Producer source conflict: '+name)
        sources[name] = h
    for name, h in sources.items():
        path = shared.ROOT/name
        payload = path.read_bytes()
        if sha256(payload).hexdigest() != h: raise ValueError('Source changed: '+name)
        target = output/'pin/source-snapshot'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    for name in names:
        if name == 'world.private.json': continue
        target = output/('presentation.json' if name == 'presentation.private.json' else name)
        with target.open('xb') as f: f.write(buffers[name])
    for name, data in (('basic-offer-task.private.json', task_bytes),
                       ('basic-offer-reference.private.json', reference_bytes)):
        with (output/name).open('xb') as f: f.write(data)
    shared.save(output/'episode.json', {'task_id': task['task_id'], 'readable_origins': True,
        'start': start, 'manual_task': {'user_message': task['user_message'], 'memories': task['memories']}})
    shared.save(output/'saved-answer-setup.private.json', setup)
    shared.save(output/'execution.private.json', {'source_sha256': sources,
        'answer_grading': {'mode': 'external_required', 'native_kind': task['kind']},
        'runtime_options': {'lazy_publication': True}})
    for name, h in expected_input_sha256.items(): _pinned({'path': str(saved/name), 'sha256': h})
    _pinned(task_file);_pinned(reference_file)
    for name, h in sources.items():
        if (sha256((shared.ROOT/name).read_bytes()).hexdigest() != h
                or sha256((output/'pin/source-snapshot'/name).read_bytes()).hexdigest() != h):
            raise ValueError('Source changed before publication: '+name)
    manifest = {'schema': 'website-world-generation-v2', 'recipe': VERSION,
        'saved_answer_recipe': publication.VERSION, 'world_id': world['world_id'],
        'source_sha256': sources, 'files': {str(p.relative_to(output)): sha256(p.read_bytes()).hexdigest()
            for p in output.rglob('*') if p.is_file() and not p.is_relative_to(output/'pin/source-snapshot')},
        'original_inputs': {name: {'path': str(saved/name), 'sha256': h} for name,h in expected_input_sha256.items()},
        'native_inputs': {'task': deepcopy(task_file), 'reference': deepcopy(reference_file)},
        'automatic_grader_supported': True, 'automatic_grading_attached': False,
        'world_draws': 0, 'model_runs': 0, 'effects': 'unknown'}
    shared.save(output/'manifest.json', manifest)
    return manifest


class SavedListedOfferGrader(ListedOfferGrader):
    extraction_instructions = SYSTEM


def checked_setup(setup, task):
    expected_start = ({'kind': 'comparison_home', 'comparison_site_id': task['comparison_site_id']}
                      if 'comparison_site_id' in task else {'kind': 'directory'})
    if (type(setup) is not dict or set(setup) != {'schema','task_id','user_message','memories','start'}
            or setup['schema'] != publication.VERSION or setup['task_id'] != task['task_id']
            or setup['memories'] != task['memories'] or setup['start'] != expected_start
            or type(setup['user_message']) is not str or not setup['user_message'].strip()):
        raise ValueError('Saved listed-offer setup identity/memories/scope changed')
    return setup


class SavedBasicOfferEpisode(ComparisonStockEpisode):
    def __init__(self, output, *, lazy_publication=True):
        from .runtime import Runtime
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        from .comparison_sku_task import episode_task
        self.output = Path(output).resolve();self.manifest = shared.load(self.output)
        if self.manifest.get('recipe') != VERSION or self.manifest.get('saved_answer_recipe') != publication.VERSION:
            raise ValueError('Not a saved basic-offer recipe')
        read = lambda name: json.loads((self.output/name).read_bytes())
        native_task, reference = read('basic-offer-task.private.json'), read('basic-offer-reference.private.json')
        setup = checked_setup(read('saved-answer-setup.private.json'), native_task)
        episode = read('episode.json')
        if episode != {'task_id': native_task['task_id'], 'readable_origins': True, 'start': setup['start'],
                       'manual_task': {'user_message': native_task['user_message'], 'memories': native_task['memories']}}:
            raise ValueError('Original native episode changed')
        self.runtime = Runtime(self.output/'pin', presentation=read('presentation.json'),
            surrounding=read('surrounding.private.json'), basket_plan=read('basket-plan.private.json'),
            checkout_domain=read('checkout-domain.private.json'), readable_origins=True, lazy_publication=lazy_publication,
            delivery_plan=read('delivery-plan.private.json') if (self.output/'delivery-plan.private.json').exists() else None)
        try:
            surrounding = read('surrounding.private.json')
            if self.runtime.compositions != read('compositions.private.json') or _reference(self.runtime.world,native_task,surrounding) != reference:
                raise ValueError('Actual composition or native reference changed')
            public = unified.bind_task(self.runtime,{**episode,'start':{'kind':'directory'}})
            if setup['start']['kind'] == 'comparison_home':
                sites = [s for s in self.runtime.site_registry if s['site_id'] == native_task['comparison_site_id']]
                if len(sites) != 1 or sites[0]['kind'] != 'aggregator' or sites[0]['name'] != native_task['comparison_scope']['site_name']:
                    raise ValueError('Actual named comparison site changed')
                public['start_url'] = sites[0]['origin'].rstrip('/')+'/'
            self.public = public_projection({**public,'user_message':setup['user_message']})
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins,helpers=False,data_tools=False)
            self.site_discovery = None
            self.answer_grader = SavedListedOfferGrader(self.runtime.world,native_task,reference,self.runtime.bindings,surrounding=surrounding)
            files = {str(self.output/name):h for name,h in self.manifest['files'].items()}
            files.update({str(shared.ROOT/name):h for name,h in self.manifest['source_sha256'].items()})
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            self.task = episode_task(self.runtime,self.public,self.profile,files=files,attachments={
                name:str(self.output/name) for name in ('basic-offer-task.private.json','basic-offer-reference.private.json')})
            self.task.site_discovery_callback = None
        except BaseException:
            self.runtime.close();raise

    export_private_runtime = _bind(ComparisonStockEpisode.export_private_runtime,VERSION=VERSION)


def native_inputs(output,runtime_directory):
    return {'world':output/'pin/world.private.json','task':output/'basic-offer-task.private.json',
        'reference':output/'basic-offer-reference.private.json','bindings':runtime_directory/'bindings.private.json',
        'surrounding':output/'surrounding.private.json'}


def run(output,run_directory,**options):
    return lifecycle.run(output,run_directory,episode_factory=SavedBasicOfferEpisode,inputs_factory=native_inputs,
        grader_factory=SavedListedOfferGrader,contract_id=VERSION,verifier='basic-listed-offer-native',**options)
