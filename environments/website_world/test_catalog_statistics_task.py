from copy import deepcopy
import pytest
from environments.website_world import catalog_statistics_task as task,ecosystem,catalog_statistics_generation as generation
from environments.website_world.catalog_statistics_grading import CatalogStatisticsGrader
from environments.website_world.test_listed_offer_grading import fixture as original


def fixture(operation='mean',grain='model',empty=False):
    w,*_=original();w['quote_as_of']='2026-10-07';q=deepcopy(w['products'][0]);q['public'].update(product_id='q',name='Second model')
    for s in q['public']['skus']:s['product_id']='q';s['sku_id']=s['sku_id'].replace('p-','q-')
    w['products'].append(q)
    for retailer,price in zip(w['retailers'],[100000,120000,90000,100000]):
        additions=[]
        for o in retailer['offers']:
            x=deepcopy(o);x.update(product_id='q',sku_id=x['sku_id'].replace('p-','q-'),offer_id=x['offer_id'].replace('/p-','/q-'),price_minor=price);additions.append(x)
        retailer['offers'].extend(additions)
    controls={'comparison_count':1,'review_count':0,'model_probability':0 if empty else 1,'retailer_pair_probability':1}
    sidecar=ecosystem.generate(w,controls)
    spec={'kind':task.KIND,'concept_id':'footwear.walking_shoes','comparison_site_id':'comparison-00','operation':operation,'grain':grain}
    t=task.make(w,sidecar,spec);r=task.reference(w,sidecar,t)
    registry=[{'site_id':s['site_id'],'kind':s['kind'],'name':s['name'],'origin':'https://compare.test'} for s in sidecar['sites']]
    return w,sidecar,t,r,registry


def answer(r,url='https://compare.test/'):
    values={'status':'summary','comparison_url':url,'population_count':r['population_count'],
        'statistic_sek':r['aggregate_sek'],'currency':'SEK' if r['aggregate_sek'] is not None else None,
        'undefined':not r['statistic_defined'] if r['operation']!='count' else None}
    text='summary; '+url+'; '+str(r['population_count'])
    if values['statistic_sek'] is not None:text+='; '+values['statistic_sek']+' SEK'
    if values['undefined']:text+='; undefined'
    return text,{**{k:{'value':v,'evidence':text if v is not None else None} for k,v in values.items()},'interpretation':'extracted','issues':[],'source_urls':[]}


@pytest.mark.parametrize('operation,value',[('count',None),('mean','765.00'),('median','765.00'),('minimum','630.00'),('maximum','900.00')])
def test_model_grain_uses_one_minimum_per_model_and_does_not_filter_zero_stock(operation,value):
    w,s,t,r,sites=fixture(operation)
    assert r['population_count']==2 and r['aggregate_sek']==value
    assert r['observations']==[{'product_id':'p','price_minor':63000},{'product_id':'q','price_minor':90000}]
    text,c=answer(r);assert CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']


def test_listing_grain_weights_every_distinct_model_retailer_once_not_skus():
    _,_,_,r,_=fixture(grain='listing')
    assert r['population_count']==8 and r['aggregate_sek']=='876.25'
    assert len({(x['product_id'],x['retailer_id']) for x in r['observations']})==8


@pytest.mark.parametrize('operation',['mean','median','minimum','maximum','count'])
def test_empty_population_is_undefined_price_but_defined_zero_count(operation):
    w,s,t,r,sites=fixture(operation,empty=True);text,c=answer(r)
    assert r['population_count']==0 and r['aggregate_sek'] is None and r['statistic_defined']==(operation=='count')
    assert CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('url',['https://retailer.test/','https://compare.test/models/p','https://compare.test/?max_price=500'])
def test_wrong_or_filtered_comparison_identity_cannot_repair_correct_aggregate(url):
    w,s,t,r,sites=fixture();text,c=answer(r,url)
    assert not CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']


