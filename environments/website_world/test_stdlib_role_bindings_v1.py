"""Prepared canonical-role regressions; no browser/runtime/native producers."""
import copy
from hashlib import sha256
from pathlib import Path
import unittest

from environments.website_world.stdlib_role_bindings_v1 import CopyRoles, RoleError


class CopyRoleTests(unittest.TestCase):
    def control(self):
        return CopyRoles(source_sha256=sha256(Path(copy.__file__).read_bytes()).hexdigest())

    def test_canonical_table_and_defaults_admitted(self):
        control = self.control()
        result = control.check()
        self.assertEqual(result['module'], 'copy')
        self.assertEqual(set(result['tables']), {'_copy_dispatch', '_deepcopy_dispatch'})

    def test_source_valid_donor_rejected_before_baseline(self):
        original = copy._deepcopy_dispatch[dict]
        try:
            copy._deepcopy_dispatch[dict] = copy._deepcopy_atomic
            with self.assertRaisesRegex(RoleError, 'wrong copy dispatcher key'): self.control()
        finally: copy._deepcopy_dispatch[dict] = original

    def test_source_valid_default_donor_rejected_before_baseline(self):
        original = copy._deepcopy_list.__defaults__
        try:
            copy._deepcopy_list.__defaults__ = (copy._deepcopy_atomic,)
            with self.assertRaisesRegex(RoleError, 'declared copy default'): self.control()
        finally: copy._deepcopy_list.__defaults__ = original

    def test_keyword_default_donor_rejected_before_baseline(self):
        original = copy._reconstruct.__kwdefaults__
        try:
            copy._reconstruct.__kwdefaults__ = {'deepcopy': copy._deepcopy_atomic}
            with self.assertRaisesRegex(RoleError, 'declared copy default'): self.control()
        finally: copy._reconstruct.__kwdefaults__ = original

    def test_table_replacement_after_admission_rejected(self):
        control = self.control(); original = copy._deepcopy_dispatch
        try:
            copy._deepcopy_dispatch = dict(original)
            with self.assertRaisesRegex(RoleError, 'identity changed'): control.check()
        finally: copy._deepcopy_dispatch = original

    def test_callback_replacement_after_admission_rejected(self):
        control = self.control(); original = copy._deepcopy_dispatch[list]
        try:
            copy._deepcopy_dispatch[list] = copy._deepcopy_atomic
            with self.assertRaises(RoleError): control.check()
        finally: copy._deepcopy_dispatch[list] = original

    def test_default_sentinel_changed_from_source_rejected(self):
        original = copy.deepcopy.__defaults__
        try:
            copy.deepcopy.__defaults__ = (None, ['changed'])
            with self.assertRaisesRegex(RoleError, 'literal default'): self.control()
        finally: copy.deepcopy.__defaults__ = original

    def test_unchanged_copy_behavior_and_detachment(self):
        control = self.control(); value = {'nested': [{'items': [1, 2, 3]}]}
        cloned = copy.deepcopy(value)
        self.assertEqual(value, cloned)
        self.assertIsNot(value['nested'], cloned['nested'])
        self.assertIsNot(value['nested'][0]['items'], cloned['nested'][0]['items'])
        control.check()
