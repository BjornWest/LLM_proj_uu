"""New exact-SKU opinion evidence, sampled before prose; legacy v1 is untouched."""
from datetime import date,timedelta

from .generate import digest,stream
from .data import field_info,pretty

VERSION='product-review-evidence-v2'
PUBLISHER='reader-panel-v2'
STANCES=('positive','negative','neutral','mixed')
# Each tuple states what positive/negative/neutral/mixed means publicly. Polarity
# describes the named claim, so positive heel_rubbing means a complaint is present.
ASPECTS={
 'comfort':{'families':['footwear'],'context':'long_walks','label':'comfort on long walks','statements':(
    'these shoes felt comfortable on long walks','these shoes felt uncomfortable on long walks',
    'the comfort on long walks was neither good nor bad','comfort on long walks varied: sometimes comfortable, sometimes uncomfortable')},
 'heel_rubbing':{'families':['footwear'],'context':'long_walks','label':'heel rubbing on long walks','statements':(
    'these shoes rubbed my heels on long walks','these shoes did not rub my heels on long walks',
    'I cannot say whether heel rubbing was a problem on long walks','they rubbed my heels on some long walks but not others')},
 'keyboard_comfort':{'families':['laptops'],'context':'typing','label':'keyboard comfort while typing','statements':(
    'typing on this keyboard felt comfortable','typing on this keyboard felt uncomfortable',
    'the keyboard felt neither comfortable nor uncomfortable','the keyboard was comfortable for some typing sessions and uncomfortable for others')},
 'fan_noise':{'families':['laptops'],'context':'typing','label':'bothersome fan noise while typing','statements':(
    'fan noise bothered me while typing','fan noise did not bother me while typing',
    'I have no clear view on the fan noise while typing','the fan noise bothered me during some typing sessions but not others')},
 'pet_acceptance':{'families':['dog_food','cat_food'],'context':'feeding','label':'pet acceptance at feeding time','statements':(
    'my pet readily ate this food','my pet refused this food','my pet showed no clear preference for or against this food',
    'my pet ate this food at some meals and refused it at others')},
 'pack_handling':{'families':['dog_food','cat_food'],'context':'feeding','label':'ease of handling the food pack','statements':(
    'this pack was easy to handle at feeding time','this pack was awkward to handle at feeding time',
    'handling this pack felt ordinary, neither easy nor awkward','this pack was easy to use for some meals and awkward for others')},
 'taste_enjoyment':{'families':['beer','wine'],'context':'tasting','label':'enjoyment of the taste','statements':(
    'I enjoyed the taste','I did not enjoy the taste','the taste left me indifferent','I enjoyed parts of the taste but disliked others')},
 'bitterness':{'families':['beer'],'context':'tasting','label':'noticeable bitterness','statements':(
    'it tasted bitter to me','it did not taste bitter to me','I cannot place its bitterness either way',
    'some sips tasted bitter to me and others did not')},
 'dryness':{'families':['wine'],'context':'tasting','label':'perceived dryness','statements':(
    'it tasted dry to me','it did not taste dry to me','I could not decide whether it tasted dry',
    'some sips seemed dry to me and others did not')},
}
PRIMARY={'footwear':'comfort','laptops':'keyboard_comfort','dog_food':'pet_acceptance',
         'cat_food':'pet_acceptance','beer':'taste_enjoyment','wine':'taste_enjoyment'}
CONTEXT_TEXT={'long_walks':'wearing these shoes on long walks','typing':'typing on this laptop',
              'feeding':'feeding this food to my pet','tasting':'tasting this drink'}


def catalog_hash(world):
    return digest({k:world['public'][k] for k in ('products','product_groups')})


def registry():
    return {key:{'families':v['families'],'context_id':v['context'],'label':v['label'],
        'stances':{s:v['statements'][i] for i,s in enumerate(STANCES)},'scale':'attributed_opinion',
        'protocol':None} for key,v in ASPECTS.items()}


