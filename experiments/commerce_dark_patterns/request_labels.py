"""Describe a requested variant without copying its factual/private payload."""

# Closed authored fixtures predate accepted-package variation annotations.
_FIXTURE_CHOICES = ('colour', 'width', 'size_eu', 'size_label', 'pack_count',
                    'configuration')


def _label(package, sku):
    product = package['public']
    fields = package.get('variant_fields', package.get('axes'))
    keys = fields if fields is not None else _FIXTURE_CHOICES
    detail = ', '.join(f'{key.replace("_", " ")}: {sku[key]}' for key in keys
                      if type(sku.get(key)) in (str, int, float, bool))
    name = product.get('name', 'item')
    return f'{name} ({detail})' if detail else name


def variant_name(package, sku_id, *, retailer=None, packages=None):
    """Use the product's declared retail choices, never all SKU record fields."""
    product = package['public']
    sku = next(s for s in product['skus'] if s['sku_id'] == sku_id)
    selected = _label(package, sku)
    if any(row['sku_id'] != sku_id and _label(package, row) == selected
           for row in product['skus']):
        raise ValueError('Product variants lack distinct public retail choices; supply an authored request')
    if (retailer is None) != (packages is None):
        raise ValueError('Retailer label scope requires its complete product packages')
    if retailer is not None:
        carried = {o['sku_id'] for o in retailer['offers']}
        for other in packages:
            if other['public']['product_id'] == product['product_id']:
                continue
            if any(row['sku_id'] in carried and _label(other, row) == selected
                   for row in other['public']['skus']):
                raise ValueError('Retailer products lack distinct public retail choices; supply an authored request')
    return selected
