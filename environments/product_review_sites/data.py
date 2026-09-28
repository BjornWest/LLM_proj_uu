"""Validate an answer-free public export and implement deterministic page queries."""
from copy import deepcopy
from datetime import date
from urllib.parse import urlsplit
import math
from environments.shopping_intent.catalog import FAMILIES as ATTRIBUTES
from .generate import FAMILIES, stats
from .facets import describe, compile_filters, matches

LAYOUTS=('lab-directory','editorial-magazine','community-feed')
NAMES={
    'footwear':('Stride Ledger','Footnote Review','Trail & Tread'),
    'laptops':('Circuit Journal','Notebook Bench','The Hardware Desk'),
    'dog_food':('Bowl Notes','Pet Recipe Review','The Feeding Desk'),
    'cat_food':('Bowl Notes','Pet Recipe Review','The Feeding Desk'),
    'beer':('Malt Circle','Brew Ledger','Glass Notes'),
    'wine':('Vine Ledger','Glass Notes','Cellar Circle'),
}


def text(value):
    if not isinstance(value,str) or not value.strip():raise ValueError('Nonempty text required')
    return value


def iso(value):
    if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:raise ValueError('ISO date required')
    return value


def pretty(value):
    if type(value) is bool:return 'Yes' if value else 'No'
    if isinstance(value,list):return ', '.join(map(str,value)) or 'None listed'
    return str(value)


def field_info(family,key):
    a=next((a for a in ATTRIBUTES[family].attributes if a.key==key),None)
    return (a.label[:1].upper()+a.label[1:],a.unit) if a else (key.replace('_',' ').capitalize(),None)


def fact_text(variant,key):
    _,unit=field_info(variant['family'],key)
    return pretty(variant['facts'][key])+(' '+unit if unit else '')


class Catalog:
    def __init__(self,public,*,families=None,bindings=None):
        if not isinstance(public,dict) or set(public)!={'as_of','articles','variants'}:raise ValueError('Only product-review-export-v1 public accepted')
        self.public=deepcopy(public);self.as_of=iso(public['as_of'])
        if not isinstance(public['articles'],list) or not isinstance(public['variants'],list):raise ValueError('Lists required')
        self.variants={};self.by_id={}
        for v in self.public['variants']:
            if set(v)!={'sku','model_id','name','family','facts'}:raise ValueError('Unexpected variant fields')
            for k in ('sku','model_id','name','family'):text(v[k])
            if v['sku'] in self.variants or v['family'] not in FAMILIES or not isinstance(v['facts'],dict):raise ValueError('Invalid variant')
            for k,value in v['facts'].items():
                text(k)
                if isinstance(value,list):
                    if not all(isinstance(x,str) for x in value):raise ValueError('String set expected')
                elif type(value) not in (str,int,float,bool) or (type(value) is float and not math.isfinite(value)):raise ValueError('Invalid fact')
            self.variants[v['sku']]=v
        for a in self.public['articles']:
            if set(a)!={'id','model_name','family','reviewed_sku','published','author','reader_opinions','reader_statistics'}:raise ValueError('Unexpected article fields')
            for k in ('id','model_name','family','reviewed_sku','author'):text(a[k])
            if a['id'] in self.by_id or not iso(a['published'])<=self.as_of:raise ValueError('Invalid article/date')
            v=self.variants.get(a['reviewed_sku'])
            if v is None or v['model_id']!=a['id'] or v['family']!=a['family']:raise ValueError('Wrong reviewed configuration')
            ids=set()
            if not isinstance(a['reader_opinions'],list):raise ValueError('Opinions must be list')
            for c in a['reader_opinions']:
                if set(c)!={'id','handle','stars','title','body','date'}:raise ValueError('Unexpected opinion fields')
                for k in ('id','handle','title','body'):text(c[k])
                if c['id'] in ids or type(c['stars']) is not int or not 1<=c['stars']<=5:raise ValueError('Invalid opinion/rating')
                if not a['published']<=iso(c['date'])<=self.as_of:raise ValueError('Opinion date outside corpus')
                ids.add(c['id'])
            expected=stats(a['reader_opinions']);given=a['reader_statistics']
            if not isinstance(given,dict) or set(given)!=set(expected) or given!=expected:raise ValueError('Inconsistent statistics')
            if type(given['count']) is not int or any(type(x) is not int for x in given['histogram'].values()) or type(given['mean']) is bool:raise ValueError('Invalid statistic types')
            self.by_id[a['id']]=a
        if any(v['model_id'] not in self.by_id for v in self.variants.values()):raise ValueError('Orphan variant')
        self.families=tuple(families) if families is not None else tuple(sorted({a['family'] for a in self.by_id.values()}))
        if not self.families or len(set(self.families))!=len(self.families) or set(self.families)-set(FAMILIES):raise ValueError('Invalid site family scope')
        self.articles=[a for a in self.by_id.values() if a['family'] in self.families]
        self.by_id={a['id']:a for a in self.articles}
        self.variants={k:v for k,v in self.variants.items() if v['family'] in self.families}
        self.bindings=dict(bindings or {})
        for sku,url in self.bindings.items():
            u=urlsplit(url)
            if sku not in self.variants or u.scheme not in ('http','https') or not u.hostname or u.username or u.password:raise ValueError('Explicit known-SKU HTTP binding required')

    def facets(self):
        return describe([self.variants[a["reviewed_sku"]] for a in self.articles])

    def find(self,q):
        terms=q.get('q','').casefold().split();family=q.get('family','');field=q.get('field','');value=q.get('value','')
        if family and family not in self.families:raise ValueError('Family outside this site')
        if bool(field)!=bool(value):raise ValueError('Attribute and value required together')
        known={k for a in self.articles for k in self.variants[a['reviewed_sku']]['facts']}
        if field and field not in known:raise ValueError('Unknown attribute')
        filters=compile_filters(q,self.facets())
        rows=[]
        for a in self.articles:
            v=self.variants[a['reviewed_sku']]
            haystack=' '.join([a['model_name'],v['name'],v['sku'],a['family'],*(pretty(x) for x in v['facts'].values())]).casefold()
            if family and a['family']!=family or not all(t in haystack for t in terms):continue
            if field:
                actual=v['facts'].get(field)
                legacy_match=value.casefold() in [str(x).casefold() for x in actual] if isinstance(actual,list) else value.casefold()==pretty(actual).casefold()
                if actual is None or not legacy_match:continue
            if not matches(v['facts'],filters):continue
            rows.append(a)
        mode=q.get('sort','name')
        if mode=='rating':rows.sort(key=lambda a:(-(a['reader_statistics']['mean'] or 0),a['id']))
        elif mode=='newest':rows.sort(key=lambda a:(-date.fromisoformat(a['published']).toordinal(),a['id']))
        else:rows.sort(key=lambda a:(a['model_name'].casefold(),a['id']))
        return rows

    def opinions(self,a,q):
        rows=[c for c in a['reader_opinions'] if not q.get('stars') or c['stars']==int(q['stars'])]
        if q.get('sort')=='lowest':return sorted(rows,key=lambda c:(c['stars'],c['id']))
        return sorted(rows,key=lambda c:(-date.fromisoformat(c['date']).toordinal(),c['id']))
