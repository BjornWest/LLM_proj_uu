"""Exact saved-review input checks; no manufacture, browser or truth changes."""
from hashlib import sha256
import json
from pathlib import Path
from .review_rating_scopes import require_public_rating_scope

REQUIRED = frozenset({'world.private.json', 'task.private.json', 'reference.private.json',
    'presentation.private.json', 'compositions.private.json', 'surrounding.private.json',
    'basket-plan.private.json', 'checkout-domain.private.json',
    'native-episode-control.json', 'review-binding.private.json', 'proposed-user-request.txt'})


def sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read_saved(saved, *, expected_manifest_sha256):
    """Retain all declared bytes, rejecting changed files or escaping names."""
    saved = Path(saved).resolve()
    manifest_path = saved/'draft-manifest.json'
    manifest_payload = manifest_path.read_bytes()
    if sha256(manifest_payload).hexdigest() != expected_manifest_sha256:
        raise ValueError('Saved review manifest changed')
    manifest = json.loads(manifest_payload)
    files, sources = manifest.get('files'), manifest.get('source_hashes')
    if (type(files) is not dict or not REQUIRED <= files.keys()
            or type(sources) is not dict or not sources):
        raise ValueError('Saved review draft lacks complete input/source pins')
    payloads = {}
    for name, expected in files.items():
        if (type(name) is not str or Path(name).name != name
                or name in ('.', '..', 'draft-manifest.json')):
            raise ValueError('Saved review input must be a unique basename')
        path = saved/name
        if not path.resolve().is_relative_to(saved):
            raise ValueError('Saved review input escapes its directory')
        payload = path.read_bytes()
        if sha256(payload).hexdigest() != expected:
            raise ValueError('Saved review input changed: '+name)
        payloads[name] = payload
    payloads['draft-manifest.json'] = manifest_payload
    request = payloads['proposed-user-request.txt'].decode('utf-8').strip()
    if not request:
        raise ValueError('Saved review public request is empty')
    return manifest, payloads, request


def target_setup(world, task, surrounding, binding, *, review_site_id, start_query=None):
    """Select an existing publication of the native subject, without resampling."""
    product_id = task['subject']['product_id']
    covered = [s['site_id'] for s in surrounding['sites']
               if s['kind'] == 'product_reviews' and product_id in s['product_ids']]
    if (binding != {'status': 'bound', 'publication_ids': covered, 'world_repaired': False}
            or len(covered) != len(set(covered))):
        raise ValueError('Saved native review coverage binding changed')
    sites = [s for s in surrounding['sites'] if s['site_id'] == review_site_id]
    if len(sites) != 1 or review_site_id not in covered:
        raise ValueError('Select one existing review site covering the native subject')
    require_public_rating_scope(task, sites[0])
    if (task['world_id'] != world['world_id'] or surrounding['source_world_id'] != world['world_id']):
        raise ValueError('Saved review world identity changed')
    query = {} if start_query is None else start_query
    if (type(query) is not dict or set(query) - {'sort', 'part'}
            or ('sort' in query and query['sort'] not in ('identity', 'lowest', 'highest'))
            or ('part' in query and (query['part'] != 'readers'
                                    or sites[0].get('layout') != 'editorial-magazine'))):
        raise ValueError('Unsupported saved review start query')
    setup = {'schema': 'website-saved-review-setup-v1',
        'start': {'kind': 'review_product', 'site_id': review_site_id, 'product_id': product_id},
        'site_name': sites[0]['name'], 'world_draws': 0,
        'surrounding_sites': 'all_retained', 'effects': 'unknown'}
    if query:
        setup['start']['query'] = dict(query)
    return setup
