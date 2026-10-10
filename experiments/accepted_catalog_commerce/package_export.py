"""A closed, source-bound accepted package slice; no legacy fact translation."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from environments.product_world.product_package import ProductPackage, PackageError
from environments.product_world.product_expressions import Expression, unresolved
from environments.product_world import footwear_context_pilot as footwear
from environments.product_world.product_package_pilot import sample_ported_product
from environments.product_world.footwear_retail_content import render_retail_content
from environments.product_world.review_population import summarize_ratings
from experiments.product_width_preview.model import SKU_CONTEXT_PROJECTIONS
from .catalog_registry import ADDITIONS, SHARED_ADDITIONS, input_defaults

ROOT = Path(__file__).resolve().parents[2]
WIDTH = ROOT/'environments/product_world/data/product_width'
LEDGER = ROOT/'.local/product-width/accepted.json'
PILOTS = ('footwear.walking_shoes', 'footwear.walking_sandals')
ACCEPTED = ('footwear.casual_trainers', 'tops.t_shirts', 'tablets.everyday_media_tablets')
CONCEPTS = (*PILOTS, *ACCEPTED)
SUPPORTED_CONCEPTS = (*CONCEPTS, *ADDITIONS)
COMPLETED = {'tops.t_shirts': '.local/product-width/annotations/tops.t_shirts/root_completed_caller_v2.py'}

def digest_file(path): return sha256(Path(path).read_bytes()).hexdigest()

def review_rating(context):
    review = context['review']
    return review['rating'] if 'rating' in review else review['stars']

def source_gate(concept_id):
    if concept_id not in SUPPORTED_CONCEPTS:
        raise PackageError('Concept not adopted by this closed commerce slice')
    if concept_id in PILOTS:
        path=ROOT/'environments/product_world/data/product_packages'/(concept_id+'.json')
        return {'capability':'ported_footwear_pilot','source_hashes':{str(path.relative_to(ROOT)):digest_file(path)}}
    entry=json.loads(LEDGER.read_text())[concept_id]
    if concept_id in SHARED_ADDITIONS:
        from .shared_semantics import source_gate as shared_gate
        return shared_gate(concept_id, root=ROOT, entry=entry)
    for path,expected in entry['source_hashes'].items():
        if digest_file(ROOT/path)!=expected:
            raise PackageError('Accepted package source changed: '+path)
    metadata=ProductPackage.load(WIDTH/(concept_id+'.json')).document.get('metadata',{})
    required=metadata.get('required_completed_consumer')
    if required and COMPLETED.get(concept_id)!=required:
        raise PackageError('Required completed consumer is not adopted by this slice')
    entry_required = entry.get('required_completed_caller')
    if entry_required and COMPLETED.get(concept_id) != entry_required:
        raise PackageError('Required completed caller is not adopted by this slice')
    if entry.get('runtime_context_validation'):
        raise PackageError('New context capability needs an explicit versioned producer binding')
    return {'capability':'source_bound_completed_factory' if required else 'accepted_package_sampler',
            'source_hashes':deepcopy(entry['source_hashes']),
            'accepted_entry_sha256':sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()}

def _package(concept_id, inputs):
    if concept_id in SHARED_ADDITIONS:
        from .shared_semantics import prepare_package
        return prepare_package(ProductPackage.load(WIDTH/(concept_id+'.json')).document,
            weights=inputs['brand'].get('market_range_weights'), validation='full')
    source=COMPLETED.get(concept_id)
    if source:
        spec=importlib.util.spec_from_file_location('commerce_consumer_'+digest_file(ROOT/source),ROOT/source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.make_package(authoritative_inputs=deepcopy(inputs))
    return ProductPackage.load(WIDTH/(concept_id+'.json'))

def _descriptions(package, entities, seed):
    rows=[]
    for pool in package.document['language']:
        if pool['meaning']['kind']!='catalog_fact':continue
        expressions=[*pool.get('slots',{}).values(),*([pool['when']] if 'when' in pool else [])]
        # Compiler introspection is distinct from executing a completed consumer.
        # Some accepted factories intentionally forbid its exposed expression API.
        refs=set().union(*(Expression(x,package.fields).references for x in expressions))
        scoped=any(x == 'sku' or x.startswith('sku.') for x in refs)
        for sku in entities['product']['skus'] if scoped else [None]:
            context=deepcopy(entities)
            if sku is not None:
                projection=SKU_CONTEXT_PROJECTIONS.get(package.document['concept_id'])
                if projection:
                    context['sku']=package.programs[projection].sample(seed,inputs={
                        'product':{'product_id':entities['product']['product_id'],'skus':deepcopy(entities['product']['skus'])},
                        'projection':{'subject':deepcopy(sku)}})['entities']['sku']
                else:context['sku']=deepcopy(sku)
            if 'when' in pool and not package._eval(pool['when'],context):continue
            if package.document['concept_id'] in SHARED_ADDITIONS and any(unresolved(package.expression(value).evaluate(context))
                    for value in pool.get('slots',{}).values()):continue
            row=package.formulate(pool['id'],context,seed=seed)
            row.update(subject_type='sku' if scoped else 'product',
                       subject_id=sku['sku_id'] if scoped else entities['product']['product_id'],
                       source_pool_id=pool['id'],mapping_status='unmapped')
            rows.append(row)
    return rows

def sample(seed, concept_id, brand, product_id, *, earlier=(), review_count=0):
    """Keep manufactured scalar/status/SKU data; names are caller display identity."""
    if type(review_count) is not int or not 0<=review_count<=1000:
        raise ValueError('Declare finite review count0..1000')
    gate=source_gate(concept_id)
    if concept_id in PILOTS:
        item=sample_ported_product(seed,concept_id.split('.')[1],brand,product_id=product_id,
                                   existing_products=[p['public'] for p in earlier])
        description=render_retail_content(item['public'],seed=seed)['description']
        description.update(subject_type='product',subject_id=product_id,mapping_status='unmapped')
        item['descriptions']=[description]
        item['reviews']=footwear.sample_reviews(seed,item,count=review_count)
        for review in item['reviews']:review['reviewer_id']=review['review_id']+'/person'
        item['rating_summary']=summarize_ratings(item['reviews'])
        item['private']['profiles']={k:deepcopy(item['private'][k]) for k in ('positioning','execution')}
        item['private']['commerce_source_gate']=gate
        fields=ProductPackage.load(ROOT/'environments/product_world/data/product_packages'/(concept_id+'.json')).fields
    else:
        declared=ProductPackage.load(WIDTH/(concept_id+'.json'))
        inputs={'brand':{path.split('.')[1]:deepcopy(brand[path.split('.')[1]])
                         for path,d in declared.fields.items()
                         if path.startswith('brand.') and path.count('.')==1 and d.get('input')
                         and path.split('.')[1] in brand},'product':{'product_id':product_id}}
        inputs['brand']['eligible_concepts']=[concept_id]
        if declared.fields.get('product.concept_id',{}).get('input'):inputs['product']['concept_id']=concept_id
        if declared.fields.get('product.name',{}).get('input'):inputs['product']['name']=brand['name']+' '+product_id.split('/')[-1]
        if concept_id in ADDITIONS:inputs=input_defaults(declared.document,inputs)
        package=_package(concept_id,inputs); result=package.sample(seed,inputs=deepcopy(inputs));entities=result['entities']
        catalog=deepcopy(entities['product'])
        # Never replace facts, configurations, status or SKU price with a generic
        # manufacturer's model. Display identity fills only undeclared labels.
        from environments.product_world.product_naming import sample_product_name
        name,_=sample_product_name(footwear.load_spec()['product_names'],brand_id=brand['brand_id'],
            existing_products=[p['public'] for p in earlier],rng=footwear.stream(seed,'commerce-model-name'))
        catalog.setdefault('name',brand['name']+' '+name)
        catalog.setdefault('model_name',name)
        catalog.update(family_id=concept_id.split('.')[0],concept_id=concept_id,
                       concept=concept_id.split('.')[1],brand_id=brand['brand_id'])
        item={'public':catalog,'private':{'profiles':deepcopy(entities['profile']),
              'sample':result,'commerce_source_gate':gate},
              'descriptions':_descriptions(package,entities,seed),'reviews':[]}
        for index in range(review_count):
            stage=package.make_review() if hasattr(package,'make_review') else package.programs['review']
            rs=int.from_bytes(sha256(f'accepted-catalog-review/{seed}/{index}'.encode()).digest()[:4],'big')
            review=stage.sample(rs,inputs=deepcopy(entities));e=review['entities'];statements=[]
            for pool in stage.document['language']:
                if 'when' not in pool or stage._eval(pool['when'],e):
                    statements.append(stage.formulate(pool['id'],e,seed=rs))
            presentation=footwear.compose_review(rs,product_id+'/review-'+str(index),
                [dict(s,polarity=s['meaning']['polarity']) for s in statements])
            item['reviews'].append({'review_id':product_id+'/review-'+str(index),
                'reviewer_id':product_id+'/reviewer-'+str(index),'sku_id':e['sku']['sku_id'],
                'rating':review_rating(e),'text':presentation['text'],
                'statements':statements,'presentation':presentation,'private_trace':review['trace']})
        item['rating_summary']=summarize_ratings(item['reviews']);fields=package.fields
    public=item['public']
    if 'sample' in item['private']:
        sampled=item['private']['sample']
        item['catalog_status']={k:deepcopy(v) for k,v in sampled['field_status'].items()
                                if k.startswith('product.facts.') or k=='product.reference_price_sek'}
        typed=sampled.get('typed_status_projection',{})
        if 'manufactured_SKU_status' in typed:
            item['sku_status']={row['sku_id']:deepcopy(row['statuses']) for row in typed['manufactured_SKU_status']}
        elif concept_id in SKU_CONTEXT_PROJECTIONS:
            item['sku_status']={}
            for row in public['skus']:
                projected=package.programs[SKU_CONTEXT_PROJECTIONS[concept_id]].sample(seed,inputs={
                    'product':{'product_id':product_id,'skus':deepcopy(public['skus'])},'projection':{'subject':deepcopy(row)}})
                item['sku_status'][row['sku_id']]={k:deepcopy(v) for k,v in projected['field_status'].items() if k.startswith('sku.')}
        else:
            item['sku_status']={row['sku_id']:{k:deepcopy(v) for k,v in sampled['field_status'].items() if k.startswith('sku.')}
                                for row in public['skus']}
        item['status_provenance']='accepted caller status projection where declared; otherwise exact compiler/projection output, no inferred status upgrade'
    else:
        item['catalog_status']={};item['sku_status']={}
        item['status_provenance']='ported pilot public scalars; no additional logical-status coverage claimed'
    if public['product_id']!=product_id or not public['skus']:
        raise PackageError('Canonical product manufacture identity changed or empty')
    if len({s['sku_id'] for s in public['skus']})!=len(public['skus']) or any(s['product_id']!=product_id for s in public['skus']):
        raise PackageError('Canonical SKU manufacture identity changed')
    item['variant_fields']={k[4:]:deepcopy(v) for k,v in fields.items()
                            if k.startswith('sku.') and 'retail_presentation' in v}
    item['public_mapping_status']='unmapped_prose; source-bound structured facts/status retained'
    item['commerce']={'shipping_class':'regular','classification_basis':'closed_ordinary_parcel_concept_slice_v1'}
    return item
