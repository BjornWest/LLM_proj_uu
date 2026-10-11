"""Version-guarded vLLM 0.28.0 union-coercion correction.

Apply before starting vLLM, never to an already running parser. This keeps
numeric-looking strings valid when a tool permits a string or an array. It
does not replace the harness's full JSON Schema validation.
"""

from __future__ import annotations

import ast
from hashlib import sha256
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

PATCH_ID = "vllm-0.28.0-container-union-types-v1"
VERSION = "0.28.0"
ORIGINAL_SHA256 = "7d1dae2075f0ae425648b91f8c94358ea874db4972d5263f44ef8b268187fbe4"
PATCHED_SHA256 = "93f9b8ec0097f5b4d416e9106442900727a3aa7ca48930469fca88a1fd33c064"


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def patched_bytes(original: bytes) -> bytes:
    if digest(original) != ORIGINAL_SHA256:
        raise ValueError("Unrecognized original vLLM parser source")
    source = original.decode("utf-8")
    matches = [n for n in ast.parse(source).body
               if isinstance(n, ast.FunctionDef) and n.name == "coerce_to_schema_type"]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous coercer")
    old = ast.get_source_segment(source, matches[0])
    needle = "            if _is_json_finite(parsed):\n"
    if old is None or old.count(needle) != 1 or source.count(old) != 1:
        raise ValueError("Unexpected coercer layout")
    new = old.replace(needle,
        '            if candidate_type == "array" and not isinstance(parsed, list):\n'
        '                continue\n'
        '            if candidate_type == "object" and not isinstance(parsed, dict):\n'
        '                continue\n' + needle)
    result = source.replace(old, new).encode("utf-8")
    ast.parse(result.decode("utf-8"))
    if digest(result) != PATCHED_SHA256:
        raise ValueError("Unexpected patched source digest")
    return result


def coercer_from_source(source: bytes):
    """Execute only the pinned coercer's stdlib dependencies for CPU checks."""
    if digest(source) not in (ORIGINAL_SHA256, PATCHED_SHA256):
        raise ValueError("Unrecognized regression-test source")
    wanted = {"_is_json_finite", "coerce_to_schema_type", "_TYPE_ALIASES"}
    selected = []
    for node in ast.parse(source.decode("utf-8")).body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            selected.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in wanted:
            selected.append(node)
    if len(selected) != 3:
        raise ValueError("Unexpected coercer dependencies")
    namespace = {"Any": Any, "json": json, "math": math}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<pinned-vllm-coercer>", "exec"), namespace)
    return namespace["coerce_to_schema_type"]


def self_test(source: bytes) -> dict:
    if digest(source) != PATCHED_SHA256:
        raise ValueError("Self-test requires actual patched source")
    coerce = coercer_from_source(source)
    cases = [
        ("42", ["string", "array"], "42"),
        ("true", ["string", "array"], "true"),
        ("null", ["string", "array"], "null"),
        ('{"a":1}', ["string", "array"], '{"a":1}'),
        ('["42","price"]', ["string", "array"], ["42", "price"]),
        ('{"a":1}', ["string", "object"], {"a": 1}),
        ("42", ["string", "object"], "42"),
        ("[1,2]", ["string", "object"], "[1,2]"),
        ("[1e999]", ["string", "array"], "[1e999]"),
        ("42", "integer", 42),
        ("true", "boolean", True),
        ("null", ["string", "null"], None),
    ]
    for value, types, expected in cases:
        actual = coerce(value, types)
        if type(actual) is not type(expected) or actual != expected:
            raise ValueError(f"Coercion regression: {value!r}, {types!r}")
    return {"passed": True, "cases": len(cases), "source_sha256": digest(source),
            "scope": "actual installed source CPU coercion; not model generation"}


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def apply_to(path: Path) -> dict:
    original = path.read_bytes()
    before = digest(original)
    if before not in (ORIGINAL_SHA256, PATCHED_SHA256):
        raise ValueError("Refusing to modify unknown installed parser")
    status = "already_applied"
    if before == ORIGINAL_SHA256:
        patched = patched_bytes(original)
        backup = path.with_name(path.name + ".pre-" + PATCH_ID)
        if backup.exists() and digest(backup.read_bytes()) != ORIGINAL_SHA256:
            raise ValueError("Unexpected existing parser backup")
        if not backup.exists():
            atomic_write(backup, original, path.stat().st_mode & 0o777)
        # No local/GPU model is loaded by this operation.
        atomic_write(path, patched, path.stat().st_mode & 0o777)
        status = "applied"
    installed = path.read_bytes()
    checks = self_test(installed)
    manifest = [{"id": PATCH_ID, "version": VERSION,
                 "module": "vllm.tool_parsers.utils", "original_sha256": ORIGINAL_SHA256,
                 "patched_sha256": PATCHED_SHA256}]
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {"status": status, "path": str(path.resolve()), "manifest": manifest,
            "vllm_source_patch_sha256": digest(manifest_bytes), "cpu_regression": checks}


def apply_installed() -> dict:
    if importlib.metadata.version("vllm") != VERSION:
        raise ValueError("Parser correction is only qualified for vLLM " + VERSION)
    spec = importlib.util.find_spec("vllm")
    if spec is None or spec.origin is None:
        raise ValueError("Cannot locate installed vLLM")
    return apply_to(Path(spec.origin).parent / "tool_parsers" / "utils.py")
