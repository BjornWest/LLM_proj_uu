"""Common disclosure exclusions; arithmetic inputs are not shopper facts."""

VERSION = 'public-field-rules-v1'
INTERNAL_PRICING_KEYS = frozenset({
    'model_price_factor', 'configuration_price_factor', 'connection_price_factor',
})


def is_public_field(path):
    """Apply to both common product facts and SKU/projection fields.

    Real reference prices and payable prices remain public through their native
    contracts. This is not a generic blacklist of words involving price.
    """
    return path.rsplit('.', 1)[-1] not in INTERNAL_PRICING_KEYS
