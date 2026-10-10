"""Finite literal T-shirt checks; genuine original20 captured separately once."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy as D
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import importlib.util,itertools,json,os
import pytest
from environments.product_world.product_package import ProductPackage,PackageError
from environments.product_world.product_expressions import ExpressionError

CID='tops.t_shirts';A=Path('.local/product-width/annotations')/CID;W=Path('environments/product_world/data/product_width')
GFILE=Path('.local/product-width/reviews/checks/t-shirts-independent-gold-v2.json')
assert sha256(GFILE.read_bytes()).hexdigest()=='4d82410cf210027da2a949a04254e6859f2676002b59e8de336fca16c372ffe9'
G=json.loads(GFILE.read_text());P=json.loads((A/'language-plan-v2.json').read_text());N=json.loads((A/'all-native-public-assertions-v2.json').read_text());F=json.loads((A/'finite-expectations-v1.json').read_text())
sp=importlib.util.spec_from_file_location('tshirts_actual_checks',A/'context_caller_v2.py');c=importlib.util.module_from_spec(sp);sp.loader.exec_module(c)
ERRORS=(PackageError,ExpressionError);TOPICS=P['sampling']['all_aspects']
def original():return json.loads((W/(CID+'.inputs.json')).read_text())
def reorder(x):return {k:reorder(x[k])for k in reversed(list(x))}if isinstance(x,dict)else[reorder(v)for v in x]if isinstance(x,list)else x
def save(name,data):
    out=Path(os.environ.get('TSHIRT_EVIDENCE_DIR',str(A/'checks-v1')));out.mkdir(parents=True,exist_ok=True)
    with(out/(name+'.json')).open('x')as f:json.dump({'status':'held_author_finite_evidence_pending_independent_Root','root_gold':{'path':str(GFILE),'sha256':sha256(GFILE.read_bytes()).hexdigest()},'caller_sha256':sha256((A/'context_caller_v2.py').read_bytes()).hexdigest(),'checker_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'new_world_draws':0,'controlled_primitive_rng_calls':0,**data},f,indent=2,ensure_ascii=False);f.write('\n')
def draw(state):
    def controlled(params,seed,stream,e):
        target=params['target'];method=params['sample'];key=None
        if target=='internal.recipe_ticket':value=0.0 if state['recipe']=='regular_cotton_crew' else 1.0
        elif method=='weighted_choice':
            key={'profile.positioning':state['position'],'product.facts.market_range':state['range'],'internal.size_menu':state['menu'],'internal.colour_set':state['palette'],'internal.pack_menu':state['packs']}.get(target)
            if key is None:key=next(k for k,w in params['effective_weights'].items()if w>0)
            assert params['effective_weights'][key]>0
            value=D(params.get('values',{}).get(key,key))
        elif target=='profile.execution':value=state.get('execution',.5)
        elif target=='internal.current_anchor_sek':value=state['anchor']
        elif target=='review.subject':value=D(next(r for r in params['resolved_values']if r['colour']==state.get('colour','navy')and r['size_label']==state.get('label','M')and r['pack_count']==state.get('count',1)))
        elif target=='review.rating':value=3
        elif target=='review.topics':value=D(state.get('topics',[]))
        elif target=='review.value_favourability':value=.6
        else:raise AssertionError('uncovered literal primitive '+target)
        return value,{'method':'controlled_literal_no_rng','declared_method':method,'stream':stream,'outcome':D(value),'option':key}
    return controlled
def fixture(recipe='regular_cotton_crew',rng='women',menu='full',palette='both',packs='both',position='mainstream',anchor=240,authority=None):
    a=D(authority or original());p=c.make_package(authoritative_inputs=a);state={'recipe':recipe,'range':rng,'menu':menu,'palette':palette,'packs':packs,'position':position,'anchor':anchor}
    p.draw=draw(state);p.rng=lambda *x:(_ for _ in()).throw(AssertionError('finite RNG reached'))
    result=p.sample(0,inputs=D(a));return p,result,a,state
def owner(p,e,state):
    r=p.make_review();r.draw=draw(state);r.rng=lambda *x:(_ for _ in()).throw(AssertionError('finite owner RNG reached'))
    return r,r.sample(0,inputs=D(e))
def cat(e,row):x=D(e);x['sku']=D(row);return x

def test_complete_108_manufactures_72_source_rows_grouping_and_unknowns():
    def one(row):
        p,s,a,st=fixture(row['recipe_id'],row['market_range'],row['size_menu_id'],row['colour_set_id'],row['pack_menu_id']);e=s['entities']
        assert len(e['product']['skus'])==row['SKU_count']
        assert e['product']['size_labels']==row['size_labels']and e['product']['colours']==row['colours']and e['product']['pack_counts']==row['pack_counts']
        for sku in e['product']['skus']:
            assert list(sku)==P['actual_SKU_keys']and type(sku['pack_count'])is int
            assert c.equal(sku['facts'],{**G['common_facts'],**G['source_recipes'][row['recipe_id']]['facts'],'recipe_id':row['recipe_id'],'market_range':row['market_range']})
            assert sku['first_shirt_id']==sku['sku_id']+'-shirt-1'
            assert sku['nominal_chart_back_length_cm']==G['source_recipes'][row['recipe_id']]['nominal_chart_back_length_cm'][sku['size_label']]
        cctx=cat(e,e['product']['skus'][0]);assert p.completed_boundary.eval('True',reorder(cctx))is True
        assert s['field_status']['product.facts.lining_material']=='not_applicable'
        assert s['field_status']['product.facts.whole_garment_cotton_percent']=='unknown'
        assert s['field_status']['product.facts.nominal_main_fabric_areal_mass_g_m2']==('known'if row['recipe_id']=='regular_cotton_crew'else'unknown')
        for path in ['product.facts.lining_material','sku.actual_back_length_cm','sku.facts.whole_garment_cotton_percent']:
            with pytest.raises(ERRORS):p.completed_boundary.eval(path,cctx)
        policies=[];listings=[{'sku_id':x['sku_id'],'stock':int(i!=0)}for i,x in enumerate(e['product']['skus'])]
        for modes in itertools.product(['selector','separate_page'],repeat=3):
            policy=dict(zip(['colour','size_label','pack_count'],modes));groups=p.group_listings(e,listings,policy)
            assert sum(len(g['listings'])for g in groups)==len(listings);policies.append(policy)
        assert len([t for t in s['trace']if t.get('target')=='product.facts.market_range'])==1
        return {'state':row,'actual_full_compiled_skus':e['product']['skus'],'market_authority':e['private']['market_stage'],'eight_grouping_policies':policies,'logical_status':s['typed_status_projection']}
    with ThreadPoolExecutor(max_workers=2)as pool:rows=list(pool.map(one,G['complete_manufactures']))
    assert len(rows)==108 and len(G['canonical_prototypes'])==72
    save('manufactures',{'complete_manufactures':108,'canonical_prototypes':72,'records':rows,'concurrency':2})

def test_196_decimal_grid_24_endpoints_exact_pack_current_value():
    def one(row):
        p,s,a,st=fixture(row['recipe_id'],position=row['positioning'],anchor=row['anchor_sek']);st['count']=row['pack_count'];r,o=owner(p,s['entities'],st);rv=o['entities']['review']
        for key,source in [('purchase_price_sek','whole_purchase_reference_paid_sek'),('price_min_sek','selected_global_min_sek'),('price_max_sek','selected_global_max_sek')]:assert Decimal(str(rv[key]))==Decimal(row[source])
        assert rv['value_price_position']==row['relative_numerator']/400
        return {'source':row,'owner_money':{k:rv[k]for k in ['purchase_price_sek','price_min_sek','price_max_sek','value_price_position']}}
    with ThreadPoolExecutor(max_workers=2)as pool:rows=list(pool.map(one,F['price_grid']))
    with ThreadPoolExecutor(max_workers=2)as pool:endpoints=list(pool.map(one,G['Decimal_endpoints']))
    assert len(rows)==196 and len(endpoints)==24
    save('prices',{'grid':rows,'compiled_endpoints':endpoints})

def test_all_3744_native_words_13320_singleton_bindings_actual_contexts():
    records=[];binding_count=0;expected={}
    for r in N['forms']:expected.setdefault(r['context_id'],[]).append(r)
    for rid,rng in itertools.product(G['source_recipes'],['women','men','unisex']):
        a=original();a['product']['product_id']='tshirt-prose-'+rid+'-'+rng
        p,s,a,st=fixture(rid,rng,authority=a);reviewer=p.make_review();reviewer.draw=draw(st);reviewer.rng=lambda *x:(_ for _ in()).throw(AssertionError('native fixture RNG reached'))
        for sku in s['entities']['product']['skus']:
            st.update(colour=sku['colour'],label=sku['size_label'],count=sku['pack_count']);o=reviewer.sample(0,inputs=D(s['entities']))
            for want in expected[sku['sku_id']]:
                pid,i=want['pool_id'],want['formulation_index'];isowner=want['prepared_literal_review_state']is not None
                if isowner:
                    e=D(o['entities']);e['review']=D(want['prepared_literal_review_state']);e['sku']=D(e['review']['subject']);b=reviewer.completed_boundary
                else:e=cat(s['entities'],sku);b=p.completed_boundary
                actual=b.formulate_index(pid,i,e);assert actual['text']==want['text']and c.equal(actual['meaning'],want['exact_planned_meaning'])
                public=b.resolve_assertions(pid,i,e);assert c.equal(public['resolved_assertions'],want['resolved_assertions'])
                binding_count+=len(public['resolved_assertions']);records.append({'context_id':sku['sku_id'],'pool_id':pid,'formulation_index':i,'text':actual['text'],'meaning':actual['meaning'],'resolved_assertions':public['resolved_assertions']})
    assert len(records)==3744 and binding_count==13320
    save('native-public',{'native_texts':3744,'public_bindings':13320,'source_templates':54,'records':records})

def test_history_polarity_soft_weights_and_silence_policy():
    assert P['sampling']['topic_count_weights']=={'0':24,'1':4,'2':3,'3':1}
    assert P['sampling']['rating_concentration']==1.5 and P['sampling']['value_sd']==.22
    assert len(G['compatible_owner_histories'])==1152
    for row in G['compatible_owner_histories']:
        assert row['polarities']['value']is(row['value_favourability']>=.5)
        assert row['history']['another_pack_unit_used_or_washed']is False
    probabilities=[]
    for position,e in itertools.product(G['price_bands'],[.05,.5,.95]):
        weights={rid:P['sampling']['recipe_position_weights'][position][rid]*(1.15-.3*e if rid=='regular_cotton_crew'else .85+.3*e)for rid in G['source_recipes']}
        assert all(w>0 for w in weights.values());probs={k:w/sum(weights.values())for k,w in weights.items()}
        assert abs(sum(probs.values())-1)<1e-12;probabilities.append({'positioning':position,'execution':e,'weights':weights,'normalized_probabilities':probs})
    save('history-policy',{'histories':1152,'same_shirt_scope':True,'soft_weights':probabilities,'silent_probability':.75,'ticket_representation':'Existing uniform unit ticket compared to exactly normalized positive scalar weights, same two-choice probability policy.'})

def test_before_effects_complete_menu_carried_owner_price_and_actual_authority(monkeypatch):
    cases=[];underlying=[];base=ProductPackage.sample
    def spy(self,*args,**kwargs):underlying.append('sample');return base(self,*args,**kwargs)
    monkeypatch.setattr(ProductPackage,'sample',spy)
    for rid in G['source_recipes']:
        p,s,a,st=fixture(rid);r,o=owner(p,s['entities'],st);e=o['entities'];underlying.clear()
        corruptions=[]
        def add(name,mut):x=D(e);mut(x);corruptions.append((name,x))
        add('unused_row_price',lambda x:x['product']['skus'][-1].update(reference_price_sek=999))
        add('coherent_all_money_edit',lambda x:(x['internal'].update(current_anchor_sek=250),x['product'].update(reference_price_sek=x['product']['reference_price_sek']+10)))
        add('bool_pack_count',lambda x:x['review']['subject'].update(pack_count=True))
        add('unknown_became_measurement',lambda x:x['review']['subject'].update(actual_back_length_cm=70))
        add('empty_carried_owner',lambda x:x.update(review={}))
        add('carried_missing_history',lambda x:x['review'].pop('history'))
        add('silent_missing_paid',lambda x:(x['review'].update(topics=[]),x['review'].pop('purchase_price_sek')))
        add('wrong_tested_shirt',lambda x:x['review'].update(tested_shirt_id='foreign'))
        add('relative_alias',lambda x:x['review'].update(value_price_position=.99))
        add('wrong_history_pack_unit',lambda x:x['review']['history'].update(unused_shirt_count=1))
        add('bool_polarity',lambda x:x['review'].update(positive_value=1))
        add('foreign_source_recipe',lambda x:x['literal_recipe_rows'][-1]['facts'].update(neck_trim_cotton_percent=99))
        add('foreign_market_token',lambda x:x['private']['market_stage'].update(value='men'))
        for name,bad in corruptions:
            before=D(bad);effects=[]
            raw=r.completed_boundary._package._eval
            r.completed_boundary._package._eval=lambda *args,**kwargs:(effects.append('eval'),raw(*args,**kwargs))[1]
            try:
                for operation in [lambda:p.completed_boundary.eval('True',bad),lambda:r.completed_boundary.eval('True',bad),lambda:r.sample(0,inputs=bad),lambda:p.group_listings(bad,[],{'colour':'selector','size_label':'selector','pack_count':'selector'})]:
                    with pytest.raises(ERRORS):operation()
                assert not effects and not underlying and c.equal(before,bad)
            finally:r.completed_boundary._package._eval=raw
            cases.append({'recipe':rid,'case':name,'operations':4,'zero_effects':True})
        assert r.completed_boundary.eval('True',reorder(e))is True
        for path in ['review.subject.actual_back_length_cm','review.subject.facts.lining_material','review.subject.facts.whole_garment_cotton_percent']:
            with pytest.raises(ERRORS):r.completed_boundary.eval(path,e)
        parent=D(s['entities']);p.completed_boundary.eval('True',parent)
        raw_boundary=c.make_package(authoritative_inputs=original())
        for unsupported in [lambda:raw_boundary.draw({},0,'bad',parent),lambda:raw_boundary.rng(0,'bad'),lambda:raw_boundary.expression('True'),lambda:raw_boundary.programs['review'].sample(0,inputs=parent),lambda:r.group_listings(e,[],{})]:
            with pytest.raises(ERRORS):unsupported()
        with pytest.raises(ERRORS):p.group_listings(parent,[{'sku_id':parent['product']['skus'][0]['sku_id'],'stock':True}],{'colour':'selector','size_label':'selector','pack_count':'selector'})
        with pytest.raises(ERRORS):p.group_listings(parent,[],{'colour':'selector','size_label':'selector'})
    save('before-effects',{'cases':cases,'zero_effects':True,'raw_unsupported':True,'valid_reordering':True})

def test_model_once_owner_reusable_private_original_and_joint_preflight(monkeypatch):
    calls=[];base=ProductPackage.sample
    def spy(self,*args,**kwargs):calls.append(self.document['concept_id']);return base(self,*args,**kwargs)
    monkeypatch.setattr(ProductPackage,'sample',spy)
    a=original();a['brand']['positioning_weights']={'budget':0,'mainstream':0,'premium':1};p=c.make_package(authoritative_inputs=a)
    with pytest.raises(ERRORS):p.sample(0,inputs=D(a),overrides={'internal.current_anchor_sek':100})
    assert not calls
    st={'recipe':'regular_cotton_crew','range':'women','menu':'full','palette':'both','packs':'both','position':'premium','anchor':300};p.draw=draw(st)
    s=p.sample(0,inputs=D(a));assert len(calls)==1
    with pytest.raises(ERRORS):p.sample(0,inputs=D(a))
    assert len(calls)==1
    r=p.make_review();r.draw=draw(st);x=r.sample(0,inputs=D(s['entities']));y=r.sample(0,inputs=D(s['entities']))
    assert c.equal(x,y)and len(calls)==3
    a['brand']['name']='changed external copy';r.completed_boundary.eval('True',x['entities'])
    failed=c.make_package(authoritative_inputs=original());failed.draw=lambda *args:(_ for _ in()).throw(PackageError('injected underlying failure'))
    with pytest.raises(ERRORS):failed.sample(0,inputs=original())
    with pytest.raises(ERRORS):failed.sample(0,inputs=original())
    with pytest.raises(ERRORS):failed.make_review()
    assert len(calls)==4
    save('lifecycle',{'invalid_joint_preflight_sampler_calls':0,'model_once':True,'owners_reusable':True,'invoked_failure_consumes':True,'original_private_copy':True})
