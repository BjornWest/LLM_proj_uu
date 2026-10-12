"""Cross-family provenance controls; no extractor, browser or model dispatch.

Supplied semantic values are intentional fixture inputs. Their interpretation
from English is tested by Evaluation, independently of native outcome grading.
"""
from copy import deepcopy

import pytest
from jsonschema import ValidationError

from experiments.footwear_world_pilot.test_basket_quote import world
from . import test_catalog_review_task as reviews
from . import test_carrier_review_task as carriers
from . import test_catalog_statistics_task as statistics
from . import test_catalog_comparison_task as comparison
from . import test_catalog_shipping_claim_task as shipping
from . import test_catalog_basket_answer_grading as baskets
from .test_variant_link_answer_grading import sample as link_sample
from .test_review_passage_task import fixture as passage_fixture
from .catalog_statistics_grading import CatalogStatisticsGrader
from .catalog_comparison_grading import CatalogComparisonGrader


FAMILIES = ('shipping', 'review', 'carrier', 'basket', 'comparison',
            'statistics', 'passage', 'variant_link')


def case(family, world):
    if family == 'shipping':
        args = shipping.fixture(world)
        answer, claims = shipping.claims(args)
        return args[-1], answer, claims, claims['assessment']
    if family == 'review':
        args = reviews.fixture()
        answer, claims = reviews.claims_for(args[1], args[2])
        return reviews.grader(*args), answer, claims, claims['verdict']
    if family == 'carrier':
        args = carriers.fixture()
        answer, claims = carriers.answer(args[1], args[2])
        return carriers.grader(args), answer, claims, claims['verdict']
    if family == 'basket':
        grader, answer, claims = baskets.sample(world)
        return grader, answer, claims, claims['orders'][0]['lines'][0]['delivery']['delivery_type']
    if family == 'comparison':
        w, task, ref, bindings, inventory = comparison.fixture()
        answer, claims = comparison.answer(w, task, ref, bindings)
        grader = CatalogComparisonGrader(w, task, ref, bindings, inventory=inventory)
        cell = next(iter(claims['rows'][0]['facts'].values()))
        return grader, answer, claims, cell['status']
    if family == 'statistics':
        w, sidecar, task, ref, sites = statistics.fixture()
        answer, claims = statistics.answer(ref)
        grader = CatalogStatisticsGrader(w, task, ref, sites, surrounding=sidecar)
        return grader, answer, claims, claims['undefined']
    if family == 'passage':
        *_, grader, answer, claims = passage_fixture()
        return grader, answer, claims, claims['status']
    grader, answer, claims = link_sample('colour')
    return grader, answer, claims, claims['recipient_must_select']


@pytest.mark.parametrize('family', FAMILIES)
def test_paraphrase_preserves_semantics_and_native_result_without_input_mutation(family, world):
    grader, answer, claims, semantic = case(family, world)
    # No enum tokens, mode names, verdict markers or absence phrases.
    paraphrase = 'My conclusion follows from the observations described above.'
    semantic['evidence'] = paraphrase
    answer += '\n' + paraphrase
    before = deepcopy(claims)
    assert grader.grade(claims, answer)['structured_claims_correct']
    assert claims == before


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('mutation', ('invented_quote', 'empty_quote', 'noncontiguous_quote',
                                     'null_with_quote', 'value_without_quote', 'invalid_type'))
def test_schema_and_provenance_stay_mandatory_for_semantic_fields(family, mutation, world):
    grader, answer, claims, semantic = case(family, world)
    if mutation == 'invented_quote': semantic['evidence'] = 'Never present in this answer.'
    elif mutation == 'empty_quote': semantic['evidence'] = ''
    elif mutation == 'noncontiguous_quote':
        answer += '\nfirst fragment intervening text last fragment'
        semantic['evidence'] = 'first fragment last fragment'
    elif mutation == 'null_with_quote': semantic['value'] = None
    elif mutation == 'value_without_quote': semantic['evidence'] = None
    else: semantic['value'] = ['invalid structured type']
    with pytest.raises((ValueError, ValidationError)):
        grader.grade(claims, answer)


@pytest.mark.parametrize('family', ('shipping', 'review', 'carrier', 'basket', 'passage'))
def test_invalid_categorical_value_rejects_instead_of_becoming_a_native_verdict(family, world):
    grader, answer, claims, semantic = case(family, world)
    semantic['value'] = 'unrecognized_category'
    with pytest.raises(ValidationError):
        grader.grade(claims, answer)


@pytest.mark.parametrize('family,wrong', (
    ('shipping', 'all_free'), ('review', 'more_negative'),
    ('carrier', 'more_negative'), ('statistics', True),
    ('passage', 'no_matching_passage'), ('variant_link', False)))
def test_valid_wrong_semantics_reach_native_fail_not_a_lexical_error(family, wrong, world):
    grader, answer, claims, semantic = case(family, world)
    assert semantic['value'] != wrong
    semantic['value'] = wrong
    result = grader.grade(claims, answer)
    assert result['structured_claims_correct'] is False
