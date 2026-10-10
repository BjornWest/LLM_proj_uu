"""Isolated executable authoring pilot; not a live-world or grading adapter."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
from .review_topic_sampling import resolve_topic_config, topic_policy
from .review_population import resolve_review_site, effective_review_lengths, summarize_ratings
from .review_rating_sampling import sample_rating, validate_concentration
from .footwear_retail_content import load_recipe, render_retail_content, bind_page_content, authoring_packet
from .concept_registry import ConceptRegistry
from .brand_sampling import validate_brand_scopes, sample_scoped_brand
from .product_naming import validate_product_names, sample_product_name
from .footwear_sizing import sample_variant_grid, reviewer_size_fit, product_review_overview, brand_review_overview, retailer_fit_notice

DATA=Path(__file__).with_name('data')/'footwear_context_pilot'
VERSION='footwear-context-pilot-v1'

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def stream(seed,key):
    return random.Random(int.from_bytes(hashlib.sha256(f'{VERSION}/{seed}/{key}'.encode()).digest(),'big'))

def load_spec():
    spec=json.loads((DATA/'spec.json').read_text())
    validate_spec(spec)
    spec['topic_selection']=resolve_topic_config(spec['topic_selection'])
    spec['review_site']=resolve_review_site(spec['review_site'])
    return spec

def validate_spec(spec):
    if spec.get('schema_version')!='footwear-context-pilot-spec-v1':raise ValueError('Unsupported pilot spec')
    def weights(w):
        if not w or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in w.values()) or sum(w.values())<=0:
            raise ValueError('Weights must be finite nonnegative numbers with positive mass')
    validate_brand_scopes(spec['brand_sampling'])
    validate_product_names(spec['product_names'])
    scope=spec['brand_sampling']['scopes']['footwear']
    if set(scope['concepts'])!=set(spec['concepts']):raise ValueError('Pilot brand scope must cover pilot concepts')
    for axis in ('positioning','emphasis'):
        if any(set(w)!=set(spec[axis+'_multipliers']) for w in scope[axis+'_profiles'].values()):raise ValueError('Unknown brand positioning/emphasis')
    for key in ['construction_weights','tread_weights','review_length_weights','colour_count_weights']:weights(spec[key])
    if not spec['colours'] or len(spec['colours'])!=len(set(spec['colours'])):raise ValueError('Invalid colour palette')
    if set(spec['colour_count_weights'])-{'1','2','3','4'}:raise ValueError('Unsupported colour count')
    for k in ['size_range_weights','extra_width_colour_weights','variant_size_weights','brand_fit_weights']:weights(spec[k])
    if set(spec['size_range_weights'])!=set(spec['size_ranges']):raise ValueError('Size range weights must match ranges')
    for sizes in spec['size_ranges'].values():
        if not sizes or sizes!=list(range(sizes[0],sizes[-1]+1)) or not set(sizes)<=set(spec['sizes_eu']):raise ValueError('Size ranges must be nonempty contiguous supported sizes')
    if set(spec['extra_width_colour_weights'])!={'all','subset'} or set(spec['variant_size_weights'])!={'full','subrange','alternating'}:raise ValueError('Invalid variant grid modes')
    if set(spec['brand_fit_weights'])!={'true_to_size','runs_small','runs_large'} or set(spec['brand_fit_offsets_eu'])!=set(spec['brand_fit_weights']):raise ValueError('Invalid brand fit settings')
    offsets=spec['brand_fit_offsets_eu']
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in offsets.values()) or not offsets['runs_small']<offsets['true_to_size']==0<offsets['runs_large']:raise ValueError('Invalid brand fit offsets')
    width_sets=spec['width_sets']
    if not width_sets or any(not values or len(values)!=len(set(values)) or 'standard' not in values or set(values)-{'standard','narrow','wide'} for values in width_sets.values()):
        raise ValueError('Width sets must contain regular width and unique valid widths')
    if len({tuple(sorted(v)) for v in width_sets.values()})!=len(width_sets):raise ValueError('Duplicate width sets')
    if set(spec['construction_weights'])!=set(spec['construction_packages']):raise ValueError('Construction package mismatch')
    domains={'construction':set(spec['construction_weights']),'tread':set(spec['tread_weights']),'material':set()}
    for concept in spec['concepts'].values():
        for k in ['material_weights','fastening_weights','width_set_weights','colour_weights']:weights(concept[k])
        if set(concept['colour_weights'])!=set(spec['colours']):raise ValueError('Colour weights must match palette')
        if max(int(k) for k,v in spec['colour_count_weights'].items() if v>0)>sum(v>0 for v in concept['colour_weights'].values()):raise ValueError('Not enough eligible colours')
        domains['material'].update(concept['material_weights'])
        if set(concept['width_set_weights'])!=set(width_sets):raise ValueError('Width set weights must match defined sets')
        for lo,hi in concept['price_ranges_sek'].values():
            if lo<=0 or hi<lo:raise ValueError('Invalid price range')
    for container in ['emphasis_multipliers','positioning_multipliers']:
        for row in spec[container].values():
            for field,w in row.items():
                if field not in domains or set(w)-domains[field]:raise ValueError('Unknown multiplier field/value')
                weights(w)
    for k in ['retailer_carry_probability','stockout_probability','fit_notice_probability']:
        if not 0<=spec[k]<=1:raise ValueError('Probability outside [0,1]')
    length_weights=effective_review_lengths(spec['review_length_weights'],spec['review_site'])
    topic=resolve_topic_config(spec['topic_selection'])
    known_topics=set(json.loads((DATA/'statements.json').read_text())['aspects'])
    if set(topic['base_weights'])-known_topics:raise ValueError('Unknown review topic')
    rules=spec['review_topic_rules'];rule_ids=[r['id'] for r in rules]
    if len(rule_ids)!=len(set(rule_ids)):raise ValueError('Duplicate review topic rule')
    for rule in rules:
        if rule['emphasis'] not in spec['emphasis_multipliers']:raise ValueError('Unknown rule emphasis')
        for field,allowed in rule['when'].items():
            if field not in {'cushioning','sole_structure'} or not allowed:raise ValueError('Unsupported review topic condition')
            domain={p[field] for p in spec['construction_packages'].values()}
            if not set(allowed)<=domain:raise ValueError('Unknown review topic condition value')
        if set(rule['multipliers'])-known_topics or 'value' in rule['multipliers']:raise ValueError('Rules must reference known non-value topics')
        weights(rule['multipliers'])
        if any(v<=0 for v in rule['multipliers'].values()):raise ValueError('Review topic multipliers must be positive')
    topic_policy(positioning='budget',execution=0,eligible=known_topics-{'footbed_heat'},
                 length_weights=length_weights,config=topic)
    lo,hi=spec['execution_range']
    if not 0<=lo<=hi<=1:raise ValueError('Invalid execution range')
    validate_concentration(spec['rating_concentration'])
    for field in ('reviewer_spread',):
        value=spec[field]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
            raise ValueError('Reviewer spreads must be finite nonnegative numbers')

def weighted_options(base, modifiers=()):
    effective={value:weight*math.prod(m.get(value,1) for m in modifiers) for value,weight in base.items()}
    total=sum(effective.values())
    if total<=0:raise ValueError('No eligible choices')
    return effective,{k:v/total for k,v in effective.items()}

def choose(seed,key,base,*,modifiers=(),trace=None):
    effective,probabilities=weighted_options(base,modifiers)
    value=stream(seed,key).choices(list(effective),weights=list(effective.values()))[0]
    if trace is not None:trace.append({'field':key.rsplit('/',1)[-1],'selected':value,'base_weights':base,'multipliers':list(modifiers),'probabilities':probabilities})
    return value

def sample_brand(seed,slot,spec,*,existing=None):
    if not isinstance(slot,int) or isinstance(slot,bool) or slot<0:raise ValueError('Invalid brand slot')
    if existing is None:
        existing=[]
        for i in range(slot):existing.append(sample_brand(seed,i,spec,existing=existing))
    brand=sample_scoped_brand(spec['brand_sampling'],scope_id='footwear',brand_id=f'brand-{slot+1}',
                              existing=existing,rng_for=lambda field:stream(seed,f'brand/{slot}/{field}'))
    brand['fit_tendency']=choose(seed,f'brand/{slot}/fit',spec['brand_fit_weights'])
    return brand

def sample_profile(seed,concept,brand,*,spec=None,overrides=None):
    spec=load_spec() if spec is None else spec;validate_spec(spec)
    if concept not in spec['concepts']:raise ValueError('Unsupported concept')
    if concept not in brand['eligible_concepts']:raise ValueError('Concept outside brand scope')
    overrides={} if overrides is None else dict(overrides)
    if set(overrides)-{'positioning','emphasis','execution'}:raise ValueError('Unknown pilot override')
    key=f'product/{concept}';trace=[]
    position=choose(seed,key+'/positioning',brand['positioning_weights'],trace=trace)
    emphasis=choose(seed,key+'/emphasis',brand['emphasis_weights'],trace=trace)
    position=overrides.get('positioning',position);emphasis=overrides.get('emphasis',emphasis)
    if position not in spec['positioning_multipliers'] or emphasis not in spec['emphasis_multipliers']:raise ValueError('Invalid positioning/emphasis')
    execution=overrides.get('execution',stream(seed,key+'/execution').uniform(*spec['execution_range']))
    if not isinstance(execution,(int,float)) or not math.isfinite(execution) or not 0<=execution<=1:raise ValueError('Invalid execution')
    for record in trace:
        if record['field'] in overrides:record['sampled_before_override']=record['selected'];record['selected']=overrides[record['field']];record['overridden']=True
    return {'positioning':position,'emphasis':emphasis,'execution':execution,'trace':trace,'overrides':overrides}

def sample_product(seed,concept,brand,*,spec=None,overrides=None,existing_products=()):
    spec=load_spec() if spec is None else spec
    profile=sample_profile(seed,concept,brand,spec=spec,overrides=overrides)
    position=profile['positioning'];emphasis=profile['emphasis'];execution=profile['execution'];trace=profile['trace']
    cfg=spec['concepts'][concept];mid=f'pilot-{concept}';key=f'product/{concept}'
    em=spec['emphasis_multipliers'][emphasis];pm=spec['positioning_multipliers'][position]
    def pick(field,base):return choose(seed,key+'/'+field,base,modifiers=[em.get(field,{}),pm.get(field,{})],trace=trace)
    package=pick('construction',spec['construction_weights']);material=pick('material',cfg['material_weights'])
    facts={**deepcopy(cfg['fixed']),**deepcopy(spec['construction_packages'][package]),'component_materials':{cfg['component']:material,'outsole':'rubber'},
           'fastening':pick('fastening',cfg['fastening_weights']),'sole_tread':pick('tread',spec['tread_weights']),
           'reference_mass_g':cfg['base_mass_g_per_shoe_eu40'][package]+stream(seed,key+'/mass').randint(-15,15),
           'mass_basis':'one item, EU 40 reference configuration','waterproof_rating':'not specified'}
    if concept=='walking_sandals':facts['toe_coverage']='open' # Bounded pilot subset; closed-toe remains eligible in the broader concept.
    width_set=choose(seed,key+'/width_set',cfg['width_set_weights'],trace=trace)
    widths=spec['width_sets'][width_set]
    colour_count=int(choose(seed,key+'/colour_count',spec['colour_count_weights'],trace=trace))
    colours=[]
    for i in range(colour_count):
        colours.append(choose(seed,key+f'/colour_{i}',{c:w for c,w in cfg['colour_weights'].items() if c not in colours},trace=trace))
    skus,variant_plan=sample_variant_grid(mid,widths,colours,spec,cfg['colour_weights'],lambda suffix:stream(seed,key+'/'+suffix))
    lo,hi=cfg['price_ranges_sek'][position];price=round(stream(seed,key+'/price').uniform(lo,hi)/10)*10
    model_name,name_trace=sample_product_name(spec['product_names'],brand_id=brand['brand_id'],
                                             existing_products=existing_products,rng=stream(seed,key+'/name'))
    name=brand['name']+' '+model_name
    public={'product_id':mid,'family_id':'footwear','concept_id':cfg['registry_id'],'concept':concept,'name':name,'model_name':model_name,'brand_id':brand['brand_id'],'facts':facts,'reference_price_sek':price,'skus':skus}
    private={**profile,'construction_package':package,'variant_plan':variant_plan,'fit_tendency':brand['fit_tendency'],'name_sampling':name_trace}
    return {'public':public,'private':private}

def describe(product, *, seed=0):
    return render_retail_content(product['public'],seed=seed)['description']

def compose_review(seed,key,statements,*,previous_connector=None):
    """Vary presentation independently of sampled meanings, phrases and rating.

    Keep original atomic statements unchanged and map each surface segment back to
    its evidence index. At most one explicit contrast per review avoids repeated
    'but ... however ... though' scaffolding in longer comments.
    """
    order=list(range(len(statements)))
    stream(seed,key+'/presentation/order').shuffle(order)
    boundaries=[i for i in range(1,len(order))
                if statements[order[i-1]]['polarity']!=statements[order[i]]['polarity']]
    weights={'plain':3,'but':3,'however':1,'though':3}
    if previous_connector in {'but','however','though'}:weights[previous_connector]=0
    style=choose(seed,key+'/presentation/style',weights) if boundaries else 'plain'
    contrast=stream(seed,key+'/presentation/boundary').choice(boundaries) if boundaries and style!='plain' else None
    segments=[]
    for position,index in enumerate(order):
        atom=statements[index]['text'];connector=style if position==contrast else 'plain'
        if connector in {'but','however'}:
            # Preserve pronouns and leading acronyms such as EU in sizing remarks.
            preserve=atom.startswith(('I ',"I'",'I\u2019')) or atom.split()[0].isupper()
            continuation=atom if preserve else atom[:1].lower()+atom[1:]
            text=('But ' if connector=='but' else 'However, ')+continuation
        elif connector=='though':
            text=atom.rstrip('.!?')+', though.'
        else:text=atom
        segments.append({'statement_index':index,'connector':connector,'text':text})
    return {'schema_version':'review-composition-v1','text':' '.join(s['text'] for s in segments),'segments':segments}


def review_topic_policy(product,spec,eligible):
    """Adapt pilot product fields to the family-independent topic policy."""
    private=product['private']
    facts=product.get('public',{}).get('facts',{});modifiers={};applied=[]
    for rule in spec['review_topic_rules']:
        if private.get('emphasis')!=rule['emphasis'] or not all(facts.get(field) in values for field,values in rule['when'].items()):continue
        applied.append(rule['id'])
        for topic,factor in rule['multipliers'].items():
            if topic in eligible:modifiers[topic]=modifiers.get(topic,1)*factor
    result=topic_policy(positioning=private['positioning'],execution=private['execution'],
                        eligible=eligible,length_weights=effective_review_lengths(spec['review_length_weights'],spec['review_site']),config=spec['topic_selection'],topic_multipliers=modifiers)
    result['applied_rules']=applied
    return result


def select_review_topics(seed,key,length,policy):
    if length==0:return []
    weights=policy.get('effective_weights',policy['base_weights']);others={a:w for a,w in weights.items() if a!='value'}
    # The pilot requires enough alternatives to preserve its anchored probability.
    if length>len(others):raise ValueError('Not enough non-value topics for the requested comment length')
    include='value' in weights and stream(seed,key+'/topics/value').random()<policy['value_probability_given_comment']
    selected=['value'] if include else []
    for slot in range(length-len(selected)):
        aspect=choose(seed,key+f'/topics/other/{slot}',others)
        selected.append(aspect);del others[aspect]
    return selected


def sample_reviews(seed,product,*,spec=None,count=None):
    spec=load_spec() if spec is None else spec
    site=resolve_review_site(spec['review_site'])
    count=site['ratings_per_product'] if count is None else count
    lengths=effective_review_lengths(spec['review_length_weights'],site)
    bank=json.loads((DATA/'statements.json').read_text());p=product['public'];private=product['private'];concept=p['concept'];used=Counter();reviews=[];previous_connector=None
    eligible={k:v for k,v in bank['aspects'].items() if concept in v.get('concepts',[concept])}
    topic_policy=review_topic_policy(product,spec,eligible)
    for i in range(count):
        key=f'reviews/{concept}/{i}';sku=stream(seed,key+'/sku').choice(p['skus']);assessments={}
        overall=sample_rating(stream(seed,key+'/rating'),private['execution'],spec['rating_concentration'])
        sizing=reviewer_size_fit(sku,private['fit_tendency'],spec,lambda suffix:stream(seed,key+'/'+suffix))
        # Conditional details keep the exact star distribution while allowing
        # mixed experiences, product effects, personal fit and value judgments.
        for aspect in eligible:
            if aspect=='size_fit':
                score=1.0 if sizing['fit_result']=='fits' else 0.0
                assessments[aspect]={'favourability':score,'polarity':'positive' if score else 'negative','fit_result':sizing['fit_result']}
                continue
            center=(overall['rating']-1)/4
            if aspect=='walking_comfort' and p['facts']['cushioning']=='substantial':center+=spec['execution_to_review']['comfort_match_bonus']
            if aspect=='forefoot_room':
                wearer=stream(seed,key+'/wearer_width').choice(['narrow','standard','wide']);order=['narrow','standard','wide'];center+=0.08*(order.index(sku['width'])-order.index(wearer))
            if aspect=='value':
                ranges=spec['concepts'][concept]['price_ranges_sek'];lo=min(v[0] for v in ranges.values());hi=max(v[1] for v in ranges.values());center-=spec['execution_to_review']['value_price_penalty']*((p['reference_price_sek']-lo)/(hi-lo)-.5)
            score=max(0,min(1,stream(seed,key+'/'+aspect).gauss(center,spec['reviewer_spread'])))
            assessments[aspect]={'favourability':score,'polarity':'positive' if score>=.5 else 'negative'}
        length=int(choose(seed,key+'/length',lengths))
        chosen=select_review_topics(seed,key,length,topic_policy);statements=[]
        for aspect in chosen:
            polarity=assessments[aspect]['polarity'];stance=sizing['fit_result'] if aspect=='size_fit' else polarity
            variants=eligible[aspect][stance];minimum=min(used[(aspect,stance,j)] for j in range(len(variants)))
            j=stream(seed,key+'/'+aspect+'/phrase').choice([j for j in range(len(variants)) if used[(aspect,stance,j)]==minimum]);used[(aspect,stance,j)]+=1
            text=variants[j].format(heel_contact='back of the shoe' if concept=='walking_shoes' else 'heel strap',usual_size=sizing['usual_size_eu'],purchased_size=sizing['purchased_size_eu'])
            context=deepcopy(eligible[aspect]['context'])
            if aspect=='forefoot_room':context['wearer_width']=wearer
            if aspect=='value':context['purchase_price_sek']=p['reference_price_sek']
            if aspect=='size_fit':context.update({k:v for k,v in sizing.items() if not k.startswith('private_')})
            statements.append({'meaning':aspect,'polarity':polarity,'context':context,'sku_id':sku['sku_id'],'text':text,'realization_id':f'{aspect}/{stance}/{j}'})
        rating=overall['rating']
        presentation=compose_review(seed,key,statements,previous_connector=previous_connector)
        previous_connector=next((s['connector'] for s in presentation['segments'] if s['connector']!='plain'),previous_connector)
        reviews.append({'review_id':f"{p['product_id']}-review-{i+1}",'reviewer':f'Customer {i+1}','product_id':p['product_id'],'sku_id':sku['sku_id'],'rating':rating,'text':presentation['text'],
          'presentation':presentation,'evidence':{'statements':statements},'private':{'overall_experience':overall,'underlying_assessments':assessments,'purchase_price_sek':p['reference_price_sek'],'length':length,'topic_selection':deepcopy(topic_policy)}})
    return reviews

def group_pages(product,listings,policy):
    """Partition carried SKUs, including zero stock, without requiring common sizes."""
    if set(policy)!={'colour','width','size_eu'} or any(v not in {'selector','page_partition'} for v in policy.values()):raise ValueError('Invalid grouping policy')
    if product['concept']=='walking_sandals' and policy['width']!='page_partition':raise ValueError('Sandal width uses separate pages in this pilot')
    skus={s['sku_id']:s for s in product['skus']};groups=defaultdict(list)
    for listing in listings:
        if listing['sku_id'] not in skus:raise ValueError('Listing references unknown SKU')
        s=skus[listing['sku_id']];partition=tuple((k,s[k]) for k,v in sorted(policy.items()) if v=='page_partition');groups[partition].append({**s,'stock':listing['stock']})
    return [{'page_key':dict(k),'selectors':{d:sorted({s[d] for s in rows}) for d,mode in policy.items() if mode=='selector'},'listings':rows,'sold_out':all(s['stock']==0 for s in rows)} for k,rows in sorted(groups.items())]

def sample_pilot(seed=0,*,spec=None,overrides=None):
    spec=load_spec() if spec is None else deepcopy(spec);validate_spec(spec)
    spec['topic_selection']=resolve_topic_config(spec['topic_selection'])
    spec['review_site']=resolve_review_site(spec['review_site'])
    recipe=load_recipe()
    brands=[];products=[]
    for i in range(2):brands.append(sample_brand(seed,i,spec,existing=brands))
    for i,concept in enumerate(spec['concepts']):
        product=sample_product(seed,concept,brands[i],spec=spec,overrides=(overrides or {}).get(concept),
                               existing_products=[p['public'] for p in products])
        product['retail_content']=render_retail_content(product['public'],seed=seed,recipe=recipe)
        product['description']=product['retail_content']['description'];product['reviews']=sample_reviews(seed,product,spec=spec)
        product['review_overview']=product_review_overview(product)
        product['rating_summary']=summarize_ratings(product['reviews']);products.append(product)
    retailers=[]
    for i in range(2):
        rid=f'pilot-retailer-{i+1}';policy={'colour':choose(seed,rid+'/colour',{'selector':1,'page_partition':1}),'shoe_width':choose(seed,rid+'/width',{'selector':1,'page_partition':1})};catalog=[]
        for product in products:
            p=product['public'];skus=p['skus'];anchor=stream(seed,rid+'/'+p['product_id']+'/anchor').choice(skus)['sku_id'];listed=[]
            for s in skus:
                key=rid+'/'+s['sku_id']
                if s['sku_id']==anchor or stream(seed,key+'/carry').random()<spec['retailer_carry_probability']:
                    stock=0 if stream(seed,key+'/stock').random()<spec['stockout_probability'] else stream(seed,key+'/quantity').randint(1,12);listed.append({'sku_id':s['sku_id'],'stock':stock})
            resolved={'colour':policy['colour'],'width':policy['shoe_width'] if p['concept']=='walking_shoes' else 'page_partition','size_eu':'selector'}
            pages=group_pages(p,listed,resolved)
            notice=retailer_fit_notice(product['private']['fit_tendency'],spec['fit_notice_probability'],stream(seed,rid+'/'+p['product_id']+'/fit_notice'))
            for page in pages:
                page['retail_content']=bind_page_content(product['retail_content'],page,resolved)
                page['retail_content']['fit_notice']=deepcopy(notice)
            catalog.append({'product_id':p['product_id'],'policy':resolved,'pages':pages,'fit_notice':notice})
        retailers.append({'retailer_id':rid,'name':['Everyday Footwear','Walking Room'][i],'policy':policy,'catalog':catalog})
    statements=json.loads((DATA/'statements.json').read_text())
    packet=authoring_packet(spec,ConceptRegistry.load(),recipe=recipe)
    packet['review_statement_bank']=statements
    return {'schema_version':VERSION,'seed':seed,'status':'isolated_authoring_pilot_not_live_world','spec_sha256':digest(spec),'statements_sha256':digest(statements),
      'retail_recipe_sha256':digest(recipe),'authoring_packet':packet,
      'brands':brands,'brand_overviews':[brand_review_overview(b,products) for b in brands],
      'products':products,'retailers':retailers,'spec':spec}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--seed',type=int,default=0);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(sample_pilot(args.seed),ensure_ascii=False,indent=2)+'\n');print(args.output)

if __name__=='__main__':main()
