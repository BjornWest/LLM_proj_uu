"""Opt-in template 5: grounded value, model sensory tendencies and wording allocation.

Semantics are drawn first. A deterministic least-reused phrase allocator then picks
wording without changing claims or dropping reviews. Historical templates stay intact.
"""
from collections import Counter
from copy import deepcopy
import re
from .generate import digest, stream
from .narrative_phrases import CONTEXTS, JUDGMENTS, VALUE
from .opinion_profiles import COST_RANGES

VERSION = 'product-profile-narratives-v1'
FLAVOURS = {
 'lager': ('bread crust', 'cracker', 'lemon zest', 'fresh bread', 'cereal', 'blossom'),
 'IPA': ('grapefruit', 'orange peel', 'pine', 'mango', 'lemon zest', 'blossom'),
 'stout': ('roasted coffee', 'dark chocolate', 'toast', 'caramel', 'cocoa', 'roasted nuts'),
 'wheat beer': ('banana', 'clove', 'lemon zest', 'bread dough', 'orange peel', 'blossom'),
 'red': ('cherry', 'plum', 'blackberry', 'raspberry', 'blackcurrant', 'black pepper'),
 'white': ('apple', 'pear', 'lemon zest', 'peach', 'grapefruit', 'elderflower'),
 'rosé': ('strawberry', 'raspberry', 'peach', 'redcurrant', 'watermelon', 'cherry'),
}
SENSORY_STARTS = ('', 'After a few sips,', 'With dinner,', 'On my first try,',
                  'After trying a glass,', 'Once I had poured it,', 'As I drank it,', 'On tasting it,')
ENJOYMENT = {
 'positive': ('I really enjoyed the flavour.', 'I liked the taste enough to buy it again.', 'the taste suited me beautifully.',
   'I was glad I had chosen this flavour.', 'this was a pleasure to drink.', 'I found the flavour delicious.',
   'I enjoyed it right to the last mouthful.', 'the flavour was exactly my sort of thing.'),
 'negative': ('I really disliked the taste.', 'I struggled to finish because of the flavour.', 'the taste was not for me at all.',
   'I wished I had picked something else to drink.', 'I found the flavour unpleasant.', 'I disliked it enough to leave some behind.',
   'I would avoid this taste next time.', 'I could not get on with the flavour.'),
 'neutral': ('I found the taste ordinary, neither good nor bad.', 'I had no strong preference for or against the flavour.',
   'the flavour left me indifferent.', 'I found it neither delicious nor unpleasant.', 'I was fairly neutral about the taste.',
   'the taste was unremarkable either way.', 'I neither liked nor disliked the flavour.', 'I had no particular praise or complaint about the taste.'),
 'mixed': ('I liked the aroma but disliked the flavour at the finish.', 'I enjoyed the first impression but disliked the aftertaste.',
   'parts of the flavour appealed to me and others did not.', 'I liked the main flavour but found the finish unpleasant.',
   'I was torn between flavours I liked and ones I disliked.', 'there was both a pleasant and an unpleasant side to the taste.',
   'I enjoyed some of the flavour but could not get on with the rest.', 'the flavour was a mixture of enjoyable and off-putting notes.'),
}
VALUE_GENERIC = {
 'positive': ('Good for the price.', 'Worth what I paid.', 'Good value, in my opinion.', 'A good buy for the money.',
   'Happy with the value here.', 'I got a fair bit for my money.', 'No regrets about the cost.', 'The price makes sense to me.'),
 'negative': ('Not worth what I paid.', 'Poor value, honestly.', 'Too much money for what I got.', 'Not a good deal for me.',
   'The price is difficult to justify.', 'I wish I had kept the money.', 'Disappointing for the price.', 'I paid more than it was worth to me.'),
}
VALUE_LOW = {
 'positive': ('A bargain for me.', 'Cheap and well worth it.', 'Low price, good value.', 'A budget buy I am happy with.',
   'The small outlay was worth it.', 'An inexpensive option that earned its keep.', 'Good value at the cheap end.', 'Glad I tried the cheaper option.'),
 'negative': ('Cheap, I guess, but not worth it.', 'Cheap for a reason, and I regret buying it.',
   'Even at this low price I feel let down.', 'A low price does not make this a good deal.',
   'Inexpensive, but still money wasted for me.', 'Cheap, but I would rather have kept the money.',
   'The budget price does not excuse it for me.', 'I spent very little and still feel I overpaid.'),
}
VALUE_HIGH = {
 'positive': ('Expensive, but worth it to me.', 'A splurge I do not regret.', 'The higher price felt justified.',
   'Costly, but I am happy with the value.', 'I think it earned that premium.', 'I paid more and feel it was worthwhile.',
   'A pricey choice that I would make again.', 'For me, it justified spending extra.'),
 'negative': ('Hard to justify the premium.', 'An expensive disappointment on value.', 'Too pricey for what I got.',
   'The premium feels wasted.', 'I expected more at the expensive end.', 'I regret paying the higher price.',
   'A costly buy that did not earn its keep.', 'I cannot see the value in spending this much.'),
}


