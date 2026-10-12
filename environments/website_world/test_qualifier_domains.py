"""Declaration domains and real native grader boundaries; no inference/browser.

Claims below stand in for extractor outputs, not independently proven semantic
interpretations. Exact quote/schema checks and native wrong-outcome comparisons
are exercised separately.
"""
from copy import deepcopy
from hashlib import sha256
import json

import pytest
from jsonschema import ValidationError

from . import qualifier_domains as domains, atomic_product_task as atomic
from .atomic_product_execution_consumer import AtomicReadGrader
from .canonical_claims import UNMATCHED
from .catalog_comparison_grading import CatalogComparisonGrader
from .test_atomic_product_tasks import fixture as atomic_fixture
from .test_catalog_comparison_task import fixture as comparison_fixture, answer as comparison_answer
from .adapter import digest

ANDROID = 'Android media 11 / 4GB / 64GB / Wi-Fi only / gray'
IOS = 'iOS media 11 / 128GB / RAM unknown / Wi-Fi only / silver'
FIELD = 'product.facts.reference_configuration'


def declaration():
    return {'fields': {FIELD: {'type': 'string'}}, 'steps': [
        {'target': 'internal.model', 'sample': 'weighted_choice',
         'weights': {'android': 1, 'ios': 0},
         'cases': [{'when': "profile.positioning == 'premium'", 'weights': {'ios': 1}}],
         'values': {'android': {'reference_configuration': ANDROID},
                    'ios': {'reference_configuration': IOS}}},
        {'target': FIELD, 'derive': 'internal.model.reference_configuration'}],
        'programs': {}}


def test_complete_source_table_is_not_filtered_by_weights_or_sampled_model():
    doc = declaration(); before = deepcopy(doc)
    assert domains.finite_strings(doc, FIELD) == [ANDROID, IOS]
    assert doc == before
    doc['steps'][0]['weights'] = {'ios': 100}
    assert domains.finite_strings(doc, FIELD) == [ANDROID, IOS]


@pytest.mark.parametrize('change', ['missing_key', 'conditional', 'multiple_writers',
    'computed_copy', 'case_table', 'cycle', 'program_writer', 'program_dependency', 'loop_writer',
    'values_expr', 'weights_from', 'values_from', 'eligible_from', 'unknown_weight', 'unknown_case_weight'])
def test_incomplete_or_dynamic_table_proofs_keep_literal_fallback(change):
    doc = declaration()
    if change == 'missing_key': del doc['steps'][0]['values']['ios']['reference_configuration']
    elif change == 'conditional': doc['steps'][1]['when'] = 'flag'
    elif change == 'multiple_writers': doc['steps'].append(deepcopy(doc['steps'][1]))
    elif change == 'computed_copy': doc['steps'][1]['derive'] = 'str(internal.model.reference_configuration)'
    elif change == 'case_table': doc['steps'][0]['cases'][0]['values'] = {'ios': {'reference_configuration': IOS}}
    elif change == 'cycle': doc['steps'][0] = {'target': 'internal.model', 'derive': FIELD}
    elif change == 'program_writer': doc['programs']['custom'] = {'steps': [{'target': FIELD, 'derive': "'other'"}]}
    elif change == 'program_dependency': doc['programs']['custom'] = {'steps': [{'target': 'internal.model', 'derive': 'other'}]}
    elif change in ('values_expr', 'weights_from', 'values_from', 'eligible_from'):
        doc['steps'][0][change] = {} if change == 'values_expr' else 'dynamic'
    elif change == 'unknown_weight': doc['steps'][0]['weights']['unlisted'] = 1
    elif change == 'unknown_case_weight': doc['steps'][0]['cases'][0]['weights']['unlisted'] = 1
    else: doc['steps'].append({'for_each': {'binding': 'item', 'in': 'items'},
                              'steps': [{'target': FIELD, 'derive': "'different'"}]})
    assert domains.finite_strings(doc, FIELD) is None


