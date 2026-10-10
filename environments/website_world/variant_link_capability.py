"""Pinned recipient-navigation evidence. Source review alone cannot release tasks.

The envelope shape is approved for source preparation; adoption stays held until
Product supplies the actual accepted browser-capability document.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re

from . import variant_link_task as native

VERSION = 'website-variant-link-navigation-evidence-v1'
ACCEPTANCE = 'website-variant-link-navigation-acceptance-v1'


def read_pin(record):
    if type(record) is not dict or set(record) != {'path', 'sha256'}:
        raise ValueError('Require a literal path/SHA256 pin')
    path = Path(record['path']).resolve()
    if sha256(path.read_bytes()).hexdigest() != record['sha256']:
        raise ValueError('Pinned capability evidence changed: ' + str(path))
    return path, json.loads(path.read_bytes())


def check_manifest(record):
    path, manifest = read_pin(record)
    if manifest.get('schema') != VERSION or type(manifest.get('files')) is not dict:
        raise ValueError('Require the complete scripted recipient evidence manifest')
    root = path.parent
    for name, expected in manifest['files'].items():
        if (type(name) is not str or not name or '\\' in name
                or PurePosixPath(name).is_absolute() or any(part in ('', '.', '..') for part in name.split('/'))
                or type(expected) is not str or re.fullmatch(r'[0-9a-f]{64}', expected) is None):
            raise ValueError('Capability members require canonical packet-relative names and SHA256 pins')
        member = root / name
        components = [root.joinpath(*PurePosixPath(name).parts[:i]) for i in range(1, len(PurePosixPath(name).parts)+1)]
        if any(part.is_symlink() for part in components) or not member.resolve().is_relative_to(root):
            raise ValueError('Capability evidence member escaped its immutable packet')
        if sha256(member.read_bytes()).hexdigest() != expected:
            raise ValueError('Capability evidence file changed: ' + name)
    required = {'catalog.private.json', 'bindings.private.json', 'navigation-capability.private.json',
                'world.private.json', 'recipient-cases.private.json', 'served-assets.private.json'}
    if not required <= set(manifest['files']):
        raise ValueError('Recipient packet lacks catalog/world/menu/state/asset bindings')
    return path, manifest


def validate(approval, *, world, catalog, bindings, asset_sha256):
    """Verify actual acceptance/file closure and actual native/renderer inputs."""
    _, accepted = read_pin(approval)
    if (accepted.get('schema') != ACCEPTANCE or accepted.get('owner') != 'Product'
            or accepted.get('status') != 'accepted'):
        raise ValueError('Source review is insufficient: actual Product browser acceptance required')
    path, manifest = check_manifest(accepted['evidence_manifest'])
    read = lambda name: json.loads((path.parent / name).read_bytes())
    capability = read('navigation-capability.private.json')
    if native.digest(capability) != accepted.get('capability_sha256'):
        raise ValueError('Accepted capability digest changed')
    if (read('world.private.json') != world or read('catalog.private.json') != catalog
            or read('bindings.private.json') != bindings
            or read('served-assets.private.json') != asset_sha256
            or capability.get('catalog_sha256') != native.digest(catalog)
            or capability.get('asset_sha256') != asset_sha256
            or capability.get('retailer_id') != catalog['siteId']
            or capability.get('protocol') != native.NAVIGATION_PROTOCOL
            or capability.get('owner') != 'Product' or capability.get('status') != 'accepted'
            or capability.get('recipient_states') != 'fresh_and_all_carried_tuples'):
        raise ValueError('Actual world/catalog/URL/asset capability binding differs')
    pages = [p for p in catalog['products'] if p['id'] == capability.get('page_id')]
    if len(pages) != 1:
        raise ValueError('Require the accepted actual merchant page')
    page = pages[0]
    cases = read('recipient-cases.private.json')
    variants = {native.digest(v['selection']) for v in page['variants']}
    if len(variants) != len(page['variants']):
        raise ValueError('Ambiguous carried tuple cannot certify recipient selection')
    expected = {(native.digest(target['selection']), previous) for target in page['variants']
                for previous in {'fresh', *variants}}
    actual = set()
    for row in cases:
        target, previous, resolved = row['target_selection'], row['previous_selection'], row['actual_selection']
        identity = (native.digest(target), 'fresh' if previous is None else native.digest(previous))
        if identity in actual or identity not in expected or row.get('status') != 'pass':
            raise ValueError('Duplicate, unrelated or failed recipient witness')
        encoded = {k: v for k, v in target.items() if catalog['configuration']['url'] == 'all'
                   or catalog['configuration']['url'] == 'colour' and k == 'colour'}
        if native.digest(resolved) not in variants or any(resolved.get(k) != v for k, v in encoded.items()):
            raise ValueError('Recipient witness loses explicit URL fields or introduces a tuple')
        for name in ('before_state_file', 'after_state_file', 'dom_file', 'ax_file'):
            if row.get(name) not in manifest['files']:
                raise ValueError('Recipient witness lacks actual state/DOM/AX evidence')
        actual.add(identity)
    if actual != expected:
        raise ValueError('Fresh/all-carried recipient coverage is incomplete')
    return deepcopy(capability)
