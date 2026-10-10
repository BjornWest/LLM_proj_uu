"""Public, paginated site discovery; no product/price/stock/task ranking."""
from copy import deepcopy
import re

PUBLIC_KINDS = {'retailer': 'retailer', 'aggregator': 'comparison', 'product_reviews': 'review'}


def words(value):
    return ' '.join(re.findall(r'[^\W_]+', value.casefold()))


class DiscoverSites:
    def __init__(self, records):
        self._sites = []
        seen = set()
        for record in records:
            sid, kind = record['site_id'], record['kind']
            if sid in seen or kind not in PUBLIC_KINDS:
                raise ValueError('Invalid or duplicate public site record')
            seen.add(sid)
            site = {'site_id': sid, 'kind': PUBLIC_KINDS[kind], 'name': record['name'],
                    'url': record['origin'] + '/', 'description': record['description']}
            if any(type(value) is not str or not value.strip() for value in site.values()):
                raise ValueError('Public site fields must be nonempty text')
            haystack = words(' '.join([site['name'], site['description'],
                                      *record.get('families', []), *record.get('types', [])]))
            self._sites.append((deepcopy(site), haystack))
        self._sites.sort(key=lambda row: (row[0]['kind'], row[0]['name'].casefold(), row[0]['site_id']))

    def search(self, query='', *, kind=None, limit=5, offset=0):
        if type(query) is not str or len(query) > 300:
            raise ValueError('Supply at most 300 query characters')
        if kind is not None and (type(kind) is not str or kind not in PUBLIC_KINDS.values()):
            raise ValueError('Unknown public site kind')
        if type(limit) is not int or not 1 <= limit <= 20 or type(offset) is not int or offset < 0:
            raise ValueError('Supply limit 1..20 and nonnegative offset')
        terms = words(query).split()
        rows = [site for site, haystack in self._sites if
                (kind is None or site['kind'] == kind) and all(term in haystack for term in terms)]
        return {'offset': offset, 'limit': limit, 'total': len(rows),
                'next_offset': offset + limit if offset + limit < len(rows) else None,
                'sites': deepcopy(rows[offset:offset + limit])}


def scope_description(types, *, kind='retailer'):
    types = sorted(set(types), key=str.casefold)
    if not types:
        return {'retailer': 'No products are currently listed.',
                'aggregator': 'No models are currently tracked.',
                'product_reviews': 'No products are currently covered.'}[kind]
    scope = ', '.join(types)
    return {'retailer': f'Sells {scope}.',
            'aggregator': f'Compares listed item prices for {scope}; coverage is partial.',
            'product_reviews': f'Customer reviews and ratings for {scope}; coverage is partial.'}[kind]