def test_constant_copy_enum_and_invalid_overlapping_producers():
    assert domains.finite_strings({'fields': {'basis': {'type': 'string', 'constant': 'one shoe'}}}, 'basis') == ['one shoe']
    assert domains.finite_strings({'fields': {'basis': {'type': 'enum', 'values': ['one shoe', 'one pair']}}}, 'basis') == ['one shoe', 'one pair']
    doc = {'fields': {'basis': {'type': 'string', 'constant': 'one shoe'}},
           'steps': [{'target': 'basis', 'derive': "'one pair'"}]}
    assert domains.finite_strings(doc, 'basis') is None


@pytest.mark.parametrize('value', [UNMATCHED, ' ', ['nested'], 3, None])
def test_invalid_literal_outputs_do_not_create_a_partial_domain(value):
    doc = declaration(); doc['steps'][0]['values']['ios']['reference_configuration'] = value
    assert domains.finite_strings(doc, FIELD) is None


def test_fixed_basis_must_be_the_declared_public_scope():
    scope = {'basis': 'one item, EU 40 reference configuration',
        'origin': 'registered_constant_field', 'declaration': {
            'type': 'string', 'constant': 'one item, EU 40 reference configuration'}}
    assert domains.measurement_basis_values(scope) == [scope['basis']]
    assert domains.measurement_basis_values({'basis': scope['basis']}) is None
    scope['basis'] = 'one pair'
    with pytest.raises(ValueError): domains.measurement_basis_values(scope)


def test_equivalent_mass_scope_reaches_native_comparison_without_literal_reparse():
    world, task, ref, bindings, inventory = comparison_fixture()
    grader = CatalogComparisonGrader(world, task, ref, bindings, inventory=inventory)
    text, claims = comparison_answer(world, task, ref, bindings)
    old = deepcopy(claims)
    for row in claims['rows']:
        cell = row['facts']['product.facts.reference_mass_g']
        quote = 'Mass for one shoe in the EU40 reference size.'
        cell['basis']['evidence'] = quote
        text += '\n'+quote
    assert grader.grade(claims, text)['structured_claims_correct']
    assert old['rows'][0]['facts']['product.facts.reference_mass_g']['basis']['value'] not in quote
    assert 'enum' not in grader.cell_schemas['product.facts.cushioning']['properties']['basis']['properties']['value']


@pytest.mark.parametrize('mode', ['wrong_size', 'per_pair', 'missing', 'fabricated', 'unrelated'])
def test_wrong_missing_and_unrelated_bases_are_not_repaired(mode):
    world, task, ref, bindings, inventory = comparison_fixture()
    grader = CatalogComparisonGrader(world, task, ref, bindings, inventory=inventory)
    text, claims = comparison_answer(world, task, ref, bindings)
    cell = claims['rows'][0]['facts']['product.facts.reference_mass_g']
    if mode == 'missing': cell['basis'] = {'value': None, 'evidence': None}
    elif mode == 'fabricated': cell['basis']['evidence'] = 'Not in this answer'
    elif mode == 'unrelated':
        other = claims['rows'][0]['facts']['product.facts.cushioning']
        text += '\nEU40'
        other['basis'] = {'value': 'EU40', 'evidence': 'EU40'}
    else:
        quote = 'Measured per pair.' if mode == 'per_pair' else 'Measured in EU42.'
        text += '\n'+quote
        cell['basis'] = {'value': UNMATCHED, 'evidence': quote}
    if mode == 'fabricated':
        with pytest.raises(ValueError): grader.grade(claims, text)
    else: assert not grader.grade(claims, text)['structured_claims_correct']


