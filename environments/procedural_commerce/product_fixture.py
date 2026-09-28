"""Small authored footwear fixture; not the future product/world sampler."""
from .generator import generate_world
from .product_controls import VERSION


def footwear_fixture():
    world = generate_world(7)
    rows = [('shoe-42-black', 'eu42', 42, 'black', 89000, 3),
            ('shoe-42-blue', 'eu42', 42, 'blue', 94000, 0),
            ('shoe-475-black', 'eu475', 47.5, 'black', 99000, 2)]
    # EU 47.5 / blue deliberately has no SKU; EU 42 / blue exists but is sold out.
    group = {'schema_version': VERSION, 'group_id': 'solvik-stride', 'family': 'footwear',
             'name': 'Solvik Stride trainers', 'axes': [
                 {'field': 'size_eu', 'label': 'EU shoe size', 'value_type': 'number', 'unit': 'EU',
                  'options': [{'id': 'eu42', 'label': 'EU 42', 'value': 42},
                              {'id': 'eu475', 'label': 'EU 47.5', 'value': 47.5}]},
                 {'field': 'colour', 'label': 'Colour', 'value_type': 'string', 'unit': None,
                  'options': [{'id': 'black', 'label': 'Black', 'value': 'black'},
                              {'id': 'blue', 'label': 'Blue', 'value': 'blue'}]}], 'variants': []}
    for sku, option, size, colour, price, stock in rows:
        world['products'].append({'product_id': sku, 'name': f'Solvik Stride trainers — EU {size:g} — {colour}',
                                  'category': 'footwear', 'reference_price_minor': 100000,
                                  'attributes': {'size_eu': size, 'colour': colour}, 'traits': []})
        group['variants'].append({'product_id': sku, 'selection': {'size_eu': option, 'colour': colour}})
        for retailer in world['retailers']:
            site = retailer['retailer_id']
            world['offers'].append({'offer_id': f'offer-{sku}-{site}', 'product_id': sku, 'retailer_id': site,
                                    'price_minor': price, 'stock_quantity': stock, 'dispatch_days': 1,
                                    'extra_name': None, 'extra_price_minor': None, 'extra_preselected': False})
            world['aggregator_claims'].append({'claim_id': f'claim-{sku}-{site}', 'product_id': sku, 'retailer_id': site,
                                              'offer_id': f'offer-{sku}-{site}', 'advertised_price_minor': price,
                                              'destination': 'SE', 'shipping_scope': 'excluded'})
    world['private_provenance']['authored_fixture'] = 'footwear-controls-v1'
    return world, [group]
