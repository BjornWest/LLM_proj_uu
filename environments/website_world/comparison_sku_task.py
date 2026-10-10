"""Bounded model lookup followed by live stock verification for one exact SKU.

The comparison's cheapest advertised listing is the target even if unavailable;
this is not a cheapest-available or shipping-inclusive optimization task. Native
stock comes from the retained world, never from the comparison price snapshot.
"""
from copy import deepcopy
from hashlib import sha256
import json
from urllib.parse import quote

VERSION = 'website-comparison-sku-stock-task-v1'


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def make(world, surrounding, *, comparison_site_id, sku_id):
    sites = [s for s in surrounding['sites']
             if s['site_id'] == comparison_site_id and s['kind'] == 'aggregator']
    if len(sites) != 1 or surrounding['source_world_id'] != world['world_id']:
        raise ValueError('Comparison site/world identity mismatch')
    # Surrounding sidecars use the Website adapter JSON digest, which preserves
    # historical json.dumps spacing. Keep that producer identity unchanged.
    if surrounding['source_world_sha256'] != sha256(
            json.dumps(world, sort_keys=True, ensure_ascii=False).encode()).hexdigest():
        raise ValueError('Comparison source bytes changed')
    targets = [(p, sku) for p in world['products'] for sku in p['public']['skus']
               if sku['sku_id'] == sku_id]
    if len(targets) != 1:
        raise ValueError('Select one manufactured SKU')
    product, sku = targets[0]
    pid = product['public']['product_id']
    if pid not in sites[0]['product_ids']:
        raise ValueError('Target model is not published on the selected comparison site')
    dimensions = sorted(product['variant_fields'])
    selectors = {k: deepcopy(sku[k]) for k in dimensions}
    matching = [s for s in product['public']['skus']
                if all(s[k] == v for k, v in selectors.items())]
    if len(matching) != 1:
        raise ValueError('Variant requirements do not identify one SKU')
    if sum(p['public']['name'] == product['public']['name'] for p in world['products']) != 1:
        raise ValueError('Displayed model name is ambiguous in this world')
    labels = {'colour': 'colour', 'size_eu': 'EU size', 'width': 'width'}
    description = ', '.join(f'{labels.get(k, k.replace("_", " "))} {v}'
                            for k, v in selectors.items())
    name, site_name = product['public']['name'], sites[0]['name']
    message = (f'On {site_name}, find the comparison page for {name}, {description}. '
        'Open the retailer with the lowest listed item price on that comparison page '
        'and select this exact variant. Confirm whether it is in stock at a shop or '
        'warehouse; a supplier backorder does not count as in stock. '
        'Report the comparison-page link, retailer, listed item price, stock status '
        'and retailer product link. If it is only in stock at a physical shop, say so. '
        f'Use only {site_name} to compare prices; you only need to visit a cheapest '
        'listed retailer to verify the variant and stock. If several retailers tie, '
        'checking any one is sufficient. Exclude shipping, coupons and cart deals. '
        'Do not place an order.')
    task = {'schema_version': VERSION, 'kind': 'comparison_cheapest_exact_sku_stock',
        'world_id': world['world_id'], 'world_sha256': digest(world),
        'surrounding_sha256': digest(surrounding),
        'comparison_site_id': comparison_site_id, 'product_id': pid, 'sku_id': sku_id,
        'product_name': name, 'selectors': selectors,
        'requirements': {'comparison_scope': comparison_site_id, 'exact_sku': sku_id,
            'ranking': 'minimum_comparison_model_item_price', 'quantity': 1,
            'stock_source': 'live_retailer', 'in_stock': 'positive_shop_or_warehouse_quantity',
            'supplier_backorder_counts_as_stock': False, 'tied_retailers': 'any_one',
            'unavailable_cheapest': 'report_unavailability_do_not_search_for_a_replacement',
            'report': ['comparison_url', 'retailer', 'listed_item_price', 'stock_status', 'retailer_url']},
        'user_message': message, 'memories': []}
    task['task_id'] = 'comparison-sku-stock-' + digest(task)[:24]
    return task


