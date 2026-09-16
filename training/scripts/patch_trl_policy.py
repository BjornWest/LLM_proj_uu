#!/usr/bin/env python3
"""Apply the audited policy-reservation patch; no heavyweight imports or downloads."""
import argparse
import difflib
import hashlib
import importlib.metadata
import json
from pathlib import Path

from browser_training.policy_compat import HASHES, patched_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--diff", action="store_true")
    args = parser.parse_args()
    folder = args.source_dir or Path(importlib.metadata.distribution("trl").locate_file(
        "trl/experimental/async_grpo"))
    changes = []
    for name in HASHES:
        path = folder / name
        source = path.read_text()
        updated = patched_source(name, source)
        compile(updated, str(path), "exec")
        changes.append((path, source, updated))
    # Validate all files before changing any. Unknown/partial installations fail closed.
    for path, source, updated in changes:
        if args.diff:
            print("".join(difflib.unified_diff(source.splitlines(True), updated.splitlines(True),
                                            fromfile=str(path), tofile=str(path))), end="")
        if args.apply and source != updated:
            temporary = path.with_suffix(".policy-tmp")
            temporary.write_text(updated)
            temporary.replace(path)
    print(json.dumps({"applied": args.apply, "files": {p.name: {
        "path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "patched": p.read_text() == updated} for p, _, updated in changes}}, indent=2))


if __name__ == "__main__":
    main()