def test_mismatched_population_grain_fails_even_if_some_statistic_coincides():
    w,s,t,r,sites=fixture();text,c=answer(r);c['population_count']={'value':8,'evidence':text+' 8'}
    with pytest.raises(ValueError):CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)
    text+='; 8';c['population_count']['evidence']=text;assert not CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']


def test_pre_sampling_unknown_operation_or_site_cannot_call_factory(monkeypatch):
    request={'schema':'website-world-generation-v2','seed':79,'world':{'concept_ids':['footwear.walking_shoes']},
        'task':{'kind':task.KIND,'concept_id':'footwear.walking_shoes','comparison_site_id':'comparison-07','operation':'mean'}}
    def forbidden(*args,**kw):raise AssertionError('No generation allowed')
    monkeypatch.setattr(generation.unified,'generate',forbidden)
    with pytest.raises(ValueError,match='Enable'):generation.generate(request)
    request['task'].update(comparison_site_id='comparison-00',operation='mean_price_change_last_month')
    with pytest.raises(ValueError):generation.generate(request)


def test_half_up_half_minor_unit_for_two_listing_average():
    w,*_=original();w['quote_as_of']='2026-10-07'
    w['retailers']=w['retailers'][:2]
    for retailer,price in zip(w['retailers'],[10000,10001]):
        for o in retailer['offers']:o['price_minor']=price
    s=ecosystem.generate(w,{'comparison_count':1,'review_count':0,'model_probability':1,'retailer_pair_probability':1})
    t=task.make(w,s,{'kind':task.KIND,'concept_id':'footwear.walking_shoes','comparison_site_id':'comparison-00','operation':'mean','grain':'listing'})
    assert task.reference(w,s,t)['aggregate_sek']=='100.01'


def test_generation_attaches_statistics_without_changing_natural_population(monkeypatch):
    w,s,_,_,_=fixture();calls=[]
    request={'schema':'website-world-generation-v2','seed':79,'world':{'concept_ids':['footwear.walking_shoes']},
        'task':{'kind':task.KIND,'concept_id':'footwear.walking_shoes','comparison_site_id':'comparison-00','operation':'median','grain':'listing'}}
    before=deepcopy(w)
    def saved(proxy,*,world_factory):
        calls.append(proxy);return {'world':w,'surrounding':s,'episode':{},'audit':{'request_sha256':'proxy'},'resolved_configuration':{}}
    monkeypatch.setattr(generation.unified,'generate',saved)
    result=generation.generate(request)
    assert len(calls)==1 and result['world']==before and result['catalog_statistics_reference']['population_count']==8
    assert result['episode']['manual_task']=={'user_message':result['catalog_statistics_task']['user_message'],'memories':[]}


def test_common_once_only_formatter_receives_public_task_not_observations(tmp_path):
    import json
    from types import SimpleNamespace
    from experiments.answer_grading.task_answer import grade_saved_once
    from scripts.trace_grades import BOUND_FILES,FILENAME,read_grade
    w,s,t,r,sites=fixture();text,claims=answer(r);trace=tmp_path/'trace';trace.mkdir()
    save=lambda p,v:p.write_text(json.dumps(v)+'\n')
    for n in BOUND_FILES:(trace/n).write_text('' if n.endswith('.jsonl') else '{}')
    save(trace/'natural-answer.json',{'text':text,'stop_reason':'agent_finished','technical_error':None})
    public={'user_message':t['user_message'],'memories':[]};save(trace/'policy-task.json',public)
    inputs={}
    for k,v in {'world':w,'task':t,'reference':r,'site_registry':sites,'surrounding':s}.items():
        p=tmp_path/(k+'.json');save(p,v);inputs[k]=p
    calls=[]
    class Backend:
        def complete(self,messages):
            payload=json.loads(messages[1]['content'])
            assert payload=={'public_task':public,'final_answer':text}
            assert '"observations"' not in messages[0]['content']
            calls.append(messages)
            return SimpleNamespace(text=json.dumps(claims),raw={'model':'scripted-statistics-formatter','choices':[{'finish_reason':'stop','message':{'content':json.dumps(claims)}}]},request={'messages':messages})
        def close(self):pass
    kw=dict(trace=trace,inputs=inputs,output=tmp_path/'grading',grader_factory=CatalogStatisticsGrader,backend_factory=lambda _:Backend(),source_paths=[])
    result=grade_saved_once(**kw);assert result['structured_claims_correct'] and len(calls)==1
    assert json.loads((trace/FILENAME).read_text())['grading_version']=='website-catalog-statistics-grading-v5'
    assert read_grade(trace)['binding_status'] == 'verified'
    with pytest.raises(FileExistsError):grade_saved_once(**kw)
    assert len(calls)==1


