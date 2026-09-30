#!/usr/bin/env python3
"""Startup observation only; spawned engine processes import the probe too."""
from browser_training.vllm_capacity import instrument

instrument()

if __name__ == "__main__":
    from vllm.entrypoints.cli.main import main
    main()
