"""Template 4: reusable drink observations, sampled before their wording.

These are attributed sensory impressions, not ingredients, lab measurements or
catalog facts. Intensity, persistence and enjoyment are different dimensions.
Legacy prose is deliberately kept in evidence_prose.py unchanged.
"""
from .evidence_prose import DETAILS, SLOT_FIELDS

FLAVOURS = {
    'lager': ('bread crust', 'cracker', 'lemon zest'),
    'IPA': ('grapefruit', 'orange peel', 'pine'),
    'stout': ('roasted coffee', 'dark chocolate', 'toast'),
    'wheat beer': ('banana', 'clove', 'lemon zest'),
    'red': ('cherry', 'plum', 'blackberry'),
    'white': ('apple', 'pear', 'lemon zest'),
    'rosé': ('strawberry', 'raspberry', 'peach'),
}
BODY = {
    'light': ('It feels quite light in the mouth.', 'Light-bodied, even after a few mouthfuls.',
              'There is not much weight to it in the mouth.'),
    'round': ('It feels round and quite full in the mouth.', 'There is a fair bit of weight to it.',
              'Full-bodied, with a weighty feel in the mouth.'),
}
BITTERNESS = {
    ('mild', 'brief'): (
        'Just a little bitterness after a sip, and it clears quickly.',
        'A gentle bitter edge at first, gone almost as soon as I swallow.',
        'Slightly bitter, but I do not taste that for long after each sip.'),
    ('mild', 'lingering'): (
        'Only mildly bitter, but that little bitter edge stays with me well after a sip.',
        'The bitterness is gentle rather than strong. I can still taste it between sips.',
        'A faint bitterness hangs around after I swallow.'),
    ('pronounced', 'brief'): (
        'Quite a bitter hit when I take a sip, but it fades quickly after I swallow.',
        'Strong bitterness up front, then it clears surprisingly fast.',
        'The first impression is really bitter. That part does not hang around for long.'),
    ('pronounced', 'lingering'): (
        'Strongly bitter, and I can still taste that bitterness well after I swallow.',
        'A big bitter kick with each sip that lingers in my mouth.',
        'The bitterness is pronounced and stays with me between sips.'),
    ('absent', 'none'): (
        'I did not pick up any bitterness, either during a sip or afterwards.',
        'No bitter edge for me, even at the end of a mouthful.',
        'I cannot taste any bitterness in this.'),
}


def flavour_pool(product):
    attrs = product['attributes']
    return FLAVOURS[attrs['beer_style'] if product['category'] == 'beer' else attrs['wine_colour']]


def sample_observations(product, assessments, rng):
    observations = {'flavour_note': rng.choice(flavour_pool(product)),
                    'body': rng.choice(tuple(BODY))}
    bitter = next((a['stance'] for a in assessments if a['aspect_id'] == 'bitterness'), None)
    if bitter is not None:
        observations['bitterness_intensity'] = rng.choice(('mild', 'pronounced')) if bitter == 'positive' else 'absent'
        observations['bitterness_persistence'] = rng.choice(('brief', 'lingering')) if bitter == 'positive' else 'none'
    return observations


def validate_observations(report, product):
    obs = report.get('sensory_observations')
    if product['category'] not in ('beer', 'wine') or not isinstance(obs, dict):
        raise ValueError('Drink observations required')
    claims = {a['aspect_id']: a['stance'] for a in report['assessments']}
    keys = {'flavour_note', 'body'}
    if 'bitterness' in claims:
        keys |= {'bitterness_intensity', 'bitterness_persistence'}
    if set(obs) != keys or obs['flavour_note'] not in flavour_pool(product) or obs['body'] not in BODY:
        raise ValueError('Invalid drink sensory observations')
    for aspect in ('bitterness', 'dryness'):
        if aspect in claims and claims[aspect] not in ('positive', 'negative'):
            raise ValueError('Template 4 does not assert changing bitterness/dryness')
    if 'bitterness' in claims:
        pair = (obs['bitterness_intensity'], obs['bitterness_persistence'])
        if pair not in BITTERNESS or (pair[0] == 'absent') != (claims['bitterness'] == 'negative'):
            raise ValueError('Bitterness observations contradict assessment')