@pytest.mark.parametrize('overrides', [{'task': None}, {'world': []}])
def test_malformed_input_objects_fail_before_generation(overrides):
    request = {'schema': 'website-world-generation-v2', 'task': {}, **overrides}
    with pytest.raises(ValueError, match='objects'):
        generation.compile_request(request)


@pytest.mark.parametrize('field', ['population_count','statistic_sek','currency','undefined'])
def test_statistics_fields_reject_fabricated_quotes(field):
    w,s,t,r,sites=fixture();text,c=answer(r)
    if field=='undefined':c[field]={'value':False,'evidence':'fabricated quotation'}
    else:c[field]['evidence']='fabricated quotation'
    with pytest.raises(ValueError,match='exact final-answer quote'):
        CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)


@pytest.mark.parametrize('field', ['population_count','statistic_sek','currency','undefined'])
def test_absent_statistics_claim_requires_absent_evidence(field):
    w,s,t,r,sites=fixture();text,c=answer(r)
    c[field]={'value':None,'evidence':text}
    with pytest.raises(ValueError,match='Absent claim'):
        CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)


@pytest.mark.parametrize('field,value,quote', [
    ('population_count',2,'We counted 12 models.'),
    ('population_count',2,'We counted 2.5 models.'),
    ('population_count',2,'We counted 2,500 models.'),
    ('population_count',2,'We counted 2,5 models.'),
    ('statistic_sek','765.00','The mean is 1765.00 SEK.'),
    ('statistic_sek','765.00','The mean is -765.00 SEK.'),
    ('currency','SEK','The SEKing service is useful.'),
])
def test_statistics_trusts_extracted_values_with_authentic_quotes(field,value,quote):
    w,s,t,r,sites=fixture();text,c=answer(r)
    text+=' '+quote;c[field]={'value':value,'evidence':quote}
    assert CatalogStatisticsGrader(w,t,r,sites,surrounding=s).validate_claims(c,text)[field] == c[field]


@pytest.mark.parametrize('amount', ['765.00','765,00'])
def test_canonical_statistic_can_be_grounded_in_ordinary_decimal_presentation(amount):
    w,s,t,r,sites=fixture();text,c=answer(r)
    text=text.replace('765.00',amount)
    for claim in c.values():
        if isinstance(claim,dict) and claim.get('evidence') is not None:claim['evidence']=text
    assert CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('quote', ['There are -2 models.','There are −2 models.','There are 2 000 models.'])
def test_count_quote_is_provenance_not_a_second_numeric_interpretation(quote):
    w,s,t,r,sites=fixture();text,c=answer(r)
    text+=' '+quote;c['population_count']={'value':2,'evidence':quote}
    g=CatalogStatisticsGrader(w,t,r,sites,surrounding=s)
    assert g.validate_claims(c,text)['population_count']==c['population_count']
    c['population_count']['value']=3
    assert not g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('quote',['The mean is −765.00 SEK.','The mean is -765.00 SEK.'])
