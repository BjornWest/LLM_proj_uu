#!/usr/bin/env python3
"""Inspect an exported safetensors adapter on CPU, without loading the base."""
import argparse
import json
from pathlib import Path
import struct


def check(path):
    path = Path(path)
    if path.is_dir():
        path /= "adapter_model.safetensors"
    with path.open("rb") as stream:
        size = struct.unpack("<Q", stream.read(8))[0]
        if size > 32 * 1024 * 1024:
            raise ValueError("Unreasonable safetensors header")
        header = json.loads(stream.read(size))
    tensors = {n: spec for n, spec in header.items() if n != "__metadata__"}
    if not tensors:
        raise AssertionError("Empty adapter")
    for name, spec in tensors.items():
        if not any(tag in name for tag in ("lora_A", "lora_B")) or spec["dtype"] != "BF16":
            raise AssertionError(f"Unexpected adapter tensor: {name}: {spec['dtype']}")
    return {"file": str(path), "adapter_tensors": len(tensors), "dtype": "BF16"}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("adapter")
    print(json.dumps(check(p.parse_args().adapter), indent=2))
