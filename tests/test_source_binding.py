"""The single-version rule for code hashes recorded inside generated tasks."""
from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from experiments import source_binding as sb


def write(root, name, text):
    path = Path(root)/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return sha256(text.encode()).hexdigest()


class CheckTests(unittest.TestCase):
    def test_current_mode_records_code_drift_but_keeps_data_exact(self):
        with TemporaryDirectory() as root, patch.dict(os.environ, {sb.ENV: 'current'}):
            code = write(root, 'environments/a.py', 'new')
            data = write(root, '.local/world.json', '{}')
            current, drift = sb.check(root, {'environments/a.py': 'old', '.local/world.json': data},
                                      error='changed: ')
            self.assertEqual(current, {'environments/a.py': code, '.local/world.json': data})
            self.assertEqual(drift, [{'path': 'environments/a.py', 'declared_sha256': 'old',
                                      'current_sha256': code}])
            with self.assertRaisesRegex(ValueError, 'changed: .local/world.json'):
                sb.check(root, {'.local/world.json': 'other'}, error='changed: ')
            with self.assertRaisesRegex(ValueError, 'changed: product_world/data/x.json'):
                sb.check(root, {'product_world/data/x.json': 'missing'}, error='changed: ')

    def test_pinned_mode_raises_the_loaders_historical_error(self):
        with TemporaryDirectory() as root, patch.dict(os.environ, {sb.ENV: 'pinned'}):
            write(root, 'environments/a.py', 'new')
            with self.assertRaisesRegex(ValueError, 'Generation source changed: environments/a.py'):
                sb.check(root, {'environments/a.py': 'old'}, error='Generation source changed: ')

    def test_declared_paths_cannot_escape_the_checkout(self):
        with TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                sb.check(root, {'../outside.py': 'x'}, error='changed: ')

    def test_unknown_mode_is_rejected(self):
        with patch.dict(os.environ, {sb.ENV: 'frozen'}), self.assertRaises(ValueError):
            sb.mode()


class RebuildTests(unittest.TestCase):
    saved = {'task_id': 'a', 'schema_version': 'v1', 'user_message': 'Find it',
             'quote_binding': {'source_sha256': {'experiments/m.py': '1', '.local/plan.json': 'p'},
                               'quote_plan_sha256': 'q'}}

    def test_upgrade_may_change_derived_ids_add_fields_and_code_hashes(self):
        rebuilt = {**self.saved, 'task_id': 'b', 'schema_version': 'v2', 'qualifier': {},
                   'quote_binding': {'source_sha256': {'experiments/m.py': '2', '.local/plan.json': 'p'},
                                     'quote_plan_sha256': 'q'}}
        self.assertEqual(sb.substantive_changes(self.saved, rebuilt), [])
        with patch.dict(os.environ, {sb.ENV: 'current'}):
            self.assertTrue(sb.compatible(self.saved, rebuilt))
        with patch.dict(os.environ, {sb.ENV: 'pinned'}):
            self.assertFalse(sb.compatible(self.saved, rebuilt))

    def test_changed_removed_or_data_values_are_substantive(self):
        changed = {**self.saved, 'user_message': 'Find something else'}
        removed = {k: v for k, v in self.saved.items() if k != 'user_message'}
        data = {**self.saved, 'quote_binding': {**self.saved['quote_binding'],
                'source_sha256': {'experiments/m.py': '1', '.local/plan.json': 'other'}}}
        plan = {**self.saved, 'quote_binding': {**self.saved['quote_binding'], 'quote_plan_sha256': 'x'}}
        self.assertEqual(sb.substantive_changes(self.saved, changed), ['/user_message'])
        self.assertEqual(sb.substantive_changes(self.saved, removed), ['/user_message'])
        self.assertEqual(sb.substantive_changes(self.saved, data),
                         ['/quote_binding/source_sha256/.local/plan.json'])
        self.assertEqual(sb.substantive_changes(self.saved, plan), ['/quote_binding/quote_plan_sha256'])
        with patch.dict(os.environ, {sb.ENV: 'current'}):
            self.assertFalse(sb.compatible(self.saved, changed))

    def test_accepted_rebuilds_and_asset_drift_are_recorded(self):
        manifest = {}
        with patch.dict(os.environ, {sb.ENV: 'current'}):
            self.assertTrue(sb.accept_rebuilt(manifest, 'task', self.saved, {**self.saved, 'task_id': 'b'}))
            self.assertTrue(sb.accept_asset_drift(manifest, {'shop.js': '1', 'x.js': '2'},
                                                  {'shop.js': '3', 'x.js': '2'}))
        self.assertEqual(manifest['source_binding']['rebuilt_upgrades'], ['task'])
        self.assertEqual(manifest['source_binding']['served_asset_drift'], [['shop.js']])

    def test_same_code_compares_only_data_entries(self):
        recorded = {'environments/a.py': '1', '.local/d.json': 'd'}
        with patch.dict(os.environ, {sb.ENV: 'current'}):
            self.assertTrue(sb.same_code(recorded, {'environments/a.py': '2', '.local/d.json': 'd'}))
            self.assertFalse(sb.same_code(recorded, {'environments/a.py': '1', '.local/d.json': 'x'}))
        with patch.dict(os.environ, {sb.ENV: 'pinned'}):
            self.assertFalse(sb.same_code(recorded, {'environments/a.py': '2', '.local/d.json': 'd'}))


if __name__ == '__main__':
    unittest.main()
