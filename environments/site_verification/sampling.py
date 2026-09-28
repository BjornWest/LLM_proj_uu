"""Independent per-site sampling; never conditions on task feasibility."""
import hashlib
import math

VERSION = 'comparator-verification-v1'
STYLES = ('interstitial', 'embedded')
TRIGGERS = ('entry', 'discovery')


def sample(site_ids, *, seed=0, probability=.25):
    if type(seed) is not int or type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError('Invalid verification sampling settings')
    ids = list(site_ids)
    if len(ids) != len(set(ids)) or any(not isinstance(s, str) or not s for s in ids):
        raise ValueError('Unique comparator IDs required')
    rows = []
    for sid in sorted(ids):
        def draw(field):
            return int.from_bytes(hashlib.sha256(f'{VERSION}|{seed}|{sid}|{field}'.encode()).digest()[:8], 'big')
        rows.append({'site_id': sid, 'enabled': draw('presence') / 2**64 < probability,
                     'style': STYLES[draw('style') % len(STYLES)],
                     'trigger': TRIGGERS[draw('trigger') % len(TRIGGERS)],
                     'challenge_ttl_seconds': 600, 'clearance_ttl_seconds': 1800})
    return {'schema_version': VERSION, 'implementation': 'offline-simulation', 'seed': seed,
            'probability': probability, 'sites': rows}


def validate(config, comparator_ids):
    if set(config) != {'schema_version', 'implementation', 'seed', 'probability', 'sites'} or config['schema_version'] != VERSION or config['implementation'] != 'offline-simulation':
        raise ValueError('Unsupported verification config')
    sample([], seed=config['seed'], probability=config['probability'])
    ids = []
    for row in config['sites']:
        if set(row) != {'site_id', 'enabled', 'style', 'trigger', 'challenge_ttl_seconds', 'clearance_ttl_seconds'}:
            raise ValueError('Unexpected gate fields')
        if type(row['enabled']) is not bool or row['style'] not in STYLES or row['trigger'] not in TRIGGERS:
            raise ValueError('Invalid gate design')
        if any(type(row[k]) is not int or not 1 <= row[k] <= 86400 for k in ('challenge_ttl_seconds', 'clearance_ttl_seconds')):
            raise ValueError('Invalid gate lifetime')
        ids.append(row['site_id'])
    if len(ids) != len(set(ids)) or set(ids) != set(comparator_ids):
        raise ValueError('Gate config must cover comparator sites only, exactly once')