def resolve_options(options):
    if not isinstance(options, dict) or set(options) - {'value_mention_probability'}:
        raise ValueError('Unknown narrative options')
    p = options.get('value_mention_probability')
    if p is not None and (type(p) not in (float, int) or not 0 <= p <= 1):
        raise ValueError('Value mention probability must be in [0,1]')
    return {'value_mention_probability': p}


def flavour_pool(product):
    a = product['attributes']
    return FLAVOURS[a['beer_style'] if product['category'] == 'beer' else a['wine_colour']]


def sensory_profile(product, profile, seed):
    r = stream(seed, VERSION + '/sensory/' + profile['model_id'])
    notes = r.sample(flavour_pool(product), 2)
    # A style is not a quality grade. These are fictional impressions, not ingredients.
    full = .8 if profile['archetype'] == 'characterful_drink' else .2 if profile['archetype'] == 'approachable_drink' else .5
    return {'dominant_notes': notes, 'body': 'round' if r.random() < full else 'light'}


def sample_semantics(row, product, profile, seed, config):
    key = row['subject']['id'] + '/' + row['handle']
    r = stream(seed, VERSION + '/value/' + key)
    claims = {a['aspect_id']: a['stance'] for a in row['assessments']}
    from .evidence import PRIMARY
    mention = config['value_mention_probability']
    if mention is None:
        mention = {'budget_basic': .8, 'premium_positioned': .8, 'characterful_drink': .4,
                   'approachable_drink': .4}.get(profile['archetype'], .55)
    value = None
    if r.random() < mention:
        # Historical purchase draw bound to this SKU, independent of current stores/stock.
        factor = r.uniform(.8, 1.2)
        paid = max(100, round(product['reference_price_minor'] * factor / 100) * 100)
        normalized = profile['reference_base_sek'] * paid / product['reference_price_minor']
        lo, hi = COST_RANGES[product['category']]
        relative = (normalized - lo) / (hi - lo)
        tier = 'low' if relative < 1/3 else 'high' if relative > 2/3 else 'middle'
        experience = {'positive': .85, 'negative': .15, 'neutral': .5, 'mixed': .5}.get(claims.get(PRIMARY[product['category']]), profile['execution_mean'])
        score = experience + {'low': .16, 'middle': 0, 'high': -.18}[tier] + r.uniform(-.07, .07)
        stance = 'positive' if score >= .62 else 'negative' if score <= .38 else 'neutral' if .46 <= score <= .54 else 'mixed'
        value = {'stance': stance, 'price_position': tier, 'purchase_price_minor': paid, 'currency': 'SEK',
                 'price_scope': 'historical_purchase_of_exact_sku', 'amount_mentioned': r.random() < .25}
    obs = None
    if product['category'] in ('beer', 'wine'):
        tendency = sensory_profile(product, profile, seed)
        r = stream(seed, VERSION + '/sensory-report/' + key)
        obs = {}
        notes_probability = .85 if profile['archetype'] == 'characterful_drink' else .45
        note = r.random() < notes_probability
        if note:
            pool = tendency['dominant_notes'] if r.random() < .8 else flavour_pool(product)
            obs['flavour_note'] = r.choice(pool)
        if not note or r.random() < .3:
            obs['body'] = tendency['body'] if r.random() < .85 else r.choice(('light', 'round'))
        if 'bitterness' in claims:
            old = row['sensory_observations']
            obs.update({k: old[k] for k in ('bitterness_intensity', 'bitterness_persistence')})
    return value, obs