def test_statistic_sign_interpretation_belongs_to_extractor(quote):
    w,s,t,r,sites=fixture();text,c=answer(r)
    text+=' '+quote;c['statistic_sek']={'value':'765.00','evidence':quote}
    g=CatalogStatisticsGrader(w,t,r,sites,surrounding=s)
    assert g.validate_claims(c,text)['statistic_sek']==c['statistic_sek']
    c['statistic_sek']['value']='766.00'
    assert not g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('quote',['The mean is 765.00, 2 models.','Amounts: 1.00 765.00 SEK.'])
def test_adjacent_numbers_do_not_merge_with_quoted_statistic(quote):
    w,s,t,r,sites=fixture();text,c=answer(r)
    text+=' '+quote;c['statistic_sek']={'value':'765.00','evidence':quote}
    assert CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']


def test_sentence_ending_count_is_grounded():
    w,s,t,r,sites=fixture();text,c=answer(r)
    quote='The number of models is 2.';text+=' '+quote
    c['population_count']={'value':2,'evidence':quote}
    assert CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('quote',['There are 0 models.','The mean is not undefined.','undefined: false'])
def test_extractor_owned_empty_mean_cannot_infer_undefined_from_zero_count_or_opposite_statement(quote):
    w,s,t,r,sites=fixture(empty=True);text,c=answer(r)
    text+=' '+quote;c['undefined']={'value':True,'evidence':quote}
    g=CatalogStatisticsGrader(w,t,r,sites,surrounding=s)
    assert g.validate_claims(c,text)['undefined'] == c['undefined']
    c['undefined']['value']=False
    assert not g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('quote',['The mean is undefined.','There are no priced models.','There are no observations.','The mean is not defined.'])
def test_explicit_undefined_statement_is_supported(quote):
    w,s,t,r,sites=fixture(empty=True);text,c=answer(r)
    text+=' '+quote;c['undefined']={'value':True,'evidence':quote}
    assert CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('quote',['"undefined": false','The mean is never undefined.','The mean is not actually undefined.'])
def test_extractor_owned_negated_or_json_false_undefined_does_not_ground_true(quote):
    w,s,t,r,sites=fixture(empty=True);text,c=answer(r)
    text+=' '+quote;c['undefined']={'value':True,'evidence':quote}
    g=CatalogStatisticsGrader(w,t,r,sites,surrounding=s)
    assert g.validate_claims(c,text)['undefined'] == c['undefined']
    c['undefined']['value']=False
    assert not g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('actual,quoted', [('-2','2'),('−2','2'),('2 000','2')])
def test_quote_authenticity_does_not_reinterpret_sign_or_grouping(actual,quoted):
    w,s,t,r,sites=fixture();text,c=answer(r)
    text=f'summary; https://compare.test/; There are {actual} models; 765.00 SEK'
    for claim in c.values():
        if isinstance(claim,dict) and claim.get('value') is not None:claim['evidence']=text
    c['population_count']={'value':2,'evidence':quoted}
    g=CatalogStatisticsGrader(w,t,r,sites,surrounding=s)
    assert g.validate_claims(c,text)['population_count']==c['population_count']
    c['population_count']['value']=3
    assert not g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('actual',[
    'The mean is never undefined.',
    'The mean is not actually undefined.',
    '"undefined": false',
])
def test_extractor_owned_short_undefined_quote_cannot_drop_actual_negation(actual):
    w,s,t,r,sites=fixture(empty=True);text,c=answer(r)
    text+=' '+actual;c['undefined']={'value':True,'evidence':'undefined'}
    g=CatalogStatisticsGrader(w,t,r,sites,surrounding=s)
    assert g.validate_claims(c,text)['undefined'] == c['undefined']
    c['undefined']['value']=False
    assert not g.grade(c,text)['structured_claims_correct']