def render_report(report,product):
    """Faithful compositional templates; opinions never follow from catalog facts."""
    if report.get('template_version')==5:
        from .profile_narratives import render_narrative
        return render_narrative(report,product)[0]
    if report.get('template_version')==4:
        from .evidence_drinks import render_drink
        return render_drink(report,product)[0]
    if report.get('template_version',1)==3:
        from .evidence_prose import render_natural
        return render_natural(report,product)[0]
    choice=report['template_choices'];name=product['name'];u=report['usage_reports'][0]
    context=CONTEXT_TEXT[u['context_id']]
    if u['experience_kind']=='actual_use':
        lead=(f'My experience with {name} comes from {context}.',f'I have tried {name}; this is about {context}.',
              f'I chose {name} and have experience of {context}.')[choice['intro']]
    elif u['experience_kind']=='intention':
        lead=f'I am considering {name} for {context}, but have not tried that yet.'
    else:lead=f'A friend discussed {name} with me in connection with {context}; I have no first-hand experience of that use.'
    facts=[]
    for key in report['mentioned_attributes']:
        label,unit=field_info(product['category'],key)
        facts.append(f'{label.lower()}: {pretty(product["attributes"][key])}'+(f' {unit}' if unit else ''))
    spec=('The listed configuration is ','The product description lists ','For reference, the listing says ')[choice['facts']]+ '; '.join(facts)+'.'
    statements=[]
    for a in report['assessments']:
        text=ASPECTS[a['aspect_id']]['statements'][STANCES.index(a['stance'])]
        statements.append(('In my experience, ','For me, ','My impression was that ')[choice['stance']]+text+'.')
    if u['experience_kind']=='actual_use':
        missing=[k for k,v in ASPECTS.items() if product['category'] in v['families'] and not any(a['aspect_id']==k for a in report['assessments'])]
        if missing:statements.append('I am not giving a view on '+', '.join(ASPECTS[k]['label'] for k in missing)+'.')
    else:statements.append('I cannot judge that use from personal experience.')
    tail=('That is just how it worked out for me.','Someone with different preferences may feel differently.',
          'I would weigh this alongside other people’s experiences.','This is my impression of this particular option.')[choice['ending']]
    if report.get('template_version',1)==2 and u['experience_kind']!='actual_use':
        tail=('I am still deciding whether to try it.','I would like to hear from people who have actually tried it.',
              'I will compare a few options before deciding.','I need some first-hand experience before making up my mind.')[choice['ending']]
    return ' '.join((lead,spec,*statements,tail))