def render_drink(report, product):
    validate_observations(report, product)
    obs = report['sensory_observations']; choice = report['template_choices']
    n = choice['stance']; note = obs['flavour_note']; body = obs['body']
    claims = {a['aspect_id']: a['stance'] for a in report['assessments']}
    stance = claims.get('taste_enjoyment')
    # Even an indifferent or aspect-omitting review contains concrete observations.
    descriptions = (
        f'I get {note} in the flavour.',
        f'The flavour reminds me of {note}.',
        f'{note.capitalize()} is what comes through for me.')
    statements = [descriptions[n], BODY[body][choice['ending'] % 3]]
    if stance == 'positive':
        statements.append((f'I really like that {note} flavour. This is my sort of drink.',
                           'The flavour and the way it feels in the mouth both work for me. Would buy again.',
                           'Enjoyed it with dinner, especially that flavour. Glad I tried it.')[n])
    elif stance == 'negative':
        statements.append((f'That {note} flavour really is not for me. I left most of my glass.',
                           'I do not like the flavour or the way it feels in my mouth. Would not buy again.',
                           'Not my sort of flavour at all. I struggled to finish a glass.')[n])
    elif stance == 'neutral':
        statements.append(('Perfectly drinkable with dinner, but I would be just as happy with something else.',
                           'Neither a favourite nor one I would avoid. Fine as part of a meal.',
                           'An ordinary dinner drink for me. I neither particularly like nor dislike the flavour.')[n])
    elif stance == 'mixed':
        complaint = 'a bit thin for my taste' if body == 'light' else 'a bit too heavy for my taste'
        statements.append((f'I like the {note} flavour, but it feels {complaint}.',
                           f'Enjoying that {note} note; less keen on the body, which is {complaint}.',
                           f'The flavour is lovely, but the body is {complaint}. Not a clear favourite.')[n])
    if 'bitterness' in claims:
        statements.append(BITTERNESS[(obs['bitterness_intensity'], obs['bitterness_persistence'])][n])
    if 'dryness' in claims:
        statements.append((('Comes across as dry to me, with no sweetness left at the finish.',
                            'Dry on my palate rather than sweet.',
                            'I get a dry finish, without a sugary aftertaste.') if claims['dryness'] == 'positive' else
                           ('There is a sweetness that stays after I swallow. I would not call it dry.',
                            'Tastes sweet to me, rather than dry.',
                            'I can taste sweetness through to the finish; not dry on my palate.'))[n])
    attrs = product['attributes']; family = product['category']; fields = []
    detail = DETAILS[family][choice['facts']]
    if detail:
        slot = 'pack_order' if family == 'beer' else 'vintage'
        value = ('one' if attrs['pack_count'] == 1 else f'a {attrs["pack_count"]}-pack') if family == 'beer' else attrs['vintage']
        # Non-vintage is a product category, not a year someone can have bought.
        if slot == 'vintage' and value == 'non-vintage': detail = 'I bought the non-vintage one.'
        else: detail = detail.format(**{slot: value})
        statements.insert(choice['intro'] % (len(statements) + 1), detail)
        fields.append(SLOT_FIELDS[slot])
    prose = ' '.join(statements); model = product['name'].split(' — ')[0]
    kind = report['usage_reports'][0]['experience_kind']
    if kind == 'hearsay':
        relative = ('dad', 'sister', 'partner', 'colleague')[choice['ending']]
        prose = f'My {relative} tried {model} and said: “{prose}”'
    elif kind == 'actual_use':
        if choice['intro'] == 1: prose = f'Went for {model}. ' + prose
    else:
        raise ValueError('Drink reviews require an attributed experience')
    return prose, fields