def reference_fixture(tmp_path, monkeypatch):
    # Tiny valid public/native joins plus a complete declaration table. This is
    # a source/control fixture, not a sampled tablet or a browser capture.
    concept = 'tablets.everyday_media_tablets'
    path = tmp_path/'environments/product_world/data/product_width'/f'{concept}.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(declaration()))
    monkeypatch.setattr(domains, 'ROOT', tmp_path)
    world, task, _, args, binding, capsule = atomic_fixture('read_public_fact')
    world['products'][0]['public']['concept_id'] = concept
    world.setdefault('provenance', {}).setdefault('accepted_package_gates', {})[concept] = {
        'source_hashes': {str(path.relative_to(tmp_path)): sha256(path.read_bytes()).hexdigest()}}
    row = {'field': 'product.facts.reference_mass_g', 'label': 'Reference weight',
           'value': 470, 'unit': 'g', 'qualifier': ANDROID, 'status': 'known',
           'assertions': [{'field': FIELD, 'value': ANDROID,
                          'authority': 'catalog_fact', 'status': 'known',
                          'subject': {'kind': 'product', 'id': 'product'}}]}
    args['catalog']['products'][0]['variants'][0]['details'][0]['facts'].append(row)
    from . import catalog_checkout_domain
    args['checkout_domain'] = catalog_checkout_domain.make(world)
    spec = {**task['spec'], 'fact': {'field': 'product.facts.reference_mass_g'}}
    task = atomic.make(world, spec, **args)
    reference = atomic.reference(world, task, **args)
    from . import catalog_cart_grading
    binding = catalog_cart_grading.storage_binding(world, binding['retailers'])
    capsule['task_sha256'] = digest(task)
    capsule['binding_sha256'] = digest(binding)
    grader = AtomicReadGrader(world, task, reference, **args,
                             binding=binding, capsule=capsule, completion=True)
    return world, task, reference, args, binding, capsule, grader, path


def read_claims(value=ANDROID, quote='Reference configuration: Android media 11, 4GB RAM, 64GB storage, Wi-Fi only, gray.'):
    return {'interpretation': 'extracted', 'issues': [], 'source_urls': [],
            'value': {'value': 470, 'evidence': 'Reference weight 470 g.'},
            'unit': {'value': 'g', 'evidence': 'Reference weight 470 g.'},
            'qualifier': {'value': value, 'evidence': quote} if value is not None else
                         {'value': None, 'evidence': None}}


def test_full_reference_menu_and_expanded_role_words_with_exact_quotes(tmp_path, monkeypatch):
    world, task, ref, args, _, _, grader, _ = reference_fixture(tmp_path, monkeypatch)
    choices = grader.schema['properties']['qualifier']['properties']['value']['enum']
    assert choices == [ANDROID, IOS, UNMATCHED, None]
    claims = read_claims(); text = 'Reference weight 470 g.\n'+claims['qualifier']['evidence']
    before = deepcopy((world, task, ref, args, claims))
    assert grader.grade(claims, text)['structured_claims_correct']
    assert (world, task, ref, args, claims) == before
    assert ANDROID not in claims['qualifier']['evidence']


@pytest.mark.parametrize('quote', [
    'Reference: Android media 11, 64GB RAM, 4GB storage, Wi-Fi only, gray.',
    'Reference: Android media 11, 4GB RAM, 128GB storage, Wi-Fi only, gray.',
    'Reference: Android media 11, 4GB RAM, 64GB storage, LTE, gray.',
    'Reference: Android media 11, 4GB RAM, 64GB storage, Wi-Fi only, green.',
    'Reference: Android media 10, 4GB RAM, 64GB storage, Wi-Fi only, gray.',
    'Reference: Android media 11, 4GB RAM, 64GB storage.',
    'Selected variant: Android media 11, 4GB RAM, 64GB storage, LTE, green.',
])
def test_extractor_supplied_unmatched_configuration_fails_native_comparison(tmp_path, monkeypatch, quote):
    *_, grader, _ = reference_fixture(tmp_path, monkeypatch)
    claims = read_claims(UNMATCHED, quote)
    assert grader.grade(claims, 'Reference weight 470 g.\n'+quote)['structured_claims_correct'] is False


def test_wrong_declared_reference_missing_and_fabricated_quote(tmp_path, monkeypatch):
    *_, grader, _ = reference_fixture(tmp_path, monkeypatch)
    claims = read_claims(IOS, 'Reference: iOS media 11, 128GB storage, RAM unknown, Wi-Fi only, silver.')
    assert grader.grade(claims, 'Reference weight 470 g.\n'+claims['qualifier']['evidence'])['structured_claims_correct'] is False
    assert grader.grade(read_claims(None), 'Reference weight 470 g.')['structured_claims_correct'] is False
    with pytest.raises(ValueError): grader.grade(read_claims(), 'Reference weight 470 g.')
    with pytest.raises(ValidationError):
        grader.grade(read_claims('unregistered configuration', 'unregistered configuration'),
                     'Reference weight 470 g. unregistered configuration')


