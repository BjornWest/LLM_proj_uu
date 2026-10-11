"""`Runtime` with one retailer mounted as a commerce scenario.

Purely additive: `runtime.py` is reused through the existing rebinding idiom
(`catalog_branch_runtime.BranchRuntime`). The scenario retailer's host gains
`POST /api/session`, its basket-quote and order handlers are wrapped, and its
served assets are projected after the native chain. Every other host, and a
`ScenarioRuntime` built without a scenario, is the native one.
"""
from copy import deepcopy
from secrets import token_hex

from experiments.accepted_catalog_commerce.execution import _bind
from environments.website_world.runtime import Host, Runtime
from . import assets as scenario_assets
from .settings import options, plain, public_settings, validate_catalog
from .store import SessionStore

VERSION = 'website-commerce-scenario-runtime-v1'
SESSION_PATH = '/api/session'
PUBLIC_KEY = 'commerceScenario'
NATIVE_POSTS = {'/api/basket-quote', '/api/order'}


def admit_post_route(host, path, callback):
    """Add one POST route to a constructed native `Host`.

    `Host` only accepts `/api/order` as an extra route, so the route is added
    to the handler table the native `do_POST` already reads. The handler class
    and its request parsing, limits and headers stay the native ones.
    """
    handler = host.server.RequestHandlerClass.do_POST
    names = handler.__code__.co_freevars
    table = handler.__closure__[names.index('post_handlers')].cell_contents if 'post_handlers' in names else None
    if type(table) is not dict or set(table) - NATIVE_POSTS or path in table or not callable(callback):
        raise ValueError('Native Host POST table changed; cannot admit the session route')
    table[path] = callback


class ScenarioRuntime(Runtime):
    def __init__(self, *args, scenario=None, scenario_assets=None, **kwargs):
        """`scenario` are settings for one retailer (see `settings.options`).

        `scenario_assets` maps served names to bytes of a family's page pieces.
        """
        self.scenario = options(scenario)
        self.session = None
        self.scenario_evidence = None
        self.closed = False
        if self.scenario is None:
            if scenario_assets:
                raise ValueError('Scenario page pieces need a scenario')
            Runtime.__init__(self, *args, **kwargs)
            return
        self._scenario_pieces = dict(scenario_assets or {})
        _bind(Runtime.__init__, Host=self._host)(self, *args, **kwargs)
        try:
            if self.session is None:
                raise ValueError('Unknown scenario retailer: ' + self.scenario['retailer_id'])
            self.manifest['commerce_scenario'] = {
                'schema': VERSION, 'retailer_id': self.scenario['retailer_id'],
                'settings': plain(self.scenario), 'assets': deepcopy(self.scenario_evidence),
                'scope': 'One target retailer; other hosts and their assets are native'}
        except BaseException:
            self.close()
            raise

    def _host(self, render, post_render=None, **kwargs):
        """Stand-in for `Host` inside `Runtime.__init__`; native unless it is the target retailer."""
        defaults = getattr(render, '__kwdefaults__', None) or {}
        target = self.scenario['retailer_id']
        if getattr(render, '__qualname__', '') != 'Runtime.__init__.<locals>.render' or defaults.get('sid') != target:
            return Host(render, post_render, **kwargs)
        if self.session is not None or post_render is None or set(kwargs) != {'post_routes'} \
                or set(kwargs['post_routes']) != {'/api/order'}:
            raise ValueError('Scenario retailer host is not the expected order-capable shop')
        catalog = self.public_catalogs[target]
        offers = validate_catalog(self.scenario, catalog)
        served, self.scenario_evidence = scenario_assets.project_assets(
            {name: render('/' + name, {})[1] for name in ('shop.js', 'quote.js')},
            expected_source_sha256=self.asset_hashes['shop.js'],
            expected_quote_sha256=self.asset_hashes['quote.js'], pieces=self._scenario_pieces)
        self.public_catalogs[target] = {**catalog, PUBLIC_KEY: public_settings(self.scenario, self._scenario_pieces)}
        store = self.session = SessionStore(self.scenario, offers=offers, runtime_id=token_hex(16))
        native_order = kwargs['post_routes']['/api/order']

        def scenario_render(path, query):
            name = path.removeprefix('/')
            if name in served and not query:
                return 200, served[name], 'text/css' if name.endswith('.css') else 'text/javascript; charset=utf-8'
            return render(path, query)

        def quote(request):
            reply = post_render(request)
            # Where the shop would pick its own default (no selection, or a stale one it
            # reset), the scenario's default applies instead, quoted by the same native oracle.
            if request['selections'] is None or reply.get('selectionReset'):
                selection = store.default_selection(request, reply)
                if selection is not None and selection != (reply.get('selected') or {}).get('selection'):
                    preferred = post_render({**request, 'selections': selection})
                    if preferred.get('selected') and not preferred.get('selectionReset'):
                        reply = {**preferred, 'selectionReset': bool(reply.get('selectionReset'))}
            store.observe_quote(request, reply)
            return reply

        host = Host(scenario_render, quote,
                    post_routes={'/api/order': lambda request: store.submit_order(request, native_order)})
        admit_post_route(host, SESSION_PATH, store.handle)
        return host

    def served_asset_hashes(self, retailer_id):
        """SHA-256 of every asset this retailer serves."""
        hashes = dict(self.asset_hashes)
        if self.scenario is not None and retailer_id == self.scenario['retailer_id']:
            hashes.update(self.scenario_evidence['served_asset_sha256'])
        return hashes

    def close(self):
        super().close()
        self.closed = True
