"""Small authored area vocabulary; offsets approximate areas, not surveyed boundaries."""
import math
from .naming import naming_locale

# Name references in data/README.md. Relative anchors are authored estimates.
NAMED_AREAS = {
    'uppsala': [('Luthagen',-.9,1.1),('Fålhagen',1,.1),('Kungsängen',.4,-1.1)],
    'malmo': [('Västra Hamnen',-1.4,1),('Möllevången',.3,-1.6),('Sorgenfri',1.7,-1)],
    'copenhagen': [('Vesterbro',-1.5,-.4),('Nørrebro',-1.2,2),('Østerbro',1.2,2.8),('Christianshavn',1.2,-.4)],
    'amsterdam': [('De Pijp',.6,-2.4),('Oud-West',-1.8,-1.2),('Oost',2.8,-1.6)],
}
LABELS = {
    'SE': ('Centrum','Öster','Nordost','Norr','Nordväst','Väster','Sydväst','Söder','Sydost','Yttre'),
    'DK': ('Centrum','Øst','Nordøst','Nord','Nordvest','Vest','Sydvest','Syd','Sydøst','Ydre'),
    'NO': ('Sentrum','Øst','Nordøst','Nord','Nordvest','Vest','Sørvest','Sør','Sørøst','Ytre'),
    'NL': ('Centrum','Oost','Noordoost','Noord','Noordwest','West','Zuidwest','Zuid','Zuidoost','Buiten'),
    'FR': ('Centre','Est','Nord-est','Nord','Nord-ouest','Ouest','Sud-ouest','Sud','Sud-est','Périphérie'),
    'DE': ('Zentrum','Ost','Nordost','Nord','Nordwest','West','Südwest','Süd','Südost','Außenbereich'),
    'FI': ('Keskusta','Itä','Koillinen','Pohjoinen','Luode','Länsi','Lounas','Etelä','Kaakko','Ulkoalue'),
    'IS': ('Miðbær','Austur','Norðaustur','Norður','Norðvestur','Vestur','Suðvestur','Suður','Suðaustur','Úthverfi'),
    'ES': ('Centro','Este','Noreste','Norte','Noroeste','Oeste','Suroeste','Sur','Sureste','Periferia'),
    'PT': ('Centro','Este','Nordeste','Norte','Noroeste','Oeste','Sudoeste','Sul','Sudeste','Periferia'),
    'IT': ('Centro','Est','Nord-est','Nord','Nord-ovest','Ovest','Sud-ovest','Sud','Sud-est','Periferia'),
}
ENGLISH = ('Centre','East','Northeast','North','Northwest','West','Southwest','South','Southeast','Outer')


def city_areas(city):
    result=[{'area_id':f"{city['city_id']}-named-{i}",'name':name,'east_km':east,'north_km':north,
             'kind':'named_area_approximate_anchor'}
            for i,(name,east,north) in enumerate(NAMED_AREAS.get(city['city_id'],[]))]
    labels=LABELS.get(naming_locale(city['country'],city['city_id']),ENGLISH)
    result.append({'area_id':city['city_id']+'-centre','name':labels[0],'east_km':0,'north_km':0,'kind':'synthetic_sector'})
    for i in range(12):
        direction=i if i<8 else (i-8)*2
        radius=1.8 if i<8 else 3.6
        angle=direction*math.pi/4
        result.append({'area_id':f"{city['city_id']}-sector-{i}",
            'name':(labels[-1]+' ' if i>=8 else '')+labels[direction+1],
            'east_km':radius*math.cos(angle),'north_km':radius*math.sin(angle),'kind':'synthetic_sector'})
    return result
