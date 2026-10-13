from copy import deepcopy
from urllib.parse import quote

import pytest

from environments.product_world.review_population import summarize_ratings
from environments.website_world import catalog_review_task as api, ecosystem
from environments.website_world.catalog_review_grading import ReviewSummaryGrader
from environments.website_world.test_listed_offer_grading import fixture as offer_fixture


def fixture(operation='topic_counts',**changes):
    world,_,_,_ = offer_fixture();item = world['products'][0]
    inventory = api.ReviewInventory('footwear.walking_shoes')
    topic = {'aspect':'walking_comfort','context':{'activity':'walking around town','duration':'several hours'}}
    context = {**topic['context'],'source':'first_hand'}
    def row(id,rating,polarities,*,written=True,source='first_hand',rendered=True):
        statements = [{'meaning':'walking_comfort','context':{**context,'source':source},'polarity':p,
                       'sku_id':'p-olive-42','text':p+' report.'} for p in polarities]
        text = ' '.join(s['text'] for s in statements) if written else ''
        return {'review_id':id,'reviewer':'Reader '+id,'sku_id':'p-olive-42','rating':rating,'text':text,
            'presentation':{'text':text,'segments':[{'statement_index':n} for n in range(len(statements))] if rendered else []},
            'evidence':{'statements':statements}}
    rows = [row('r1',5,['positive']),row('r2',1,['negative']),row('r3',3,['positive','negative']),
        row('r4',3,['neutral']),row('r5',2,['positive'],rendered=False),row('r6',5,['positive'],source='hearsay'),
        row('r7',5,[],written=False)]
    item.update(reviews=rows,rating_summary=summarize_ratings(rows))
    spec = {'kind':api.KIND,'concept_id':inventory.concept_id,'operation':operation,**changes}
    if operation == 'topic_counts': spec.setdefault('topic',topic)
    task = api.make(world,spec,inventory=inventory);reference = api.reference(world,task,inventory=inventory)
    surrounding = ecosystem.generate(world,{'comparison_count':0,'review_count':2})
    registry = [{**{k:s[k] for k in ('kind','site_id','name')},'origin':'https://reviews'+str(i)+'.test'}
                for i,s in enumerate(surrounding['sites'])]
    return world,task,reference,registry,surrounding,inventory


def claims_for(task,reference,*,url=None):
    url = url or 'https://reviews0.test/reviews/'+quote(task['subject']['product_id'],safe='')
    values = {'status':'summary','product_name':task['subject']['product_name'],'review_url':url,'sku_id':None,
              'mean_rating':None,'mean_undefined':None,'verdict':None}
    if task['operation']=='rating_summary':
        s = reference['summary'];values.update({k:s[k] for k in ('rating_count','written_review_count','rating_only_count')})
        values.update({f'star_{n}_count':s['star_counts'][str(n)] for n in range(1,6)})
        values.update(mean_rating=s['mean_rounded'],mean_undefined=s['mean_rounded'] is None)
    else:
        values.update(reference['counts']);values.update({k:reference[k] for k in ('written_review_count','assessed_count','verdict')})
    words = ['undefined' if k=='mean_undefined' and v is True else str(v) for k,v in values.items() if v is not None]
    text = '; '.join(words)
    if task['subject_scope']=='sku':
        values['sku_id'] = task['subject']['sku_id'];text += '; '+values['sku_id']
    c = {k:{'value':v,'evidence':text if v is not None else None} for k,v in values.items()}
    c.update(interpretation='extracted',issues=[],variant={},source_urls=[])
    return text,c


def grader(w,t,r,s,p,i): return ReviewSummaryGrader(w,t,r,s,surrounding=p,inventory=i)


def test_topic_counts_use_written_explicit_rendered_first_hand_reports_not_stars():
    _,task,r,_,_,_ = fixture()
    assert r['counts'] == {'positive':1,'negative':1,'neutral':1,'mixed':1,'not_assessed':2}
    assert r['written_review_count']==6 and r['assessed_count']==4 and r['verdict']=='tie'
    assert len(r['canonical_review_ids'])==7 and 'no publication dates' in task['user_message']


def test_rating_summary_includes_silent_ratings_and_half_up_mean():
    _,_,r,_,_,_ = fixture('rating_summary')
    assert r['summary']['rating_count']==7 and r['summary']['written_review_count']==6
    assert r['summary']['rating_only_count']==1 and r['summary']['mean_rounded']=='3.43'


