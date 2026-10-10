"""One status row per registry concept, with explicit acceptance provenance."""
from pathlib import Path
import hashlib
import json

from environments.product_world.concept_registry import ConceptRegistry

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ROOT / 'environments/product_world/data/product_width'
ACCEPTED = ROOT / '.local/product-width/accepted.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def coverage():
    accepted = json.loads(ACCEPTED.read_text()) if ACCEPTED.exists() else {}
    rows = []
    for concept in ConceptRegistry.load().concepts():
        cid = concept['id']
        pilot = ROOT / 'environments/product_world/data/product_packages' / (cid + '.json')
        authored = PACKAGES / (cid + '.json')
        entry = accepted.get(cid)
        status = 'pending'
        path = None
        if pilot.exists():
            status, path = 'validated_pilot', pilot
        if authored.exists():
            status, path = 'authored_pending_acceptance', authored
        if entry:
            # A later edit invalidates acceptance instead of relabeling old checks.
            paths = entry['source_hashes']
            if not all((ROOT / p).is_file() and sha(ROOT / p) == h for p, h in paths.items()):
                status = 'acceptance_source_mismatch'
            else:
                status = 'domain_accepted'
        rows.append({'concept_id': cid, 'label': concept['label'], 'family_id': concept['family_id'],
                     'status': status, 'package_path': str(path.relative_to(ROOT)) if path else None,
                     'package_sha256': sha(path) if path else None,
                     'acceptance': entry, 'consumer_status': 'isolated_authoring_only',
                     'production_task_registration': False})
    return {'version': 'product-width-coverage-v1',
            'concept_count': len(rows), 'family_count': len({r['family_id'] for r in rows}),
            'concepts': rows}
