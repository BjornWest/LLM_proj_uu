"""Authored fictional retailer names, selected from the merchant's home geography."""
from .generator import rng


def naming_locale(country, city_id=None):
    # City-aware defaults for the multilingual countries in our bundled city set.
    if country == 'BE': return 'NL' if city_id == 'antwerp' else 'FR'
    if country == 'CH': return 'FR' if city_id == 'geneva' else 'DE'
    return {'AT':'DE', 'LU':'FR', 'IE':'GB'}.get(country, country)


# Five terms, in specialization order: footwear, electronics, pets, drinks, marketplace.
KINDS = {
    'SE': ('Skor','Datorbutik','Djurbutik','Drycker','Marknad'),
    'NO': ('Sko','Data','Dyrebutikk','Drikkevarer','Handel'),
    'DK': ('Sko','Computerbutik','Dyrebutik','Drikkevarer','Handel'),
    'FI': ('Kenkäkauppa','Tietokonekauppa','Eläinkauppa','Juomakauppa','Tavaratalo'),
    'IS': ('Skór','Tölvur','Gæludýr','Vín og bjór','Verslun'),
    'GB': ('Shoes','Computers','Pet Supplies','Wine & Beer','Market'),
    'NL': ('Schoenen','Computers','Dierenspeciaalzaak','Dranken','Warenhuis'),
    'FR': ('Chaussures','Informatique','Animalerie','Vins et Bières','Maison'),
    'DE': ('Schuhe','Computer','Tierbedarf','Getränke','Kaufhaus'),
    'ES': ('Calzados','Informática','Mascotas','Vinos y Cervezas','Almacenes'),
    'PT': ('Calçado','Informática','Animais','Vinhos e Cervejas','Armazéns'),
    'IT': ('Calzature','Informatica','Animali','Vini e Birre','Emporio'),
}
BRANDS = {
    'SE': ('Björk','Ekdal','Lind','Sund','Viken','Åsen'),
    'NO': ('Bjørk','Fjell','Lunden','Vik','Hagen','Åsen'),
    'DK': ('Birk','Egelund','Lind','Sund','Vang','Høj'),
    'FI': ('Koivu','Laakso','Niemi','Salo','Kallio','Ranta'),
    'IS': ('Lind','Fjall','Hraun','Berg','Tindur','Mýri'),
    'GB': ('Alder','Oakfield','Willow','Brook','Hillford','Westmere'),
    'IE': ('Rowan','Glenmore','Ashgrove','Clonvale','Briar','Loughview'),
    'NL': ('Linde','Eikenhof','Duin','Veld','Waterkant','Haven'),
    'FR': ('Delorme','Deschamps','Clairmont','Rivière','Vallier','Morel'),
    'DE': ('Linde','Eichenhof','Bergmann','Wiesenbach','Talblick','Stein'),
    'ES': ('Oliva','Robles','Vega','Sierra','Rivera','Encina'),
    'PT': ('Oliveira','Carvalho','Faria','Vale','Monte','Ribeiro'),
    'IT': ('Bellini','Rovere','Monti','Fontana','Valle','Moretti'),
}
SPECIALIZATIONS = ('footwear','electronics','pets','drinks','marketplace')


def retailer_name(seed, retailer_id, ordinal, profile, country, city_id=None):
    locale = naming_locale(country, city_id)
    if locale not in KINDS: raise ValueError('Unsupported retailer naming locale')
    brand = rng(seed, retailer_id+'/name').choice(BRANDS.get(country, BRANDS[locale]))
    kind = KINDS[locale][SPECIALIZATIONS.index(profile)]
    words = (kind, brand) if locale in ('FR','ES','PT','IT') else (brand, kind)
    return ' '.join(words) + f' {ordinal:02d}'
