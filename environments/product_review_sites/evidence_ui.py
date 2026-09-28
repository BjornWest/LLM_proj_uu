"""Render the frozen Reader Panel corpus; never infer claims from legacy opinions."""
from copy import deepcopy
from urllib.parse import quote
from .evidence import validate_evidence
from . import render as ui


class Corpus:
    def __init__(self,world,export,db):
        validate_evidence(world,export)
        self.public=deepcopy(export['public']);self.db=db
        self.reviews=[r for r in self.public['reviews'] if r['subject']['id'] in db.variants]
        self.coverage=[r for r in self.public['coverage'] if r['sku_id'] in db.variants]
        self.by_article={aid:[r for r in self.reviews if r['article_id']==aid] for aid in db.by_id}

    def section(self,article_id):
        if article_id not in self.db.by_id:raise KeyError('Unknown article')
        rows=self.by_article[article_id]
        skus=sorted({c['sku_id'] for c in self.coverage if self.db.variants[c['sku_id']]['model_id']==article_id}|{r['subject']['id'] for r in rows})
        body='<section id="reader-panel" aria-labelledby="reader-panel-heading"><h2 id="reader-panel-heading">Reader Panel: experiences with exact product options</h2><p>Reader Panel is a separate collection from the community comments elsewhere on this site. These reports apply only to the exact option named, not automatically to every size, colour or pack.</p><p>Published reports as of '+ui.e(self.public['as_of'])+'. '+ui.e(self.public['scope'])+'</p>'
        if not skus:body+='<p>No Reader Panel coverage for this model. Missing reports do not establish a positive or negative experience.</p>'
        for sku in skus:
            v=self.db.variants[sku];reports=[r for r in rows if r['subject']['id']==sku]
            body+='<section><h3>'+ui.e(v['name'])+'</h3><p>Exact option: <a href="'+ui.variant_url(v)+'">'+ui.e(sku)+'</a></p><dl>'
            for c in self.coverage:
                if c['sku_id']!=sku:continue
                aspect=self.public['registry'][c['aspect_id']]
                text='All published panel reports included' if c['status']=='complete' else 'Incomplete published panel coverage'
                body+='<dt>'+ui.e(aspect['label'])+'</dt><dd>'+text+'</dd>'
            body+='</dl><p>'+str(len(reports))+' panel reports for this exact option.</p>'
            for r in reports:
                href='/reviews/'+quote(article_id,safe='')+'#'+quote(r['review_id'],safe='')
                body+='<article id="'+ui.e(r['review_id'])+'"><h4>'+ui.e(r['handle'])+'</h4><p>Panel member: '+ui.e(r['reviewer_id'])+'</p><p><time>'+ui.e(r['published_date'])+'</time> · '+('Rating not given' if r['stars'] is None else str(r['stars'])+' out of 5')+'</p><p class="panel-report-body">'+ui.e(r['body'])+'</p><p><a href="'+ui.e(href)+'">Permanent link to this report</a></p></article>'
            body+='</section>'
        return body+'</section>'

    def directory(self,site):
        body='<main id="main"><h1>Reader Panel</h1><p>Exact-option experiences, separate from the general community comments. Coverage is limited to the published reports listed here.</p><ul>'
        for a in self.db.articles:
            body+='<li><a href="'+ui.review_url(a)+'#reader-panel">'+ui.e(a['model_name'])+'</a> · '+str(len(self.by_article[a['id']]))+' reports</li>'
        return ui.document(site,'Reader Panel',body+'</ul></main>')

    def decorate(self,body,path,q):
        nav='<nav aria-label="Reader Panel"><a href="/reader-panel">Browse exact-option reader experiences</a></nav>'
        section=''
        if path.startswith('/reviews/') and '/opinions/' not in path and q.get('part','overview')=='overview':
            section=self.section(path[len('/reviews/'):])
        elif path.startswith('/variants/'):
            v=self.db.variants.get(path[len('/variants/'):])
            if v:section='<p><a href="/reviews/'+quote(v['model_id'],safe='')+'#reader-panel">Reader Panel coverage for this model — check the exact option</a></p>'
        return body.replace('</main>',nav+section+'</main>',1)
