"""Named-comparator scope uses published membership, never hidden winners."""
from copy import deepcopy
from pathlib import Path
import json
import pytest

from environments.website_world import basic_offer_task as basic, surrounding_config, unified_generation
from environments.website_world.adapter import digest
from environments.website_world.listed_offer_grading import ListedOfferGrader


@pytest.fixture(scope='module')
def packet():
    world = json.loads(Path('.local/website-basic-offer-medium-20261006-v1/pin/world.private.json').read_text())
    sidecar = surrounding_config.generate(world, {'version': 'native-rich-surrounding-v3',
        'scope_weights': {'general': 1, 'specialist': 0}, 'model_probability': .8,
        'retailer_pair_probability': .4})
    selection = {'kind': basic.KIND, 'concept_id': 'footwear.walking_shoes',
                 'comparison_site_id': 'comparison-00'}
    task = basic.make(world, selection, surrounding=sidecar)
    ref = basic.reference(world, task, surrounding=sidecar)
    bindings = {'retailer_offers': {o['offer_id']: {
        'retailer_id': r['retailer_id'], 'product_id': o['product_id'], 'sku_id': o['sku_id'],
        'url': 'https://shop.test/#/offer/' + o['offer_id'], 'selection': {}, 'required_selection': {}}
        for r in world['retailers'] for o in r['offers']}}
    return world, sidecar, selection, task, ref, bindings


def test_only_published_model_retailer_pairs_with_all_native_variants(packet):
    world, sidecar, selection, task, ref, _ = packet
    site = next(s for s in sidecar['sites'] if s['site_id'] == selection['comparison_site_id'])
    pairs = {(r['product_id'], r['retailer_id']) for r in site['listings']}
    pids = {p['public']['product_id'] for p in world['products']
            if p['public']['concept_id'] == selection['concept_id']}
    expected = [o for r in world['retailers'] for o in r['offers'] if
                (o['product_id'], r['retailer_id']) in pairs and o['product_id'] in pids and
                (any(o['stock_by_source'].values()) or o['supplier_order']['enabled'])]
    assert expected
    assert {c['offer_id'] for c in ref['candidates']} == {o['offer_id'] for o in expected}
    minimum = min(o['price_minor'] for o in expected)
    assert ref['minimum_price_minor'] == minimum
    assert {c['offer_id'] for c in ref['winners']} == {o['offer_id'] for o in expected if o['price_minor'] == minimum}
    assert site['name'] in task['user_message']
    assert 'do not need to search retailers absent' in task['user_message']
    assert task['comparison_scope']['surrounding_sha256'] == digest(sidecar)


def claims_for(grader, candidate, bindings):
    text = f"{candidate['product_name']} at {candidate['retailer_name']}: {candidate['price_minor']/100:.2f} SEK. {bindings['retailer_offers'][candidate['offer_id']]['url']}"
    claim = lambda value: {'value': value, 'evidence': text if value is not None else None}
    return text, {'interpretation': 'extracted', 'issues': [], 'status': claim('selection'),
        'product_name': claim(candidate['product_name']), 'retailer_name': claim(candidate['retailer_name']),
        'offer_url': claim(bindings['retailer_offers'][candidate['offer_id']]['url']), 'sku_id': claim(None),
        'variant': {f: claim(None) for f in grader.contract['variant_fields']},
        'total': {'amount': f"{candidate['price_minor']/100:.2f}", 'currency': 'SEK', 'evidence': text},
        'source_urls': []}


def test_native_grader_accepts_scope_winner_rejects_unlisted_offer(packet):
    world, sidecar, _, task, ref, bindings = packet
    grader = ListedOfferGrader(world, task, ref, bindings, surrounding=sidecar)
    text, claims = claims_for(grader, ref['winners'][0], bindings)
    assert grader.grade(claims, text)['structured_claims_correct']
    global_task = basic.make(world, {'kind': basic.KIND, 'concept_id': task['concept_id']})
    global_ref = basic.reference(world, global_task)
    scoped_ids = {r['offer_id'] for r in ref['candidates']}
    excluded = next(r for r in global_ref['candidates'] if r['offer_id'] not in scoped_ids)
    text, claims = claims_for(grader, excluded, bindings)
    checks = grader.grade(claims, text)['oracle_grade']['requirements']
    assert checks['public_selection_identity'] and checks['reported_price']
    assert not checks['task_eligible'] and not checks['cheapest_listed_offer']


