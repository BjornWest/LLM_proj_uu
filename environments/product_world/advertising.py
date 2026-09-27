"""Frozen contextual ads over canonical offers; no ranking or outcome conditioning.

This public sidecar never changes catalog membership, reviews or comparison coverage.
Context is only a broad product family. Hidden preferences and task answers are not
inputs. Static ads do not use cookies, tracking, or third-party resources.
"""
import re

from .config import FAMILY_IDS, _number
from .generator import digest, rng
from .stores import validate_store_world

VERSION = 'shopping-advertising-v1'
PLACEMENTS = ('banner', 'inline', 'sidebar')
AD_FIELDS = {'ad_id', 'placement', 'label', 'retailer_id', 'product_id', 'model_id',
             'family', 'headline', 'body', 'cta', 'price_minor', 'currency'}
BODY_TEMPLATES = ('Explore this option at {store}.',
                  'Take a closer look at this product from {store}.',
                  'Discover more from {store}. View this product in their range.')


def resolve_config(patch=None):
    result = {'aggregator_site_probability': 1.0, 'review_site_probability': .5,
              'contextual_probability': .75, 'ads_per_site': 2}
    if patch is not None:
        if not isinstance(patch, dict) or set(patch) - set(result):
            raise ValueError('Unknown advertising configuration')
        result.update(patch)
    for key in ('aggregator_site_probability', 'review_site_probability', 'contextual_probability'):
        _number(result[key], key, probability=True)
    if type(result['ads_per_site']) is not int or not 0 <= result['ads_per_site'] <= 3:
        raise ValueError('ads_per_site must be 0..3')
    return result


def _families(values):
    if (not isinstance(values, list) or not values or
        any(not isinstance(f, str) or f not in FAMILY_IDS for f in values) or
        len(set(values)) != len(values)):
        raise ValueError('Invalid advertising families')
    return sorted(values)


