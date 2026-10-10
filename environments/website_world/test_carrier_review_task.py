from copy import deepcopy
import pytest

from environments.website_world import carrier_review_task as api
from environments.website_world import carrier_review_generation as generation
from environments.website_world.carrier_review_grading import CarrierReviewGrader


def fixture(operation='topic_counts', **changes):
    policy = {'carrier_id': 'carrier-01', 'name': 'Sendora', 'services': [
        {'service_id': 'carrier-01-regular', 'shipping_class': 'regular'},
        {'service_id': 'carrier-01-bulky', 'shipping_class': 'bulky'}]}
    def statement(pool, sign, index=0, **slots):
        from experiments.carrier_service_pilot.prose import POOLS
        return {'aspect': 'tracking' if pool.startswith('tracking') else pool,
            'sentiment': sign, 'text': POOLS[(pool, sign)][index].format(**slots),
            'template_id': f'{pool}:{sign}:{index}', 'evidence_ids': []}
    def row(rid, stars, statements, *, shipping='regular', date='2026-08-01', text=None):
        value = {'review_id': rid, 'reviewer_id': rid+'/person', 'reviewer_name': 'Sam',
            'carrier_id': 'carrier-01', 'service_id': 'carrier-01-'+shipping,
            'shipping_class': shipping, 'date': date, 'stars': stars,
            'text': text if text is not None else ' '.join(s['text'] for s in statements) or None}
        return {**value, 'shipment_id': rid+'/shipment', 'statements': statements}
    private = [row('r1',5,[statement('punctuality','positive'),statement('punctuality','positive',1)]),
        row('r2',1,[statement('punctuality','negative',late_duration='a day')]),
        row('r3',3,[statement('punctuality','positive'),statement('punctuality','negative',5)],
            text='The parcel arrived on the day they said it would. But they missed the delivery date.'),
        row('r4',3,[statement('collection','neutral',point_name='the lockers')]),
        row('r5',2,[statement('tracking_stale','negative')]), row('r6',5,[]),
        row('r7',4,[statement('punctuality','positive')],shipping='bulky',date='2026-08-02')]
    public = [{k:v for k,v in r.items() if k not in ('shipment_id','statements')} for r in private]
    world = {'world_id':'authored-carrier-fixture','seed':0,'carrier_evidence':{
        'schema_version':'carrier-service-evidence-v1','corpus_id':'fixture-corpus',
        'public':{'corpus_id':'fixture-corpus','carriers':[policy],'reviews':public,'collection_points':[]},
        'private':{'reviews':private,'shipments':[{'destination_type':'home','hidden_success':True}],
                   'carrier_parameters':[{'quality':'high'}]}}}
    inventory = api.ReviewInventory()
    spec = {'kind':api.KIND,'operation':operation,'shipping_class':'regular',**changes}
    if operation=='topic_counts':spec.setdefault('aspect','punctuality')
    task = api.make(world,spec,inventory=inventory)
    reference = api.reference(world,task,inventory=inventory)
    publication = api.public_projection(world)
    registry = [{'site_id':publication['site_id'],'name':publication['name'],
                 'kind':publication['kind'],'origin':'https://parcels.test'}]
    return world,task,reference,publication,registry,inventory


def answer(task, reference):
    values = {'carrier_name':task['subject']['carrier_name'],
        'review_url':'https://parcels.test/carriers/'+task['subject']['carrier_id'],
        'status':'summary','mean_rating':None,'mean_undefined':None,'verdict':None}
    if task['operation']=='rating_summary':
        s=reference['summary']
        values.update({k:s[k] for k in ('rating_count','written_review_count','rating_only_count')})
        values.update({f'star_{n}_count':s['star_counts'][str(n)] for n in range(1,6)})
        values.update(mean_rating=s['mean_rounded'],mean_undefined=s['mean_rounded'] is None)
    else:
        values.update(reference['counts'])
        values.update({k:reference[k] for k in ('written_review_count','assessed_count','verdict')})
    text='; '.join('undefined' if k=='mean_undefined' and v is True else str(v)
                   for k,v in values.items() if v is not None)
    claims={k:{'value':v,'evidence':text if v is not None else None} for k,v in values.items()}
    claims.update(interpretation='extracted',issues=[],source_urls=[])
    return text,claims


