"""Manufactured variant grids and brand sizing for the isolated footwear pilot."""

FIT_LABELS={'true_to_size':'Generally true to size.',
            'runs_small':'Tends to run slightly small.',
            'runs_large':'Tends to run slightly large.'}
NOTICES={'runs_small':'Runs slightly small. Consider sizing up.',
         'runs_large':'Runs slightly large. Consider sizing down.'}


def size_group_options(sizes, mode):
    if mode=='full' or len(sizes)==1:return [list(sizes)]
    if mode=='subrange':return [sizes[a:b] for a in range(len(sizes)) for b in range(a+1,len(sizes)+1) if b-a<len(sizes)]
    if mode=='alternating':return [sizes[::2],sizes[1::2]]
    raise ValueError('Unknown size coverage mode')


def sample_variant_grid(product_id, widths, colours, spec, colour_weights, rng_for):
    def draw(key, weights):
        return rng_for(key).choices(list(weights),weights=list(weights.values()))[0]
    range_id=draw('size_range',spec['size_range_weights'])
    sizes=spec['size_ranges'][range_id]
    width_colours=[];groups=[];skus=[]
    for width in widths:
        requested='all' if width=='standard' else draw('colour_coverage/'+width,spec['extra_width_colour_weights'])
        subset=list(colours)
        if requested=='subset' and len(colours)>1:
            n=rng_for('colour_subset_count/'+width).randint(1,len(colours)-1)
            subset=[]
            for i in range(n):
                remaining={c:colour_weights[c] for c in colours if c not in subset}
                subset.append(draw(f'colour_subset/{width}/{i}',remaining))
        width_colours.append({'width':width,'colours':subset,'requested_mode':requested,
                              'realized_mode':'all' if len(subset)==len(colours) else 'subset'})
        for colour in subset:
            key=f'sizes/{colour}/{width}'
            mode=draw(key+'/mode',spec['variant_size_weights'])
            selected=rng_for(key+'/coverage').choice(size_group_options(sizes,mode))
            groups.append({'colour':colour,'width':width,'sizes_eu':selected,'requested_mode':mode,
                           'realized_mode':mode if selected!=sizes else 'full'})
            for size in selected:
                skus.append({'sku_id':f'{product_id}-{colour}-{width}-{size}','product_id':product_id,
                             'colour':colour,'width':width,'size_eu':size})
    return skus,{'size_range_id':range_id,'size_range_eu':list(sizes),'width_colours':width_colours,'size_groups':groups}


def reviewer_size_fit(sku, tendency, spec, rng_for):
    # Reviewer may have compensated by half a nominal EU size. The chosen SKU is
    # always real; usual size is personal context, not an invented second purchase.
    adjustment=rng_for('size_adjustment').choices([0,.5,-.5],weights=[8,1,1])[0]
    usual=sku['size_eu']-adjustment
    label_offset=spec['brand_fit_offsets_eu'][tendency]+rng_for('size_experience').gauss(0,.2)
    actual_offset=label_offset+adjustment
    result='too_short' if actual_offset<-.3 else 'too_long' if actual_offset>.3 else 'fits'
    return {'usual_size_eu':usual,'purchased_size_eu':sku['size_eu'],'fit_result':result,
            'private_effective_length_offset_eu':actual_offset}


def product_review_overview(product):
    p=product['public'];private=product['private']
    return {'product_id':p['product_id'],'concept_id':p['concept_id'],
            'price_positioning':private['positioning'],'fit_tendency':private['fit_tendency'],
            'fit_text':FIT_LABELS[private['fit_tendency']],
            'authority':'synthetic_editorial_guidance_not_review_vote_counts'}


def brand_review_overview(brand, products):
    owned=[p for p in products if p['public']['brand_id']==brand['brand_id']]
    concepts=sorted({p['public']['concept_id'] for p in owned})
    weights=brand['positioning_weights'];segment=max(weights,key=weights.get)
    return {'brand_id':brand['brand_id'],'name':brand['name'],'concept_ids':concepts,
            'scope_id':brand['scope_id'],'emphasis_tendency':brand['emphasis_tendency'],
            'product_ids':[p['public']['product_id'] for p in owned],
            'usual_price_positioning':segment,'fit_tendency':brand['fit_tendency'],
            'fit_text':FIT_LABELS[brand['fit_tendency']],
            'authority':'synthetic_editorial_guidance_not_review_vote_counts'}


def retailer_fit_notice(tendency, probability, rng):
    if tendency=='true_to_size':return None
    if rng.random()>=probability:return None
    return {'text':NOTICES[tendency],'fit_tendency':tendency,'authority':'retailer_sizing_guidance'}
