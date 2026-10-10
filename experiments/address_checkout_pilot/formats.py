"""Coarse national formatting, not real postcode validity or street geocoding."""
import re
import unicodedata

COUNTRIES = {
    'AT': ('Austria', 'numeric4', 'Parkgasse', 'Wohnung', 'aut'),
    'BE': ('Belgium', 'numeric4', 'Rue des Tilleuls', 'Apartment / appartement', 'bel'),
    'CH': ('Switzerland', 'numeric4', 'Lindenweg', 'Wohnung / appartement', 'che'),
    'DE': ('Germany', 'numeric5', 'Lindenstraße', 'Wohnung', 'deu'),
    'DK': ('Denmark', 'numeric4', 'Birkevej', 'Lejlighed', 'dnk'),
    'ES': ('Spain', 'numeric5', 'Calle del Olmo', 'Piso / puerta', 'esp'),
    'FI': ('Finland', 'numeric5', 'Koivukuja', 'Asunto', 'fin'),
    'FR': ('France', 'numeric5', 'Rue des Tilleuls', 'Appartement', 'fra'),
    'GB': ('United Kingdom', 'uk', 'Willow Lane', 'Flat', 'gbr'),
    'IE': ('Ireland', 'ireland', 'Willow Grove', 'Apartment', 'irl'),
    'IS': ('Iceland', 'numeric3', 'Birkiás', 'Íbúð', 'isl'),
    'IT': ('Italy', 'numeric5', 'Via dei Tigli', 'Interno', 'ita'),
    'LU': ('Luxembourg', 'numeric4', 'Rue des Tilleuls', 'Appartement', 'lux'),
    'NL': ('Netherlands', 'netherlands', 'Lindenlaan', 'Toevoeging / appartement', 'nld'),
    'NO': ('Norway', 'numeric4', 'Bjørkeveien', 'Bolignummer', 'nor'),
    'PT': ('Portugal', 'portugal', 'Rua das Oliveiras', 'Andar / apartamento', 'prt'),
    'SE': ('Sweden', 'sweden', 'Björkvägen', 'Lägenhetsnummer', 'swe'),
}


def folded(value):
    """Case/whitespace and Unicode normalization; never guess spelling corrections."""
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def postcode(country, value):
    if country not in COUNTRIES:
        raise ValueError('Unsupported country')
    if not isinstance(value, str):
        raise ValueError('Postcode must be text')
    text = unicodedata.normalize('NFKC', value).strip().upper()
    kind = COUNTRIES[country][1]
    if country == 'LU' and text.startswith('L-'):
        text = text[2:]
    if kind == 'portugal':
        text = re.sub(r'[\s\-–]', '', text)
        pattern = r'[0-9]{7}'
    else:
        text = re.sub(r'\s', '', text)
        pattern = {'numeric3': r'[0-9]{3}', 'numeric4': r'[0-9]{4}',
                   'numeric5': r'[0-9]{5}', 'sweden': r'[0-9]{5}',
                   'netherlands': r'[0-9]{4}[A-Z]{2}',
                   'ireland': r'(?:[A-Z][0-9]{2}|D6W)[A-Z0-9]{4}',
                   'uk': r'(?:[A-Z]{1,2}[0-9][A-Z0-9]?|GIR)[0-9][A-Z]{2}'}[kind]
    if not re.fullmatch(pattern, text):
        raise ValueError('Postcode does not match the prototype country format')
    return text


def display_postcode(country, compact):
    kind = COUNTRIES[country][1]
    if kind == 'sweden':
        return compact[:3] + ' ' + compact[3:]
    if kind == 'netherlands':
        return compact[:4] + ' ' + compact[4:]
    if kind == 'portugal':
        return compact[:4] + '-' + compact[4:]
    if kind == 'ireland':
        return compact[:3] + ' ' + compact[3:]
    if kind == 'uk':
        return compact[:-3] + ' ' + compact[-3:]
    return compact


def make_postcodes(country, rng, count):
    result = []
    alphabet = 'ABCEHJKMNPRSTVWXY'
    while len(result) < count:
        kind = COUNTRIES[country][1]
        if kind == 'uk':
            code = f"{rng.choice(('AB', 'EH', 'SW', 'NE'))}{rng.randint(1, 99)}{rng.randrange(10)}{rng.choice(alphabet)}{rng.choice(alphabet)}"
        elif kind == 'ireland':
            code = f"{rng.choice(alphabet)}{rng.randint(10, 99)}" + ''.join(rng.choice(alphabet + '0123456789') for _ in range(4))
        elif kind == 'netherlands':
            code = str(rng.randint(1000, 9999)) + rng.choice(alphabet) + rng.choice(alphabet)
        elif kind == 'portugal':
            code = f'{rng.randint(1000, 9999)}{rng.randrange(1000):03d}'
        else:
            length = 3 if kind == 'numeric3' else 4 if kind == 'numeric4' else 5
            code = f'{rng.randrange(10 ** length):0{length}d}'
            if country == 'FI':
                code = code[:-1] + '0'
        if code not in result:
            result.append(code)
    return [display_postcode(country, c) for c in result]


def address_lines(address):
    country = address['country']
    name = address.get('recipient', '')
    street, house = address.get('street', ''), address.get('house_number', '')
    street_line = f'{house} {street}' if country in ('GB', 'IE', 'FR') else f'{street} {house}'
    unit = address.get('unit', '')
    unit_line = f'{COUNTRIES[country][3]} {unit}' if unit else ''
    city, code = address.get('city', ''), address.get('postcode', '')
    locality = [city, code] if country in ('GB', 'IE') else [f'{code} {city}']
    return [line.strip() for line in [name, street_line, unit_line, *locality, COUNTRIES[country][0]] if line.strip()]


def metadata():
    return [{'country': code, 'name': row[0], 'postcode_kind': row[1], 'unit_label': row[3],
             'source': f'https://www.upu.int/UPU/media/upu/PostalEntitiesFiles/addressingUnit/{row[4]}En.pdf',
             'scope': 'Simplified fictional-address formatting; not national validation or real postal boundaries.'}
            for code, row in sorted(COUNTRIES.items())]
