#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_training.dataset import convert_file

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert normalized trajectory JSONL to assistant-masked SFT conversations")
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--target", choices=["action", "reasoning-action"], default="action")
    parser.add_argument("--layout", choices=["trajectory", "state-action"], default="trajectory")
    parser.add_argument("--include-failures", action="store_true")
    args = parser.parse_args()
    print(json.dumps(convert_file(args.source, args.destination, target=args.target, layout=args.layout,
                                  successful_only=not args.include_failures), indent=2))