def _sentences(starts, endings):
    return [start + ' ' + end if start else end[0].upper() + end[1:] for start in starts for end in endings]


def chunk_options(report, product):
    """Every candidate for a chunk states the same structured opinion/observation."""
    chunks = []
    pet = 'dog' if product['category'] == 'dog_food' else 'cat'
    for a in report['assessments']:
        aspect, stance = a['aspect_id'], a['stance']
        if aspect in JUDGMENTS:
            variants = _sentences(CONTEXTS[a['context_id']], [s.format(pet=pet) for s in JUDGMENTS[aspect][stance]])
        elif aspect == 'taste_enjoyment': variants = _sentences(SENSORY_STARTS, ENJOYMENT[stance])
        elif aspect == 'bitterness':
            obs = report['sensory_observations']; intensity = obs['bitterness_intensity']; persistence = obs['bitterness_persistence']
            if stance == 'negative':
                endings = ('I could not taste any bitterness.', 'there was no bitter edge.', 'I picked up no bitter flavour.',
                           'bitterness was absent for me.', 'I found no bitter aftertaste.', 'nothing tasted bitter to me.')
            else:
                amount = ('a slight bitter edge', 'gentle bitterness', 'a little bitterness', 'mild bitterness') if intensity == 'mild' else ('strong bitterness', 'a big bitter kick', 'pronounced bitterness', 'an intense bitter edge')
                tail = ('that faded quickly after swallowing.', 'that cleared soon after each sip.', 'that did not linger.') if persistence == 'brief' else ('that stayed well after swallowing.', 'that lingered between sips.', 'that hung around in the aftertaste.')
                endings = ['I noticed ' + x + ' ' + y for x in amount for y in tail]
            variants = _sentences(SENSORY_STARTS, endings)
        elif aspect == 'dryness':
            endings = ('it tasted dry rather than sweet.', 'the finish was dry.', 'I found no sweetness at the finish.',
                       'I got a dry impression on my palate.', 'there was no sugary finish.', 'it came across as distinctly dry.') if stance == 'positive' else (
                       'it tasted sweet rather than dry.', 'there was sweetness at the finish.', 'I would not describe it as dry.',
                       'I could taste sweetness lingering.', 'the sweet impression stayed with me.', 'I got a sweet finish, not a dry one.')
            variants = _sentences(SENSORY_STARTS, endings)
        else: raise ValueError('Unsupported narrative aspect')
        chunks.append(('aspect:' + aspect, variants))
    obs = report.get('sensory_observations', {})
    if 'flavour_note' in obs:
        note = obs['flavour_note']
        endings = (f'I picked up {note}.', f'the flavour reminded me of {note}.', f'I could make out {note} in the flavour.',
                   f'there was something of {note} in the taste.', f'I noticed {note} coming through.',
                   f'the clearest flavour for me was {note}.', f'I got a hint of {note}.', f'I found a note of {note}.')
        chunks.append(('sensory:note', _sentences(SENSORY_STARTS, endings)))
    if 'body' in obs:
        endings = ('it felt light in the mouth.', 'the body was quite light.', 'there was little weight to it.',
                   'I found it light-bodied.', 'the texture felt light.', 'it was on the lighter side for body.') if obs['body'] == 'light' else (
                   'it felt full in the mouth.', 'the body was rounded and weighty.', 'there was a fair bit of weight to it.',
                   'I found it full-bodied.', 'the texture felt round.', 'it was on the fuller side for body.')
        chunks.append(('sensory:body', _sentences(SENSORY_STARTS, endings)))
    value = report.get('value_opinion')
    if value is not None:
        stance = value['stance']; tier = value['price_position']
        phrases = list(VALUE[stance]) + list(VALUE_GENERIC.get(stance, ()))
        phrases += list((VALUE_LOW if tier == 'low' else VALUE_HIGH if tier == 'high' else {}).get(stance, ()))
        if tier == 'low' and stance == 'positive' and any(a['stance'] == 'positive' and a['aspect_id'] in ('comfort', 'keyboard_comfort', 'pet_acceptance', 'taste_enjoyment') for a in report['assessments']):
            phrases += ['I did not expect this much for what I paid.', 'Better than I expected at this price.', 'Cheap, but a pleasant surprise.']
        # Exact amount is optional; generic value comments remain grounded in the same record.
        if value['amount_mentioned']:
            price = f'{value["purchase_price_minor"] / 100:g} kr'
            a = product['attributes']
            scope = ('the pair' if product['category'] == 'footwear' else 'this configuration' if product['category'] == 'laptops'
                     else f'the {a["net_weight_kg"]} kg pack' if product['category'] in ('dog_food', 'cat_food')
                     else f'the pack of {a["pack_count"]} × {a["volume_ml"]} ml')
            prefixes = (f'I paid {price} for {scope}.', f'My price for {scope} was {price}.', f'This cost me {price} for {scope}.',
                        f'I spent {price} on {scope}.', f'The amount I paid for {scope} was {price}.',
                        f'For {scope}, I handed over {price}.', f'Buying {scope} set me back {price}.',
                        f'My outlay was {price} for {scope}.', f'I got {scope} for {price}.', f'At the time, {scope} cost me {price}.')
            phrases = _sentences(prefixes, phrases)
        chunks.append(('value', phrases))
    return chunks


