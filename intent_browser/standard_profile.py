"""Current composable browser policy, separate from frozen historical profiles."""
import os
from dataclasses import replace
from pathlib import Path
from .ax_explorer import AXConfig
from .harness import native_tools_profile, with_subagents
from .vision import VisionConfig

STANDARD_PROFILE = 'core-tools-v10-agents'

def tokenizer_path():
    path=Path(os.environ.get('HARNESS_AX_TOKENIZER',
        Path(__file__).resolve().parents[1]/'training/.cache/qwen38-tokenizer/tokenizer.json'))
    if not path.is_file():
        raise ValueError('Current harness requires the local Qwen tokenizer; set HARNESS_AX_TOKENIZER. No automatic download is performed.')
    return str(path)

def standard_profile(*, navigation_origins=(), helpers=True, tokenizer=None):
    """Fixed tools, compact incremental AX, requested images, preserved reasoning.

    Explicit old profile factories remain available for reproducible ablations.
    Own-browser helpers require a trusted environment factory; no-browser helpers
    can reason over parent-supplied public evidence without extra site setup.
    """
    profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        timeout_feedback=True,navigation_origins=tuple(navigation_origins),
        ax_config=AXConfig(tokenizer or tokenizer_path(),incremental=True),
        vision_config=VisionConfig('retain'),reasoning_replay='preserve',batch_size=8)
    profile=replace(profile,navigation_from_reset=not bool(navigation_origins))
    return with_subagents(profile) if helpers else profile