def test_currency_is_extracted_not_reclassified_from_quote_word_boundaries():
    w,s,t,r,sites=fixture();text,c=answer(r)
    text=text.replace('SEK','SEKing')
    for claim in c.values():
        if isinstance(claim,dict) and claim.get('value') is not None:claim['evidence']=text
    c['currency']={'value':'SEK','evidence':'SEK'}
    g=CatalogStatisticsGrader(w,t,r,sites,surrounding=s)
    assert g.validate_claims(c,text)['currency']==c['currency']
    c['currency']['value']='EUR'
    assert not g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('shown,canonical',[
    ('765','765.00'),('765,00','765.00'),('1 234,50','1234.50'),
    ('1\u00a0234,50','1234.50'),('1.234,50','1234.50'),('1,234.50','1234.50'),
])
def test_statistics_semantic_decimal_claim_preserves_canonical_value_and_quote(shown,canonical):
    w,s,t,r,sites=fixture();text,c=answer(r)
    quote='The mean is '+shown+' SEK.';text+=' '+quote
    c['statistic_sek']={'value':canonical,'evidence':quote}
    result=CatalogStatisticsGrader(w,t,r,sites,surrounding=s).validate_claims(c,text)
    assert result['statistic_sek']==c['statistic_sek']


@pytest.mark.parametrize('shown',['- 765.00','− 765,00'])
def test_statistic_semantics_are_not_reparsed_from_spaced_signs(shown):
    w,s,t,r,sites=fixture();text,c=answer(r)
    text+=' The mean is '+shown+' SEK.'
    c['statistic_sek']={'value':'765.00','evidence':shown}
    g=CatalogStatisticsGrader(w,t,r,sites,surrounding=s)
    assert g.validate_claims(c,text)['statistic_sek']==c['statistic_sek']
    c['statistic_sek']['value']='766.00'
    assert not g.grade(c,text)['structured_claims_correct']

def rich_citation_fixture(operation='mean',grain='model',empty=False):
    from . import rich_ecosystem
    w,_,t,_,_=fixture(operation,grain,empty)
    for item in w['products']:
        item['public']['family_id']='footwear'
        item['public']['facts']={}
    s=rich_ecosystem.generate(w,{'comparison_count':1,'review_count':0,
        'model_probability':0 if empty else 1,'retailer_pair_probability':1,
        'scope_weights':{'general':1,'specialist':0},'price_ceiling_probability':1,'sorting_probability':1})
    t=task.make(w,s,{k:t[k] for k in ('kind','concept_id','comparison_site_id','operation','grain')})
    r=task.reference(w,s,t)
    sites=[{'site_id':x['site_id'],'kind':x['kind'],'name':x['name'],'origin':'https://compare.test'} for x in s['sites']]
    return w,s,t,r,sites


@pytest.mark.parametrize('query',[
    'category=footwear','category=footwear&q=&max_price=&sort=name',
    'sort=price_desc','max_price=1000000','page=2',
])
def test_population_preserving_catalog_queries_are_valid_citations(query):
    w,s,t,r,sites=rich_citation_fixture();text,c=answer(r,'https://compare.test/search?'+query)
    assert CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('query',[
    'q=Second','category=tablets','max_price=700','stock=in_stock',
    'sort=foreign','category=footwear&category=tablets','page=0','page=01',
])
def test_population_losing_or_unsupported_queries_do_not_repair_a_correct_aggregate(query):
    w,s,t,r,sites=rich_citation_fixture();text,c=answer(r,'https://compare.test/search?'+query)
    assert not CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']


def test_filtered_citation_preserves_all_models_for_listing_grain_too():
    w,s,t,r,sites=rich_citation_fixture(grain='listing');text,c=answer(r,'https://compare.test/search?category=footwear&max_price=900')
    assert CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']


def test_empty_population_does_not_credit_an_unrelated_filtered_empty_search():
    w,s,t,r,sites=rich_citation_fixture(empty=True);text,c=answer(r,'https://compare.test/search?q=foreign')
    assert not CatalogStatisticsGrader(w,t,r,sites,surrounding=s).grade(c,text)['structured_claims_correct']
