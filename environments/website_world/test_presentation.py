from copy import deepcopy
from math import isclose

import pytest

from environments.website_world.adapter import PublicAdapter, load_pin, supported_destination
from environments.website_world.presentation import VERSION, site_plan, validate_request


def request(world, **spec):
    return {'schema': VERSION, 'world_id': world['world_id'],
            'sites': {world['retailers'][0]['retailer_id']: spec}}


def test_conditional_mass_includes_reset_policy_and_discovery_before_layout():
    world, _ = load_pin()
    retailer = world['retailers'][0]
    conditions = {'site.resetPolicy': ['services'], 'site.url': ['none'],
                  'site.policyEntry': ['checkout']}
    spec = validate_request(world, request(world, conditions=conditions))
    plan = site_plan(world, retailer, spec)
    assert plan == site_plan(world, retailer, spec)
    assert plan['config']['resetPolicy'] == 'services'
    assert plan['config']['url'] == 'none'
    assert plan['config']['policy'] == 'checkout'
    assert isclose(plan['presentation']['condition_mass'], .05 * (1/3) * (1/3) * .8)
    mixed = site_plan(world, retailer, request(world, conditions={
        'site.resetPolicy': ['preserve', 'services'], 'site.reset': ['true']}))
    assert mixed['config']['resetPolicy'] == 'services'
    assert isclose(mixed['presentation']['condition_mass'], .05 * .8)


def test_layout_conditions_do_not_resample_unrelated_site_factors():
    world, _ = load_pin()
    r = world['retailers'][0]
    before = site_plan(world, r, request(world))
    after = site_plan(world, r, request(world, conditions={'module.product': ['tabs']}))
    for key in ('global', 'resetPolicy', 'url', 'search', 'policy'):
        assert before['config'][key] == after['config'][key]
    assert before['presentation']['initial_form'] == 'producer'


def test_impossible_or_unbound_plans_fail_without_silent_repair():
    world, _ = load_pin()
    r = world['retailers'][0]
    for conditions in ({'site.opaque': ['true']}, {'site.resetPolicy': ['services'], 'site.reset': ['false']},
                       {'site.policyEntry': ['elsewhere']}, {'site.resetPolicy': []}):
        with pytest.raises(ValueError):
            site_plan(world, r, request(world, conditions=conditions))
    for change in ({'world_id': 'other'}, {'sites': {'unknown': {}}}, {'task': 'winner'}):
        with pytest.raises(ValueError):
            validate_request(world, {**request(world), **change})


def test_producer_autofill_and_remembered_destination_are_distinct():
    world, _ = load_pin()
    adapter = PublicAdapter(world)
    r = world['retailers'][0]
    for mode in ('producer', 'canonical', 'old', 'old_missing_unit', 'missing_unit', 'postcode'):
        plan = site_plan(world, r, request(world, initial_form=mode))
        public = adapter.catalog(r['retailer_id'], plan['config'], presentation=plan['presentation'])
        assert public['rememberedAddress']['unit'] == '24'
        assert public['initialInstructions'] == ''
        if mode == 'producer':
            assert public['initialAddress']['name'] == ''
            assert public['initialFulfilment'] is None
        if mode.startswith('old'):
            assert public['initialAddress']['street'] != public['rememberedAddress']['street']
            assert public['initialFulfilment']['address'] == public['initialAddress']
        if mode.endswith('unit'):
            assert public['initialAddress']['unit'] == ''
            assert public['initialFulfilment'] is not None
        if mode == 'postcode':
            assert public['initialFulfilment'] is None


def test_optional_unit_omission_does_not_repair_the_users_destination():
    world, _ = load_pin()
    a = {'name': 'Alex Lind', 'street': 'Björkvägen 12', 'unit': '',
         'postcode': '076 89', 'city': 'Uppsala'}
    assert supported_destination(world, a)['location_id'] == 'user-home'
    p = PublicAdapter(world).fulfilment(world['retailers'][0]['retailer_id'], a)
    assert p['address']['unit'] == ''
    with pytest.raises(ValueError):
        supported_destination(world, {**a, 'street': 'Björkvägen 12, Apartment 24', 'unit': '99'})


def test_presentation_never_changes_the_frozen_commercial_world():
    world, _ = load_pin()
    before = deepcopy(world)
    plan = site_plan(world, world['retailers'][0], request(world, initial_form='old'))
    PublicAdapter(world).catalog(world['retailers'][0]['retailer_id'], plan['config'],
                                 presentation=plan['presentation'])
    assert world == before
