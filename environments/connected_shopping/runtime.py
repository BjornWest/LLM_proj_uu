"""Compose one frozen scenario into bound, research-only sites.

Tasks/references are deliberately not retained. Quotes call the product-owned
geographic implementation; the fixed-shipping commerce engine is never involved.
"""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote as urlencode_path,urlsplit
import hashlib,json
from environments.product_world.stores import validate_store_world
from environments.product_world.locations import validate_locations,quote
from environments.product_world.generator import digest
from environments.product_world.travel import export_travel_planner
from environments.product_review_sites.generate import generate_reviews
from environments.product_review_sites.runtime import Runtime as ProductReviews
from environments.merchant_reviews.data import ReviewCatalog
from environments.merchant_reviews import render as merchant_ui
from environments.merchant_reviews.runtime import query_for
from environments.merchant_reviews.identity import sample_identity
from environments.travel_planner.runtime import Runtime as Travel
from environments.site_consent.runtime import design_for
from environments.procedural_commerce.product_controls import validate_groups
from .http import Site
from . import index,pages,comparison

VERSION='connected-shopping-world-v1'
LAYOUTS={'footwear':'lab-directory','laptops':'editorial-magazine','dog_food':'lab-directory','cat_food':'lab-directory','beer':'community-feed','wine':'community-feed'}