def grader(args):
    w,t,r,p,s,i=args
    return CarrierReviewGrader(w,t,r,s,publication=p,inventory=i)


def test_written_counts_use_comments_not_statements_stars_or_hidden_success():
    args=fixture();w,t,r,_,_,i=args
    assert r['counts']=={'positive':1,'negative':1,'neutral':0,'mixed':1,'not_assessed':2}
    assert r['assessed_count']==3 and r['written_review_count']==5 and r['verdict']=='tie'
    before=deepcopy(r)
    w['carrier_evidence']['private']['shipments']=[{'destination_type':'collection','hidden_success':False}]
    w['carrier_evidence']['private']['carrier_parameters']=[{'quality':'low'}]
    t2=api.make(w,{k:t[k] for k in ('kind','operation','shipping_class','aspect','min_assessed')},inventory=i)
    r2=api.reference(w,t2,inventory=i)
    assert r2['counts']==before['counts'] and r2['verdict']==before['verdict']


@pytest.mark.parametrize('operation',['rating_summary','topic_counts'])
def test_correct_summary_grades_and_never_requires_product_or_sku(operation):
    args=fixture(operation);text,claims=answer(args[1],args[2]);g=grader(args)
    assert g.grade(claims,text)['structured_claims_correct']
    assert isinstance(g.grade(claims,text)['derivations'],list)
    assert not {'sku_id','variant','product_name'} & set(g.schema['properties'])


def test_silent_ratings_and_explicit_half_up_mean():
    args=fixture('rating_summary');s=args[2]['summary']
    assert s['rating_count']==6 and s['rating_only_count']==1 and s['written_review_count']==5
    assert s['mean_rounded']=='3.17'


def test_empty_inclusive_date_scope_has_zero_count_and_undefined_mean():
    args=fixture('rating_summary',date_from='1900-01-01',date_to='1900-01-01')
    assert args[2]['summary']['rating_count']==0 and args[2]['summary']['mean_rounded'] is None
    text,c=answer(args[1],args[2]);assert grader(args).grade(c,text)['structured_claims_correct']
    c['mean_rating']={'value':'0','evidence':text};assert not grader(args).grade(c,text)['structured_claims_correct']


def test_class_and_date_are_public_filters_not_home_scope():
    assert fixture('rating_summary',shipping_class='bulky')[2]['canonical_review_ids']==['r7']
    assert fixture('rating_summary',shipping_class='all')[2]['summary']['rating_count']==7
    assert fixture('rating_summary',date_from='2026-08-01',date_to='2026-08-01')[2]['summary']['rating_count']==6
    assert 'not a home-only filter' in fixture()[1]['user_message']


def test_insufficient_and_neutral_aspects_remain_distinct():
    assert fixture(min_assessed=4)[2]['verdict']=='insufficient_evidence'
    r=fixture(aspect='collection')[2]
    assert r['counts']['neutral']==1 and r['assessed_count']==1 and r['verdict']=='tie'


def test_syndicated_copies_deduplicate_and_conflicts_reject():
    w,t,r,_,_,i=fixture('rating_summary')
    rows=w['carrier_evidence']['public']['reviews'];rows.append(deepcopy(rows[0]))
    spec={k:t[k] for k in ('kind','operation','shipping_class')}
    t=api.make(w,spec,inventory=i);assert api.reference(w,t,inventory=i)['summary']==r['summary']
    rows[-1]['stars']=1
    with pytest.raises(ValueError,match='Conflicting'):api.make(w,spec,inventory=i)


