"""Supplied-answer controls for task families, never an answer interpreter.

These fixtures deliberately use private native references to construct positive
and counterexample answers. The offline formatter copies the supplied JSON;
this tests graders/lifecycle, not a real extractor's interpretation of prose.
"""
from copy import deepcopy
from decimal import Decimal
import json
from urllib.parse import quote


def _empty(schema):
    if schema.get('type')=='object':
        return {key:_empty(value) for key,value in schema['properties'].items()}
    if schema.get('type')=='array':return []
    if 'anyOf' in schema and any(s.get('type')=='null' for s in schema['anyOf']):return None
    typ=schema.get('type')
    if isinstance(typ,list) and 'null' in typ:return None
    if 'enum' in schema:return schema['enum'][0]
    raise ValueError('No safe empty control for schema node')


def controls(grader, family, world, *, site_registry=None, bindings=None):
    """Return schema-shaped correct/wrong supplied answers for one native case."""
    task,ref=grader.task,grader.reference
    result=_empty(grader.schema)
    result['interpretation']='extracted';result['issues']=[];result['source_urls']=[]
    scalar=lambda value:{'value':value,'evidence':None}
    if family in ('feature_offer','catalog_priority','catalog_shortlist','basic_offer'):
        if bindings is None:raise ValueError('Offer control requires actual complete public bindings')
        products={p['public']['product_id']:p for p in world['products']}
        offers={o['offer_id']:{**o,'retailer_name':r['name']} for r in world['retailers'] for o in r['offers']}
        def row(candidate):
            offer=offers[candidate['offer_id']];product=products[offer['product_id']]
            sku=next(s for s in product['public']['skus'] if s['sku_id']==offer['sku_id'])
            variant_schema=(grader.row_schema if family=='catalog_shortlist' else grader.schema)['properties']['variant']
            variant={name:scalar(str(sku[name]) if name in product['variant_fields'] else None)
                     for name in variant_schema['properties']}
            return {'product_name':scalar(product['public']['name']),
                    'retailer_name':scalar(offer['retailer_name']),
                    'offer_url':scalar(bindings['retailer_offers'][candidate['offer_id']]['url']),
                    'sku_id':scalar(sku['sku_id']),'variant':variant,
                    'total':{'amount':format(Decimal(offer['price_minor'])/100,'.2f'),'currency':'SEK','evidence':None}}
        if family=='catalog_shortlist':
            result['status']=scalar('shortlist' if ref['selected_models'] else 'no_match')
            result['rows']=[row(m['winners'][0]) for m in ref['selected_models']]
        else:
            result['status']=scalar('selection' if ref['status']=='match' else 'no_match')
            if ref['status']=='match':result.update(row(ref['winners'][0]))
        wrong=deepcopy(result)
        if result['status']['value']=='no_match':
            wrong['status']=scalar('shortlist' if family=='catalog_shortlist' else 'selection')
            available=[o for o in offers.values() if o['offer_id'] in bindings['retailer_offers']]
            if not available:raise ValueError('Concrete no-match counterexample needs a real public offer')
            chosen=next((o for o in available if products[o['product_id']]['public']['concept_id']==task.get('concept_id')),available[0])
            if family=='catalog_shortlist':wrong['rows']=[row(chosen)]
            else:wrong.update(row(chosen))
        else:
            changed=wrong['rows'][0] if family=='catalog_shortlist' else wrong
            changed['total']['amount']=str(Decimal(changed['total']['amount'])+1)
        mutation='reported_item_price_plus_one_SEK' if ref.get('status')=='match' else 'concrete_real_offer_in_no_match_world'
    elif family=='catalog_statistics':
        site=next(s for s in site_registry if s['site_id']==task['comparison_site_id'])
        result.update(status=scalar('summary'),comparison_url=scalar(site['origin'].rstrip('/')+'/search'),
                      population_count=scalar(ref['population_count']),statistic_sek=scalar(ref['aggregate_sek']),
                      currency=scalar('SEK' if ref['aggregate_sek'] is not None else None),
                      undefined=scalar(False if task['operation']=='count' or ref['statistic_defined'] else True))
        wrong=deepcopy(result);wrong['population_count']['value']+=1;mutation='requested_population_count_plus_one'
    elif family=='catalog_review':
        site=next(s for s in site_registry if s['kind']=='product_reviews' and
                  (s['origin'].split('://',1)[0],s['origin'].split('://',1)[1].rstrip('/')) in grader.origins)
        url=site['origin'].rstrip('/')+'/reviews/'+quote(task['subject']['product_id'],safe='')
        result.update(status=scalar('summary'),product_name=scalar(task['subject']['product_name']),
                      review_url=scalar(url))
        if task['subject_scope']=='sku':
            result['sku_id']=scalar(task['subject']['sku_id']);result['review_url']=scalar(url+'?sku='+quote(task['subject']['sku_id'],safe=''))
        if task['operation']=='rating_summary':
            summary=ref['summary']
            for key in ('rating_count','written_review_count','rating_only_count'):result[key]=scalar(summary[key])
            for star in range(1,6):result[f'star_{star}_count']=scalar(summary['star_counts'][str(star)])
            result['mean_rating']=scalar(summary['mean_rounded']);result['mean_undefined']=scalar(summary['mean_rounded'] is None)
            wrong=deepcopy(result);wrong['rating_count']['value']+=1;mutation='rating_count_plus_one'
        else:
            for key,value in ref['counts'].items():result[key]=scalar(value)
            for key in ('written_review_count','assessed_count'):result[key]=scalar(ref[key])
            result['verdict']=scalar(ref['verdict'])
            wrong=deepcopy(result);wrong['positive']['value']+=1;mutation='positive_comment_count_plus_one'
    else:raise ValueError('No supplied-answer control for this family')

    mutations=[(mutation,wrong)]
    if family in ('feature_offer','catalog_priority','catalog_shortlist','basic_offer') and result['status']['value']!='no_match':
        wrong=deepcopy(result);changed=wrong['rows'][0] if family=='catalog_shortlist' else wrong
        changed['sku_id']=scalar('__nonexistent_sku__');mutations.append(('nonexistent_sku_identity',wrong))
        wrong=deepcopy(result);changed=wrong['rows'][0] if family=='catalog_shortlist' else wrong
        changed['total']['currency']='EUR';mutations.append(('wrong_currency',wrong))
        selected={o['offer_id'] for m in ref['selected_models'] for o in m['winners']} if family=='catalog_shortlist' else {o['offer_id'] for o in ref['winners']}
        alternatives=[o for o in offers.values() if o['offer_id'] not in selected and o['offer_id'] in bindings['retailer_offers']
                      and products[o['product_id']]['public']['concept_id']==task.get('concept_id')]
        if alternatives:
            wrong=deepcopy(result)
            if family=='catalog_shortlist':wrong['rows'][0]=row(alternatives[0])
            else:wrong.update(row(alternatives[0]))
            mutations.append(('real_nonwinner_or_ineligible_offer',wrong))
    if family=='catalog_statistics':
        if task['operation']!='count' and ref['aggregate_sek'] is not None:
            wrong=deepcopy(result);wrong['statistic_sek']=scalar(str(Decimal(ref['aggregate_sek'])+1));mutations.append(('aggregate_plus_one_SEK',wrong))
        elif task['operation']!='count':
            wrong=deepcopy(result);wrong['statistic_sek']=scalar('0.00');wrong['undefined']=scalar(False);wrong['currency']=scalar('SEK');mutations.append(('invented_aggregate_for_empty_population',wrong))
        wrong=deepcopy(result);wrong['comparison_url']=scalar(site['origin'].rstrip('/')+'/not-a-catalog');mutations.append(('wrong_citation_route',wrong))
    if family=='catalog_review':
        wrong=deepcopy(result);wrong['review_url']=scalar(site['origin'].rstrip('/')+'/not-a-review');mutations.append(('wrong_review_citation_route',wrong))
        if task['operation']=='rating_summary':
            wrong=deepcopy(result);wrong['mean_rating']=scalar('0.00' if ref['summary']['mean_rounded']!='0.00' else '1.00');wrong['mean_undefined']=scalar(False);mutations.append(('wrong_rating_mean',wrong))
        else:
            wrong=deepcopy(result);wrong['verdict']=scalar('tie' if ref['verdict']!='tie' else 'more_positive');mutations.append(('wrong_directional_verdict',wrong))

    def ground(value):
        # Output is a literal structured answer fixture. No text is interpreted
        # or normalized; all evidence authenticates this exact answer only.
        clean=deepcopy(value)
        def clear(obj):
            if isinstance(obj,dict):
                obj.pop('evidence',None)
                for child in obj.values():clear(child)
            elif isinstance(obj,list):
                for child in obj:clear(child)
        clear(clean);answer=json.dumps(clean,ensure_ascii=False,allow_nan=False)
        def fill(obj):
            if isinstance(obj,dict):
                if 'evidence' in obj:
                    obj['evidence']=answer if obj.get('value',obj.get('amount')) is not None else None
                for child in obj.values():fill(child)
            elif isinstance(obj,list):
                for child in obj:fill(child)
        fill(value)
        return {'answer':answer,'claims':value}
    return [{'control':'correct','expected_verdict':True,**ground(result)},
            *[{'control':'wrong','expected_verdict':False,'mutation':name,**ground(value)} for name,value in mutations]]