class Runtime:
    def __init__(self,scenario,*,product_review_seed=42,opinions_per_review=24,consent=True,comparison_coverage=None,comparison_profiles=None,advertising=None,verification=None,interaction_patterns=None,storefront_content=None):
        if type(consent) is not bool:raise ValueError('Consent must be boolean')
        self.world=deepcopy(scenario['bundle']);self.locations=deepcopy(scenario['locations']);self.merchant_reviews=deepcopy(scenario['merchant_reviews'])
        validate_store_world(self.world);validate_locations(self.world,self.locations)
        mr=self.merchant_reviews
        if mr['private_provenance']['source_world_sha256']!=self.world['world_sha256'] or mr['private_provenance']['public_sha256']!=digest(mr['public']):raise ValueError('Merchant reviews do not match world')
        p=self.world['public'];validate_groups(p['product_groups'],{'products':p['products']})
        self.products={v['product_id']:v for v in p['products']};self.stores={s['retailer_id']:s for s in p['retailers']}
        self.offers={o['offer_id']:o for o in p['offers']};self.offer_by_store={(o['retailer_id'],o['product_id']):o for o in p['offers']}
        self.group_for={v['product_id']:g for g in p['product_groups'] for v in g['variants']}
        self.account_pages=None
        if scenario.get('accounts') is not None:
            from .accounts import AccountPages
            self.account_pages=AccountPages(self,scenario['accounts'])
        self.comparisons=comparison.build(self.world);self.comparison_by_id={c['id']:c for c in self.comparisons}
        self.comparison_coverage=deepcopy(comparison_coverage);self.comparison_designs={};self.comparison_profiles={}
        self.groups_by_store={sid:{a['model_id'] for a in p['assortments'] if a['retailer_id']==sid} for sid in self.stores}
        self.merchants={m['retailer_id']:m for m in self.locations['public']['merchants']};self.families=sorted({p['category'] for p in self.products.values()})
        if self.comparison_coverage is not None:
            from environments.product_world.comparison_coverage import validate_coverage
            from .comparison_profiles import demonstration,create
            validate_coverage(self.world,self.comparison_coverage)
            self.comparison_profiles=deepcopy(comparison_profiles if comparison_profiles is not None else demonstration(self))
            if set(self.comparison_profiles)!={c['site_id'] for c in self.comparison_coverage['sites']}:raise ValueError('Each coverage site requires exactly one presentation profile')
            for covered in self.comparison_coverage['sites']:
                sid=covered['site_id'];self.comparison_designs[sid]=create(self,self.comparison_profiles[sid],covered)
        elif comparison_profiles is not None:raise ValueError('Profiles require explicit comparison membership')
        self.interaction_patterns=deepcopy(interaction_patterns if interaction_patterns is not None else scenario.get('interaction_patterns'))
        self.interaction_sites={}
        if self.interaction_patterns is not None:
            from environments.product_world.interaction_patterns import validate_interaction_patterns
            validate_interaction_patterns(self.world,self.interaction_patterns,self.locations,coverage=self.comparison_coverage)
            self.interaction_sites={row['site_id']:row for row in self.interaction_patterns['sites']}
        self.storefront_content=deepcopy(storefront_content if storefront_content is not None else scenario.get('storefront_content'))
        self.storefront_by_store={}
        if self.storefront_content is not None:
            from environments.product_world.storefront_content import validate_storefront_content
            validate_storefront_content(self.world,self.storefront_content,accounts=scenario.get('accounts'))
            self.storefront_by_store={row['retailer_id']:row for row in self.storefront_content['retailers']}
        self.product_review_evidence=deepcopy(scenario.get('product_review_evidence'))
        if self.product_review_evidence is not None:
            from environments.product_review_sites.evidence import validate_evidence
            validate_evidence(self.world,self.product_review_evidence)
        self.product_reviews=generate_reviews(self.world,seed=product_review_seed,opinions_per_review=opinions_per_review,as_of=mr['public']['as_of'])
        self.designs={sid:('dense-storefront' if s['profile_id']=='marketplace' else ('editorial-boutique','dense-storefront','technical-catalog')[i%3]) for i,(sid,s) in enumerate(self.stores.items())}
        self.origins={};self.sites={};self.index_origin='';self._stack=ExitStack();self._closed=False
        self.advertising=None
        if advertising is not None:
            from .advertising import Advertising
            specs=([{'site_id':sid,'kind':'aggregator','families':d.families} for sid,d in self.comparison_designs.items()]
                   if self.comparison_designs else [{'site_id':'aggregator','kind':'aggregator','families':self.families}])
            specs += [{'site_id':'reviews-'+f,'kind':'product_review','families':[f]} for f in self.families]
            self.advertising=Advertising(self.world,advertising,specs,self.origins)
        self.verification=deepcopy(verification);self.verification_gates={}
        if verification is not None:
            from environments.site_verification import validate,Gate
            validate(verification,list(self.comparison_designs) or ['aggregator'])
            self.verification_gates={row['site_id']:Gate(row) for row in verification['sites']}
        seed=self.world['seed']
        try:
            for sid in self.stores:
                action=(lambda path,fields,sid=sid:self.account_pages.action(sid,path,fields)) if self.account_pages else None
                site=self._stack.enter_context(Site(lambda path,q,raw,sid=sid:self.retailer(sid,path,q),action=action,consent_design=design_for(seed,sid) if consent else None));self.sites[sid]=site;self.origins[sid]=site.origin
            if self.comparison_designs:
                for sid,design in self.comparison_designs.items():
                    site=self._stack.enter_context(Site(lambda path,q,raw,sid=sid,design=design:self.ad_page(sid,design.render(path,q,raw)),verification=self.verification_gates.get(sid),consent_design=design_for(seed,sid) if consent else None));self.sites[sid]=site;self.origins[sid]=site.origin
                # Navigation alias only; no additional all-products comparison server.
                primary=next((sid for sid,d in self.comparison_designs.items() if d.family is None),next(iter(self.comparison_designs)))
                self.origins['aggregator']=self.origins[primary]
            else:
                agg=self._stack.enter_context(Site(lambda path,q,raw:self.ad_page('aggregator',(200,pages.aggregator(self,path,q))),verification=self.verification_gates.get('aggregator'),consent_design=design_for(seed,'aggregator') if consent else None));self.sites['aggregator']=agg;self.origins['aggregator']=agg.origin
            self.merchant_db=ReviewCatalog(mr['public'],{sid:origin for sid,origin in self.origins.items() if sid in self.stores},site_name=sample_identity(seed)['name'])
            merchant=self._stack.enter_context(Site(self.merchant_page,consent_design=design_for(seed,'merchant-reviews') if consent else None));self.sites['merchant-reviews']=merchant;self.origins['merchant-reviews']=merchant.origin
            self.travel_export=export_travel_planner(self.world,self.locations)
            travel=self._stack.enter_context(Travel());self.travel_url=travel.register(self.travel_export);self.origins['travel']=travel.origin
            # Bind each reviewed/variant SKU only to a retailer that actually lists it.
            bindings={sku:self.origins[sorted(o['retailer_id'] for o in self.offers.values() if o['product_id']==sku)[0]]+pages.path_product(sku) for sku in self.products if any(o['product_id']==sku for o in self.offers.values())}
            for family in self.families:
                sid='reviews-'+family
                r=self._stack.enter_context(ProductReviews(self.product_reviews['public'],families=[family],layout=LAYOUTS[family],seed=product_review_seed,site_id=sid,bindings={sku:url for sku,url in bindings.items() if self.products[sku]['category']==family},consent_design=design_for(seed,sid) if consent else None,evidence=self.product_review_evidence,evidence_world=self.world,decorate=(lambda body,sid=sid:self.advertising.decorate(sid,body)) if self.advertising else None))
                self.sites[sid]=r;self.origins[sid]=r.origin
            self.site_records=self.make_sites();self.documents=self.make_documents()
            self.index=self._stack.enter_context(index.Runtime(self.site_records,self.documents));self.index_origin=self.index.origin;self.origins['index']=self.index.origin
            self.public_manifest={'schema_version':VERSION,'index_url':self.index_origin,'sites':deepcopy(self.site_records)}
            self.bindings={'origins':deepcopy(self.origins),'retailer_products':bindings,'travel_url':self.travel_url}
            self.provenance={'schema_version':VERSION,'world_sha256':self.world['world_sha256'],'locations_sha256':self.locations['locations_sha256'],'merchant_reviews_public_sha256':digest(mr['public']),'product_reviews_public_sha256':digest(self.product_reviews['public']),'bindings_sha256':digest(self.bindings),'product_review_config':{'seed':product_review_seed,'opinions_per_review':opinions_per_review,'as_of':mr['public']['as_of']},'capabilities':['research','geographic_quotes','consent'],'purchase_supported':False}
            if self.interaction_patterns is not None:
                self.provenance.update(interaction_patterns_sha256=digest(self.interaction_patterns),interaction_patterns_version=self.interaction_patterns['schema_version'])
            if self.storefront_content is not None:
                self.provenance.update(storefront_content_sha256=digest(self.storefront_content),storefront_content_version=self.storefront_content['schema_version'])
            if verification is not None:
                self.provenance.update(verification_sha256=digest(verification),verification_version=verification['schema_version'],verification_implementation='offline-simulation')
            if self.account_pages:
                self.provenance.update(accounts_sha256=digest(scenario['accounts']),accounts_version=scenario['accounts']['schema_version'])
                self.provenance['capabilities']+=['account_tracking','order_cancellation','coupon_quotes']
            if self.product_review_evidence is not None:
                self.provenance.update(product_review_evidence_sha256=digest(self.product_review_evidence['public']),product_review_evidence_version=self.product_review_evidence['schema_version'])
                self.bindings['product_review_reports']={r['review_id']:self.origins['reviews-'+self.products[r['subject']['id']]['category']]+'/reviews/'+r['article_id']+'#'+r['review_id'] for r in self.product_review_evidence['public']['reviews']}
                self.provenance['bindings_sha256']=digest(self.bindings)
            if self.comparison_designs:
                self.bindings['comparison_products']={cid:[self.origins[sid]+design.by_id[cid]['path'] for sid,design in self.comparison_designs.items() if cid in design.by_id] for cid in self.comparison_by_id}
                self.provenance.update(comparison_coverage_sha256=digest(self.comparison_coverage),comparison_profiles_sha256=digest(self.comparison_profiles),bindings_sha256=digest(self.bindings))
            if self.advertising is not None:
                self.provenance.update(advertising_sha256=digest(self.advertising.public),advertising_version=self.advertising.public['schema_version'])
        except BaseException:self._stack.close();raise

    def ad_page(self,site,result):
        status,body=result
        return status,self.advertising.decorate(site,body) if self.advertising and status==200 else body

    def catalog(self,site):
        offers=[deepcopy(o) for o in self.offers.values() if o['retailer_id']==site];ids={o['product_id'] for o in offers}
        return {'currency':'SEK','products':[{k:deepcopy(v) for k,v in p.items() if k!='reference_price_minor'} for p in self.products.values() if p['product_id'] in ids],'offers':offers,'retailer':{'retailer_id':site,'name':self.stores[site]['name']},'cart_quantity':0}

    def quote(self,offer_id,*,quantity=1,method='delivery',branch_id=None,coupon_code=None):
        base=quote(self.world,self.locations,offer_id,quantity=quantity,method=method,branch_id=branch_id)
        if coupon_code:
            if not self.account_pages:raise ValueError('Coupon quotes are unavailable')
            if method=='inspect':raise ValueError('Inspection is not a purchase quote')
            return self.account_pages.session.quote(base,coupon_code=coupon_code)
        return base

    def retailer(self,site,path,q):
        from . import storefront
        if self.account_pages and (path=='/account' or path.startswith('/account/')):return self.account_pages.render(site,path,q)
        if path in ('/','/search'):return 200,pages.listing(self,site,q,home=path=='/')
        if path.startswith(('/collections/','/highlights/')):
            if len(path.strip('/').split('/'))!=2:raise KeyError('Unknown collection')
            return 200,storefront.listing(self,site,path,q)
        if path.startswith('/products/'):
            parts=path.strip('/').split('/')
            if len(parts)==2 or len(parts)==3 and parts[2]=='details':return 200,pages.product(self,site,parts[1],q,details=len(parts)==3)
            raise KeyError('Unknown route')
        if path=='/quote':return 200,pages.quote_page(self,site,q)
        if q:raise ValueError('Unexpected parameters')
        if path in ('/returns','/terms','/contact') and storefront.content(self,site) is not None:return 200,storefront.information(self,site,path)
        if path=='/policy':return 200,pages.policy(self,site)
        if path=='/branches':return 200,pages.branches(self,site)
        if path=='/cart':return 200,pages.shell(self,site,'Shopping bag','<h1>Shopping bag</h1><p>Online ordering is not available in this catalog. You can compare products and check delivery or pickup quotes.</p>')
        raise KeyError('Unknown route')

    def merchant_page(self,path,q,raw):
        q=query_for(path,raw);db=self.merchant_db
        if path=='/':html=merchant_ui.home(db)
        elif path=='/search':html=merchant_ui.search(db,q)
        elif path=='/categories':html=merchant_ui.document('Categories','<main id="main"><h1>Company categories</h1>'+merchant_ui.category_links(db)+'</main>',db.site_name)
        elif path=='/about':html=merchant_ui.about(db.site_name)
        elif path.startswith('/review/') and path[8:] in db.by_id:html=merchant_ui.profile(db,db.by_id[path[8:]],q)
        elif path.startswith('/reviews/') and path[9:] in db.by_review:
            c,r=db.by_review[path[9:]];html=merchant_ui.document(r['title'],'<main id="main"><h1>Customer experience</h1>'+merchant_ui.review_card(c,r)+'</main>',db.site_name)
        else:raise KeyError('Unknown profile')
        return 200,html.replace('</footer>',pages.link(self.index_origin,'Search the web')+'</footer>')

    def make_sites(self):
        rows=[]
        def add(sid,kind,name,families,desc):rows.append({'site_id':sid,'kind':kind,'name':name,'origin':self.origins[sid],'families':families,'description':desc})
        for sid,s in self.stores.items():add(sid,'retailer',s['name'],s['families'],s['specialization']+' in '+s['location']['city']+'. Product listings, variants, delivery quotes and branch information.')
        if self.comparison_designs:
            for sid,d in self.comparison_designs.items():add(sid,'aggregator',d.name,d.families,'Compare tracked products and advertised retailer prices. This site does not cover every retailer or product.')
        else:add('aggregator','aggregator','Prislyktan',self.families,'Compare footwear models and other product configurations. Choose shoe options and check final prices at retailers.')
        add('merchant-reviews','merchant_reviews',self.merchant_db.site_name,self.families,'Independent customer opinions, merchant ratings and review filters.')
        for family in self.families:
            sid='reviews-'+family;add(sid,'product_reviews',self.sites[sid].name,[family],'Product specifications, comparisons and reader reviews for '+family.replace('_',' ')+'.')
        add('travel','travel','Vägval',self.families,'Find store branches and compare walking, cycling and driving estimates from your saved location.')
        return rows

    def make_documents(self):
        docs=[]
        def add(sid,path,title,description,keywords=''):docs.append({'site_id':sid,'path':path,'title':title,'description':description,'keywords':keywords})
        for s in self.site_records:add(s['site_id'],'/',s['name'],s['description'])
        for sid in self.stores:
            for p in self.catalog(sid)['products']:
                if p['category']!='footwear':add(sid,pages.path_product(p['product_id']),p['name'],self.stores[sid]['name']+' · '+p['category'].replace('_',' '),p['product_id']+' '+str(p['attributes']))
            for model in self.comparisons:
                if model['kind']=='model':
                    for row in model['listings']:
                        if row['retailer_id']==sid:add(sid,pages.path_product(row['entry_product_id']),model['name'],self.stores[sid]['name']+' · Footwear; choose options at the store',model['id']+' footwear '+str(model['attributes']))
            add(sid,'/branches',self.stores[sid]['name']+' locations','Branches, pickup and travel information')
        for sid,items in ([(sid,d.items) for sid,d in self.comparison_designs.items()] if self.comparison_designs else [('aggregator',self.comparisons)]):
            for p in items:add(sid,p['path'],p['name'],'Compare retailer listings for this model' if p['kind']=='model' else 'Compare item prices for this exact option',p['id']+' '+p['category']+' '+str(p['attributes']))
        for c in self.merchant_db.companies:add('merchant-reviews','/review/'+c['company_id'],c['name']+' reviews','Customer ratings and experiences',c['name']+' '+c['domain'])
        for a in self.product_reviews['public']['articles']:
            v=self.products[a['reviewed_sku']]
            if a['family']=='footwear':
                model=self.comparison_by_id[a['id']];add('reviews-footwear','/reviews/'+a['id'],a['model_name']+' review','Model review; see the article for the exact reviewed option',model['id']+' footwear '+str(model['attributes']))
            else:add('reviews-'+a['family'],'/reviews/'+a['id'],a['model_name']+' review','Exact reviewed option: '+v['name'],a['reviewed_sku']+' '+str(v['attributes']))
        if self.product_review_evidence is not None:
            for r in self.product_review_evidence['public']['reviews']:
                v=self.products[r['subject']['id']]
                add('reviews-'+v['category'],'/reviews/'+r['article_id']+'#'+r['review_id'],v['name']+' Reader Panel', 'Exact-option reader experience',v['product_id']+' '+r['body'])
        return docs

    def snapshot(self):
        accounts=self.account_pages.session.snapshot() if self.account_pages else None
        orders=[deepcopy(o) for a in accounts['accounts'] for o in a['orders']] if accounts is not None else []
        mutations=[deepcopy(e) for e in accounts['events'] if e['changed']] if accounts is not None else []
        return {'schema_version':'connected-shopping-journal-v2' if accounts is not None else 'connected-shopping-journal-v1','scope':'research_and_account_management' if accounts is not None else 'research_only','orders':orders,'commerce_mutations':mutations,
                **({'accounts':accounts} if accounts is not None else {}),
                'requests':{sid:s.access_log() for sid,s in self.sites.items()},
                **({'verification':{sid:g.snapshot() for sid,g in self.verification_gates.items()}} if self.verification_gates else {}),
                'consent':{sid:s.consent.snapshot() for sid,s in self.sites.items() if s.consent}}
    def close(self):
        if not self._closed:self._stack.close();self._closed=True
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
