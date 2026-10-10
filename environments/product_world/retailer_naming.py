"""Fictional fresh-world shop names; identity stays in retailer_id, not prose.

The old naming module remains a legacy recipe. These independent streams only
select names, without touching population, geography, prices or availability.
"""
from .generator import rng
from .naming import BRANDS, KINDS, SPECIALIZATIONS, naming_locale

VERSION = 'retailer-names-v2'
PROFILES = (*SPECIALIZATIONS, 'apparel')

# Complete names deliberately mix short brands, traditional shops and modern
# storefronts. A shop need not put its entire scope in its name; discovery owns
# the separate assortment description.
LOCAL = {
    'SE': ('Stråk', 'Kvarteret', 'Lilla Torget', 'Sund & Co', 'Valvet',
           'Mellanrum', 'Hamnmagasinet', 'Form & Funktion', 'Nära', 'Gläntan',
           'Lindbergs', 'Södra Kompaniet'),
    'NO': ('Lysning', 'Torghjørnet', 'Varde', 'Hagen & Co', 'Bryggen',
           'Nær', 'Fjellboden', 'Nordlys', 'Lunden', 'Vik Handel'),
    'DK': ('Birk & Co', 'Torvehuset', 'Lysningen', 'Krogen', 'Vesterbro Handel',
           'Lindholm', 'Sundsted', 'Nærvær', 'Hjørnet', 'Egelund'),
    'FI': ('Aava', 'Kulmakauppa', 'Koivu & Co', 'Toritalo', 'Valo',
           'Rantapuoti', 'Kallion Kauppa', 'Niemi', 'Salo', 'Laakson Puoti'),
    'IS': ('Lind', 'Hraun', 'Berg & Co', 'Tindur', 'Mýri',
           'Sund', 'Norðurljós', 'Fjallabúðin', 'Hlíð', 'Lundur'),
    'GB': ('The Arcade', 'Westmere', 'Alder & Co', 'The Corner Shop', 'Fieldwork',
           'Willow House', 'Brook Lane', 'Oakfield Trading', 'Common Ground', 'The Good Find'),
    'NL': ('De Hoek', 'Havenhuis', 'Linde & Co', 'Het Pakhuis', 'Duin',
           'De Marktzaal', 'Eikenhof', 'Waterkant', 'Veldhuis', 'De Kleine Zaak'),
    'FR': ('Le Comptoir', 'Maison Vallier', 'Les Arcades', 'Delorme & Cie', 'Clairmont',
           'La Petite Halle', 'La Traverse', 'Rivière', 'Deschamps', 'Le Passage'),
    'DE': ('Lindenhof', 'Bergmann & Co', 'Das Kontor', 'Steinhaus', 'Talblick',
           'Die Ecke', 'Wiesenbach', 'Am Markt', 'Nordlicht', 'Eichenhof'),
    'ES': ('La Esquina', 'Casa Vega', 'El Portal', 'Oliva & Co', 'La Galería',
           'Sierra', 'El Encuentro', 'Robles', 'La Plaza', 'Casa Rivera'),
    'PT': ('A Esquina', 'Casa Vale', 'O Mercado', 'Ribeiro & Co', 'A Galeria',
           'Carvalho', 'Monte', 'O Armazém', 'Casa Faria', 'Oliveira'),
    'IT': ('La Bottega', 'Casa Rovere', 'Il Portico', 'Bellini & Co', 'Fontana',
           'La Galleria', 'Monti', 'Emporio Valle', 'Moretti', 'Il Cortile'),
}

# Neutral invented names can be reused across scopes and naming locales. They
# carry no persistent price/quality profile across worlds.
NEUTRAL = ('Lumero', 'Virela', 'Kavelo', 'Omari', 'Terava', 'Luneti', 'Navora',
           'Maveli', 'Eloro', 'Veluma', 'Soreno', 'Avora', 'Tenari', 'Veska',
           'Arvella', 'Nuvio', 'Merato', 'Seluna', 'Koriva', 'Talora', 'Esvero',
           'Noravo', 'Livora', 'Verendi', 'Rovela', 'Montiva', 'Averio', 'Oveli',
           'Caluno', 'Vireto', 'Lumeri', 'Orenda')

