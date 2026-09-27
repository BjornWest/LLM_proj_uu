from copy import deepcopy
from random import Random

import pytest

from .evidence import generate_evidence, validate_evidence, digest, render_report
from .evidence_drinks import BITTERNESS, FLAVOURS, render_drink, sample_observations
from environments.product_world.stores import generate_store_world
from environments.shopping_intent.review_evidence import summarize


def report(product, taste='neutral', bitter=None):
    assessments = [{'aspect_id': 'taste_enjoyment', 'context_id': 'tasting', 'stance': taste}]
    if bitter is not None:
        assessments.append({'aspect_id': 'bitterness', 'context_id': 'tasting', 'stance': bitter})
    r = {'review_id': 'review-1', 'reviewer_id': 'person-1', 'subject': {'scope': 'sku', 'id': 'sku-1'},
         'stars': 3, 'template_version': 4, 'assessments': assessments,
         'usage_reports': [{'context_id': 'tasting', 'experience_kind': 'actual_use'}],
         'template_choices': {'intro': 0, 'facts': 0, 'stance': 0, 'ending': 0}}
    r['sensory_observations'] = sample_observations(product, assessments, Random(0))
    return r


@pytest.fixture
def beer():
    return {'category': 'beer', 'name': 'Example IPA', 'attributes': {'beer_style': 'IPA', 'pack_count': 6}}


@pytest.mark.parametrize('intensity,persistence', BITTERNESS)
def test_presence_is_independent_of_strength_and_duration(beer, intensity, persistence):
    r = report(beer, bitter='negative' if intensity == 'absent' else 'positive')
    r['sensory_observations'].update(bitterness_intensity=intensity, bitterness_persistence=persistence)
    for variant in range(3):
        r['template_choices']['stance'] = variant
        body, _ = render_drink(r, beer)
        assert BITTERNESS[intensity, persistence][variant] in body
    result = summarize([r], sku_id='sku-1', aspect_id='bitterness', context_id='tasting', complete=True)
    assert result['review_counts']['positive'] == (intensity != 'absent')
    assert result['review_counts']['mixed'] == 0


def test_omission_is_unassessed_and_hearsay_never_becomes_a_firsthand_vote(beer):
    r = report(beer)
    assert set(r['sensory_observations']) == {'flavour_note', 'body'}
    result = summarize([r], sku_id='sku-1', aspect_id='bitterness', context_id='tasting', complete=True)
    assert result['review_counts']['not_assessed'] == 1
    r = report(beer, bitter='positive'); r['usage_reports'][0]['experience_kind'] = 'hearsay'
    assert 'My dad tried' in render_drink(r, beer)[0]
    result = summarize([r], sku_id='sku-1', aspect_id='bitterness', context_id='tasting', complete=True)
    assert result['contextual_reviewer_count'] == 0


def test_all_styles_and_stances_give_specific_sensory_information():
    for style, flavours in FLAVOURS.items():
        family = 'wine' if style in ('red', 'white', 'rosé') else 'beer'
        product = {'category': family, 'name': 'Example', 'attributes':
                   {'beer_style': style, 'wine_colour': style, 'pack_count': 1, 'vintage': 'non-vintage'}}
        for stance in ('positive', 'negative', 'mixed', 'neutral'):
            r = report(product, taste=stance)
            for variant in range(3):
                r['template_choices'].update(stance=variant, facts=1)
                body, fields = render_drink(r, product)
                assert any(note in body.lower() for note in flavours)
                assert 'Had a taste' not in body and 'some mouthfuls' not in body.lower()
                assert 'non-vintage vintage' not in body
                assert fields == (['vintage'] if family == 'wine' else ['pack_count'])


@pytest.fixture(scope='module')
def corpus():
    world = generate_store_world(42, models_per_store=3)
    return world, generate_evidence(world, seed=42)


@pytest.mark.parametrize('mutation', ('wrong_flavour', 'contradiction', 'missing_duration', 'extra_fact', 'mixed'))
def test_semantic_tampering_rejected_after_hash_recomputation(corpus, mutation):
    world, export = corpus; export = deepcopy(export)
    r = next(r for r in export['public']['reviews'] if 'bitterness_intensity' in r.get('sensory_observations', {}))
    obs = r['sensory_observations']
    if mutation == 'wrong_flavour': obs['flavour_note'] = 'diesel'
    if mutation == 'contradiction':
        obs['bitterness_intensity'] = 'absent' if obs['bitterness_intensity'] != 'absent' else 'pronounced'
    if mutation == 'missing_duration': del obs['bitterness_persistence']
    if mutation == 'extra_fact': obs['cures_insomnia'] = True
    if mutation == 'mixed':
        next(a for a in r['assessments'] if a['aspect_id'] == 'bitterness')['stance'] = 'mixed'
    export['private_provenance']['public_sha256'] = digest(export['public'])
    with pytest.raises(ValueError): validate_evidence(world, export)


def test_conflicting_sensory_copies_are_not_silently_deduplicated(beer):
    r = report(beer, bitter='positive'); other = deepcopy(r)
    other['sensory_observations']['bitterness_persistence'] = 'brief'
    r['sensory_observations']['bitterness_persistence'] = 'lingering'
    with pytest.raises(ValueError, match='Conflicting copies'):
        summarize([r, other], sku_id='sku-1', aspect_id='bitterness', context_id='tasting', complete=True)


def test_legacy_drink_templates_can_still_be_validated(corpus):
    world, export = corpus; export = deepcopy(export)
    products = {p['product_id']: p for p in world['public']['products']}
    from .evidence_prose import render_natural
    for r in export['public']['reviews']:
        if r['template_version'] == 4:
            r['template_version'] = 3; del r['sensory_observations']
            r['body'], r['mentioned_attributes'] = render_natural(r, products[r['subject']['id']])
            assert r['body'] == render_report(r, products[r['subject']['id']])
    export['private_provenance']['public_sha256'] = digest(export['public'])
    assert validate_evidence(world, export)['valid']
