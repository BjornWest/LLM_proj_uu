"""Bounded fictional merchant testimony; public corpus, private authored priors.

No proprietary score, verified-purchase claim, SKU fact or safety oracle. Each
review has an independent store/index stream, so corpus prefixes remain stable.
"""
from collections import Counter
from datetime import date, timedelta
from urllib.parse import urlsplit
import copy

from .config import _number, _weights
from .generator import digest, rng, weighted
from .stores import validate_store_world

VERSION = 'merchant-review-export-v1'
TOPICS = ('delivery', 'communication', 'returns', 'product_condition')
# Each topic has negative, mixed and positive testimony. These refer to fictional
# historical experiences, never current stock, arrival guarantees or SKU facts.
TEXT = {
    'delivery': (
        ('Disappointing delivery', 'My order arrived later than I expected, and the waiting was frustrating.'),
        ('Delivery was a mixed experience', 'The parcel arrived, but the delivery updates could have been clearer.'),
        ('Smooth delivery', 'My parcel arrived when expected and the delivery process went smoothly.')),
    'communication': (
        ('Hard to get an answer', 'I struggled to get a useful response when I contacted the shop.'),
        ('Eventually got an answer', 'It took a few messages, but I eventually got the information I needed.'),
        ('Helpful communication', 'The shop answered my questions clearly and kept me informed.')),
    'returns': (
        ('Frustrating return process', 'I found the return instructions confusing and had trouble getting help.'),
        ('Return took some effort', 'The return was completed, although it took more back-and-forth than I expected.'),
        ('Straightforward return', 'The return instructions were clear and the shop handled my request helpfully.')),
    'product_condition': (
        ('Disappointed with the parcel condition', 'My order arrived in poor condition, which spoiled the experience.'),
        ('Condition was acceptable', 'The packaging looked worn, but the contents appeared fine when I checked them.'),
        ('Arrived in good condition', 'The packaging was intact and my order arrived in good condition.')),
}
ENDINGS = {
    1: ('Overall, I was very disappointed.', 'This was a very poor experience for me.'),
    2: ('Overall, this fell short of my expectations.', 'I was unhappy with the experience overall.'),
    3: ('Overall, it was an average experience.', 'There were good and bad parts to the experience.'),
    4: ('Overall, I was pleased.', 'I had a good experience overall.'),
    5: ('Overall, I was very pleased.', 'This was an excellent experience for me.'),
}


def review_defaults():
    return {'star_weights': {str(n): 1.0 for n in range(1, 6)},
            'topic_weights': {topic: 1.0 for topic in TOPICS},
            'reply_probability': .25, 'company_star_weights': {}}


def resolve_review_config(patch, company_ids):
    cfg = review_defaults()
    if patch is None: return cfg
    if not isinstance(patch, dict) or set(patch) - set(cfg): raise ValueError('Unknown review configuration field')
    for key in ('star_weights', 'topic_weights'):
        if key in patch: cfg[key] = _weights(cfg[key], patch[key], key)
    if 'reply_probability' in patch:
        _number(patch['reply_probability'], 'reply_probability', probability=True)
        cfg['reply_probability'] = patch['reply_probability']
    overrides = patch.get('company_star_weights', {})
    if not isinstance(overrides, dict) or set(overrides) - set(company_ids):
        raise ValueError('Company star priors must reference stores in this world')
    cfg['company_star_weights'] = {id: _weights(cfg['star_weights'], weights, 'company_star_weights')
                                   for id, weights in overrides.items()}
    return copy.deepcopy(cfg)


def statistics(reviews):
    counts = Counter(r['stars'] for r in reviews)
    return {'review_count': len(reviews), 'star_counts': {str(n): counts[n] for n in range(1, 6)},
            'mean_stars': sum(r['stars'] for r in reviews) / len(reviews) if reviews else None}


def generate_reviews(world, seed=0, as_of='2026-09-25', reviews_per_store=24, config=None):
    validate_store_world(world)
    if type(seed) is not int: raise ValueError('seed must be an integer')
    if type(reviews_per_store) is not int or not 0 <= reviews_per_store <= 200:
        raise ValueError('reviews_per_store must be 0..200')
    if not isinstance(as_of, str): raise ValueError('as_of must be an ISO calendar date')
    try: today = date.fromisoformat(as_of)
    except ValueError: raise ValueError('as_of must be an ISO calendar date') from None
    if today.isoformat() != as_of or today < date(2, 2, 1): raise ValueError('as_of must be YYYY-MM-DD on or after 0002-02-01')
    stores = world['public']['retailers']
    cfg = resolve_review_config(config, [s['retailer_id'] for s in stores])
    companies = []
    for store in stores:
        id = store['retailer_id']
        priors = cfg['company_star_weights'].get(id, cfg['star_weights'])
        reviews = []
        for i in range(reviews_per_store):
            ns = f'{VERSION}/{id}/{i}'
            stars = weighted(rng(seed, ns+'/stars'), list(range(1,6)), [priors[str(n)] for n in range(1,6)])
            topic = weighted(rng(seed, ns+'/topic'), list(TOPICS), [cfg['topic_weights'][t] for t in TOPICS])
            title, body = TEXT[topic][0 if stars <= 2 else (1 if stars == 3 else 2)]
            body += ' ' + rng(seed, ns+'/body').choice(ENDINGS[stars])
            age = rng(seed, ns+'/publication').randint(0, 364)
            published = today - timedelta(days=age)
            experience = published - timedelta(days=rng(seed, ns+'/experience').randint(0, 21))
            reply = None
            if rng(seed, ns+'/reply').random() < cfg['reply_probability']:
                reply = {'body': ('We are sorry to hear about your experience. Please contact our team so we can look into it.' if stars <= 2 else
                                 'Thank you for sharing your feedback. We appreciate hearing about your experience.'),
                         'published_date': (published + timedelta(days=rng(seed, ns+'/reply-date').randint(0, min(age, 14)))).isoformat()}
            reviews.append({'review_id': f'review-{id}-{i+1:04d}',
                'reviewer': {'handle': 'shopper_' + digest([VERSION, seed, id, i])[:12]},
                'stars': stars, 'title': title, 'body': body, 'experience_date': experience.isoformat(),
                'published_date': published.isoformat(), 'topic': topic, 'company_reply': reply})
        companies.append({'company_id': id, 'name': store['name'], 'domain': urlsplit(store['site_url']).netloc,
            'website_url': store['site_url'], 'category': store['specialization'],
            'reviews': reviews, 'statistics': statistics(reviews)})
    public = {'as_of': as_of, 'companies': companies}
    return {'schema_version': VERSION, 'public': public,
        'private_provenance': {'seed': seed, 'reviews_per_store': reviews_per_store, 'config': cfg,
            'source_world_sha256': world['world_sha256'], 'public_sha256': digest(public),
            'sampling': 'Independent per-company/per-review streams; authored, uncalibrated star/topic priors; no time trend',
            'evidence_boundary': 'Fictional historical testimony, not generated commerce events or latent merchant safety proof',
            'aggregation': 'Complete bounded corpus; arithmetic mean of stars, not TrustScore'}}
