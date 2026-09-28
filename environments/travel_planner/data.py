"""Validated public-only travel data, usable independently of world-generation code."""
import math
import unicodedata


def normalized(text):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c)).split())


class Catalog:
    def __init__(self, public):
        if set(public)!={'places','modes','trips'}:raise ValueError('Unexpected public travel fields')
        if public['modes'] not in (['walking','driving'], ['walking','cycling','driving']):raise ValueError('Unsupported travel modes')
        self.places={}
        for p in public['places']:
            if not isinstance(p.get('place_id'),str) or not p['place_id'] or p['place_id'] in self.places:raise ValueError('Duplicate/invalid place ID')
            if p['kind'] not in ('saved_place','branch') or any(not isinstance(p[k],str) or not p[k] for k in ('name','label','city','country')):raise ValueError('Invalid place')
            if not isinstance(p['aliases'],list) or any(not isinstance(a,str) for a in p['aliases']):raise ValueError('Invalid aliases')
            self.places[p['place_id']]=p
        if not 1<=len(self.places)<=161:raise ValueError('Travel catalog supports 1..161 places')
        self.trips={}
        for t in public['trips']:
            key=(t['origin_id'],t['destination_id'],t['mode'])
            if key in self.trips or key[0] not in self.places or key[1] not in self.places or key[2] not in public['modes']:raise ValueError('Invalid trip binding')
            if t['status']=='estimated':
                if type(t['distance_km']) not in (int,float) or not math.isfinite(t['distance_km']) or t['distance_km']<0 or type(t['duration_minutes']) is not int or t['duration_minutes']<0:raise ValueError('Invalid trip metrics')
            elif t['status']=='not_modelled':
                if t['distance_km'] is not None or t['duration_minutes'] is not None:raise ValueError('Unknown route must have null metrics')
            else:raise ValueError('Unknown trip status')
            self.trips[key]=t
        if len(self.trips)!=len(public['modes'])*len(self.places)**2:raise ValueError('Incomplete trip matrix')
        self.public=public

    def search(self, query='', kind=None):
        terms=normalized(query).split()
        matches=[]
        for place in self.places.values():
            if kind and place['kind']!=kind:continue
            haystack=normalized(' '.join([place['place_id'],place['label'],place['city'],place['country'],*place['aliases']]))
            if all(t in haystack for t in terms):matches.append(place)
        return sorted(matches,key=lambda p:(normalized(p['name']),p['place_id']))

    def resolve(self, query):
        if not query.strip():return []
        if query in self.places:return [self.places[query]]
        exact=[p for p in self.places.values() if normalized(query) in [normalized(p['label']),*[normalized(a) for a in p['aliases']]]]
        return exact or self.search(query)

    def trip(self, origin, destination, mode):
        if (origin,destination,mode) not in self.trips:raise ValueError('Choose known places and a supported travel mode')
        return self.trips[(origin,destination,mode)]
