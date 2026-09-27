from copy import deepcopy
from types import SimpleNamespace
import pytest
from .scenario import generate_scenario
from .generator import digest
from .comparison_coverage import generate_coverage
from .geography import cities,user_location
from .interaction_patterns import (generate_interaction_patterns,validate_interaction_patterns,
    destination_alias,destination_matches,attach_interaction_patterns)
from .episode import Episode
from .outcomes import evaluate


@pytest.fixture(scope='module')
def fixture():
    s=generate_scenario({'seed':0,'family':'footwear','requirements':1,'hidden':'none','destination_city':'malmo',
        'world_preferences':'none'}, {'seed':42,'store_count':2,'models_per_store':1}, {})
    coverage=generate_coverage(s['bundle'],[{'site_id':'comparison-a','families':['footwear']}],seed=0)
    return s,coverage


def test_repeatable_draw_validates_without_mutation_and_defaults_remain_opt_in(fixture):
    s,c=fixture;before=deepcopy(s)
    a=generate_interaction_patterns(s['bundle'],s['locations'],coverage=c,seed=42)
    assert a==generate_interaction_patterns(s['bundle'],s['locations'],coverage=c,seed=42)
    assert validate_interaction_patterns(s['bundle'],a,s['locations'],coverage=c)['sites']==3
    assert s==before and 'interaction_patterns' not in s
    assert a['destination']==generate_interaction_patterns(s['bundle'],s['locations'],coverage=c,seed=99)['destination']
    b=generate_interaction_patterns(s['bundle'],coverage=c)
    assert b['destination'] is None and all(r['destination_form']=='none' for r in b['sites'])


def test_forced_controls_kind_scopes_and_no_destination_gate_without_locations(fixture):
    s,c=fixture;config={'search_sections_probability':1,'list_probability':1,'offer_expand_probability':1,
        'spec_expand_probability':1,'shipping_separate_probability':1,'destination_form_weights':{'split':1},'related_limits':[12]}
    a=generate_interaction_patterns(s['bundle'],s['locations'],coverage=c,config=config)
    for row in a['sites']:
        assert row['search_sections']
        if row['kind']=='retailer':
            assert row['result_presentation']=='list' and row['offer_disclosure']=='inline'
            assert row['specification_disclosure']=='expand' and row['shipping_disclosure']=='separate'
            assert row['destination_form']=='split' and row['related_limit']==12
        else:
            assert row['offer_disclosure']=='expand' and row['destination_form']=='none'
            assert row['specification_disclosure']=='inline' and row['related_limit']==0


def test_single_part_country_falls_back_without_inventing_postcode_pieces():
    s=generate_scenario({'family':'footwear','destination_city':'berlin','hidden':'none'},
                       {'store_count':2,'models_per_store':1},{})
    a=generate_interaction_patterns(s['bundle'],s['locations'],config={'destination_form_weights':{'split':1}})
    assert len(a['destination']['postcode_parts'])==1
    assert all(r['destination_form']=='single' for r in a['sites'] if r['kind']=='retailer')


def test_task_changes_and_input_order_do_not_condition_pattern_draw(fixture):
    s,c=fixture;a=attach_interaction_patterns(s,coverage=c,seed=7)
    other=deepcopy(s);other['task']['resolved_task']['constraints']={'budget_minor':1}
    other['task']['public']['user_message']='An entirely different request'
    assert attach_interaction_patterns(other,coverage=c,seed=7)['interaction_patterns']==a['interaction_patterns']


@pytest.mark.parametrize('country',sorted({c['country'] for c in cities().values()}))
def test_all_supported_countries_have_stable_aliases_and_exact_matching(country):
    loc={'public':{'user_location':user_location(17,'random',country)}}
    d=destination_alias(loc);data={'destination':d}
    assert d==destination_alias(loc) and d['synthetic'] is True
    assert destination_matches(data,country,d['postcode'])
    assert destination_matches(data,country.lower(),d['postcode'].lower().replace(' ','-'))
    assert destination_matches(data,country,parts=d['postcode_parts'])
    assert not destination_matches(data,'WRONG',d['postcode'])
    assert not destination_matches(data,country,d['postcode']+'9')
    assert not destination_matches(data,country,parts=[''])
    assert not destination_matches(data,country,d['postcode'],parts=d['postcode_parts'])
    assert not destination_matches(data,country,42)


