"""Opt-in carrier host; existing Runtime and all old hosts remain untouched."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from .runtime import Runtime, Host, ROOT
from .site_discovery import DiscoverSites, PUBLIC_KINDS
from .carrier_review_pages import CarrierReviewPages, path
from . import carrier_review_task as native

VERSION = 'website-carrier-review-runtime-v1'
_KINDS = {**PUBLIC_KINDS,'carrier_reviews':'review'}


class CarrierDirectory(DiscoverSites):
    __init__ = _bind(DiscoverSites.__init__,PUBLIC_KINDS=_KINDS)
    search = _bind(DiscoverSites.search,PUBLIC_KINDS=_KINDS)


class CarrierReviewRuntime(Runtime):
    def __init__(self,*args,publication,**kwargs):
        self.carrier_publication=deepcopy(publication);self._carrier_mounted=False
        try:
            super().__init__(*args,**kwargs)
            if not self._carrier_mounted:self._mount_carrier()
        except BaseException:
            if hasattr(self,'_stack'):self._stack.close()
            raise

    def _mount_carrier(self):
        if self.carrier_publication!=native.public_projection(self.world):raise ValueError('Carrier profile publication changed')
        data=self.carrier_publication;sid=data['site_id']
        if sid in self.sites or any(s['site_id']==sid for s in self.site_registry):raise ValueError('Carrier site identity collides')
        view=CarrierReviewPages(data)
        assert view.page('/',{})[0]==200
        for cid in view.profiles:assert view.page(path(cid),{})[0]==200
        host=self._stack.enter_context(Host(view.page));self.sites[sid]=host
        self.surrounding_origins[sid]=host.origin;self.carrier_view=view
        self.site_registry.append({'site_id':sid,'kind':data['kind'],'name':data['name'],'origin':host.origin,'families':[],
            'types':['carrier profiles','delivery companies','parcel reviews'],
            'description':'Published customer reviews and dated star ratings for delivery companies; regular and bulky service policies and collection locations.'})
        self.navigation_origins.append(host.origin);self.site_discovery=CarrierDirectory(self.site_registry)
        self.bindings['carrier_profiles']={cid:host.origin+path(cid) for cid in view.profiles}
        self.manifest['capabilities'].append('published_carrier_review_profiles')
        self.manifest['carrier_reviews']={'schema':VERSION,'site_id':sid,'profiles':len(view.profiles),'ratings':sum(len(p['reviews']) for p in data['profiles']),'publication_sha256':sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'binding_status':'bound','handler_routes_validated':True,'browser_exposure':'not_inferred'}
        self.manifest['discovery']['site_count']=len(self.site_registry)
        for module in ['carrier_review_runtime.py','carrier_review_pages.py']:
            p=Path(__file__).with_name(module);self.sources[str(p.relative_to(ROOT))]=sha256(p.read_bytes()).hexdigest()
        self.manifest['source_sha256']=deepcopy(self.sources);self._carrier_mounted=True

    def _adopt_readable_origins(self):
        """Same single OriginMap as Runtime; carrier sites use the private directory."""
        from .local_origins import OriginMap
        self._mount_carrier()
        self.preview_origins=deepcopy(self.origins);self.preview_bindings=deepcopy(self.bindings)
        self.preview_index_origin=self.index_origin;self.preview_site_discovery=self.site_discovery
        records=deepcopy(self.site_registry)
        records.append({'site_id':'@index','name':'World index','kind':'index','origin':self.index_origin})
        if self.discovery_mode=='tool':
            self.preview_research_origin=self.research_origin
            records.append({'site_id':'@start','name':'New tab','kind':'start','origin':self.research_origin})
        self.origin_map=OriginMap(records,world_id=self.world['world_id'])
        for attribute in ['origins','surrounding_origins','index_origin','navigation_origins','bindings','site_registry','manifest']:
            setattr(self,attribute,self.origin_map.project(getattr(self,attribute)))
        if self.discovery_mode=='tool':self.research_origin=self.origin_map.to_public(self.research_origin)
        self.site_discovery=CarrierDirectory(self.site_registry);self.manifest['logical_origins']=self.origin_map.descriptor
        self.manifest['capabilities'].append('context_local_readable_origins')
        dependency=ROOT/'intent_browser/checkpoint_browser.py';self.sources[str(dependency.relative_to(ROOT))]=sha256(dependency.read_bytes()).hexdigest()
        self.manifest['source_sha256']=deepcopy(self.sources)

    def index_page(self,path_,query):
        if path_=='/' and not query and self._carrier_mounted:
            from .discovery import directory_page
            return 200,directory_page(getattr(self,'preview_site_discovery',self.site_discovery),search=self.discovery is not None),'text/html; charset=utf-8'
        return super().index_page(path_,query)