@pytest.mark.parametrize('fault',['unrendered','aspect','public_text','template','notification_aspect'])
def test_private_composition_cannot_credit_unspoken_or_mislabelled_claims(fault):
    w,t,_,_,_,i=fixture();record=w['carrier_evidence']['private']['reviews'][0]
    if fault=='unrendered':record['statements'].append(deepcopy(record['statements'][0]))
    elif fault=='aspect':record['statements'][0]['aspect']='handling'
    elif fault=='public_text':w['carrier_evidence']['public']['reviews'][0]['text']='Nothing about delivery.'
    elif fault=='template':record['statements'][0]['template_id']='punctuality:positive:999'
    else:record['statements'][0]['template_id']='notification:positive:0'
    t=api.make(w,{k:t[k] for k in ('kind','operation','shipping_class','aspect','min_assessed')},inventory=i)
    with pytest.raises(ValueError):api.reference(w,t,inventory=i)


@pytest.mark.parametrize('fault',['wrong_name','foreign','home','filtered_stars','narrow_class','wrong_date','duplicate_query','wrong_count','missing_mean'])
def test_wrong_subject_scope_links_and_omitted_arithmetic_fail(fault):
    args=fixture('rating_summary');text,c=answer(args[1],args[2])
    if fault=='wrong_count':c['rating_count']={'value':999,'evidence':'999'};text+=';999'
    elif fault=='missing_mean':c['mean_rating']={'value':None,'evidence':None}
    elif fault=='wrong_name':c['carrier_name']={'value':'Other Carrier','evidence':'Other Carrier'};text+=';Other Carrier'
    else:
        url={'foreign':'https://foreign.test/carriers/carrier-01','home':'https://parcels.test/',
             'filtered_stars':'https://parcels.test/carriers/carrier-01?stars=5',
             'narrow_class':'https://parcels.test/carriers/carrier-01?shipping_class=bulky',
             'wrong_date':'https://parcels.test/carriers/carrier-01?date_from=2026-08-01',
             'duplicate_query':'https://parcels.test/carriers/carrier-01?page=1&page=2'}[fault]
        c['review_url']={'value':url,'evidence':url};text+=';'+url
    assert not grader(args).grade(c,text)['structured_claims_correct']


def test_changed_reference_or_publication_fails_before_grading():
    args=list(fixture());args[2]['counts']['positive']+=1
    with pytest.raises(ValueError,match='binding changed'):grader(args)
    args=list(fixture());args[3]['profiles'][0]['carrier']['name']='Alias'
    with pytest.raises(ValueError,match='binding changed'):grader(args)


def test_export_retains_all_carriers_classes_silent_rows_and_no_private_history():
    w,_,_,p,_,_=fixture()
    assert len(p['profiles'][0]['reviews'])==7
    assert p['profiles'][0]['reviews']==w['carrier_evidence']['public']['reviews']
    assert all(not {'statements','shipment_id','hidden_success'} & set(r) for r in p['profiles'][0]['reviews'])
    before=deepcopy(w);api.public_projection(w);assert w==before


@pytest.mark.parametrize('patch',[{'shipping_class':'home'},{'destination_type':'home'},{'operation':'hidden_success'},
    {'carrier_index':True},{'date_from':'2026-02-30'},{'date_from':'2026-09-01','date_to':'2026-08-01'},
    {'aspect':'latent_reliability'},{'min_assessed':0}])
def test_invalid_notation_rejects_before_world_factory(patch):
    request={'schema':'website-world-generation-v2','seed':85,'world':{'concept_ids':['footwear.walking_shoes']},
        'task':{'kind':api.KIND,'operation':'topic_counts','aspect':'punctuality',**patch}}
    calls=[]
    with pytest.raises(ValueError):generation.generate(request,world_factory=lambda *a,**kw:calls.append(1))
    assert calls==[]


def test_existing_public_summary_does_not_replace_raw_scope_counts():
    w,t,r,_,_,i=fixture('rating_summary')
    w['carrier_evidence']['public']['carriers'][0]['summary']={'average_stars':1,'rating_count':999}
    t=api.make(w,{k:t[k] for k in ('kind','operation','shipping_class')},inventory=i)
    assert api.reference(w,t,inventory=i)['summary']==r['summary']
