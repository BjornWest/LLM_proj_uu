"""CPU tests against exact installed upstream source, always patching temp copies."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from browser_training import vllm_qwen_schema_patch as m


class ParserPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(os.environ["VLLM_PARSER_SOURCE"]).read_bytes()
        if m.digest(cls.source) != m.ORIGINAL_SHA256:
            raise ValueError("Tests require original pinned vLLM 0.28.0 utils.py")
        cls.fixed = m.patched_bytes(cls.source)

    def test_original_numeric_union_bug(self):
        coerce = m.coercer_from_source(self.source)
        self.assertIs(type(coerce("42", ["string", "array"])), int)
        self.assertIs(type(coerce("true", ["string", "array"])), bool)
        self.assertIsNone(coerce("null", ["string", "array"]))

    def test_fixed_numeric_strings(self):
        coerce = m.coercer_from_source(self.fixed)
        for value in ("42", "0", "-42", "3.5", "1e6", "true", "false", "null"):
            for schema in (["string", "array"], ["array", "string"], ["string", "object"]):
                with self.subTest(value=value, schema=schema):
                    actual = coerce(value, schema)
                    self.assertIs(type(actual), str)
                    self.assertEqual(actual, value)

    def test_preserves_allowed_containers(self):
        coerce = m.coercer_from_source(self.fixed)
        self.assertEqual(coerce('["42","product"]', ["string", "array"]), ["42", "product"])
        self.assertEqual(coerce('{"size":"42"}', ["string", "object"]), {"size": "42"})

    def test_container_wrong_union_member(self):
        coerce = m.coercer_from_source(self.fixed)
        self.assertEqual(coerce('{"size":"42"}', ["string", "array"]), '{"size":"42"}')
        self.assertEqual(coerce('["42"]', ["string", "object"]), '["42"]')

    def test_preserves_explicit_scalar_types(self):
        coerce = m.coercer_from_source(self.fixed)
        self.assertIs(type(coerce("42", "integer")), int)
        self.assertIs(coerce("true", "boolean"), True)
        self.assertIsNone(coerce("null", ["string", "null"]))
        self.assertEqual(coerce("3.5", "number"), 3.5)

    def test_preserves_nonfinite_guard(self):
        coerce = m.coercer_from_source(self.fixed)
        for raw in ('[1e999]', '{"x":1e999}', "1e999", "not json"):
            self.assertEqual(coerce(raw, ["string", "array", "object"]), raw)

    def test_expected_module_hash_and_small_delta(self):
        self.assertEqual(m.digest(self.fixed), m.PATCHED_SHA256)
        self.assertEqual(len(self.fixed.splitlines()) - len(self.source.splitlines()), 4)

    def test_unknown_source_refused(self):
        with self.assertRaises(ValueError):
            m.patched_bytes(self.source + b"\n")
        with self.assertRaises(ValueError):
            m.coercer_from_source(b"malicious or unexpected source")

    def test_selftest_requires_patch_and_passes(self):
        with self.assertRaises(ValueError):
            m.self_test(self.source)
        self.assertEqual(m.self_test(self.fixed)["cases"], 12)

    def test_apply_temp_backup_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "utils.py"
            p.write_bytes(self.source)
            p.chmod(0o640)
            first = m.apply_to(p)
            self.assertEqual(first["status"], "applied")
            self.assertEqual(p.stat().st_mode & 0o777, 0o640)
            self.assertEqual(p.with_name(p.name + ".pre-" + m.PATCH_ID).read_bytes(), self.source)
            second = m.apply_to(p)
            self.assertEqual(second["status"], "already_applied")
            self.assertEqual(first["vllm_source_patch_sha256"], second["vllm_source_patch_sha256"])
            self.assertEqual(p.read_bytes(), self.fixed)

    def test_unknown_installed_file_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "utils.py"
            p.write_bytes(b"unknown")
            with self.assertRaises(ValueError):
                m.apply_to(p)
            self.assertEqual(p.read_bytes(), b"unknown")
            self.assertEqual(len(list(p.parent.iterdir())), 1)

    def test_bad_backup_refused_before_source_write(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "utils.py"
            p.write_bytes(self.source)
            p.with_name(p.name + ".pre-" + m.PATCH_ID).write_bytes(b"unknown")
            with self.assertRaises(ValueError):
                m.apply_to(p)
            self.assertEqual(p.read_bytes(), self.source)

    def test_wrong_version_refused_before_module_lookup(self):
        with patch.object(m.importlib.metadata, "version", return_value="0.29.0"):
            with patch.object(m.importlib.util, "find_spec", side_effect=AssertionError("lookup should not run")):
                with self.assertRaises(ValueError):
                    m.apply_installed()

    def test_atomic_replace_failure_leaves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "utils.py"
            p.write_bytes(self.source)
            with patch.object(m.os, "replace", side_effect=OSError("simulated")):
                with self.assertRaises(OSError):
                    m.atomic_write(p, self.fixed, 0o600)
            self.assertEqual(p.read_bytes(), self.source)
            self.assertEqual(len(list(p.parent.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
