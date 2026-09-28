"""Presentation of sampled shopping interactions; never samples or changes facts.

These helpers intentionally use ordinary links, lists, headings and disclosures.
No task, oracle label, sampled difficulty or pattern ID is exposed to policy pages.
"""
from html import escape
from urllib.parse import urlencode


def options(owner, site):
    return getattr(owner, 'interaction_sites', {}).get(site, {})


def e(value):
    return escape(str(value), quote=True)


def link(url, label):
    return '<a href="'+e(url)+'">'+e(label)+'</a>'


def disclosure(body, label, enabled=False):
    return '<details><summary>'+e(label)+'</summary>'+body+'</details>' if enabled else body


def search_context(items, query, review_url, *, list_style=False, story_kind='Product review', story_text='Specifications and reader experiences.'):
    """Shortcuts and editorial matches, both functional and scoped to this catalog.

    Text matches intentionally overlap with product results. Review vs purchase
    intent is discoverable from link wording and neighbouring facts, not a magic
    answer-bearing attribute. Empty searches never acquire invented matches.
    """
    if not query or not items:
        return ''
    families=list(dict.fromkeys(x['category'] for x in items))
    shortcuts=''.join('<li>'+link('/search?'+urlencode({'q':query,'category':f}),
                                  f.replace('_',' ').title()+' — '+query)+'</li>' for f in families)
    sample=items[:2]
    stories=''.join('<li><article><p>'+e(story_kind)+'</p><h3>'+link(review_url(x),x['name'])+
                    '</h3><p>'+e(story_text)+'</p></article></li>' for x in sample)
    return ('<nav aria-label="Browse related departments"><ul>'+shortcuts+'</ul></nav>'+
            ('<ul>' if list_style else '<section aria-label="Reading and advice"><h2>Reading and advice</h2><ul>')+
            stories+('</ul>' if list_style else '</ul></section>'))


def comparison_options(design):
    sid=(design.coverage or {}).get('site_id','aggregator')
    return options(design.owner,sid)


def comparison_search(design, q):
    cfg=comparison_options(design)
    if not cfg.get('search_sections'):
        return ''
    items,_,_=design.filtered(q)
    return search_context(items,q.get('q',''),design.review_url,
                          list_style=design.layout in ('ledger','finder'))


def comparison_offers(design, body):
    return disclosure(body,'Show retailer offers',comparison_options(design).get('offer_disclosure')=='expand')


def retailer_search(owner, site, products, query):
    if not options(owner,site).get('search_sections'):
        return ''
    def review_url(p):
        return '/products/'+p['product_id']+'/details'
    # One editorial link per model, not per size.
    unique={}
    for p in products:
        unique.setdefault(owner.group_for[p['product_id']]['group_id'],p)
    return search_context(list(unique.values()),query,review_url,
                          list_style=options(owner,site).get('result_presentation')=='list',
                          story_kind='Product information',story_text='Read the full specifications and available options.')


def needs_destination(owner, site):
    return options(owner,site).get('destination_form','none')!='none'


def destination_form(owner, site, query):
    if not needs_destination(owner,site):
        return ''
    destination=owner.interaction_patterns['destination']
    body='<fieldset><legend>Delivery location</legend><label>Country code<input name="destination_country" value="'+e(query.get('destination_country',destination['country']))+'" maxlength="2"></label>'
    split=options(owner,site)['destination_form']=='split' and len(destination['postcode_parts'])==2
    if split:
        for i,part in enumerate(destination['postcode_parts']):
            name='postcode_'+str(i+1)
            body+='<label>Postcode '+('first part' if i==0 else 'last part')+'<input name="'+name+'" value="'+e(query.get(name,''))+'" maxlength="'+str(len(part))+'" autocomplete="off"></label>'
    else:
        body+='<label>Postcode<input name="postcode" value="'+e(query.get('postcode',''))+'" autocomplete="postal-code"></label>'
    return body+'</fieldset>'


def destination_valid(owner, site, query):
    if not needs_destination(owner,site):return True
    from environments.product_world.interaction_patterns import destination_matches
    destination=owner.interaction_patterns['destination']
    split=options(owner,site)['destination_form']=='split' and len(destination['postcode_parts'])==2
    if split:
        return destination_matches(owner.interaction_patterns,query.get('destination_country',''),
                                   parts=[query.get('postcode_1',''),query.get('postcode_2','')])
    return destination_matches(owner.interaction_patterns,query.get('destination_country',''),query.get('postcode',''))


def editorial_result(design, item):
    return ('<article><p>Reading and advice</p><h3>'+link(design.review_url(item),item['name'])+
            '</h3><p>Read specifications and reader experiences.</p></article>')


def comparison_cards(design, items):
    pieces=[design.card(x,i) for i,x in enumerate(items)]
    if items and comparison_options(design).get('search_sections'):
        # A genuine review is interleaved with products, not a fake offer.
        pieces.insert(0 if design.layout=='directory' else min(2,len(pieces)),editorial_result(design,items[0]))
    return ''.join(pieces)