def normalize(text):
    return ' '.join(re.findall(r"[a-z]+|#", re.sub(r'\d+(?:\.\d+)?', '#', text.lower())))


def grams(text):
    tokens = normalize(text).split()
    return set(tuple(tokens[i:i+5]) for i in range(max(0, len(tokens)-4)))


def sentence_units(text):
    return [normalize(s) for s in re.split(r'(?<=[.!?])\s+', text) if normalize(s)]


class Allocator:
    def __init__(self):
        self.sentences = Counter(); self.ngrams = Counter(); self.bodies = Counter()
        self.exhausted = 0

    def choose(self, candidates, rng, used_openers):
        # Minimise exact reuse first, then repeated five-word phrases. Stable seeded ties.
        def score(i):
            g = grams(candidates[i])
            opener = candidates[i].split(',', 1)[0]
            return (sum(self.sentences[u] for u in sentence_units(candidates[i])), int(opener in used_openers),
                    sum(self.ngrams[x] for x in g) / max(1, len(g)), rng.random())
        idx = min(range(len(candidates)), key=score)
        text = candidates[idx]
        used_openers.add(text.split(',', 1)[0])
        self.exhausted += int(any(self.sentences[u] for u in sentence_units(text)))
        self.sentences.update(sentence_units(text))
        self.ngrams.update(grams(text))
        return idx


def render_narrative(report, product):
    choices = report['narrative_choices']; options = chunk_options(report, product)
    if set(choices) != {'chunks', 'order', 'attribution'} or len(choices['chunks']) != len(options):
        raise ValueError('Invalid narrative choices')
    sentences = []
    for (key, variants), selected in zip(options, choices['chunks']):
        if set(selected) != {'key', 'variant'} or selected['key'] != key or type(selected['variant']) is not int or not 0 <= selected['variant'] < len(variants):
            raise ValueError('Invalid narrative phrase selection')
        sentences.append(variants[selected['variant']])
    order = choices['order']
    if any(type(i) is not int for i in order) or sorted(order) != list(range(len(sentences))):
        raise ValueError('Invalid narrative ordering')
    body = ' '.join(sentences[i] for i in order)
    attribution = choices['attribution']
    if type(attribution) is not int or not 0 <= attribution < 8: raise ValueError('Invalid attribution')
    if report['usage_reports'][0]['experience_kind'] == 'hearsay':
        person = ('dad', 'sister', 'partner', 'colleague', 'brother', 'mum', 'friend', 'neighbour')[attribution]
        body = f'My {person} bought these and told me: “{body}”' if product['category'] == 'footwear' else f'My {person} tried this and told me: “{body}”'
    elif report['usage_reports'][0]['experience_kind'] != 'actual_use': raise ValueError('Narrative requires attributed use')
    value = report.get('value_opinion')
    fields = []
    if value and value['amount_mentioned']:
        if product['category'] in ('beer', 'wine'): fields = ['pack_count', 'volume_ml']
        elif product['category'] in ('dog_food', 'cat_food'): fields = ['net_weight_kg']
    return body, fields


