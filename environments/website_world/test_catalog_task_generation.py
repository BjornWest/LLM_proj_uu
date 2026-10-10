"""Routing contracts plus retained compiler gate; no world draws or browsers."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from environments.website_world import catalog_task_generation as api


@pytest.mark.parametrize('kind,module',list(api.generators().items()))
def test_exact_native_route_forwards_once_preserving_arguments_results_and_errors(monkeypatch,kind,module):
    request={'task':{'kind':kind},'opaque':'retained compiler validates this'}
    initial=deepcopy(request);factory=object();compiled=object();result=object();calls=[]
    def compile_request(value):
        assert value is request;calls.append('compile');return compiled
    def generate(value,*,world_factory):
        assert value is request and world_factory is factory
        calls.append('generate');return result
    fake=SimpleNamespace(compile_request=compile_request,generate=generate)
    def load(name,package):
        assert package+name==module;return fake
    monkeypatch.setattr(api,'import_module',load)
    assert api.compile_request(request) is compiled
    assert api.generate(request,world_factory=factory) is result
    assert calls==['compile','generate'] and request==initial
    error=ValueError('retained validation failure')
    def reject(*args,**kwargs):raise error
    fake.generate=reject
    with pytest.raises(ValueError) as raised:api.generate(request)
    assert raised.value is error


@pytest.mark.parametrize('invalid_request',[None,[],{}, {'task':[]}, {'task':{}},
    {'task':{'kind':None}}, {'task':{'kind':[]}}, {'task':{'kind':'purchase'}},
    {'task':{'user_message':'manual request','memories':[]}}])
def test_unknown_or_manual_kind_rejects_before_import_or_sampling(monkeypatch,invalid_request):
    def forbidden(*args):raise AssertionError('Unexpected import/sampling')
    monkeypatch.setattr(api,'import_module',forbidden)
    with pytest.raises(ValueError):api.generate(invalid_request)


def test_feature_conditioning_is_explicit_and_forwards_native_result(monkeypatch):
    result=object();seen=[]
    def load(name,package):
        seen.append(name);return SimpleNamespace(generate=lambda request,**kwargs:result)
    monkeypatch.setattr(api,'import_module',load)
    request={'task':{'kind':'cheapest_matching_available'}}
    assert api.generate(request) is result
    assert api.generate(request,profile='feature_conditioned') is result
    assert seen==['.feature_offer_generation','.conditioned_feature_generation']


@pytest.mark.parametrize('kind,profile',[
    ('prepare_matching_carts','feature_conditioned'),
    ('cheapest_matching_available','unsupported'),
])
def test_wrong_profile_never_changes_native_task_meaning(monkeypatch,kind,profile):
    monkeypatch.setattr(api,'import_module',lambda *a:pytest.fail('Unexpected import'))
    with pytest.raises(ValueError):api.generate({'task':{'kind':kind}},profile=profile)


def test_routing_metadata_is_detached():
    result=api.generators();result.clear()
    assert len(api.generators())==17


def test_actual_feature_compiler_still_rejects_unreleased_address_input():
    request={'schema':'website-world-generation-v2','seed':0,
        'world':{'concept_ids':['footwear.walking_shoes']},
        'task':{'kind':'cheapest_matching_available','concept_id':'footwear.walking_shoes'},
        'difficulty':{'address_probabilities':{'autofill_probability':0.9}}}
    with pytest.raises(ValueError,match='address-probability pass-through is not released'):
        api.compile_request(request)


def test_actual_comparison_compiler_preserves_comparison_home_requirement():
    request={'schema':'website-world-generation-v2','seed':0,
        'task':{'kind':'comparison_cheapest_exact_sku_stock','comparison_site_id':'comparison-00',
                'target':{'concept_id':'footwear.walking_shoes'}},
        'episode':{'start':{'kind':'tool_discovery'}}}
    with pytest.raises(ValueError,match='starts at its named comparison home'):
        api.compile_request(request)