SCOPED = {
    'SE': {
        'footwear': ('Stegvis', 'Skomagasinet', 'På Foten', 'Stad & Stig', 'Skohörnan'),
        'electronics': ('Krets', 'Teknikrummet', 'Pixelboden', 'Signal & System', 'Digitala Torget'),
        'pets': ('Tass & Nos', 'Djurhörnan', 'Foderboden', 'Fyrbenta Vänner'),
        'drinks': ('Humle & Druva', 'Flaskboden', 'Källaren', 'Druvriket'),
        'marketplace': ('Allting', 'Torghallen', 'Vardagsvaror', 'Stora Magasinet'),
        'apparel': ('Tråd', 'Garderoben', 'Systrarnas', 'Tyg & Form', 'Vardagsrum'),
    },
    'GB': {
        'footwear': ('Goodstride', 'Sole House', 'Town & Trail', 'The Shoe Room', 'Footpath'),
        'electronics': ('Circuit House', 'Signal Works', 'Pixel Yard', 'The Digital Room'),
        'pets': ('Paw & Pantry', 'The Feed Room', 'Four Paws', 'Companion Corner'),
        'drinks': ('Hop & Vine', 'The Bottle Room', 'Cellar Door', 'Barrel House'),
        'marketplace': ('Everyday Goods', 'The Trading Hall', 'Open Market', 'Town Stores'),
        'apparel': ('Thread House', 'The Wardrobe', 'Cloth & Cut', 'Everyday Wear'),
    },
}
APPAREL = {'SE': 'Kläder', 'NO': 'Klær', 'DK': 'Tøj', 'FI': 'Vaatteet',
           'IS': 'Fatnaður', 'GB': 'Clothing', 'NL': 'Kleding', 'FR': 'Vêtements',
           'DE': 'Bekleidung', 'ES': 'Ropa', 'PT': 'Roupa', 'IT': 'Abbigliamento'}


def pools(profile, country, city_id=None):
    locale = naming_locale(country, city_id)
    if profile not in PROFILES or locale not in LOCAL:
        raise ValueError('Unsupported retailer naming profile or locale')
    roots = BRANDS.get(country, BRANDS[locale])
    kind = APPAREL[locale] if profile == 'apparel' else KINDS[locale][SPECIALIZATIONS.index(profile)]
    scoped = SCOPED.get(locale, {}).get(profile)
    if scoped is None:
        scoped = tuple(f'{kind} {root}' if locale in ('FR', 'ES', 'PT', 'IT')
                       else f'{root} {kind}' for root in roots)
    # A larger, low-weight support avoids numeric suffixes even in large worlds.
    # These are retail wordmarks, not extra stores or geography/brand profiles.
    extended = tuple(f'{root} & {name}' for root in roots for name in NEUTRAL)
    return ((.65, (*LOCAL[locale], *NEUTRAL)), (.25, scoped), (.10, extended))


def allocate(seed, retailers):
    """Pick without replacement across this world, independent of input order.

    Retailers supply retailer_id, profile, country and optional city_id. IDs are
    used only as private RNG keys and output mapping keys, never as name text.
    """
    if type(seed) is not int or seed < 0:
        raise ValueError('Retailer naming seed must be a nonnegative integer')
    rows = list(retailers)
    if any(type(row) is not dict or set(row) - {'retailer_id', 'profile', 'country', 'city_id'}
           or not all(type(row.get(key)) is str and row[key]
                      for key in ('retailer_id', 'profile', 'country')) for row in rows):
        raise ValueError('Declare retailer identity, profile and home country')
    if len({row['retailer_id'] for row in rows}) != len(rows):
        raise ValueError('Duplicate retailer naming identity')
    result, used = {}, set()
    for row in sorted(rows, key=lambda row: row['retailer_id']):
        available = [(weight, tuple(dict.fromkeys(name for name in names if name.casefold() not in used)))
                     for weight, names in pools(row['profile'], row['country'], row.get('city_id'))]
        available = [(weight, names) for weight, names in available if names]
        if not available:
            raise ValueError('Retailer name pool exhausted; expand names instead of adding indices')
        stream = rng(seed, VERSION + '/' + row['retailer_id'])
        point = stream.random() * sum(weight for weight, _ in available)
        names = available[-1][1]
        for weight, candidates in available:
            point -= weight
            if point < 0:
                names = candidates
                break
        name = stream.choice(names)
        result[row['retailer_id']] = name
        used.add(name.casefold())
    return result