def test_grader_does_not_trust_task_supplied_membership(packet):
    world, sidecar, _, task, ref, bindings = packet
    with pytest.raises(ValueError, match='sidecar'):
        ListedOfferGrader(world, task, ref, bindings)
    forged = deepcopy(task)
    forged['comparison_scope']['product_retailer_pairs'] = []
    with pytest.raises(ValueError, match='binding'):
        ListedOfferGrader(world, forged, ref, bindings, surrounding=sidecar)
    wrong = deepcopy(sidecar); wrong['sites'][0]['listings'] = []
    with pytest.raises(ValueError, match='replay'):
        ListedOfferGrader(world, task, ref, bindings, surrounding=wrong)


def test_empty_comparison_membership_is_honest_no_match(packet):
    world, _, selection, _, _, bindings = packet
    empty = surrounding_config.generate(world, {'version': 'native-rich-surrounding-v3',
        'model_probability': 0, 'retailer_pair_probability': 0})
    task = basic.make(world, selection, surrounding=empty)
    ref = basic.reference(world, task, surrounding=empty)
    assert ref['status'] == 'no_match' and ref['minimum_price_minor'] is None
    assert ref['candidates'] == ref['winners'] == ref['unavailable_offer_ids'] == []
    grader = ListedOfferGrader(world, task, ref, bindings, surrounding=empty)
    text = 'No available match on the specified comparison website.'
    claims = {'interpretation': 'extracted', 'issues': [],
        'status': {'value': 'no_match', 'evidence': 'No available match'},
        **{k: {'value': None, 'evidence': None} for k in
           ('product_name', 'retailer_name', 'offer_url', 'sku_id')},
        'variant': {}, 'total': None, 'source_urls': []}
    assert grader.grade(claims, text)['structured_claims_correct']


@pytest.mark.parametrize('site_id', [None, True, 'product-reviews-00', 'comparison-99'])
def test_bad_comparison_selector_rejects_before_world(packet, site_id):
    world = packet[0]
    with pytest.raises(ValueError, match='comparison_site_id'):
        basic.resolve({'kind': basic.KIND, 'comparison_site_id': site_id},
                      seed=world['seed'], concept_ids=world['config']['concept_ids'])


def test_disabled_or_missing_site_rejects_before_sampling(packet):
    request = {'schema': unified_generation.VERSION, 'seed': packet[0]['seed'], 'task': packet[2],
               'surrounding_sites': {'comparison_count': 0}}
    with pytest.raises(ValueError, match='enabled'):
        unified_generation.compile_request(request)


def test_generation_binds_the_actual_sidecar_once_without_world_repair(packet):
    from types import SimpleNamespace
    from intent_browser.connected_world_task import public_projection
    world, _, selection, _, _, _ = packet
    request = {'schema': unified_generation.VERSION, 'seed': world['seed'], 'task': selection,
        'budget': {'max_proposals': 1}, 'episode': {'start': {'kind': 'tool_discovery'}}}
    before = deepcopy(world); calls = []
    def factory(seed, **kwargs):
        calls.append(seed)
        return world
    result = unified_generation.generate(request, world_factory=factory)
    assert calls == [world['seed']] and world == before
    assert result['basic_offer_reference'] == basic.reference(world, result['basic_offer_task'],
                                                             surrounding=result['surrounding'])
    assert result['episode']['manual_task']['user_message'] == result['basic_offer_task']['user_message']
    public = public_projection(unified_generation.bind_task(
        SimpleNamespace(discovery_mode='tool', research_origin='http://localhost:1234', world=world),
        result['episode']))
    assert public['environment_context']['shopping_scope'] == 'Products and retailer listings shown on Prislyktan'
    assert 'product_retailer_pairs' not in json.dumps(public)
