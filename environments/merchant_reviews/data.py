"""Validate the public review contract and answer deterministic corpus queries."""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
import math
from urllib.parse import urlsplit
from .identity import validate_name

TOPICS=('delivery','communication','returns','product_condition')


def statistics(reviews):
    counts=Counter(r['stars'] for r in reviews)
    return {'review_count':len(reviews),'star_counts':{str(i):counts[i] for i in range(1,6)},
            'mean_stars':sum(r['stars'] for r in reviews)/len(reviews) if reviews else None}


def _text(v):
    if not isinstance(v,str) or not v:raise ValueError('Expected nonempty string')
    return v


def _date(v):
    if not isinstance(v,str):raise ValueError('Expected ISO date')
    d=date.fromisoformat(v)
    if d.isoformat()!=v:raise ValueError('Expected ISO date')
    return d


class ReviewCatalog:
    def __init__(self,public,website_bindings=None,*,site_name="Omdömeskollen"):
        self.site_name=validate_name(site_name)
        if not isinstance(public,dict) or set(public)!={'as_of','companies'}:raise ValueError('Pass only merchant-review-export-v1 public data')
        self.as_of=public['as_of'];as_of=_date(self.as_of)
        if not isinstance(public['companies'],list):raise ValueError('companies must be a list')
        self.companies=deepcopy(public['companies']);self.by_id={};self.by_review={}
        for c in self.companies:
            if set(c)!={'company_id','name','domain','website_url','category','reviews','statistics'}:raise ValueError('Unexpected company fields')
            for key in ('company_id','name','domain','website_url','category'):_text(c[key])
            if c['company_id'] in self.by_id:raise ValueError('Duplicate company')
            if not isinstance(c['reviews'],list):raise ValueError('reviews must be list')
            u=urlsplit(c['website_url'])
            if u.scheme not in ('http','https') or u.hostname!=c['domain'] or u.username or u.password:raise ValueError('Invalid website identity')
            for r in c['reviews']:
                if set(r)!={'review_id','reviewer','stars','title','body','experience_date','published_date','topic','company_reply'}:raise ValueError('Unexpected review fields')
                if r['review_id'] in self.by_review:raise ValueError('Duplicate review')
                for key in ('review_id','title','body'):_text(r[key])
                if not isinstance(r['reviewer'],dict) or set(r['reviewer'])!={'handle'}:raise ValueError('Unexpected reviewer fields')
                _text(r['reviewer']['handle'])
                if type(r['stars']) is not int or not 1<=r['stars']<=5 or r['topic'] not in TOPICS:raise ValueError('Invalid review rating/topic')
                if not _date(r['experience_date'])<=_date(r['published_date'])<=as_of:raise ValueError('Invalid review dates')
                reply=r['company_reply']
                if reply is not None:
                    if not isinstance(reply,dict) or set(reply)!={'body','published_date'}:raise ValueError('Unexpected reply fields')
                    _text(reply['body'])
                    if not _date(r['published_date'])<=_date(reply['published_date'])<=as_of:raise ValueError('Invalid reply date')
                self.by_review[r['review_id']]=(c,r)
            expected=statistics(c['reviews']);given=c['statistics']
            if not isinstance(given,dict) or set(given)!=set(expected):raise ValueError('Invalid statistics')
            if type(given['review_count']) is not int or given['review_count']!=expected['review_count']:raise ValueError('Inconsistent review count')
            if given['star_counts']!=expected['star_counts'] or any(type(v) is not int for v in given['star_counts'].values()):raise ValueError('Inconsistent star counts')
            mean=given['mean_stars'];want=expected['mean_stars']
            if (want is None and mean is not None) or (want is not None and (type(mean) not in (int,float) or not math.isfinite(mean) or abs(mean-want)>1e-9)):raise ValueError('Inconsistent mean')
            self.by_id[c['company_id']]=c
        self.bindings=dict(website_bindings or {})
        if set(self.bindings)-set(self.by_id):raise ValueError('Unknown company binding')
        for url in self.bindings.values():
            u=urlsplit(url)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:raise ValueError('Invalid website binding')

    def search(self,query):
        terms=query.get('q','').casefold().split();category=query.get('category','')
        rows=[c for c in self.companies if (not category or c['category']==category) and all(t in (' '.join(c[k] for k in ('name','domain','category'))).casefold() for t in terms)]
        sort=query.get('sort','name')
        if sort=='rating':rows.sort(key=lambda c:(-(c['statistics']['mean_stars'] or 0),-len(c['reviews']),c['company_id']))
        elif sort=='count':rows.sort(key=lambda c:(-len(c['reviews']),c['company_id']))
        else:rows.sort(key=lambda c:(c['name'].casefold(),c['company_id']))
        return rows

    def reviews(self,company_id,query):
        rows=list(self.by_id[company_id]['reviews']);stars=query.get('stars','');topic=query.get('topic','')
        terms=query.get('q','').casefold().split()
        cutoff=max(date.min.toordinal(),date.fromisoformat(self.as_of).toordinal()-int(query['period'])) if query.get('period') else None
        rows=[r for r in rows if (not stars or r['stars']==int(stars)) and (not topic or r['topic']==topic) and (cutoff is None or _date(r['published_date']).toordinal()>=cutoff) and all(t in (r['title']+' '+r['body']).casefold() for t in terms)]
        mode=query.get('sort','newest')
        if mode=='oldest':rows.sort(key=lambda r:(r['published_date'],r['review_id']))
        elif mode=='lowest':rows.sort(key=lambda r:(r['stars'],-_date(r['published_date']).toordinal(),r['review_id']))
        elif mode=='highest':rows.sort(key=lambda r:(-r['stars'],-_date(r['published_date']).toordinal(),r['review_id']))
        else:rows.sort(key=lambda r:(-_date(r['published_date']).toordinal(),r['review_id']))
        return rows