def reference(world, surrounding, task):
    expected = make(world, surrounding, comparison_site_id=task['comparison_site_id'],
                    sku_id=task['sku_id'])
    if task != expected:
        raise ValueError('Task requirements or source binding changed')
    site = next(s for s in surrounding['sites'] if s['site_id'] == task['comparison_site_id'])
    rows = [r for r in site['listings'] if r['product_id'] == task['product_id']]
    retailers = {r['retailer_id']: r for r in world['retailers']}
    if not rows:
        raise ValueError('Selected model has no comparison listings')
    minimum = min(r['price_minor'] for r in rows)
    winners = []
    for row in sorted(rows, key=lambda r: (r['price_minor'], r['retailer_id'])):
        if row['price_minor'] != minimum:
            continue
        retailer = retailers[row['retailer_id']]
        offers = [o for o in retailer['offers'] if o['sku_id'] == task['sku_id']]
        if len(offers) > 1:
            raise ValueError('Retailer/SKU offer identity is ambiguous')
        offer = offers[0] if offers else None
        sources = {s['source_id']: s for s in retailer['source_locations']}
        stocks = []
        if offer:
            for sid, quantity in offer['stock_by_source'].items():
                if type(quantity) is not int or quantity < 0 or sid not in sources:
                    raise ValueError('Invalid native source stock')
                if quantity:
                    stocks.append({'source_id': sid, 'quantity': quantity,
                                   'shipping_enabled': sources[sid]['shipping_enabled'],
                                   'source': deepcopy(sources[sid])})
        winners.append({'retailer_id': retailer['retailer_id'], 'retailer_name': retailer['name'],
            'advertised_price_minor': row['price_minor'],
            'offer_id': offer['offer_id'] if offer else None,
            'live_price_minor': offer['price_minor'] if offer else None,
            'in_stock': bool(stocks), 'stock': stocks,
            'supplier_order_enabled': offer['supplier_order']['enabled'] if offer else False,
            'availability': 'in_stock' if stocks else 'backorder' if offer and offer['supplier_order']['enabled']
                else 'unavailable' if offer else 'variant_not_sold'})
    return {'schema_version': VERSION, 'task_id': task['task_id'],
        'world_id': world['world_id'], 'sku_id': task['sku_id'], 'currency': 'SEK',
        'minimum_advertised_price_minor': minimum, 'winners': winners,
        'comparison_path': '/models/' + quote(task['product_id'], safe='')}


def bind_public(runtime, task):
    site = next(s for s in runtime.site_registry if s['site_id'] == task['comparison_site_id'])
    return {'schema_version': 'connected-world-manual-v1', 'task_id': task['task_id'],
        'user_message': task['user_message'], 'memories': deepcopy(task['memories']),
        'environment_context': {'currency': 'SEK', 'scenario_date': runtime.world['quote_as_of'],
            'shopping_scope': f'Price comparison on {site["name"]}; cheapest listing verified at its retailer'},
        'start_url': site['origin'] + '/'}


def episode_task(runtime, public, profile, *, files, attachments=None):
    """Fresh comparison-home episode; full surrounding world remains available.

    Native expected outcomes are retained privately. Natural-answer and actual
    retailer-visit grading are manual until this distinct task gets an extractor;
    do not reuse the cheapest-available grader for the different stock semantics.
    """
    from intent_browser.connected_world_task import ConnectedWorldTask

    class VerificationTask(ConnectedWorldTask):
        supports_observation_pipeline = 'native_full_only'

        def make_env(self, video=None):
            env = super().make_env(video)
            if runtime.origin_map is not None:
                from browsergym.core.task import OpenEndedTask

                class LocalWorldStart(OpenEndedTask):
                    def setup(self, page):
                        runtime.attach_browser(page.context)
                        return super().setup(page)

                env.unwrapped.task_entrypoint = LocalWorldStart
            return env

        def prepare(self, trace):
            result = super().prepare(trace)
            if runtime.origin_map is not None:
                from intent_browser.trace import write_json
                name = 'site-origins.private.json'
                write_json(trace.directory/'manual-review-private'/name, runtime.origin_map.descriptor)
                result['private_attachment_sha256'][name] = sha256(
                    (trace.directory/'manual-review-private'/name).read_bytes()).hexdigest()
                result['logical_origins_private_artifact'] = 'manual-review-private/' + name
            return result

    return VerificationTask(public, origins=runtime.navigation_origins, files=files,
                            attachments=attachments, profile_name=profile.name)
