"""Public fictional publisher identity; an independent deterministic sampling stream."""
from hashlib import sha256

NAMES = ('Omdömeskollen', 'Kundkompassen', 'Handelsröster', 'Butikspanelen',
         'Köparblick', 'Omdömesplatsen', 'Kundspegeln', 'Handelsintryck')
VERSION = 'merchant-review-identity-v1'


def sample_identity(seed=0, site_id='merchant-reviews'):
    if type(seed) is not int or not isinstance(site_id, str) or not site_id.strip():
        raise ValueError('Expected integer seed and nonempty stable site ID')
    index = int.from_bytes(sha256(f'{VERSION}:{seed}:{site_id}'.encode()).digest(), 'big') % len(NAMES)
    return {'version': VERSION, 'site_id': site_id, 'name': NAMES[index]}


def validate_name(name):
    if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name):
        raise ValueError('Expected a short printable site name')
    return name
