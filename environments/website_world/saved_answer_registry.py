"""Declarative saved-answer consumers over the shared lifecycle.

One contract per native answer family names its existing episode, grader
factory, saved files and reference check. Preparation, the public-request
binding, the declared grader inputs and the run are shared. Native task,
reference, grader and page semantics are reused unchanged.

Family imports are literal so the frozen source union of a prepared recipe
contains every native module a contract can reach.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from . import saved_answer_lifecycle as lifecycle, saved_answer_publication as publication

VERSION = 'website-saved-answer-registry-v1'
SETUP = 'saved-answer-setup.private.json'
# The lifecycle loads each declared file as one keyword argument of the factory.
RECIPE_FILES = {'world': 'pin/world.private.json', 'surrounding': 'surrounding.private.json',
    'basket_plan': 'basket-plan.private.json', 'plan': 'basket-plan.private.json',
    'checkout_domain': 'checkout-domain.private.json', 'delivery_plan': 'delivery-plan.private.json',
    'admission_plan': 'delivery-plan.private.json', 'publication': 'carrier-publication.private.json'}
RUNTIME_FILES = {'bindings': 'bindings.private.json', 'site_registry': 'site-registry.private.json'}


def _quote_offer():
    from .quote_offer_execution import QuoteOfferEpisode, grader_from_records
    return QuoteOfferEpisode, grader_from_records


def _memory_offer():
    from .memory_offer_execution import MemoryOfferEpisode
    from .memory_offer_grading import MemoryOfferGrader
    return MemoryOfferEpisode, MemoryOfferGrader


def _hidden_offer():
    from .hidden_offer_execution import HiddenOfferEpisode
    from .hidden_offer_grading import HiddenOfferGrader
    return HiddenOfferEpisode, HiddenOfferGrader


def _catalog_basket():
    from .catalog_basket_execution import CatalogBasketEpisode
    from .catalog_basket_answer_grading import CatalogBasketAnswerGrader
    return CatalogBasketEpisode, CatalogBasketAnswerGrader


def _catalog_shortlist():
    from .catalog_shortlist_execution import CatalogShortlistEpisode
    from .catalog_shortlist_grading import CatalogShortlistGrader
    return CatalogShortlistEpisode, CatalogShortlistGrader


def _catalog_relaxation():
    from .catalog_relaxation_execution import CatalogRelaxationEpisode
    from .catalog_relaxation_grading import CatalogRelaxationGrader
    return CatalogRelaxationEpisode, CatalogRelaxationGrader


def _catalog_priority():
    from .catalog_priority_execution import CatalogPriorityEpisode
    from .catalog_priority_grading import CatalogPriorityGrader
    return CatalogPriorityEpisode, CatalogPriorityGrader


def _catalog_comparison():
    from .catalog_comparison_execution import CatalogComparisonEpisode
    from .catalog_comparison_grading import CatalogComparisonGrader
    return CatalogComparisonEpisode, CatalogComparisonGrader


def _carrier_review():
    from .carrier_review_execution import CarrierReviewEpisode
    from .carrier_review_grading import CarrierReviewGrader
    return CarrierReviewEpisode, CarrierReviewGrader


def _shipping_claim():
    from .shipping_claim_execution import ShippingClaimEpisode, grader_from_records
    return ShippingClaimEpisode, grader_from_records


def _inventory(task):
    from .feature_offer_task import FieldInventory
    return FieldInventory(task['concept_id'])


def _quotes(world, records):
    from experiments.accepted_catalog_commerce.prepared_quote import prepare
    return prepare(world, plan=records['basket_plan'], admission_plan=records.get('delivery_plan'))


def _replay_quote_offer(world, task, records):
    from . import quote_offer_task as native
    return native.reference(world, task, inventory=_inventory(task),
        quote_context=_quotes(world, records), surrounding=records['surrounding'])


def _replay_memory_offer(world, task, records):
    from . import memory_offer_task as native
    return native.reference(world, task, inventory=_inventory(task), surrounding=records['surrounding'])


def _replay_hidden_offer(world, task, records):
    from . import hidden_offer_task as native
    return native.reference(world, task, inventory=_inventory(task), surrounding=records['surrounding'])


def _replay_catalog_basket(world, task, records):
    # The saved search result carries wall-clock statistics, so it is bound
    # through the native deterministic check instead of recomputed to equality.
    from . import catalog_basket_grading as structured
    structured._bound(world, task, records['reference'], records['plan'], records['checkout_domain'],
        None, records.get('admission_plan'))
    return records['reference']


def _replay_catalog_shortlist(world, task, records):
    from . import catalog_shortlist_task as native
    return native.reference(world, task, inventory=_inventory(task), surrounding=records['surrounding'])


def _replay_catalog_relaxation(world, task, records):
    from . import catalog_relaxation_task as native
    return native.reference(world, task, inventory=_inventory(task), surrounding=records['surrounding'])


def _replay_catalog_priority(world, task, records):
    from . import catalog_priority_task as native
    return native.reference(world, task, inventory=_inventory(task), surrounding=records['surrounding'])


def _replay_catalog_comparison(world, task, records):
    from . import catalog_comparison_task as native
    return native.reference(world, task, inventory=_inventory(task))


def _replay_carrier_review(world, task, records):
    from . import carrier_review_task as native
    if records['publication'] != native.public_projection(world):
        raise ValueError('Saved carrier publication changed')
    return native.reference(world, task, inventory=native.ReviewInventory())


def _replay_shipping_claim(world, task, records):
    from . import catalog_shipping_claim_task as native
    return native.reference(world, task, quote_context=_quotes(world, records),
        checkout_domain=records['checkout_domain'])


def _contract(stem, native, replay, inputs, *, optional=(), interaction=False):
    # `inputs` are the grader factory's keyword arguments besides world, task and
    # reference; `optional` ones are declared only when their recipe file exists.
    return {'recipe': 'website-'+stem+'-publication-v1', 'task': stem+'-task.private.json',
        'reference': stem+'-reference.private.json', 'native': native, 'replay': replay,
        'inputs': tuple(inputs), 'optional': tuple(optional),
        'contract_id': 'website-'+stem+'-saved-answer-v1', 'verifier': stem+'-native',
        'interaction': interaction}


CONTRACTS = {
    'quote_offer': _contract('quote-offer', _quote_offer, _replay_quote_offer,
        ('bindings', 'surrounding', 'basket_plan'), optional=('delivery_plan',)),
    'memory_offer': _contract('memory-offer', _memory_offer, _replay_memory_offer,
        ('bindings', 'surrounding')),
    # The hidden-requirement grade needs the actual clarification exchange.
    'hidden_offer': _contract('hidden-offer', _hidden_offer, _replay_hidden_offer,
        ('bindings', 'surrounding'), interaction=True),
    'catalog_basket': _contract('catalog-basket', _catalog_basket, _replay_catalog_basket,
        ('bindings', 'surrounding', 'plan', 'checkout_domain'), optional=('admission_plan',)),
    'catalog_shortlist': _contract('catalog-shortlist', _catalog_shortlist, _replay_catalog_shortlist,
        ('bindings', 'surrounding')),
    'catalog_relaxation': _contract('catalog-relaxation', _catalog_relaxation, _replay_catalog_relaxation,
        ('bindings', 'surrounding')),
    'catalog_priority': _contract('catalog-priority', _catalog_priority, _replay_catalog_priority,
        ('bindings', 'surrounding')),
    'catalog_comparison': _contract('catalog-comparison', _catalog_comparison, _replay_catalog_comparison,
        ('bindings',)),
    'carrier_review': _contract('carrier-review', _carrier_review, _replay_carrier_review,
        ('site_registry', 'publication')),
    'shipping_claim': _contract('shipping-claim', _shipping_claim, _replay_shipping_claim,
        ('bindings', 'basket_plan', 'checkout_domain'), optional=('delivery_plan',)),
}
_EPISODES = {}


def contract(kind):
    if type(kind) is not str or kind not in CONTRACTS:
        raise ValueError('Unknown saved-answer contract')
    return CONTRACTS[kind]


def prepare_saved(saved, output, *, kind, expected_manifest_sha256, user_message):
    """Rebind one saved native recipe; the caller supplies only the public request."""
    declared = contract(kind)
    snapshot = publication.read_recipe(saved, expected_manifest_sha256=expected_manifest_sha256)
    _, manifest, buffers = snapshot
    if manifest.get('recipe') != declared['recipe']:
        raise ValueError('Wrong saved answer recipe kind')
    read = lambda name: json.loads(buffers[name])
    task, reference = read(declared['task']), read(declared['reference'])
    if type(task) is not dict or type(reference) is not dict:
        raise ValueError('Saved recipe has no bound native task and reference')
    records = {'reference': reference}
    for name in declared['inputs'] + declared['optional']:
        if name in RECIPE_FILES and RECIPE_FILES[name] in buffers:
            records[name] = read(RECIPE_FILES[name])
        elif name in RECIPE_FILES and name not in declared['optional']:
            raise ValueError('Saved recipe lacks a declared native input: '+name)
    if declared['replay'](read('pin/world.private.json'), task, records) != reference:
        raise ValueError('Saved native answer reference changed')
    setup = {'schema': publication.VERSION, 'task_id': task['task_id'],
        'user_message': user_message, 'memories': deepcopy(task['memories']),
        'start': deepcopy(read('episode.json')['start'])}
    return publication.prepare_saved(snapshot, output, expected_manifest_sha256=expected_manifest_sha256,
        setup=setup, task_filename=declared['task'], adapter_file=__file__,
        dependency_records=(task, reference))


def checked_setup(raw, manifest, task, original_start):
    if (manifest.get('saved_answer_recipe') != publication.VERSION
            or sha256(raw).hexdigest() != manifest['files'][SETUP]):
        raise ValueError('Saved answer setup differs from frozen recipe')
    setup = json.loads(raw)
    if (type(setup) is not dict or set(setup) != {'schema','task_id','user_message','memories','start'}
            or setup['schema'] != publication.VERSION or setup['task_id'] != task['task_id']
            or setup['memories'] != task['memories'] or setup['start'] != original_start
            or type(setup['user_message']) is not str or not setup['user_message'].strip()):
        raise ValueError('Saved answer public identity, memories or start changed')
    return setup


def saved_episode(kind):
    """The family's native episode with only the public request replaced."""
    declared = contract(kind)
    if kind in _EPISODES:
        return _EPISODES[kind]
    native_episode, _ = declared['native']()

    class SavedAnswerEpisode(native_episode):
        def __init__(self, output, *, lazy_publication=True):
            output = Path(output).resolve()
            super().__init__(output, lazy_publication=lazy_publication)
            try:
                from intent_browser.connected_world_task import public_projection
                from .comparison_sku_task import episode_task
                setup_path = output/SETUP
                setup = checked_setup(setup_path.read_bytes(), self.manifest,
                    json.loads((output/declared['task']).read_bytes()),
                    json.loads((output/'episode.json').read_bytes())['start'])
                self.public = public_projection({**self.public, 'user_message': setup['user_message']})
                native_task = self.task
                files = deepcopy(native_task.files)
                files[str(setup_path)] = self.manifest['files'][SETUP]
                self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                                        attachments=deepcopy(native_task.attachments))
                self.task.site_discovery_callback = self.site_discovery
                if declared['interaction']:
                    self.task.clarification_callback = native_task.clarification_callback
                    self.task.clarification_audit_id = native_task.clarification_audit_id
            except BaseException:
                self.runtime.close()
                raise

    SavedAnswerEpisode.__name__ = SavedAnswerEpisode.__qualname__ = 'Saved'+native_episode.__name__
    _EPISODES[kind] = SavedAnswerEpisode
    return SavedAnswerEpisode


