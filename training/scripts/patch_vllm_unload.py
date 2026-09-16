#!/usr/bin/env python3
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
from browser_training.vllm_compat import patched_source


def main():
    p=argparse.ArgumentParser(); p.add_argument('--apply',action='store_true'); args=p.parse_args()
    path=Path(importlib.metadata.distribution('vllm').locate_file('vllm/entrypoints/openai/models/serving.py'))
    updated=patched_source(path.read_text())
    if args.apply: path.write_text(updated)
    print(json.dumps({'path':str(path),'applied':args.apply,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))


if __name__=='__main__': main()