@pytest.mark.parametrize('operation',['topic_counts','rating_summary'])
def test_correct_native_summary_grades_with_actual_public_review_link(operation):
    args=fixture(operation);text,c=claims_for(args[1],args[2])
    assert grader(*args).grade(c,text)['structured_claims_correct']


def test_rating_zero_is_count_and_mean_is_undefined_not_zero():
    w,t,_,s,_,i=fixture('rating_summary');w['products'][0].update(reviews=[],rating_summary=summarize_ratings([]))
    t=api.make(w,{k:t[k] for k in ('kind','concept_id','operation','subject_scope','product_index')},inventory=i)
    r=api.reference(w,t,inventory=i);p=ecosystem.generate(w,{'comparison_count':0,'review_count':2})
    text,c=claims_for(t,r);g=grader(w,t,r,s,p,i)
    assert r['summary']['mean_rounded'] is None and g.grade(c,text)['structured_claims_correct']
    c['mean_rating']={'value':'0','evidence':text};assert not g.grade(c,text)['structured_claims_correct']


def test_insufficient_topic_reports_are_an_explicit_verdict_with_real_counts():
    args=fixture(min_assessed=5);r=args[2]
    assert r['verdict']=='insufficient_evidence' and r['assessed_count']==4
    text,c=claims_for(args[1],r);assert grader(*args).grade(c,text)['structured_claims_correct']


def test_identical_canonical_copy_counts_once_conflicting_copy_rejects():
    w,t,r,_,_,i=fixture();w['products'][0]['reviews'].append(deepcopy(w['products'][0]['reviews'][0]))
    spec={k:t[k] for k in ('kind','concept_id','operation','subject_scope','product_index','topic','min_assessed')}
    task=api.make(w,spec,inventory=i);ref=api.reference(w,task,inventory=i)
    assert ref['counts']==r['counts'] and ref['canonical_review_ids']==r['canonical_review_ids']
    w['products'][0]['reviews'][-1]['rating']=1;task=api.make(w,spec,inventory=i)
    with pytest.raises(ValueError,match='Conflicting'):api.reference(w,task,inventory=i)


@pytest.mark.parametrize('change',['sku','unrendered','context','hearsay'])
def test_out_of_scope_opinion_does_not_count(change):
    w,t,_,_,_,i=fixture();row=w['products'][0]['reviews'][0]
    if change=='sku':row['sku_id']='p-brown-43';row['evidence']['statements'][0]['sku_id']='p-brown-43'
    elif change=='unrendered':row['presentation']['segments']=[]
    elif change=='context':row['evidence']['statements'][0]['context']['duration']='five minutes'
    else:row['evidence']['statements'][0]['context']['source']='hearsay'
    spec={k:t[k] for k in ('kind','concept_id','operation','subject_scope','product_index','topic','min_assessed')}
    if change=='sku':spec.update(subject_scope='sku',sku_index=2)
    task=api.make(w,spec,inventory=i);r=api.reference(w,task,inventory=i)
    assert r['counts']['positive']==0


@pytest.mark.parametrize('field',['positive','written_review_count','assessed_count'])
def test_wrong_or_missing_counts_fail_without_native_repair(field):
    args=fixture();text,c=claims_for(args[1],args[2]);c[field]={'value':None,'evidence':None}
    assert not grader(*args).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('url',['https://retailer.test/reviews/p','https://reviews0.test/reviews/foreign',
                               'https://reviews0.test/reviews/p?stars=5','https://reviews0.test/reviews/p?sku=p-olive-42',
                               'https://reviews0.test/reviews/p?sku=x&sku=y'])
def test_wrong_public_source_or_filtered_model_corpus_does_not_repair_counts(url):
    args=fixture();text,c=claims_for(args[1],args[2],url=url)
    assert not grader(*args).grade(c,text)['structured_claims_correct']


def test_another_syndicated_site_can_support_same_summary_without_extra_votes():
    args=fixture();text,c=claims_for(args[1],args[2],url='https://reviews1.test/reviews/p')
    assert grader(*args).grade(c,text)['structured_claims_correct']


def test_exact_sku_requires_independent_option_identity():
    args=fixture(subject_scope='sku',sku_index=2);text,c=claims_for(args[1],args[2]);g=grader(*args)
    assert g.grade(c,text)['structured_claims_correct']
    c['sku_id']={'value':None,'evidence':None}
    assert not g.grade(c,text)['structured_claims_correct']
    url='https://reviews0.test/reviews/p?sku='+args[1]['subject']['sku_id']
    text,c=claims_for(args[1],args[2],url=url);c['sku_id']={'value':None,'evidence':None}
    assert g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('value',[True,-1,'0'])