def native_inputs(kind):
    declared = contract(kind)

    def inputs(output, runtime_directory):
        output, runtime_directory = Path(output), Path(runtime_directory)
        result = {'world': output/RECIPE_FILES['world'], 'task': output/declared['task'],
            'reference': output/declared['reference']}
        for name in declared['inputs']:
            result[name] = (runtime_directory/RUNTIME_FILES[name] if name in RUNTIME_FILES
                            else output/RECIPE_FILES[name])
        for name in declared['optional']:
            if (output/RECIPE_FILES[name]).exists():
                result[name] = output/RECIPE_FILES[name]
        return result
    return inputs


def _interaction_bindings(grader, run_directory, options):
    """Give the native runner its saved reply contract and the grader the actual exchange."""
    runner_options = options.get('runner_options')
    if type(runner_options) is not dict or set(runner_options) & {
            'clarification_callback', 'clarification_audit_id'}:
        raise ValueError('Runner options cannot replace the saved reply binding')
    runner = options.get('runner')
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    runs, returned = Path(run_directory).resolve()/'runs', []

    def actual_runner(*args, episode_task, **kwargs):
        result = runner(*args, episode_task=episode_task,
            clarification_callback=episode_task.clarification_callback,
            clarification_audit_id=episode_task.clarification_audit_id, **kwargs)
        trace = Path(result[0]).resolve()
        if not trace.is_relative_to(runs):
            raise ValueError('Returned policy trace is outside this execution')
        returned.append(trace)
        return result

    def grader_factory(**records):
        if len(returned) != 1:
            raise ValueError('Interaction grading requires the one actual returned main trace')
        return grader(**records, interaction_trace=returned[0])
    return actual_runner, grader_factory


def _interaction_sources(trace):
    from .hidden_offer_execution import interaction_sources
    return interaction_sources(trace)


def run(output, run_directory, *, kind, **options):
    """Same positional interface as the per-family adapters; `kind` selects the contract."""
    declared = contract(kind)
    if 'evidence_sources' in options:
        raise TypeError('Caller cannot replace native interaction evidence binding')
    _, grader_factory = declared['native']()
    if declared['interaction']:
        options['runner'], grader_factory = _interaction_bindings(grader_factory, run_directory, options)
        options['evidence_sources'] = _interaction_sources
    return lifecycle.run(output, run_directory, episode_factory=saved_episode(kind),
        inputs_factory=native_inputs(kind), grader_factory=grader_factory,
        contract_id=declared['contract_id'], verifier=declared['verifier'], **options)
