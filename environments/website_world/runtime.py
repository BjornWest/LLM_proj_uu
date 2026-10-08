"""Isolated new-page runtime over a trusted native footwear pin.

No directory is mounted. Exact public endpoints/assets are allowlisted; the pin,
task/reference and private manifests remain server-side. Each retailer has a
separate origin. Reuse this context manager with a fresh browser per episode.
"""
from contextlib import ExitStack
from copy import deepcopy
from hashlib import sha256
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread, Lock
from urllib.parse import parse_qsl, urlencode, urlsplit
import json
from pathlib import Path

from environments.website_drafts.component_sampling import sample_components, canonical
from .adapter import PIN, ROOT, VERSION, PublicAdapter, load_pin, digest
from .presentation import validate_request, site_plan
from .coupons import Coupons
from .basket import Baskets, basket_shop_source
from .ecosystem import public_products
from .surrounding_config import validate as validate_surrounding
from .surrounding import mount as mount_surrounding

RUNTIME_VERSION = 'website-footwear-runtime-v1'
DRAFTS = ROOT / 'environments/website_drafts'
LOCAL = ROOT / 'environments/website_world'


class Host:
    def __init__(self, render, post_render=None, *, max_query_fields=20, post_routes=None):
        post_handlers = {'/api/basket-quote': post_render} if post_render is not None else {}
        if post_routes is not None:
            if type(post_routes) is not dict or set(post_routes)-{'/api/order'} or any(not callable(f) for f in post_routes.values()):
                raise ValueError('Only the explicit simulated-order route may extend this Host')
            post_handlers.update(post_routes)
        self.events = []
        self.lock = Lock()
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, status, body, mime):
                raw = body.encode() if isinstance(body, str) else body
                self.send_response(status)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src data:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(raw)
                with outer.lock:
                    outer.events.append({'method': self.command, 'path': self.path, 'status': status})

            def do_GET(self):
                try:
                    target = urlsplit(self.path)
                    if target.scheme or target.netloc or len(self.path) > 8192:
                        raise ValueError('Invalid target')
                    pairs = parse_qsl(target.query, keep_blank_values=True, strict_parsing=True, max_num_fields=max_query_fields)
                    if len(dict(pairs)) != len(pairs):
                        raise ValueError('Duplicate query field')
                    result = render(target.path, dict(pairs))
                except (ValueError, UnicodeError) as error:
                    result = 400, json.dumps({'error': str(error)}), 'application/json'
                except KeyError:
                    result = 404, '<h1>Page not found</h1>', 'text/html; charset=utf-8'
                self.respond(*result)

            def do_POST(self):
                callback = post_handlers.get(self.path)
                if callback is None:
                    self.respond(405, json.dumps({'error': 'Purchase and order mutations are unavailable'}), 'application/json')
                    return
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 262144 or self.headers.get_content_type() != 'application/json':
                        raise ValueError('Supply a bounded JSON basket request')
                    def unique(pairs):
                        result = {}
                        for key, value in pairs:
                            if key in result:
                                raise ValueError('Duplicate JSON field')
                            result[key] = value
                        return result
                    request = json.loads(self.rfile.read(size), object_pairs_hook=unique)
                    value = callback(request)
                    self.respond(200, json.dumps(value, ensure_ascii=False), 'application/json; charset=utf-8')
                except (ValueError, UnicodeError) as error:
                    self.respond(400, json.dumps({'error': str(error)}), 'application/json')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.origin = f'http://localhost:{self.server.server_port}'
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Runtime:
    def __init__(self, pin=PIN, *, presentation=None, coupon_pin=None, surrounding=None, basket_plan=None, checkout_domain=None, selected_content=False, page_variations=None, delivery_plan=None,lazy_publication=False,source_store=None,discovery_mode='index',readable_origins=False,review_presentation=None,page_option_order=None,partial_url_navigation=False,selector_capture=None):
        self.selector_capture_evidence = None
        if selector_capture is not None:
            from .selector_action_capture import options as selector_options
            selector_capture = selector_options(selector_capture)
        if type(partial_url_navigation) is not bool:
            raise ValueError('Partial URL navigation must be boolean')
        self.partial_url_navigation_evidence = None
        self.page_option_order_evidence = {}
        if page_option_order is not None:
            from .page_option_order import options as option_order_options
            page_option_order = option_order_options(page_option_order)
        self.review_presentation_evidence = None
        if review_presentation is not None:
            if surrounding is None:
                raise ValueError('Review presentation requires a native surrounding review surface')
            from .review_presentation import options as review_options
            review_presentation = review_options(review_presentation)
        if type(readable_origins) is not bool:
            raise ValueError('Readable origins must be boolean')
        self.origin_map = None
        self._browser_bridges = []
        if discovery_mode not in ('index', 'tool'):
            raise ValueError('Discovery mode must be index or tool')
        self.discovery_mode = discovery_mode
        if type(lazy_publication) is not bool:raise ValueError('Lazy publication must be boolean')
        self.lazy_publication=lazy_publication
        self.prepared=None
        if type(selected_content) is not bool:raise ValueError("selected_content must be boolean")
        recipe_selection=presentation.get('selected_content',False) if isinstance(presentation,dict) else False
        if type(recipe_selection) is not bool:raise ValueError('Invalid recipe selected_content flag')
        selected_content=selected_content or recipe_selection
        from .product_disclosure import validate_settings as validate_disclosure
        disclosure=validate_disclosure(presentation['product_disclosure']) if isinstance(presentation,dict) and 'product_disclosure' in presentation else None
        if page_variations is not None and not isinstance(page_variations,dict):raise ValueError("page_variations must map retailer IDs to explicit settings")
        header=json.loads((Path(pin)/'manifest.json').read_text())
        self.catalog_backend=None
        if header.get('schema_version') in ('accepted-catalog-commerce-pin-v1','accepted-catalog-commerce-pin-v2'):
            from . import catalog_adapter, catalog_checkout_domain
            self.catalog_backend=catalog_adapter
            self.world,self.pin=catalog_adapter.load_pin(pin,source_store=source_store)
            if coupon_pin is not None:raise ValueError('Accepted-catalog account/coupon adoption is unavailable')
            if basket_plan is None:basket_plan=catalog_adapter.basket_quote.make_plan(self.world)
            if checkout_domain is None:checkout_domain=catalog_checkout_domain.make(self.world)
            self.delivery_oracle = catalog_adapter.basket_quote
            if delivery_plan is not None:
                from experiments.accepted_catalog_commerce import delivery_admission
                self.delivery_oracle = delivery_admission.Oracle(self.world,basket_plan,delivery_plan)
            self.domain_provider=catalog_checkout_domain
            if lazy_publication:
                from experiments.accepted_catalog_commerce import prepared_quote
                self.prepared=prepared_quote.prepare(self.world,plan=basket_plan,admission_plan=delivery_plan)
            self.adapter=catalog_adapter.PublicAdapter(self.world,basket_plan,selected_content=selected_content,oracle=self.delivery_oracle,disclosure_settings=disclosure,
                disclosure_profiles=presentation.get('retailer_disclosure_profiles') if isinstance(presentation,dict) else None,
                prepared=self.prepared,lazy=lazy_publication)
        else:
            if lazy_publication:raise ValueError('Prepared lazy publication is released for accepted-catalog worlds only')
            if delivery_plan is not None and (basket_plan is None or checkout_domain is None):raise ValueError('Native delivery admission requires basket shipping and shared checkout domain')
            if selected_content:raise ValueError("Selected content requires accepted-catalog commerce")
            from . import checkout_domain as native_domain
            self.world,self.pin=load_pin(pin)
            if delivery_plan is not None:
                from experiments.accepted_catalog_commerce import delivery_admission
                self.delivery_oracle=delivery_admission.Oracle(self.world,basket_plan,delivery_plan)
                self.adapter=PublicAdapter(self.world,basket_plan=basket_plan,oracle=self.delivery_oracle)
            else:self.adapter=PublicAdapter(self.world)
            self.domain_provider=native_domain
            if basket_plan is None:
                from experiments.footwear_world_pilot import basket_quote as fresh_basket_quote
                basket_plan=fresh_basket_quote.make_plan(self.world)
                if checkout_domain is None:checkout_domain=native_domain.make(self.world)
        if page_variations and set(page_variations)-set(self.adapter.retailers):raise ValueError("Unknown retailer variation binding")
        if page_option_order and set(page_option_order)-set(self.adapter.retailers):
            raise ValueError('Unknown retailer option-order binding')
        if selector_capture and set(selector_capture)-set(self.adapter.retailers):
            raise ValueError('Unknown retailer selector-capture binding')
        self.selected_content=selected_content
        from environments.website_drafts.variation_settings import validate as validate_variations
        self.page_variations={rid:validate_variations(value) for rid,value in (page_variations or {}).items()}
        self.presentation = validate_request(self.world, presentation)
        requested_delivery = self.presentation is not None and 'delivery_options' in self.presentation
        if requested_delivery != (delivery_plan is not None):
            raise ValueError('Delivery sampling requires both its presentation settings and admission plan')
        self.delivery_plan=deepcopy(delivery_plan)
        self.coupons = Coupons(self.adapter, coupon_pin) if coupon_pin else None
        if checkout_domain is not None and basket_plan is None:
            raise ValueError('Shared checkout domain requires native basket shipping')
        if self.catalog_backend:
            self.baskets=Baskets(self.adapter,basket_plan,domain=checkout_domain,
                oracle=self.delivery_oracle,domain_provider=self.domain_provider,delivery_plan=delivery_plan,prepared=self.prepared)
        else:
            kwargs={'oracle':self.delivery_oracle,'delivery_plan':delivery_plan} if delivery_plan is not None else {}
            self.baskets = Baskets(self.adapter, basket_plan, self.coupons, checkout_domain,**kwargs) if basket_plan is not None else None
        from .simulated_order_runtime import initialize as initialize_orders
        initialize_orders(self)
        self._stack = ExitStack()
        self.sites = {}
        self.origins = {}
        self.compositions = {}
        self.public_catalogs = {}
        self.discovery = None
        self.surrounding_origins = {}
        if surrounding is not None:
            validate_surrounding(self.world, surrounding)
        review_export=self.catalog_backend.public_products if self.catalog_backend else public_products
        review_products = review_export(self.world) if surrounding is not None else {}
        self.review_products=review_products
        if surrounding is not None and surrounding['schema_version'] == 'native-rich-surrounding-v3' and not self.catalog_backend:
            raise ValueError('Rich review v3 requires accepted-catalog commerce')
        assets = {p.name: p.read_bytes() for p in DRAFTS.iterdir() if p.suffix in ('.js', '.css')}
        # No fixture catalogs, prices or quote evaluator are served on these hosts.
        for name in ('generated-catalog.js', 'market-range-fixture.js', 'reviewer.js'):
            assets.pop(name, None)
        for name, source in {'catalog.js': 'catalog.js', 'quote.js': 'world_quote.js', 'world-data.js': 'world_data.js'}.items():
            assets[name] = (LOCAL / source).read_bytes()
        if self.catalog_backend:
            source=assets['quote.js'].decode()
            source=source.replace('walking and everyday journeys','the available departments')
            source=source.replace('Check the EU size, width and fit guidance on the selected product page. Regular-width task requests correspond to the standard width label. Reference mass describes the specified reference configuration.',
                'Check the size system, available configurations and declared measurements on the selected product page. Clothing labels and EU footwear sizes use different systems; reference measurements describe only their stated configuration.')
            source=source.replace('Follow the care instructions supplied with your footwear. Material and construction details are listed on each product page.',
                'Follow the declared care instructions for the selected product and configuration. Clothing wash instructions, footwear materials and tablet care declarations are displayed where provided.')
            assets['quote.js']=source.encode()
        if self.baskets:
            assets['item_quote.js'] = assets['quote.js']
            assets['quote.js'] = (LOCAL/'basket_quote.js').read_bytes()
            assets['shop.js'] = basket_shop_source(assets['shop.js'].decode(),
                canonical_domain=checkout_domain is not None).encode()
        from .simulated_order_presentation import project_assets as order_assets
        assets, self.order_presentation_evidence = order_assets(assets,
            expected_source_sha256=sha256(assets['shop.js']).hexdigest())
        if surrounding is not None:
            # Additive served-renderer extension. The shared draft source and
            # legacy runtime behavior remain unchanged.
            source = assets['shop.js'].decode()
            hook = 'function productPage(id,params) {'
            if source.count(hook) != 1:
                raise ValueError('Product-page review extension hook changed')
            source = source.replace(hook, 'function originalProductPage(id,params) {')
            source += '\nimport {customerReviews} from "./retailer_reviews.js";\nfunction productPage(id,params){const body=originalProductPage(id,params);const p=products.find(p=>p.id===id);return body+(p?customerReviews(p,{e}):"");}\n'
            assets['shop.js'] = source.encode()
            assets['retailer_reviews.js'] = (LOCAL/'retailer_reviews.js').read_bytes()
        if review_presentation is not None:
            from .review_presentation import project_assets
            assets, self.review_presentation_evidence = project_assets(assets, review_presentation)
        if partial_url_navigation:
            from .partial_url_navigation import project_assets as navigation_assets
            assets, self.partial_url_navigation_evidence = navigation_assets(assets,
                expected_source_sha256=sha256(assets['shop.js']).hexdigest())
        if selector_capture is not None:
            from .selector_action_capture import project_assets as selector_assets
            assets, self.selector_capture_evidence = selector_assets(assets,
                expected_source_sha256=sha256(assets['shop.js']).hexdigest(), settings=selector_capture)
        self.asset_hashes = {name: sha256(body).hexdigest() for name, body in assets.items()}
        self.sources = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
                        for p in [*LOCAL.glob('*.py'), *LOCAL.glob('*.js'),
                                  DRAFTS/'shop.html', DRAFTS/'component_sampling.py', DRAFTS/'component-priors-v1.json', DRAFTS/'variation_settings.py',
                                  *[DRAFTS/name for name in assets if (DRAFTS/name).exists() and name not in ('catalog.js','quote.js')]]}
        field_rules=ROOT/'environments/product_world/public_field_rules.py'
        self.sources[str(field_rules.relative_to(ROOT))]=sha256(field_rules.read_bytes()).hexdigest()
        if delivery_plan is not None:
            source=ROOT/'experiments/accepted_catalog_commerce/delivery_admission.py'
            self.sources[str(source.relative_to(ROOT))]=sha256(source.read_bytes()).hexdigest()
        if selected_content:
            from environments.product_world.feature_publication import CATALOGUE
            from environments.product_world.tablet_publication import SPEC
            from environments.product_world.reviewed_feature_publication import CATALOGUE as REVIEWED
            catalogue=json.loads((CATALOGUE/'manifest.json').read_text())
            selected_sources=[ROOT/'environments/product_world/tshirt_publication.py',
                ROOT/'environments/product_world/tablet_publication.py',
                ROOT/'environments/product_world/feature_publication.py',
                ROOT/'environments/product_world/reviewed_feature_publication.py',
                ROOT/'environments/product_world/shared_state.py',
                CATALOGUE/'manifest.json', CATALOGUE/catalogue['concepts']['tops.t_shirts']['file'],
                SPEC, REVIEWED/'manifest.json', REVIEWED/'tablets.everyday_media_tablets.json']
            from environments.product_world import catalog_publication
            generic_concepts=sorted({p['public']['concept_id'] for p in self.world['products']} & set(catalog_publication.CONCEPTS))
            if generic_concepts:
                selected_sources.extend([Path(catalog_publication.__file__),
                    ROOT/'environments/product_world/disclosure_sampling.py',
                    ROOT/'environments/product_world/retailer_disclosure.py',
                    *[REVIEWED/(cid+'.json') for cid in generic_concepts]])
            self.sources.update({str(path.relative_to(ROOT)):sha256(path.read_bytes()).hexdigest() for path in selected_sources})
        if disclosure is not None:
            for name in ('disclosure_sampling.py','count_first_publication.py'):
                source=ROOT/'environments/product_world'/name
                self.sources[str(source.relative_to(ROOT))]=sha256(source.read_bytes()).hexdigest()
            if self.adapter.disclosure_profiles is not None:
                from environments.product_world.retailer_disclosure import SPEC
                for source in [ROOT/'environments/product_world/retailer_disclosure.py',SPEC]:
                    self.sources[str(source.relative_to(ROOT))]=sha256(source.read_bytes()).hexdigest()
        if surrounding is not None:
            index_source = ROOT/'environments/connected_shopping/index.py'
            self.sources[str(index_source.relative_to(ROOT))] = sha256(index_source.read_bytes()).hexdigest()
            if surrounding['schema_version'] == 'native-rich-surrounding-v3':
                review_style = ROOT/'environments/product_review_sites/render.py'
                self.sources[str(review_style.relative_to(ROOT))] = sha256(review_style.read_bytes()).hexdigest()
        if self.prepared is not None:
            source=ROOT/'experiments/accepted_catalog_commerce/prepared_quote.py'
            self.sources[str(source.relative_to(ROOT))]=sha256(source.read_bytes()).hexdigest()
        html = (DRAFTS / 'shop.html').read_text()
        self.html_hashes = {}
        try:
            option_order_catalogs = {}
            if page_option_order is not None or selector_capture is not None:
                from .page_option_order import validate_catalog, project_catalog
                # Validate all requested IDs/menus before the first Host.
                # Cache native plans/catalogs so each target is built once.
                for sid in dict.fromkeys([*(page_option_order or {}), *(selector_capture or {})]):
                    retailer = self.adapter.retailers[sid]
                    plan = site_plan(self.world, retailer, self.presentation,
                                     coupon_supported=self.coupons is not None,
                                     basket_policy=self.baskets.policy(sid) if self.baskets else None)
                    if sid in self.page_variations:
                        plan['config']['variations'] = deepcopy(self.page_variations[sid])
                    if 'deliveryOrder' in plan['config']:
                        self.adapter.delivery_orders[sid] = plan['config']['deliveryOrder']
                    public = self.adapter.catalog(sid, plan['config'], presentation=plan.get('presentation'))
                    if page_option_order is not None and sid in page_option_order:
                        validate_catalog(public, retailer_id=sid, settings=page_option_order)
                    if selector_capture is not None and sid in selector_capture:
                        from .selector_action_capture import validate_catalog as validate_selector_catalog
                        validate_selector_catalog(public, retailer_id=sid, settings=selector_capture)
                    option_order_catalogs[sid] = (plan, public)
            for sid, retailer in self.adapter.retailers.items():
                if sid in option_order_catalogs:
                    plan, public = option_order_catalogs[sid]
                else:
                    plan = site_plan(self.world, retailer, self.presentation,
                                     coupon_supported=self.coupons is not None,
                                     basket_policy=self.baskets.policy(sid) if self.baskets else None)
                    if sid in self.page_variations:
                        plan["config"]["variations"]=deepcopy(self.page_variations[sid])
                    if 'deliveryOrder' in plan['config']:
                        self.adapter.delivery_orders[sid]=plan['config']['deliveryOrder']
                    public = self.adapter.catalog(sid, plan['config'],
                        presentation=plan.get('presentation'))
                public['simulatedOrders'] = True
                self.compositions[sid] = plan
                if surrounding is not None:
                    for product in public['products']:
                        corpus = review_products[product['canonicalProductId']]
                        product['reviewCorpus'] = {k: deepcopy(corpus[k]) for k in ('reviews', 'rating_summary')}
                if self.coupons:
                    public['couponProgramme'] = True
                    public['account'] = self.coupons.account(sid)
                    public['couponScopes'] = {p['public']['concept_id']:
                        p['public']['concept'].replace('_', ' ')
                        for p in self.world['products']}
                if self.baskets:
                    public['basket'] = {'worldId': self.world['world_id'],
                        'planId': self.baskets.plan_id, 'policy': self.baskets.policy(sid)}
                    if self.baskets.domain is not None:
                        public['basket']['domain'] = self.baskets.public_domain(sid)
                if page_option_order is not None and sid in page_option_order:
                    public, evidence = project_catalog(public, retailer_id=sid, settings=page_option_order)
                    self.page_option_order_evidence[sid] = evidence
                if self.partial_url_navigation_evidence is not None:
                    from .partial_url_navigation import menu_binding
                    self.partial_url_navigation_evidence['catalog_menus'][sid] = menu_binding(public)
                self.public_catalogs[sid] = public
                body = html.replace('Northline', escape(retailer['name']))
                self.html_hashes[sid] = sha256(body.encode()).hexdigest()
                def render(path, query, *, sid=sid, body=body):
                    if path in ('/', '/shop.html'):
                        if query:
                            raise ValueError('Unexpected page query')
                        return 200, body, 'text/html; charset=utf-8'
                    if path == '/api/catalog':
                        if query:
                            raise ValueError('Unexpected catalog query')
                        return 200, json.dumps(self.public_catalogs[sid], ensure_ascii=False), 'application/json; charset=utf-8'
                    if path == '/api/fulfilment':
                        address=dict(query)
                        if self.lazy_publication:
                            sku=address.pop('sku_id',None)
                            value=(self.adapter.pending_fulfilment(sid,address) if sku is None else
                                   self.adapter.fulfilment(sid,address,sku_ids=[sku]))
                        else:value = self.adapter.fulfilment(sid, address)
                        return 200, json.dumps(value, ensure_ascii=False), 'application/json; charset=utf-8'
                    if path == '/api/quote' and self.coupons:
                        value = self.coupons.quote(sid, query)
                        return 200, json.dumps(value, ensure_ascii=False), 'application/json; charset=utf-8'
                    name = path.removeprefix('/')
                    if query or name not in assets:
                        raise KeyError('Unknown public path')
                    return 200, assets[name], 'text/css' if name.endswith('.css') else 'text/javascript; charset=utf-8'
                post = (lambda request, sid=sid: self.baskets.quote(sid, request)) if self.baskets else None
                from .simulated_order_runtime import submit as submit_order
                order_post = lambda request, sid=sid: submit_order(self,sid,request)
                host = self._stack.enter_context(Host(render, post, post_routes={'/api/order': order_post}))
                self.sites[sid] = host
                self.origins[sid] = host.origin
            self.index = self._stack.enter_context(Host(self.index_page))
            self.index_origin = self.index.origin
            if discovery_mode == 'tool':
                def research_page(path, query):
                    from .discovery_start import page, script
                    if path == '/discovery-start.js' and not query:
                        return 200, script(), 'text/javascript; charset=utf-8'
                    if path != '/' or query:
                        raise KeyError('Unknown research page')
                    return 200, page(), 'text/html; charset=utf-8'
                self.research = self._stack.enter_context(Host(research_page))
                self.research_origin = self.research.origin
        except BaseException:
            self._stack.close()
            raise
        sku_urls, offer_urls, pages = {}, {}, {}
        for sid, public in self.public_catalogs.items():
            sku_urls[sid] = {}
            pages[sid] = {}
            for product in public['products']:
                pages[sid][product['id']] = self.origins[sid] + '/#/product/' + product['id']
                for variant in product['variants']:
                    behavior = public['configuration']['url']
                    encoded = {k: v for k, v in variant['selection'].items()
                               if behavior == 'all' or behavior == 'colour' and k == 'colour'}
                    url = pages[sid][product['id']] + ('?' + urlencode(encoded) if encoded else '')
                    sku_urls[sid][variant['skuId']] = url
                    offer_urls[variant['offerId']] = {'retailer_id': sid, 'product_id': product['canonicalProductId'],
                        'sku_id': variant['skuId'], 'url': url,
                        'required_selection': {k: v for k, v in variant['selection'].items() if k not in encoded},
                        'url_behavior': behavior, 'selection': deepcopy(variant['selection'])}
        self.bindings = {'schema': RUNTIME_VERSION, 'origins': self.origins,
                         'retailer_skus': sku_urls, 'retailer_offers': offer_urls, 'retailer_pages': pages}
        self.navigation_origins = [self.index_origin, *self.origins.values()]
        from .discovery import retailer_records
        from .site_discovery import DiscoverSites
        self.site_registry = retailer_records(self.public_catalogs, self.origins)[0]
        self.site_discovery = DiscoverSites(self.site_registry)
        if discovery_mode == 'tool':
            self.navigation_origins = [self.research_origin, *self.origins.values()]
        if surrounding is not None:
            try:
                mount_surrounding(self, surrounding, Host)
            except BaseException:
                self._stack.close()
                raise
        self.manifest = {'schema': RUNTIME_VERSION, 'adapter_version': VERSION,
            'world_id': self.world['world_id'], 'world_sha256': self.pin['files'].get('world.json', self.pin['files'].get('world.private.json')),
            'start_url': self.index_origin, 'sites': [{'retailer_id': sid, 'name': self.adapter.retailers[sid]['name'],
                'origin': origin, 'offers': sum(len(p['variants']) for p in self.public_catalogs[sid]['products']),
                'pages': len(self.public_catalogs[sid]['products'])} for sid, origin in self.origins.items()],
            'source_sha256': self.sources, 'served_asset_sha256': self.asset_hashes,
            'served_html_sha256': self.html_hashes,
            'capabilities': ['listed_sku_pages', 'source_stock', 'single_item_delivery_inquiry'],
            'purchase_supported': False, 'automatic_grader_supported': False,
            'prose_mapping_status': 'unmapped',
            'presentation_schema': self.presentation['schema'] if self.presentation else None,
            'limitations': ['Frozen shoe/sandal development pin, not arbitrary accepted-width commerce.',
                           'Manual verification against the native private reference.',
                           'Single-item quantity-one quotes only; no multi-line baskets or order mutation.',
                           'Branch stock/transfers shown; no invented store-transfer checkout fees.',
                           'No shared assertion exporter or complete exposure-coverage claim.',
                           'Coupon opacity requires an opt-in native coupon pin.',
                           'Presentation/form overrides are declared development setup conditions.']}
        if self.review_presentation_evidence is not None:
            self.manifest['review_presentation'] = deepcopy(self.review_presentation_evidence)
        if self.page_option_order_evidence:
            self.manifest['page_option_order'] = deepcopy(self.page_option_order_evidence)
        if self.partial_url_navigation_evidence is not None:
            self.manifest['partial_url_navigation'] = deepcopy(self.partial_url_navigation_evidence)
        if self.selector_capture_evidence is not None:
            self.manifest['selector_capture'] = deepcopy(self.selector_capture_evidence)
        if self.coupons:
            self.manifest['capabilities'].append('single_item_native_coupon_quote')
            self.manifest['coupon_pin'] = deepcopy(self.coupons.manifest)
            self.manifest['limitations'].append('Explicit initial signed-in coupon fixture; no account mutations or natural coupon sampler.')
        if surrounding is not None:
            self.manifest['surrounding'] = {'schema_version': surrounding['schema_version'],
                'sites': deepcopy(self.site_registry), 'sidecar_sha256': sha256(json.dumps(surrounding, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                'coverage_seed': surrounding['coverage_seed'],
                'index_documents': len(self.discovery.catalog.documents)}
            self.manifest['capabilities'].append('public_search_index')
            kinds = {site['kind'] for site in surrounding['sites']}
            if 'aggregator' in kinds:
                self.manifest['capabilities'].append('partial_model_price_snapshots')
            if 'product_reviews' in kinds:
                self.manifest['capabilities'].append('syndicated_product_reviews')
            self.manifest['limitations'].extend(['Comparison prices are native item-price snapshots; no independently stale advertising layer.',
                'Review publications syndicate one native corpus; no additional independent tests or votes.',
                'Native merchant-review evidence is unavailable; merchant-review hosts and retailer badges are deferred.'])
        if self.baskets:
            self.manifest['capabilities'].append('native_basket_delivery_inquiry')
            self.manifest['basket'] = {'plan_sha256': self.baskets.plan_id,
                'schema_version': self.baskets.plan['schema_version'], 'origin': self.baskets.plan['origin']}
            self.manifest['limitations'] = [s for s in self.manifest['limitations']
                if s != 'Single-item quantity-one quotes only; no multi-line baskets or order mutation.']
            self.manifest['limitations'].extend([
                'Basket shipping uses explicit world-bound policies and deterministic source dispatch; no global basket optimizer or basket task/grader.',
                'Charged transfers, natural basket-policy/coupon/choice-count sampling and broad product envelopes remain unimplemented.',
                'Optional arrival groups share their required delivery service; no purchase/order mutation.'])

        if self.catalog_backend:
            self.bindings['schema']='website-accepted-catalog-runtime-v1'
            self.manifest.update(schema='website-accepted-catalog-runtime-v1',adapter_version=self.catalog_backend.VERSION,
                capabilities=['listed_sku_pages','source_stock','central_basket_delivery_inquiry',
                    'source_status_and_scoped_prose',*[c for c in self.manifest['capabilities'] if c in
                    ('public_search_index','partial_model_price_snapshots','syndicated_product_reviews')]],
                limitations=['Closed walking/casual footwear, T-shirts and media-tablet regular-parcel slice.',
                    'Manufacturer reference prices are distinct from retailer offers.',
                    'Prose remains unmapped; no complete assertion/exposure claim.',
                    'Native footwear task/grader is separate; manual task inspection only.',
                    'Account/coupon, bulky, charged transfer and natural basket-policy sampling remain unavailable.'])

        if delivery_plan is not None:
            self.manifest['capabilities'].append('sampled_delivery_menus')
            self.manifest['delivery_options']={'admission_plan_sha256':digest(delivery_plan),
                'orders':deepcopy(self.adapter.delivery_orders),
                'scope':'Fixed seeded retailer menus; address/cart eligibility can reduce alternatives; live authoritative sorting.'}
        self.manifest['discovery'] = {'mode': discovery_mode,
            'callable': 'runtime.site_discovery.search',
            'site_count': len(self.site_registry), 'index_origin': self.index_origin,
            'tool_registration': 'Requires explicitly adopted harness profile and callback'}
        self.manifest['capabilities'].append('public_site_discovery_callable')
        if discovery_mode == 'tool':
            self.manifest['start_url'] = self.research_origin + '/'
        if selected_content:
            self.manifest['capabilities'].extend(['selected_tshirt_content','selected_media_tablet_content'])
            self.manifest['prose_mapping_status']='selected_tshirt_and_media_tablet_assertions; legacy_other_concepts_unmapped'
            self.manifest['selected_content']={'schema':'selected-product-content-v1',
                'concept_ids':['tops.t_shirts','tablets.everyday_media_tablets'],'opt_in':True,
                'tablet_cache_scope':'Immutable adapter world/seed and retailer/product/SKU; topic draws stay retailer/product-stable',
                'sampling':disclosure['protocol'] if disclosure is not None else 'Existing producer group-probability selection',
                'scope':'Retailer optional descriptions, detail rows, highlights and card/public payloads; independent review/comparison publications retain their own disclosure.'}
            self.manifest['limitations']=[line for line in self.manifest['limitations'] if line!='Prose remains unmapped; no complete assertion/exposure claim.']
            self.manifest['limitations'].append('Selected T-shirt and media-tablet statements are mapped; other prose is unmapped. No complete task evidence/exposure coverage acceptance.')
            if generic_concepts:
                self.manifest['capabilities'].append('selected_generic_catalog_content')
                self.manifest['selected_content']['concept_ids'].extend(generic_concepts)
                self.manifest['selected_content']['generic_protocol']=catalog_publication.VERSION
                self.manifest['selected_content']['generic_cache_scope']='Immutable adapter world/seed and retailer/product/SKU plus disclosure options/profile digest'
                self.manifest['prose_mapping_status']='Selected specialty assertions and generic source-scoped scalar records; undeclared semantic meanings remain unmapped'
                self.manifest['limitations'][-1]='Generic scalar records retain authored assertion or native source-field mapping status. No complete task evidence/exposure coverage acceptance.'
        if disclosure is not None:
            self.manifest['product_disclosure']={'controls':deepcopy(disclosure),
                'cache_control_sha256':self.adapter.disclosure_digest,
                'topic_scope':'Retailer/product stable; SKU resolves availability without topic refill',
                'conditioning':'Selected-topic event masses are not adopted as world visible-evidence requirements'}
            if self.adapter.disclosure_profiles is not None:
                self.manifest['product_disclosure'].update(retailer_profiles=deepcopy(self.adapter.disclosure_profiles),
                    cache_profile_sha256=deepcopy(self.adapter.disclosure_profile_digests))
        if self.presentation is not None and 'variation_priors' in self.presentation:
            self.manifest['page_variations'] = {
                'mode': 'seeded_conditional',
                'schema': self.presentation['variation_priors']['schema'],
                # Priors exist even when the natural world has no retailers.
                'priors_sha256': sha256(canonical(self.presentation['variation_priors']).encode()).hexdigest(),
                'scope': 'Site conventions first; page choices conditional on their selected module.',
                'inactive': ['Gallery media are unavailable in the current live product export.']}
        if self.page_variations:
            self.manifest['page_variations']={'mode':'explicit_authoring_overrides','retailers':deepcopy(self.page_variations)}
        if self.lazy_publication:
            self.manifest['publication']={'mode':'lazy_selected_sku','prepared_binding':self.prepared.binding,
                                         'status':'bounded_candidate_independent_adoption_pending'}
        self.manifest['purchase_supported'] = True
        self.manifest['capabilities'].append('simulated_checkout_completion')
        self.manifest['simulated_orders'] = {'schema': 'website-simulated-order-runtime-v1',
            'default': True, 'presentation': deepcopy(self.order_presentation_evidence),
            'scope': 'Private simulated receipts only; no payment, stock or fulfillment mutation'}
        self.manifest['limitations'] = [s.replace('no purchase/order mutation','simulated order completion only') for s in self.manifest['limitations']]
        if readable_origins:
            try:
                self._adopt_readable_origins()
            except BaseException:
                self._stack.close()
                raise

    def _adopt_readable_origins(self):
        from .local_origins import OriginMap
        from .site_discovery import DiscoverSites
        # Renderer instances retain transport URLs for ordinary human previews.
        # The browser bridge projects their HTTP responses using this same map.
        self.preview_origins = deepcopy(self.origins)
        self.preview_bindings = deepcopy(self.bindings)
        self.preview_index_origin = self.index_origin
        self.preview_site_discovery = self.site_discovery
        records = deepcopy(self.site_registry)
        records.append({'site_id': '@index', 'name': 'World index', 'kind': 'index', 'origin': self.index_origin})
        if self.discovery_mode == 'tool':
            self.preview_research_origin = self.research_origin
            records.append({'site_id': '@start', 'name': 'New tab', 'kind': 'start', 'origin': self.research_origin})
        self.origin_map = OriginMap(records, world_id=self.world['world_id'])
        for attribute in ('origins', 'surrounding_origins', 'index_origin', 'navigation_origins', 'bindings', 'site_registry', 'manifest'):
            setattr(self, attribute, self.origin_map.project(getattr(self, attribute)))
        if self.discovery_mode == 'tool':
            self.research_origin = self.origin_map.to_public(self.research_origin)
        self.site_discovery = DiscoverSites(self.site_registry)
        self.manifest['logical_origins'] = self.origin_map.descriptor
        self.manifest['capabilities'].append('context_local_readable_origins')
        dependency = ROOT/'intent_browser/checkpoint_browser.py'
        self.sources[str(dependency.relative_to(ROOT))] = sha256(dependency.read_bytes()).hexdigest()
        self.manifest['source_sha256'] = deepcopy(self.sources)

    def attach_browser(self, context):
        """Attach to the existing task page before navigation; Chromium only."""
        if self.origin_map is None:
            return None
        if any(owned is context for owned, _ in self._browser_bridges):
            raise ValueError('Readable-origin bridge already attached to context')
        from .local_origins import LocalOriginBridge
        bridge = LocalOriginBridge(self.origin_map)
        try:
            bridge.attach(context)
        except BaseException:
            bridge.close()
            raise
        self._browser_bridges.append((context, bridge))
        return bridge

    def preview_url(self, url):
        """Resolve a public URL/answer to its unchanged local preview transport."""
        return self.origin_map.to_transport(url) if self.origin_map else url

    def index_page(self, path, query):
        if self.discovery is not None:
            return self.discovery.page(path, query)
        if path != '/' or query:
            raise KeyError('Unknown index page')
        from .discovery import directory_page
        return 200, directory_page(getattr(self, 'preview_site_discovery', self.site_discovery), search=False), 'text/html; charset=utf-8'

    def snapshot(self):
        ledger=self.orders.snapshot()
        return {'world_id': self.world['world_id'], 'requests': {sid: deepcopy(host.events) for sid, host in self.sites.items()},
                'orders': ledger['orders'], 'commerce_mutations': ledger['events'], 'order_snapshot': ledger}

    def close(self):
        for _, bridge in self._browser_bridges:
            bridge.close()
        self._stack.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