def test_declaration_drift_invalidates_native_task_and_changed_table_changes_whole_menu(tmp_path, monkeypatch):
    world, task, _, args, _, _, grader, path = reference_fixture(tmp_path, monkeypatch)
    doc = declaration(); doc['steps'][0]['values']['ios']['reference_configuration'] = 'Other full declared reference'
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError): atomic.reference(world, task, **args)
    with pytest.raises(ValueError, match='frozen world'): atomic.make(world, task['spec'], **args)
    # A separately constructed source-bound world can carry a different full
    # table. This is explicit test construction, not historical repair.
    world = deepcopy(world); world['world_id'] += '-new-declaration'
    world['provenance']['accepted_package_gates']['tablets.everyday_media_tablets']['source_hashes'][
        str(path.relative_to(domains.ROOT))] = sha256(path.read_bytes()).hexdigest()
    from . import catalog_checkout_domain
    args = {**args, 'checkout_domain': catalog_checkout_domain.make(world)}
    new_task = atomic.make(world, task['spec'], **args)
    assert new_task['public_fact']['qualifier_declaration']['values'] == [ANDROID, 'Other full declared reference']
    assert new_task['task_id'] != task['task_id']


@pytest.mark.parametrize('field', ['internal.model.reference_configuration', 'product.facts.undeclared_scope'])
def test_public_assertion_cannot_admit_a_private_or_undeclared_domain(tmp_path, monkeypatch, field):
    world, task, _, _, _, _, _, path = reference_fixture(tmp_path, monkeypatch)
    fact = deepcopy(task['public_fact'])
    fact['row']['assertions'][0]['field'] = field
    doc = declaration()
    # Even a producer internal enum must not become an extraction menu merely
    # because an externally supplied assertion labels it as a product fact.
    if field.startswith('internal.'):
        doc['fields'][field] = {'type': 'enum', 'values': [ANDROID, 'private-only label']}
    else:
        doc['steps'].append({'target': field, 'derive': "'private-only label'"})
    path.write_text(json.dumps(doc))
    world['provenance']['accepted_package_gates']['tablets.everyday_media_tablets']['source_hashes'][
        str(path.relative_to(domains.ROOT))] = sha256(path.read_bytes()).hexdigest()
    assert domains.public_fact_domain(world, task['product_id'], fact) is None


def test_ambiguous_labels_and_status_sentinels_keep_literal_fallback():
    doc = declaration(); doc['steps'][0]['values']['ios']['reference_configuration'] = ANDROID.upper()
    assert domains.finite_strings(doc, FIELD) is None
    doc = {'fields': {FIELD: {'type': 'enum', 'values': ['reference', 'unknown', 'N/A'],
                             'unknown_values': ['unknown'], 'not_applicable_values': ['N/A']}}}
    assert domains.finite_strings(doc, FIELD) == ['reference']
    doc = declaration(); doc['fields'][FIELD]['unknown_values'] = [IOS]
    assert domains.finite_strings(doc, FIELD) == [ANDROID]


def test_domain_uses_world_pins_not_ambient_files_and_pinned_absence_fails(tmp_path, monkeypatch):
    world, task, _, _, _, _, _, path = reference_fixture(tmp_path, monkeypatch)
    assert task['schema_version'] == atomic.QUALIFIED_VERSION
    unpinned = deepcopy(world); unpinned.pop('provenance')
    assert domains.public_fact_domain(unpinned, task['product_id'], task['public_fact']) is None
    path.unlink()
    with pytest.raises(ValueError, match='Missing world-pinned'):
        domains.public_fact_domain(world, task['product_id'], task['public_fact'])


def test_qualifier_instructions_are_scoped_to_declared_tasks(tmp_path, monkeypatch):
    from .atomic_product_execution_consumer import READ_INSTRUCTIONS, QUALIFIED_INSTRUCTIONS
    *_, grader, _ = reference_fixture(tmp_path, monkeypatch)
    assert grader.extraction_instructions == QUALIFIED_INSTRUCTIONS
    assert 'unmatched label' not in READ_INSTRUCTIONS
    world, task, ref, args, binding, capsule = atomic_fixture('read_listed_price')
    plain = AtomicReadGrader(world, task, ref, **args, binding=binding, capsule=capsule, completion=True)
    assert plain.extraction_instructions == READ_INSTRUCTIONS
    assert task['schema_version'] == atomic.VERSION