def apply_narratives(world, base, options):
    config = resolve_options(options); result = deepcopy(base)
    seed = base['private_provenance']['seed']; profiles = {p['model_id']: p for p in base['private_provenance']['profile_sampling']['models']}
    products = {p['product_id']: p for p in world['public']['products']}
    allocators = {}; signatures = {}
    for row in result['public']['reviews']:
        product = products[row['subject']['id']]; profile = profiles[row['article_id']]
        value, sensory = sample_semantics(row, product, profile, seed, config)
        old_id = row['review_id']
        row['value_opinion'] = value
        if sensory is not None:
            row['sensory_observations'] = sensory
            signatures[row['article_id']] = sensory_profile(product, profile, seed)
        row['template_version'] = 5
        row['review_id'] = 'review-' + digest([VERSION, old_id, config, value, sensory])[:20]
        row['reviewer_id'] = 'reviewer-' + digest([VERSION, row['reviewer_id'], config])[:20]
        row['source_locator']['fragment'] = row['review_id']
        allocator = allocators.setdefault(row['subject']['id'], Allocator())
        rng = stream(seed, VERSION + '/words/' + row['review_id'])
        options_for_chunks = chunk_options(row, product)
        order = list(range(len(options_for_chunks))); rng.shuffle(order)
        used_openers = set()
        row['narrative_choices'] = {'chunks': [{'key': key, 'variant': allocator.choose(variants, rng, used_openers)} for key, variants in options_for_chunks],
                                    'order': order, 'attribution': rng.randrange(8)}
        row['body'], row['mentioned_attributes'] = render_narrative(row, product)
        allocator.bodies[normalize(row['body'])] += 1
    stats = {'subjects': len(allocators), 'reused_chunks': sum(a.exhausted for a in allocators.values()),
             'duplicate_normalized_bodies': sum(sum(n-1 for n in a.bodies.values()) for a in allocators.values())}
    result['private_provenance']['narrative_sampling'] = {'schema_version': VERSION, 'config': config,
        'source_profile_corpus_sha256': digest(base['public']), 'sensory_profiles': signatures,
        'wording_allocation': 'Per-SKU generation order; least repeated normalized chunk, then five-word overlap; bounded candidate pools.',
        'diversity': stats}
    result['private_provenance']['public_sha256'] = digest(result['public'])
    return result


def generate_narrative_evidence(world, *, profile_options, narrative_options, **kwargs):
    if profile_options is None: raise ValueError('Narratives require product profiles')
    from .evidence import generate_evidence, validate_evidence
    result = apply_narratives(world, generate_evidence(world, profile_options=profile_options, **kwargs), narrative_options)
    validate_evidence(world, result)
    return result


def validate_narrative_binding(world, export):
    from .evidence import generate_evidence
    provenance = export['private_provenance']; meta = provenance['narrative_sampling']
    if meta.get('schema_version') != VERSION: raise ValueError('Unknown narrative sampler')
    base = generate_evidence(world, seed=provenance['seed'], as_of=export['public']['as_of'],
        reviews_per_sku=provenance['reviews_per_sku'], reviewed_variants_per_model=provenance['reviewed_variants_per_model'],
        profile_options=provenance['profile_sampling']['config'])
    expected = apply_narratives(world, base, meta['config'])
    if expected != export: raise ValueError('Narrative corpus differs from its bound semantic/wording draw')
