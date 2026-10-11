#!/usr/bin/env python3
"""Apply the exact reviewed parser correction before starting vLLM."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_training.vllm_qwen_schema_patch import apply_installed

if __name__ == "__main__":
    print(json.dumps(apply_installed(), sort_keys=True))