def test_bad_identity_indices_reject_before_sampling(value):
    with pytest.raises(ValueError):fixture(product_index=value)


def test_unaccepted_topic_context_rejects_and_dsl_inventory_is_source_bound():
    with pytest.raises(ValueError,match='not an accepted'):fixture(topic={'aspect':'walking_comfort','context':{'duration':'sprinting'}})
    i=api.ReviewInventory('footwear.casual_trainers')
    assert {'aspect':'value','context':'purchase'} in i.topics
    assert any(t['aspect']=='everyday_comfort' for t in i.topics)


def test_rating_and_opinion_source_prose_tampering_rejects():
    w,t,r,_,_,i=fixture();t['user_message']+=' changed'
    with pytest.raises(ValueError,match='binding'):api.reference(w,t,inventory=i)


def test_wrong_extracted_count_fails_native_comparison():
    args=fixture();text,c=claims_for(args[1],args[2]);c['positive']={'value':100,'evidence':text}
    assert not grader(*args).grade(c,text)['structured_claims_correct']


def test_accepted_dsl_context_reports_use_rendered_first_hand_meanings():
    w,_,_,_,_,_=fixture();item=w['products'][0]
    i=api.ReviewInventory('footwear.casual_trainers')
    item['public']['concept_id']=i.concept_id;w['config']['concept_ids']=[i.concept_id]
    rows=item['reviews']
    for row in rows:
        row['statements']=[]
        for statement in row.pop('evidence')['statements']:
            source=statement['context']['source']
            row['statements'].append({**statement,'meaning':{
                'kind':'customer_experience','aspect':'everyday_comfort',
                'context':'casual everyday wear','source':source,'polarity':statement['polarity']}})
    task=api.make(w,{'kind':api.KIND,'concept_id':i.concept_id,'operation':'topic_counts',
        'topic':{'aspect':'everyday_comfort','context':'casual everyday wear'}},inventory=i)
    r=api.reference(w,task,inventory=i)
    assert r['counts']=={'positive':1,'negative':1,'neutral':1,'mixed':1,'not_assessed':2}
    assert r['written_review_count']==6 and r['verdict']=='tie'


@pytest.mark.parametrize('shown',['3.43','3,43'])
def test_review_mean_semantic_claim_binds_decimal_presentation(shown):
    args=fixture('rating_summary');text,c=claims_for(args[1],args[2])
    text=text.replace('3.43',shown)
    for value in c.values():
        if isinstance(value,dict) and value.get('value') is not None:value['evidence']=text
    c['mean_rating']={'value':'3.43','evidence':shown}
    result=grader(*args).grade(c,text)
    assert result['structured_claims_correct']
    assert result['claims']['mean_rating']==c['mean_rating']


@pytest.mark.parametrize('shown,quote',[
    ('13.43','3.43'),('-3.43','3.43'),('−3.43','3.43'),
    ('- 3.43','3.43'),('− 3,43','3,43'),('3 430','3'),
])
def test_review_mean_uses_extracted_value_not_quote_token_interpretation(shown,quote):
    args=fixture('rating_summary');text,c=claims_for(args[1],args[2])
    text=text.replace('3.43',shown)
    for value in c.values():
        if isinstance(value,dict) and value.get('value') is not None:value['evidence']=text
    c['mean_rating']={'value':'3.43','evidence':quote}
    g=grader(*args)
    assert g.validate_claims(c,text)['mean_rating'] == c['mean_rating']
    c['mean_rating']['value']='4.00'
    assert not g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('value',['NaN','Infinity','-Infinity'])
def test_review_mean_rejects_nonfinite_normalized_values(value):
    args=fixture('rating_summary');text,c=claims_for(args[1],args[2])
    text+=' '+value;c['mean_rating']={'value':value,'evidence':value}
    with pytest.raises(ValueError,match='Nonfinite'):
        grader(*args).grade(c,text)


@pytest.mark.parametrize('field',['mean_rating','mean_undefined'])
@pytest.mark.parametrize('bad_evidence',['not in the answer',None])
def test_review_mean_semantic_fields_keep_shared_quote_checks(field,bad_evidence):
    args=fixture('rating_summary');text,c=claims_for(args[1],args[2])
    c[field]={'value':'3.43' if field=='mean_rating' else True,'evidence':bad_evidence}
    with pytest.raises(ValueError,match='exact final-answer quote'):
        grader(*args).grade(c,text)


