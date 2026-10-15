"""Synthetic pinned-packet controls; never certify a browser or real fixture."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from .test_variant_link_task import fixture
from . import variant_link_task as native, variant_link_capability as cap
from .variant_link_publication import compile_packet
from . import variant_link_publication as publication


def packet(root):
    world, spec, inputs = fixture('colour')
    catalog, bindings, capability = (inputs[k] for k in ('catalog', 'bindings', 'navigation_capability'))
    assets = capability['asset_sha256']
    files = {}
    def save(name, value):
        path = root / name
        path.write_text(json.dumps(value))
        files[name] = sha256(path.read_bytes()).hexdigest()
    rows = []
    variants = catalog['products'][0]['variants']
    for target in variants:
        for previous in [None, *[v['selection'] for v in variants]]:
            i = len(rows)
            row = {'target_selection': target['selection'], 'previous_selection': previous,
                   'actual_selection': target['selection'], 'status': 'pass'}
            for key in ('before_state_file', 'after_state_file', 'dom_file', 'ax_file'):
                name = f'{i}-{key}.json'
                save(name, {'synthetic_control': True})
                row[key] = name
            rows.append(row)
    for name, value in {'catalog.private.json': catalog, 'bindings.private.json': bindings,
                        'navigation-capability.private.json': capability, 'world.private.json': world,
                        'recipient-cases.private.json': rows, 'served-assets.private.json': assets}.items(): save(name, value)
    manifest_path = root / 'manifest.json'
    manifest_path.write_text(json.dumps({'schema': cap.VERSION, 'files': files}))
    pin = lambda path: {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}
    accepted = {'schema': cap.ACCEPTANCE, 'owner': 'Product', 'status': 'accepted',
                'capability_sha256': native.digest(capability), 'evidence_manifest': pin(manifest_path)}
    approval_path = root / 'synthetic-approval.json'
    approval_path.write_text(json.dumps(accepted))
    return world, spec, inputs, assets, pin(approval_path), rows


class CapabilityControls(unittest.TestCase):
    def test_archive_keeps_prior_manifest_member_and_named_current_envelope(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); source=root/'packet';source.mkdir()
            _, _, _, _, approval, _ = packet(source)
            accepted=json.loads(Path(approval['path']).read_bytes())
            original=Path(accepted['evidence_manifest']['path'])
            first=original.read_bytes();manifest=json.loads(first)
            manifest['files']['manifest.json']=sha256(first).hexdigest()
            current=source/'manifest-v2.json';current.write_text(json.dumps(manifest))
            pin={'path':str(current),'sha256':sha256(current.read_bytes()).hexdigest()}
            path, checked=cap.check_manifest(pin)
            archive=root/'archive'
            publication.archive_evidence(path,checked,archive,expected_manifest_sha256=pin['sha256'])
            self.assertEqual((archive/'manifest.json').read_bytes(),first)
            self.assertEqual((archive/'manifest-v2.json').read_bytes(),current.read_bytes())
            cap.check_manifest({'path':str(archive/'manifest-v2.json'),'sha256':pin['sha256']})

    def test_archive_rejects_internally_consistent_unapproved_envelope_drift(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);source=root/'packet';source.mkdir()
            _, _, _, _, approval, _=packet(source)
            accepted=json.loads(Path(approval['path']).read_bytes())
            pin=accepted['evidence_manifest'];path,checked=cap.check_manifest(pin)
            world=source/'world.private.json';world.write_text('{"world_id":"unapproved"}')
            changed=deepcopy(checked);changed['files']['world.private.json']=sha256(world.read_bytes()).hexdigest()
            path.write_text(json.dumps(changed))
            # The changed packet remains self-consistent, but its envelope was
            # never approved by Product. Retain the originally approved hash.
            cap.check_manifest({'path':str(path),'sha256':sha256(path.read_bytes()).hexdigest()})
            with self.assertRaisesRegex(ValueError,'Pinned capability evidence changed'):
                publication.archive_evidence(path,checked,root/'archive',
                    expected_manifest_sha256=pin['sha256'])

    def test_complete_synthetic_packet_can_compile_but_inputs_stay_unchanged(self):
        with TemporaryDirectory() as folder:
            w, spec, inputs, assets, approval, _ = packet(Path(folder))
            before = deepcopy((w, spec, inputs, assets, approval))
            result = compile_packet(world=w, spec=spec, catalog=inputs['catalog'],
                bindings=inputs['bindings'], asset_sha256=assets, acceptance=approval)
            self.assertEqual(result['task']['selection'], {'size_eu': '38', 'colour': 'brown'})
            self.assertEqual((w, spec, inputs, assets, approval), before)

    def test_source_only_status_and_mutated_receipt_reject(self):
        for status in ('source_accepted_browser_capability_pending', 'accepted_but_hash_changed'):
            with TemporaryDirectory() as folder:
                w, _, inputs, assets, approval, _ = packet(Path(folder))
                p = Path(approval['path']);value = json.loads(p.read_bytes())
                if status.startswith('source'): value['status'] = status
                else: value['capability_sha256'] = '0' * 64
                p.write_text(json.dumps(value));approval['sha256'] = sha256(p.read_bytes()).hexdigest()
                with self.assertRaises(ValueError): cap.validate(approval, world=w,
                    catalog=inputs['catalog'], bindings=inputs['bindings'], asset_sha256=assets)

    def test_actual_asset_world_or_binding_mismatch_reject(self):
        for key in ('assets', 'world', 'bindings'):
            with TemporaryDirectory() as folder, patch.dict(os.environ, {'TASK_SOURCE_BINDING': 'pinned'}):
                w, _, inputs, assets, approval, _ = packet(Path(folder))
                if key == 'assets': assets = {'shop.js': 'b' * 64}
                elif key == 'world': w['world_id'] = 'different'
                else: inputs['bindings']['retailer_offers']['shop/brown38']['url'] += '&extra=true'
                with self.assertRaises(ValueError): cap.validate(approval, world=w,
                    catalog=inputs['catalog'], bindings=inputs['bindings'], asset_sha256=assets)

    def test_single_version_serves_current_assets_but_keeps_world_and_bindings_exact(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {'TASK_SOURCE_BINDING': 'current'}):
            w, _, inputs, assets, approval, _ = packet(Path(folder))
            cap.validate(approval, world=w, catalog=inputs['catalog'], bindings=inputs['bindings'],
                         asset_sha256={'shop.js': 'b' * 64})  # Current page code may differ.
            w['world_id'] = 'different'
            with self.assertRaisesRegex(ValueError, 'world'): cap.validate(approval, world=w,
                catalog=inputs['catalog'], bindings=inputs['bindings'], asset_sha256=assets)

    def test_missing_or_altered_raw_witness_file_reject(self):
        with TemporaryDirectory() as folder:
            root = Path(folder); w, _, inputs, assets, approval, rows = packet(root)
            (root / rows[0]['dom_file']).write_text('Changed raw witness')
            with self.assertRaises(ValueError): cap.validate(approval, world=w,
                catalog=inputs['catalog'], bindings=inputs['bindings'], asset_sha256=assets)

    def test_packet_aliases_absolute_names_and_symlinked_parents_reject(self):
        for mode in ('parent_alias', 'dot_alias', 'absolute', 'symlink_parent'):
            with self.subTest(mode=mode), TemporaryDirectory() as folder:
                root = Path(folder); w, _, inputs, assets, approval, _ = packet(root)
                approved_path = Path(approval['path'])
                accepted = json.loads(approved_path.read_bytes())
                manifest_path = Path(accepted['evidence_manifest']['path'])
                manifest = json.loads(manifest_path.read_bytes())
                original = 'world.private.json'
                if mode == 'parent_alias': name = 'unused/../' + original
                elif mode == 'dot_alias': name = './' + original
                elif mode == 'absolute': name = str(root / original)
                else:
                    (root/'linked').symlink_to(root, target_is_directory=True)
                    name = 'linked/' + original
                manifest['files'][name] = manifest['files'][original]
                manifest_path.write_text(json.dumps(manifest))
                accepted['evidence_manifest']['sha256'] = sha256(manifest_path.read_bytes()).hexdigest()
                approved_path.write_text(json.dumps(accepted))
                approval['sha256'] = sha256(approved_path.read_bytes()).hexdigest()
                with self.assertRaises(ValueError): cap.validate(approval, world=w,
                    catalog=inputs['catalog'], bindings=inputs['bindings'], asset_sha256=assets)


if __name__ == '__main__': unittest.main()