def generate_evidence(world,*,seed=0,as_of='2026-09-26',reviews_per_sku=12,reviewed_variants_per_model=1,profile_options=None,narrative_options=None):
    if narrative_options is not None:
        from .profile_narratives import generate_narrative_evidence
        return generate_narrative_evidence(world,seed=seed,as_of=as_of,reviews_per_sku=reviews_per_sku,
            reviewed_variants_per_model=reviewed_variants_per_model,profile_options=profile_options,narrative_options=narrative_options)
    if profile_options is not None:
        from .opinion_profiles import generate_profiled_evidence
        return generate_profiled_evidence(world,seed=seed,as_of=as_of,reviews_per_sku=reviews_per_sku,
            reviewed_variants_per_model=reviewed_variants_per_model,profile_options=profile_options)
    if type(seed) is not int:raise ValueError('Integer evidence seed required')
    for key,value,maximum in [('reviews_per_sku',reviews_per_sku,100),('reviewed_variants_per_model',reviewed_variants_per_model,6)]:
        if type(value) is not int or not 0<=value<=maximum:raise ValueError(f'{key} must be 0..{maximum}')
    today=date.fromisoformat(as_of)
    if today.isoformat()!=as_of:raise ValueError('ISO date required')
    products={p['product_id']:p for p in world['public']['products']}
    reports=[];coverage=[]
    for group in sorted(world['public']['product_groups'],key=lambda g:g['group_id']):
        skus=sorted(v['product_id'] for v in group['variants'])
        # Stable random ranking makes increasing coverage a prefix expansion.
        chosen=sorted(skus,key=lambda sku:stream(seed,VERSION+'/subject/'+sku).random())[:reviewed_variants_per_model]
        for sku in chosen:
            p=products[sku];family=p['category'];aspects=[k for k,v in ASPECTS.items() if family in v['families']]
            narrative_aspects=[a for a in aspects if not (a=='heel_rubbing' and p['attributes'].get('shoe_type')=='flip-flops')]
            template_version=4 if family in ('beer','wine') else 3
            context=ASPECTS[PRIMARY[family]]['context']
            for aspect in aspects:
                coverage.append({'sku_id':sku,'aspect_id':aspect,'context_id':context,'status':'complete'})
            for i in range(reviews_per_sku):
                key=f'{VERSION}/{sku}/{i}';r=stream(seed,key);rid='review-'+digest([PUBLISHER,template_version,seed,sku,i])[:20]
                experience=r.choices(('actual_use','hearsay'),(.85,.15))[0]
                assessments=[]
                # A review has something to say. Choose its focus before drawing
                # stances; omitted aspects stay absent rather than label-like prose.
                focus=r.choice(narrative_aspects)
                for aspect in narrative_aspects:
                    if aspect==focus or r.random()<.65:
                        choices=STANCES if aspect==PRIMARY[family] else ('positive','negative','mixed')
                        weights=(.45,.25,.1,.2) if len(choices)==4 else (.5,.3,.2)
                        if template_version==4 and aspect in ('bitterness','dryness'):
                            choices=('positive','negative');weights=(.6,.4)
                        stance=r.choices(choices,weights)[0]
                        assessments.append({'aspect_id':aspect,'context_id':context,'stance':stance})
                attributes=sorted(p['attributes']);r.shuffle(attributes)
                primary=next((a['stance'] for a in assessments if a['aspect_id']==PRIMARY[family]),'not_assessed')
                star_choices={'positive':(4,5),'negative':(1,2),'neutral':(3,),
                              'mixed':(2,3,4),'not_assessed':(2,3,4)}[primary]
                row={'review_id':rid,'reviewer_id':'reviewer-'+digest([PUBLISHER,template_version,seed,sku,i])[:20],
                    'publisher_id':PUBLISHER,'article_id':group['group_id'],'subject':{'scope':'sku','id':sku},
                    'handle':'Reader '+digest([seed,sku,i])[:6],
                    'published_date':(today-timedelta(days=r.randint(0,min(365,today.toordinal()-1)))).isoformat(),
                    'source_locator':{'article_id':group['group_id'],'fragment':rid},
                    'stars':r.choice(star_choices) if r.random()<.85 else None,'usage_reports':[{'context_id':context,'experience_kind':experience}],
                    'assessments':assessments,'mentioned_attributes':sorted(attributes[:2]),
                    'template_version':template_version,
                    'template_choices':{'intro':r.randrange(3),'facts':r.randrange(3),'stance':r.randrange(3),'ending':r.randrange(4)}}
                if template_version==4:
                    from .evidence_drinks import sample_observations,render_drink
                    row['sensory_observations']=sample_observations(p,assessments,r)
                    row['body'],row['mentioned_attributes']=render_drink(row,p)
                else:
                    from .evidence_prose import render_natural
                    row['body'],row['mentioned_attributes']=render_natural(row,p)
                reports.append(row)
    public={'as_of':as_of,'source_catalog_sha256':catalog_hash(world),'publisher_id':PUBLISHER,
        'registry':registry(),'coverage':coverage,'reviews':reports,
        'scope':'Published reports in this corpus as of the stated date; exact SKU only. Missing subject coverage is unknown.',
        'identity_policy':'One active canonical review per reviewer and SKU; identical copies count once; conflicting copies are invalid.'}
    result={'schema_version':VERSION,'public':public,'private_provenance':{'seed':seed,'reviews_per_sku':reviews_per_sku,
        'reviewed_variants_per_model':reviewed_variants_per_model,'public_sha256':digest(public),
        'sampling':'Independent SKU/reviewer streams; authored uncalibrated opinions. No task, stock, price or layout inputs.'}}
    validate_evidence(world,result)
    return result