@pytest.mark.parametrize('field',['mean_rating','mean_undefined'])
def test_review_null_semantic_claim_requires_null_evidence(field):
    args=fixture('rating_summary');text,c=claims_for(args[1],args[2])
    c[field]={'value':None,'evidence':text}
    with pytest.raises(ValueError,match='Absent claim'):
        grader(*args).grade(c,text)


def empty_ratings_fixture():
    w,t,_,sites,_,i=fixture('rating_summary')
    w['products'][0].update(reviews=[],rating_summary=summarize_ratings([]))
    t=api.make(w,{k:t[k] for k in ('kind','concept_id','operation','subject_scope','product_index')},inventory=i)
    r=api.reference(w,t,inventory=i)
    surrounding=ecosystem.generate(w,{'comparison_count':0,'review_count':2})
    return w,t,r,sites,surrounding,i


@pytest.mark.parametrize('shown',['undefined','not defined','no ratings','no observations'])
def test_empty_review_mean_requires_explicit_undefined_statement(shown):
    args=empty_ratings_fixture();text,c=claims_for(args[1],args[2])
    text+=' Mean: '+shown+'.';c['mean_undefined']={'value':True,'evidence':shown}
    assert grader(*args).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('shown,quote',[
    ('There are 0 ratings.','There are 0 ratings.'),
    ('The mean is not undefined.','undefined'),
    ('The mean is never undefined.','undefined'),
    ('"mean_undefined": false','"mean_undefined": false'),
])
def test_extractor_owned_empty_review_mean_does_not_infer_undefined_from_zero_or_contradictory_quote(shown,quote):
    args=empty_ratings_fixture();text,c=claims_for(args[1],args[2])
    text+=' '+shown;c['mean_undefined']={'value':True,'evidence':quote}
    assert grader(*args).validate_claims(c,text)['mean_undefined'] == c['mean_undefined']
    c['mean_undefined']['value'] = False
    assert not grader(*args).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('phrase',[
    'undefined','not defined','no ratings','no published ratings','no star ratings','no observations',
])
@pytest.mark.parametrize('statement',[
    'It is not true that there are {phrase}.',
    "It isn't true that there are {phrase}.",
    'It is false that there are {phrase}.',
    'The claim that there are {phrase} is not correct.',
    "It can't be true that there are {phrase}.",
    'It cannot be true that there are {phrase}.',
    'The claim that there are {phrase} is false.',
    "The claim that there are {phrase} isn't true.",
    'It is not true that there are "{phrase}".',
    "It is not true that there are '{phrase}'.",
    'The mean is not even {phrase}.',
    'The mean is not at all {phrase}.',
    'The mean can never be {phrase}.',
    'The mean is never truly {phrase}.',
    'The mean is not genuinely {phrase}.',

])
def test_extractor_owned_empty_review_mean_rejects_denial_of_every_supported_phrase(phrase,statement):
    args=empty_ratings_fixture();text,c=claims_for(args[1],args[2])
    text+=' '+statement.format(phrase=phrase)
    c['mean_undefined']={'value':True,'evidence':phrase}
    assert grader(*args).validate_claims(c,text)['mean_undefined'] == c['mean_undefined']
    c['mean_undefined']['value'] = False
    assert not grader(*args).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('shown,quote',[
    ('There are no ratings.','no ratings'),
    ('There are no published ratings.','no published ratings'),
    ('There are no star ratings.','no star ratings'),
    ('There are no observations.','no observations'),
    ('The mean is not defined.','not defined'),
    ('There are no ratings so the mean is not defined.','not defined'),
    ('The mean is not defined because there are no observations.','no observations'),
    ('The statement is false; there are no ratings.','no ratings'),
    ('The mean is undefined, not zero.','undefined'),
    ('There are no ratings, not even silent ratings.','no ratings'),
    ('The mean is not defined because there are no ratings, not zero.','not defined'),
    ('It is not a numeric zero; the mean is not defined.','not defined'),
    ('The mean is not zero but undefined.','undefined'),
    ('A numeric mean cannot be computed because there are no ratings.','no ratings'),
    ("There aren't any ratings, so the mean is undefined.",'undefined'),
    ("A numeric mean can't be computed because there are no observations.",'no observations'),
])
def test_empty_review_mean_retains_affirmative_phrases_and_clause_scope(shown,quote):
    args=empty_ratings_fixture();text,c=claims_for(args[1],args[2])
    text+=' '+shown;c['mean_undefined']={'value':True,'evidence':quote}
    assert grader(*args).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('verdict',[None,'tie'])
