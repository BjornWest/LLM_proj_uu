"""Scripted control construction for trapped recipes whose runtime has no scenario overlay."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts import hindrance_answers as answers, hindrance_budget as budget, hindrance_suite as build

# Mechanism/tier cells whose scenario_for() legitimately returns (None, None).
SCENARIO_FREE = [('stale_comparison_light', 2), ('stale_comparison_heavy', 2), ('size_price_step_heavy', 2),
                 ('stale_comparison_light', answers.PAIR_TIER), ('stale_comparison_heavy', answers.PAIR_TIER),
                 ('size_price_step_heavy', answers.PAIR_TIER), ('remote_area_surcharge_heavy', answers.PAIR_TIER),
                 ('size_step_over_budget_heavy', budget.TIER), ('surcharge_over_budget_heavy', budget.TIER)]


def runtime(scenario):
    variants = [{'offerId': o, 'key': 'k-' + o, 'state': 'in_stock'} for o in ('o1', 'o2', 'o3')]
    return SimpleNamespace(scenario=scenario, origins={'r1': 'http://shop.test'}, baskets=None,
        bindings={'retailer_offers': {v['offerId']: {'retailer_id': 'r1', 'url': 'http://shop.test/#/p/' + v['offerId']}
                                      for v in variants}},
        public_catalogs={'r1': {'products': [{'name': 'Shoe', 'variants': variants}], 'rememberedAddress': {}}})


def free_variables(policy):
    return dict(zip(policy.__code__.co_freevars, (cell.cell_contents for cell in policy.__closure__)))


def build_policies(tmp_path, recipe, instance, scenario):
    path = tmp_path / 'instance.json'
    path.write_text(json.dumps(instance))
    recipe = {'instance_path': str(path), 'clean': False, 'order_spec': {},
              'winner': {'offer_id': 'o1', 'retailer_id': 'r1'},
              'apparent_winner': {'offer_id': 'o2', 'retailer_id': 'r1'}, **recipe}
    episode = SimpleNamespace(runtime=runtime(scenario), retailer_id='r1')
    with patch('environments.website_world.simulated_order_task.make', lambda baskets, spec: spec), \
         patch('environments.website_world.simulated_order_task.reference',
               lambda baskets, task: {'status': 'ready', 'winners': [{'id': 'home'}]}), \
         patch('environments.commerce_scenarios.steering_recurrence.control_config',
               lambda prepared, case: {'offer_id': 'o1', 'option_id': 'home'}):
        return {case: build.browser_policy(episode, recipe, case, {}) for case in ('positive', 'wrong-A', 'wrong-B')}


@pytest.mark.parametrize('mechanism, tier', SCENARIO_FREE)
def test_scenario_free_trapped_controls_build(tmp_path, mechanism, tier):
    budgeted = budget.is_budget(mechanism)
    recipe = {'mechanism': mechanism, 'tier': tier, 'budget' if budgeted else 'answer': {'witness': 'fixture'}}
    scenario, _ = (budget if budgeted else answers).scenario_for({**recipe, 'clean': False})
    assert scenario is None
    policies = build_policies(tmp_path, recipe,
                              {'family': 'budget_hindrance' if budgeted else 'answer_hindrance'}, scenario)
    for policy in policies.values():
        assert callable(policy)
        assert free_variables(policy)['substitute'] is None


def test_substitution_control_keeps_its_substitute(tmp_path):
    scenario = {'retailer_id': 'r1', 'presentation': {'execution': 'substitution_at_checkout_light',
                                                      'substitute_offer_id': 'o2'}}
    policies = build_policies(tmp_path, {'mechanism': 'substitution_at_checkout_light', 'tier': 1},
                              {'family': 'steering_recurrence', 'prepared': {}}, scenario)
    for policy in policies.values():
        assert free_variables(policy)['substitute'] == 'o2'