def _specs(sites):
    if not isinstance(sites, list) or not 1 <= len(sites) <= 32:
        raise ValueError('Expected 1..32 advertising sites')
    result = []; seen = set()
    for s in sites:
        if not isinstance(s, dict) or set(s) != {'site_id', 'kind', 'families'}:
            raise ValueError('Invalid advertising site specification')
        sid = s['site_id']
        if not isinstance(sid, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', sid) or sid in seen:
            raise ValueError('Invalid/duplicate advertising site ID')
        if s['kind'] not in ('aggregator', 'product_review'):
            raise ValueError('Unsupported advertising site kind')
        seen.add(sid)
        result.append({'site_id': sid, 'kind': s['kind'], 'families': _families(s['families'])})
    return sorted(result, key=lambda s: s['site_id'])


def _world_facts(world):
    validate_store_world(world)
    public = world['public']
    return ({p['product_id']: p for p in public['products']},
            {s['retailer_id']: s for s in public['retailers']},
            {v['product_id']: g['group_id'] for g in public['product_groups'] for v in g['variants']},
            {(o['retailer_id'], o['product_id']): o for o in public['offers']})


def generate_advertising(world, sites, *, seed=42, focus_families=None, config=None):
    """Draw site participation and up to three distinct canonical offer adverts.

    Family → model → retailer → SKU avoids giving models with many sizes extra
    campaign probability. No stock, price, review or outcome influences the draw.
    """
    if type(seed) is not int:
        raise ValueError('Advertising seed must be an integer')
    settings = resolve_config(config); specs = _specs(sites)
    focus = set() if focus_families is None else set(_families(focus_families))
    products, stores, models, offers = _world_facts(world)
    rows = []
    for spec in specs:
        sid = spec['site_id']; ns = VERSION+'/'+sid
        context = (focus & set(spec['families'])) or set(spec['families'])
        probability = settings['aggregator_site_probability' if spec['kind']=='aggregator' else 'review_site_probability']
        ads = []; remaining = sorted(offers)
        placements = PLACEMENTS if spec['kind']=='aggregator' else ('sidebar', 'banner', 'inline')
        if rng(seed, ns+'/enabled').random() < probability:
            for placement in placements[:settings['ads_per_site']]:
                if not remaining: break
                stream = rng(seed, ns+'/'+placement)
                available = {products[sku]['category'] for _,sku in remaining}
                want_context = stream.random() < settings['contextual_probability']
                pool = available & context if want_context else available - context
                family = stream.choice(sorted(pool or available))
                choices = [p for p in remaining if products[p[1]]['category']==family]
                model = stream.choice(sorted({models[sku] for _,sku in choices}))
                choices = [p for p in choices if models[p[1]]==model]
                retailer = stream.choice(sorted({sid for sid,_ in choices}))
                pair = stream.choice([p for p in choices if p[0]==retailer]); remaining.remove(pair)
                product = products[pair[1]]; offer = offers[pair]
                ads.append({'ad_id':'ad-'+sid+'-'+placement, 'placement':placement,
                    'label':'Advertisement', 'retailer_id':retailer, 'product_id':pair[1],
                    'model_id':model, 'family':family, 'headline':product['name'],
                    'body':stream.choice(BODY_TEMPLATES).format(store=stores[retailer]['name']),
                    'cta':'View product', 'price_minor':offer['price_minor'], 'currency':'SEK'})
        rows.append({**spec, 'ads':ads})
    result = {'schema_version':VERSION, 'source_world_sha256':world['world_sha256'], 'sites':rows}
    validate_advertising(world, result)
    return result


def validate_advertising(world, data):
    products, stores, models, offers = _world_facts(world)
    if (not isinstance(data, dict) or set(data) != {'schema_version','source_world_sha256','sites'}
        or data['schema_version'] != VERSION):
        raise ValueError('Unsupported advertising sidecar')
    if data['source_world_sha256'] != world['world_sha256']:
        raise ValueError('Advertising belongs to another world')
    if not isinstance(data['sites'], list): raise ValueError('Invalid advertising sites')
    for site in data['sites']:
        if not isinstance(site, dict) or set(site) != {'site_id','kind','families','ads'}:
            raise ValueError('Invalid advertising site')
    _specs([{k:s[k] for k in ('site_id','kind','families')} for s in data['sites']])
    seen = set()
    for site in data['sites']:
        if not isinstance(site['ads'], list) or len(site['ads']) > 3:
            raise ValueError('Expected up to three advertisements per site')
        placements = set(); pairs = set()
        for ad in site['ads']:
            if not isinstance(ad, dict) or set(ad) != AD_FIELDS:
                raise ValueError('Invalid advertisement fields')
            if any(not isinstance(ad[k], str) for k in AD_FIELDS-{'price_minor'}):
                raise ValueError('Invalid advertisement text/identity')
            if ad['placement'] not in PLACEMENTS or ad['placement'] in placements:
                raise ValueError('Invalid/duplicate advertisement placement')
            if ad['ad_id'] != 'ad-'+site['site_id']+'-'+ad['placement'] or ad['ad_id'] in seen:
                raise ValueError('Invalid/duplicate advertisement ID')
            pair = ad['retailer_id'], ad['product_id']
            if pair not in offers or pair in pairs:
                raise ValueError('Advertisement must name a distinct existing retailer offer')
            product = products[pair[1]]
            if (ad['model_id'] != models[pair[1]] or ad['family'] != product['category']
                or ad['headline'] != product['name']):
                raise ValueError('Advertisement product identity/claims differ from catalog')
            if (type(ad['price_minor']) is not int or ad['price_minor'] != offers[pair]['price_minor']
                or ad['currency'] != 'SEK'):
                raise ValueError('Advertisement item price differs from retailer offer')
            if ad['label'] != 'Advertisement' or ad['cta'] != 'View product':
                raise ValueError('Advertisement must retain its explicit label and product action')
            if ad['body'] not in {t.format(store=stores[pair[0]]['name']) for t in BODY_TEMPLATES}:
                raise ValueError('Unsupported advertisement claim')
            placements.add(ad['placement']); pairs.add(pair); seen.add(ad['ad_id'])
    return {'valid':True, 'sites':len(data['sites']), 'ads':len(seen), 'public_sha256':digest(data)}