def test_complete_topic_table_does_not_require_an_enum_label(verdict):
    args=fixture();text,c=claims_for(args[1],args[2])
    c['verdict']={'value':verdict,'evidence':text if verdict else None}
    result=grader(*args).grade(c,text)
    assert result['structured_claims_correct']
    assert result['claims']['verdict']['value']==verdict


def test_missing_verdict_does_not_repair_wrong_counts_or_insufficient_evidence():
    args=fixture();text,c=claims_for(args[1],args[2]);c['verdict']={'value':None,'evidence':None}
    c['positive']={'value':2,'evidence':text}
    assert not grader(*args).grade(c,text)['structured_claims_correct']
    args=fixture(min_assessed=5);text,c=claims_for(args[1],args[2]);c['verdict']={'value':None,'evidence':None}
    assert not grader(*args).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('comparison',['1 negative versus 1 positive','1 are negative versus 1 positive'])
def test_review_verdict_binds_ordinary_explicit_numeric_comparison(comparison):
    args=fixture();text,c=claims_for(args[1],args[2]);text+=' '+comparison
    c['verdict']={'value':'tie','evidence':comparison}
    assert grader(*args).grade(c,text)['structured_claims_correct']


def test_review_numeric_comparison_does_not_justify_opposite_direction():
    args=fixture();text,c=claims_for(args[1],args[2]);text+=' 1 negative versus 1 positive'
    c['verdict']={'value':'more_negative','evidence':'1 negative versus 1 positive'}
    assert grader(*args).validate_claims(c,text)['verdict'] == c['verdict']
    assert not grader(*args).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('shown,quote',[
    ('-1 negative versus 1 positive','1 negative versus 1 positive'),
    ('−1 negative versus 1 positive','1 negative versus 1 positive'),
    ('2 negative versus 1 positive; 1 negative','2 negative versus 1 positive; 1 negative'),
    ('It is not true that there are 1 negative versus 1 positive.','1 negative versus 1 positive'),
    ('Not 1 negative versus 1 positive.','1 negative versus 1 positive'),
])
def test_extractor_owned_review_numeric_comparison_rejects_cropped_duplicate_or_negated_counts(shown,quote):
    args=fixture();text,c=claims_for(args[1],args[2]);text+=' '+shown
    c['verdict']={'value':'tie','evidence':quote}
    assert grader(*args).validate_claims(c,text)['verdict'] == c['verdict']


@pytest.mark.parametrize('shown,quote',[
    ('1 001 negative versus 1 positive','1 001 negative versus 1 positive'),
    ('-\u00a01 negative versus 1 positive','1 negative versus 1 positive'),
    ('−\u202f1 negative versus 1 positive','1 negative versus 1 positive'),
    ('Not a tie; more negative','Not a tie; more negative'),
    ('It is not true that the counts tie.','It is not true that the counts tie.'),
])
def test_extractor_owned_review_verdict_retains_grouping_sign_and_marker_negation(shown,quote):
    args=fixture();text,c=claims_for(args[1],args[2]);text+=' '+shown
    c['verdict']={'value':'tie','evidence':quote}
    assert grader(*args).validate_claims(c,text)['verdict'] == c['verdict']


def test_review_verdict_scope_exclusion_does_not_negate_numeric_comparison():
    args=fixture();text,c=claims_for(args[1],args[2])
    quote='1 negative versus 1 positive'
    text+=' '+quote+', not including rating-only entries.'
    c['verdict']={'value':'tie','evidence':quote}
    assert grader(*args).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('shown,quote',[
    ('Not a **tie**','tie'),
    ('Not **1 negative versus 1 positive**','1 negative versus 1 positive'),
    ('**tie** is false','tie'),
])
def test_extractor_owned_review_verdict_markdown_does_not_hide_outer_denial(shown,quote):
    args=fixture();text,c=claims_for(args[1],args[2]);text=text.replace('tie','unspecified')
    for value in c.values():
        if isinstance(value,dict) and value.get('value') is not None:value['evidence']=text
    text+='; '+shown
    c['verdict']={'value':'tie','evidence':quote}
    assert grader(*args).validate_claims(c,text)['verdict'] == c['verdict']