@pytest.mark.parametrize('mutation',['world','geography','coverage','alias','missing','duplicate','unknown','bool','enum','related','kind'])
def test_tampered_bindings_and_invalid_rows_rejected(fixture,mutation):
    s,c=fixture;a=generate_interaction_patterns(s['bundle'],s['locations'],coverage=c)
    row=next(r for r in a['sites'] if r['kind']=='retailer')
    if mutation=='world':a['source_world_sha256']='wrong'
    elif mutation=='geography':a['source_locations_sha256']='wrong'
    elif mutation=='coverage':a['source_comparison_coverage_sha256']='wrong'
    elif mutation=='alias':a['destination']['postcode']='12345'
    elif mutation=='missing':a['sites'].pop()
    elif mutation=='duplicate':a['sites'].append(deepcopy(row))
    elif mutation=='unknown':row['site_id']='missing-store'
    elif mutation=='bool':row['search_sections']=1
    elif mutation=='enum':row['result_presentation']='masonry'
    elif mutation=='related':row['related_limit']=True
    elif mutation=='kind':row['offer_disclosure']='expand'
    with pytest.raises(ValueError):validate_interaction_patterns(s['bundle'],a,s['locations'],coverage=c)


@pytest.mark.parametrize('config',[{'typo':1},{'list_probability':float('nan')},{'profile_weights':{'alien':1}},
 {'profile_weights':{'direct':0,'browse':0,'compact':0}},{'related_limits':[13]},
 {'related_limits':[0,0]},{'destination_form_weights':{'none':0,'single':0,'split':0}}])
def test_invalid_sampler_priors_rejected(fixture,config):
    s,c=fixture
    with pytest.raises(ValueError):generate_interaction_patterns(s['bundle'],s['locations'],coverage=c,config=config)


def test_attachment_keeps_oracle_fixed_and_public_context_has_only_known_destination(fixture):
    s,c=fixture;new=attach_interaction_patterns(s,coverage=c,seed=42)
    assert new['task']==s['task'] and new['bundle']==s['bundle'] and new['locations']==s['locations']
    assert evaluate(new)==evaluate(s)
    e=Episode(new,index_url='http://localhost:12345',comparison_coverage=c)
    assert e.policy_input()['environment_context']['delivery_destination']=={
        'country':'SE','postcode':new['interaction_patterns']['destination']['postcode']}
    assert 'interaction_patterns' not in e.policy_input()
    assert e.episode_id!=Episode(s,index_url='http://localhost:12345').episode_id


def test_runtime_mismatch_and_missing_task_alias_fail_closed(fixture):
    s,_=fixture;new=attach_interaction_patterns(s)
    rt=SimpleNamespace(index_origin='http://localhost:12345',public_manifest={'index_url':'http://localhost:12345',
        'sites':[{'site_id':st['retailer_id'],'kind':'retailer','origin':f'http://localhost:{12500+i}'} for i,st in enumerate(s['bundle']['public']['retailers'])]},
        provenance={'world_sha256':s['bundle']['world_sha256'],'locations_sha256':s['locations']['locations_sha256'],
            'merchant_reviews_public_sha256':digest(s['merchant_reviews']['public']),
            'interaction_patterns_sha256':digest(new['interaction_patterns'])},interaction_patterns=new['interaction_patterns'])
    assert Episode.from_runtime(new,rt).policy_input()['environment_context']['delivery_destination']['country']=='SE'
    with pytest.raises(ValueError,match='lacks runtime'):Episode.from_runtime(s,rt)
    rt.provenance['interaction_patterns_sha256']='wrong'
    with pytest.raises(ValueError,match='different interaction'):Episode.from_runtime(new,rt)
