#!/usr/bin/env python3
"""Opt-in compatibility patch for the pinned TRL source. No CUDA imports."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

from browser_training.attention_compat import is_patched, patched_source


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, help="Default: trainer in this interpreter's installed TRL")
    p.add_argument("--apply", action="store_true", help="Write the verified one-line change")
    args = p.parse_args()
    path = args.source
    if path is None:
        path = Path(importlib.metadata.distribution("trl").locate_file(
            "trl/experimental/async_grpo/async_grpo_trainer.py"))
    source = path.read_text()
    updated = patched_source(source)
    if args.apply and source != updated:
        path.write_text(updated)
    print(json.dumps({"path": str(path), "applied": args.apply,
        "patched": is_patched(path.read_text()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, indent=2))


if __name__ == "__main__":
    main()
