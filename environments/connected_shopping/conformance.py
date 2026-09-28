"""Read-only world-to-page conformance. Expected facts come from canonical inputs.

No renderer imports, browser/model dispatches, task-conditioned selection or writes.
Browser action/AX acceptance remains a separate layer.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass,field
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode,quote as urlquote,urlsplit
from urllib.request import urlopen
from environments.product_world.generator import digest
from environments.product_world.locations import quote,validate_locations
from environments.product_world.stores import validate_store_world
from environments.product_review_sites.data import field_info


@dataclass
class Node:
    tag:str
    attrs:dict=field(default_factory=dict)
    children:list=field(default_factory=list)
    def text(self):return ''.join(x if isinstance(x,str) else x.text() for x in self.children)
    def find(self,tag=None,**attrs):
        result=[]
        for child in self.children:
            if isinstance(child,str):continue
            if (tag is None or child.tag==tag) and all(child.attrs.get(k)==v for k,v in attrs.items()):result.append(child)
            result.extend(child.find(tag,**attrs))
        return result
    def one(self,tag=None,**attrs):
        rows=self.find(tag,**attrs)
        if len(rows)!=1:raise AssertionError(f'Expected one {tag}/{attrs}, found {len(rows)}')
        return rows[0]


class Document(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=True);self.root=Node('document');self.stack=[self.root];self.feed(text)
    def handle_starttag(self,tag,attrs):
        n=Node(tag,dict(attrs));self.stack[-1].children.append(n)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:self.stack.append(n)
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs);self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:self.stack=self.stack[:i];break
    def handle_data(self,data):self.stack[-1].children.append(data)


def equal(actual,expected,label):
    if actual!=expected:raise AssertionError(f'{label}: expected {expected!r}, got {actual!r}')


def currency(n):return 'Unavailable' if n is None else f'{Decimal(n)/100:.2f} SEK'
def value(v):return ('Yes' if v else 'No') if type(v) is bool else (', '.join(map(str,v)) or 'None listed') if isinstance(v,list) else str(v)
def cells(row):return [x.text().strip() for x in row.children if isinstance(x,Node) and x.tag in ('th','td')]
def table_rows(table):return [cells(r) for r in table.find('tr')]


def product_check(root,product,offer,group,selection):
    equal(root.one(id='selected-sku').text(),product['product_id'],'selected SKU')
    assert any(n.text()==product['name'] for n in root.find('h2')),'Selected product name missing'
    table=root.one('table',**{'class':'fact-table'})
    expected={field_info(product['category'],k)[0]:value(v)+(' '+field_info(product['category'],k)[1] if field_info(product['category'],k)[1] else '') for k,v in product['attributes'].items()}
    equal(dict(table_rows(table)),expected,'product facts')
    section=root.one('section',**{'aria-label':'Offer'})
    equal(section.one('p',**{'class':'price'}).text(),currency(offer['price_minor'])+' per unit','item price')
    assert any(n.text()=='Online warehouse stock: '+str(offer['stock_quantity']) for n in section.find('p')),'Wrong stock'
    for axis in group['axes']:
        name='option_'+axis['field'];controls=root.find('select',name=name)
        if controls:
            options=[x.attrs['value'] for x in controls[0].find('option') if 'selected' in x.attrs]
        else:options=[n.attrs['value'] for n in root.find('input',name=name) if 'checked' in n.attrs]
        equal(options,[selection[axis['field']]],'selected option '+name)


def quote_check(root,expected,offer,n,method):
    block=root.one('section',id='offer-quote')
    equal(block.attrs['data-offer-id'],offer['offer_id'],'quote offer identity')
    equal(block.one('strong').text(),'Available' if expected['eligible'] else 'Unavailable','eligibility')
    equal([x.text() for x in block.find('li')],[x.replace('_',' ') for x in expected['reason_codes']],'eligibility reasons')
    if method!='inspect':
        equal(block.one(id='shipping-total').text(),currency(expected['shipping_minor']),'shipping charge')
        equal(block.one(id='delivered-total').text(),currency(expected['total_minor']),'mandatory total')
        equal(block.find('dd')[0].text(),currency(offer['price_minor']*n),'quantity subtotal')
    ready='No arrival/ready estimate available.' if expected['ready_days'] is None else f"Ready in {expected['ready_days']} calendar days after ordering."
    equal(block.one(id='arrival-days').text(),ready,'ready estimate')


def review_check(root,rows):
    panel=root.one(id='reader-panel')
    # Pages group reports by exact SKU. Export order can interleave those groups;
    # report identity and attribution are the contract, not a global display order.
    equal(sorted(n.attrs.get('id','') for n in panel.find('article')),
          sorted(r['review_id'] for r in rows),'review identity multiset')
    equal(len(panel.find('p',**{'class':'panel-report-body'})),len(rows),'review body count')
    for r in rows:
        article=panel.one('article',id=r['review_id'])
        equal(article.one('p',**{'class':'panel-report-body'}).text(),r['body'],'review body '+r['review_id'])
        if 'subject' in r:
            groups=[s for s in panel.find('section') if s.find('article',id=r['review_id'])]
            equal(len(groups),1,'exact-option group '+r['review_id'])
            sku=r['subject']['id']
            equal(groups[0].one('a',href='/variants/'+urlquote(sku,safe='')).text(),sku,'review subject')
        assert r['reviewer_id'] in article.text(),'Reviewer identity missing'
        href='/reviews/'+r['article_id']+'#'+r['review_id']
        equal(len(article.find('a',href=href)),1,'source permalink')
    for label in ('experience_kind','First-hand use','Second-hand account; not tried','Considering this use; not tried'):
        assert label not in panel.text(),'Generated experience shortcut exposed'


class Audit:
    def __init__(self,scenario,runtime):
        self.scenario=scenario;self.directory=Path(runtime)
        self.manifest=json.loads((self.directory/'manifest.json').read_text());self.provenance=json.loads((self.directory/'provenance.json').read_text())
        self.origins={s['site_id']:s['origin'] for s in self.manifest['sites']}
        for origin in self.origins.values():
            u=urlsplit(origin)
            if u.scheme!='http' or u.hostname not in ('localhost','127.0.0.1') or u.username:raise ValueError('Only local published origins supported')
        self.world=scenario['bundle'];self.locations=scenario['locations'];p=self.world['public']
        validate_store_world(self.world);validate_locations(self.world,self.locations)
        published_sources=json.loads((self.directory/'sources.json').read_text())
        for rel in ('locations.py','geography.py','data/europe_locations.json'):
            path=Path('environments/product_world')/rel
            equal(sha256(path.read_bytes()).hexdigest(),published_sources[str(path)],'quote dependency revision '+str(path))
        equal(self.provenance['world_sha256'],self.world['world_sha256'],'world binding')
        equal(self.provenance['locations_sha256'],self.locations['locations_sha256'],'geography binding')
        self.products={x['product_id']:x for x in p['products']};self.groups={v['product_id']:g for g in p['product_groups'] for v in g['variants']}
        self.offers=p['offers'];self.jobs=[]
        self.interactions=scenario.get('interaction_patterns')
        self.interaction_sites={}
        if self.interactions is not None:
            from environments.product_world.interaction_patterns import validate_interaction_patterns
            coverage_file=self.directory/'comparison-coverage.json'
            coverage=json.loads(coverage_file.read_text()) if coverage_file.exists() else None
            validate_interaction_patterns(self.world,self.interactions,self.locations,coverage=coverage)
            equal(self.provenance.get('interaction_patterns_sha256'),digest(self.interactions),'interaction binding')
            equal(json.loads((self.directory/'interaction-patterns.public.json').read_text()),self.interactions,'served interaction sidecar')
            self.interaction_sites={r['site_id']:r for r in self.interactions['sites']}
        self.storefront=scenario.get('storefront_content')
        if self.storefront is not None:
            from environments.product_world.storefront_content import validate_storefront_content
            validate_storefront_content(self.world,self.storefront,accounts=scenario.get('accounts'))
            equal(self.provenance.get('storefront_content_sha256'),digest(self.storefront),'storefront binding')
            equal(json.loads((self.directory/'storefront-content.public.json').read_text()),self.storefront,'served storefront sidecar')
    def destination_query(self,sid):
        mode=self.interaction_sites.get(sid,{}).get('destination_form','none')
        if mode=='none':return {}
        d=self.interactions['destination'];q={'destination_country':d['country']}
        if mode=='split':q.update(zip(('postcode_1','postcode_2'),d['postcode_parts']))
        else:q['postcode']=d['postcode']
        return q
    def add(self,kind,key,url,check,status=200):self.jobs.append((kind,key,url,check,status))
    def build(self):
        first={}
        for o in self.offers:
            sid=o['retailer_id'];sku=o['product_id'];g=self.groups[sku];p=self.products[sku];base=self.origins[sid]
            first.setdefault((sid,g['group_id']),sku)
            selection=next(v['selection'] for v in g['variants'] if v['product_id']==sku)
            # Details path is valid for all retailer bases, including separate-detail boutiques.
            direct=base+'/products/'+urlquote(sku,safe='')+'/details'
            checker=lambda root,p=p,o=o,g=g,s=selection:product_check(root,p,o,g,s)
            self.add('retailer_product',o['offer_id'],direct,checker)
            params={'option_'+k:v for k,v in selection.items()}
            changed=base+'/products/'+urlquote(first[(sid,g['group_id'])],safe='')+'/details?'+urlencode(params)
            self.add('variant_selection',o['offer_id'],changed,checker)
            expected=quote(self.world,self.locations,o['offer_id'],quantity=1,method='delivery',branch_id=None)
            self.add('delivery_quote',o['offer_id'],base+'/quote?'+urlencode({'offer_id':o['offer_id'],'quantity':1,'method':'delivery',**self.destination_query(sid)}),lambda root,e=expected,o=o:quote_check(root,e,o,1,'delivery'))
        # Bounded boundary coverage independent of task and feasibility; no preferred outcomes.
        merchants={x['retailer_id']:x for x in self.locations['public']['merchants']}
        for sid in sorted({o['retailer_id'] for o in self.offers}):
            o=next(o for o in self.offers if o['retailer_id']==sid)
            for method,branch,n in [('delivery',None,2)]+[(method,b['branch_id'],1) for b in merchants[sid]['branches'] for method in ('pickup','inspect')]:
                expected=quote(self.world,self.locations,o['offer_id'],quantity=n,method=method,branch_id=branch)
                q={'offer_id':o['offer_id'],'quantity':n,'method':method}
                if method=='delivery':q.update(self.destination_query(sid))
                if branch:q['branch_id']=branch
                self.add('fulfillment_boundary',sid+':'+method+':'+str(branch),self.origins[sid]+'/quote?'+urlencode(q),lambda root,e=expected,o=o,n=n,m=method:quote_check(root,e,o,n,m))
        self.comparisons()
        self.storefront_pages()
        evidence=self.scenario.get('product_review_evidence')
        if evidence is not None:
            equal(self.provenance.get('product_review_evidence_sha256'),digest(evidence['public']),'review corpus binding')
            article_ids=sorted({r['article_id'] for r in evidence['public']['reviews']})
            for aid in article_ids:
                rows=[r for r in evidence['public']['reviews'] if r['article_id']==aid];family=self.products[rows[0]['subject']['id']]['category']
                self.add('review_article',aid,self.origins['reviews-'+family]+'/reviews/'+aid,lambda root,rows=rows:review_check(root,rows))
        return self.jobs
    def storefront_pages(self):
        for row in (self.storefront or {}).get('retailers',[]):
            sid=row['retailer_id'];base=self.origins[sid]
            def home_check(root,row=row):
                nav=root.one('nav',**{'aria-label':'Shop by category'})
                equal([a.text() for a in nav.find('a')],[c['title'] for c in row['collections']],'store categories')
                for section in row['sections']:
                    block=root.one('section',**{'aria-labelledby':'home-'+section['section_id']})
                    equal(block.one('h2').text(),section['title'],'merchandising title')
                    assert section['body'] in block.text(),'Missing merchandising description'
                assert not root.find('nav',**{'aria-label':'Other websites'}),'Retailer discovery shortcut'
            self.add('storefront_home',sid,base+'/',home_check)
            for collection in row['collections']:
                ids=collection['product_ids'];identities={self.groups[sku]['group_id'] if self.products[sku]['category']=='footwear' else sku for sku in ids}
                total=max(1,(len(identities)+11)//12)
                for page in range(1,total+1):
                    def check(root,ids=set(ids),count=len(identities),title=collection['title']):
                        assert any(h.text()==title for h in root.find('h1')),'Wrong collection'
                        result=root.one('section',**{'aria-label':'Product results'})
                        assert str(count)+' product listings' in result.text(),'Wrong collection population'
                        shown={urlsplit(a.attrs['href']).path.split('/products/')[-1] for a in result.find('a') if '/products/' in a.attrs.get('href','')}
                        assert shown and shown<=ids,'Collection card outside declared membership'
                    self.add('storefront_collection',sid+':'+collection['collection_id']+':'+str(page),base+'/collections/'+urlquote(collection['collection_id'],safe='')+'?page='+str(page),check)

    def comparisons(self):
        coverage_path=self.directory/'comparison-coverage.json'
        if not coverage_path.exists():return
        coverage=json.loads(coverage_path.read_text());equal(digest(coverage),self.provenance['comparison_coverage_sha256'],'coverage binding')
        identities={}
        for sku,p in self.products.items():
            g=self.groups[sku]
            if p['category']=='footwear':
                variants=[self.products[v['product_id']] for v in g['variants']];excluded={x['field'] for x in g['axes']}|{'size_eu','colour','width'}
                attrs={k:v for k,v in variants[0]['attributes'].items() if k not in excluded and all(x['attributes'].get(k)==v for x in variants)}
                identities[g['group_id']]={'name':g['name'],'family':'footwear','attrs':attrs,'path':'/models/'+g['group_id']}
            else:identities[sku]={'name':p['name'],'family':p['category'],'attrs':p['attributes'],'path':'/products/'+sku}
        for site in coverage['sites']:
            sid=site['site_id'];base=self.origins[sid];pairs={(r['comparison_id'],r['retailer_id']) for r in site['listings']}
            def price(cid):
                if identities[cid]['family']=='footwear':
                    rows=[r['advertised_price_minor'] for r in self.world['public'].get('comparison_listings',[]) if r['model_id']==cid and (cid,r['retailer_id']) in pairs]
                    if 'comparison_listings' not in self.world['public']:
                        rows=[o['price_minor'] for o in self.offers if self.groups[o['product_id']]['group_id']==cid and (cid,o['retailer_id']) in pairs]
                else:rows=[o['price_minor'] for o in self.offers if o['product_id']==cid and (cid,o['retailer_id']) in pairs]
                return min(rows) if rows else None
            for family in site['families']:
                ids=sorted(cid for cid in site['comparison_ids'] if identities[cid]['family']==family)[:2]
                if len(ids)<2:continue
                expected=[['Attribute']+[identities[c]['name'] for c in ids],['Lowest listed item price']+[currency(price(c)) for c in ids]]
                for key in sorted(set().union(*(identities[c]['attrs'] for c in ids))):
                    label,unit=field_info(family,key)
                    expected.append([label]+[value(identities[c]['attrs'][key])+(' '+unit if unit else '') if key in identities[c]['attrs'] else 'Not specified' for c in ids])
                self.add('comparison_matrix',sid+':'+family,base+'/compare?'+urlencode({f'pick{i}':c for i,c in enumerate(ids)}),lambda root,e=expected:equal(table_rows(root.one('main').one('table')),e,'comparison table'))
            missing=next((c for c in sorted(identities) if c not in site['comparison_ids']),None)
            if missing:self.add('omitted_comparison',sid,base+identities[missing]['path'],lambda root:None,status=404)


def run(scenario,runtime,output,workers=4):
    if type(workers) is not int or not 1<=workers<=8:raise ValueError('workers must be 1..8')
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    audit=Audit(scenario,runtime);jobs=audit.build()
    def execute(job):
        kind,key,url,check,status=job;html=None
        result={'kind':kind,'case':key,'url':url,'passed':False}
        try:
            try:
                with urlopen(url,timeout=15) as response:code=response.status;raw=response.read()
            except HTTPError as exc:code=exc.code;raw=exc.read()
            html=raw.decode();result['status']=code;result['response_sha256']=sha256(raw).hexdigest()
            equal(code,status,'HTTP status');check(Document(html).root);result['passed']=True
        except Exception as exc:
            result['error']=str(exc);result['exception_type']=type(exc).__name__
            if html is not None:
                artifact=sha256((kind+key).encode()).hexdigest()[:20]+'.html';(out/artifact).write_text(html);result['failure_html']=artifact
        return result
    with ThreadPoolExecutor(max_workers=workers) as pool:results=list(pool.map(execute,jobs))
    counts={k:sum(r['kind']==k for r in results) for k in sorted({r['kind'] for r in results})}
    report={'schema':'connected-world-page-conformance-v1','passed':all(r['passed'] for r in results),'counts':counts,'cases':results,'scenario_sha256':digest(scenario),'manifest_sha256':sha256((Path(runtime)/'manifest.json').read_bytes()).hexdigest(),'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'published_sources_sha256':sha256((Path(runtime)/'sources.json').read_bytes()).hexdigest(),'workers':workers,'model_calls':0,'scope':'Read-only HTTP contract checks; native action/AX suites are separate. All offers/default delivery, all offered selections; one quantity boundary per retailer, all branches for one offer per retailer, one comparison pair per covered family/site, all supplied panel reports. Not all possible quantities/option combinations.'}
    (out/'report.json').write_text(json.dumps(report,indent=2));return report