def validate_evidence(world,export):
    if not isinstance(export,dict) or export.get('schema_version')!=VERSION:raise ValueError('Unsupported product evidence version')
    public=export['public']
    if public['source_catalog_sha256']!=catalog_hash(world) or export['private_provenance']['public_sha256']!=digest(public):
        raise ValueError('Product evidence catalog/corpus hash mismatch')
    if public['publisher_id']!=PUBLISHER or public['registry']!=registry():raise ValueError('Unknown evidence publisher or aspect registry')
    if date.fromisoformat(public['as_of']).isoformat()!=public['as_of']:raise ValueError('Invalid evidence date')
    products={p['product_id']:p for p in world['public']['products']}
    group_for={v['product_id']:g['group_id'] for g in world['public']['product_groups'] for v in g['variants']}
    scopes=set()
    for c in public['coverage']:
        key=(c['sku_id'],c['aspect_id'],c['context_id']);p=products.get(c['sku_id']);a=ASPECTS.get(c['aspect_id'])
        if key in scopes or not p or not a or p['category'] not in a['families'] or c['context_id']!=a['context'] or c['status'] not in ('complete','incomplete'):
            raise ValueError('Invalid product evidence coverage')
        scopes.add(key)
    ids=set();authors=set()
    for r in public['reviews']:
        sku=r['subject']['id'];p=products.get(sku);author=(r['reviewer_id'],sku)
        if not p or r['subject']['scope']!='sku' or r['review_id'] in ids or author in authors:raise ValueError('Invalid/duplicate review identity or scope')
        if not all(isinstance(r[k],str) and r[k] for k in ('review_id','reviewer_id','handle')):raise ValueError('Missing reviewer identity')
        ids.add(r['review_id']);authors.add(author)
        if r['publisher_id']!=PUBLISHER or r['article_id']!=group_for[sku] or r['source_locator']!={'article_id':r['article_id'],'fragment':r['review_id']}:
            raise ValueError('Invalid source locator')
        if date.fromisoformat(r['published_date']).isoformat()!=r['published_date'] or r['published_date']>public['as_of']:raise ValueError('Invalid review date')
        if r['stars'] is not None and (type(r['stars']) is not int or not 1<=r['stars']<=5):raise ValueError('Invalid review stars')
        if len(r['usage_reports'])!=1:raise ValueError('One usage report required in v2')
        u=r['usage_reports'][0]
        if u['context_id']!=ASPECTS[PRIMARY[p['category']]]['context'] or u['experience_kind'] not in ('actual_use','intention','hearsay'):raise ValueError('Invalid usage context')
        seen=set()
        for a in r['assessments']:
            key=(sku,a['aspect_id'],a['context_id'])
            if key not in scopes or key in seen or a['stance'] not in STANCES or u['experience_kind']=='intention':raise ValueError('Invalid aspect judgment')
            seen.add(key)
            if p['attributes'].get('shoe_type')=='flip-flops' and a['aspect_id']=='heel_rubbing':
                raise ValueError('Closed-back heel-rubbing prose does not apply to flip-flops')
        if any((sku,aspect,ASPECTS[aspect]['context']) not in scopes for aspect,v in ASPECTS.items() if p['category'] in v['families']):raise ValueError('Review lacks scope coverage')
        attrs=r['mentioned_attributes']
        if not isinstance(attrs,list) or len(attrs)!=len(set(attrs)) or any(k not in p['attributes'] for k in attrs):raise ValueError('Unknown mentioned attribute')
        if set(r['template_choices'])!={'intro','facts','stance','ending'} or any(type(v) is not int or not 0<=v<(4 if k=='ending' else 3) for k,v in r['template_choices'].items()):raise ValueError('Invalid prose template choice')
        if type(r.get('template_version',1)) is not int or r.get('template_version',1) not in (1,2,3,4,5):raise ValueError('Unknown review template version')
        if r.get('template_version')==5 and 'narrative_sampling' not in export['private_provenance']:raise ValueError('Narrative provenance required')
        if r.get('template_version') in (3,4,5):
            if r['template_version']==5:
                from .profile_narratives import render_narrative as render_natural
            elif r['template_version']==4:
                from .evidence_drinks import render_drink as render_natural
            else:
                from .evidence_prose import render_natural
            if not r['assessments'] or u['experience_kind']=='intention':raise ValueError('Natural reports need substantive claims')
            if render_natural(r,p)[1]!=attrs:raise ValueError('Mentioned attributes differ from prose slots')
        if r['body']!=render_report(r,p):raise ValueError('Review prose differs from structured claims')
    if 'narrative_sampling' in export['private_provenance']:
        from .profile_narratives import validate_narrative_binding
        validate_narrative_binding(world,export)
    elif 'profile_sampling' in export['private_provenance']:
        from .opinion_profiles import validate_profile_binding
        validate_profile_binding(world,export)
    return {'valid':True,'review_count':len(ids),'public_sha256':digest(public)}
