"""Current composable browser policy, separate from frozen historical profiles."""
import os
from dataclasses import replace
from pathlib import Path
from .ax_explorer import AXConfig
from .harness import native_tools_profile, with_subagents, with_data_tools
from .vision import VisionConfig

STANDARD_PROFILE = 'core-tools-v12-ax-reuse'

def tokenizer_path():
    path=Path(os.environ.get('HARNESS_AX_TOKENIZER',
        Path(__file__).resolve().parents[1]/'training/.cache/qwen38-tokenizer/tokenizer.json'))
    if not path.is_file():
        raise ValueError('Current harness requires the local Qwen tokenizer; set HARNESS_AX_TOKENIZER. No automatic download is performed.')
    return str(path)

def standard_profile(*, navigation_origins=(), helpers=True, tokenizer=None, data_tools=True, data_config=None):
    """Fixed tools, compact incremental AX, requested images, preserved reasoning.

    Explicit old profile factories remain available for reproducible ablations.
    Own-browser helpers require a trusted environment factory; no-browser helpers
    can reason over parent-supplied public evidence without extra site setup.
    """
    profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        timeout_feedback=True,navigation_origins=tuple(navigation_origins),
        ax_config=AXConfig(tokenizer or tokenizer_path(),incremental=True,overview_tokens=1000,
                           revisit_reuse=True,agent_overview=True),
        vision_config=VisionConfig('retain'),reasoning_replay='preserve',batch_size=8)
    profile=replace(profile,navigation_from_reset=not bool(navigation_origins))
    profile=with_subagents(profile) if helpers else profile
    if data_tools:
        from .data_tools import DataConfig
        profile=with_data_tools(profile, data_config or DataConfig(image=os.environ.get('HARNESS_PYTHON_IMAGE', 'intent-browser-python:stdlib-v1'), script_workspace=True))
    return with_adaptive_ax(profile)


def with_adaptive_ax(profile):
    """Apply current AX presentation; explicit historical factories stay unchanged."""
    return replace(profile,name=STANDARD_PROFILE,
        ax_config=replace(profile.ax_config,overview_tokens=1000,revisit_reuse=True,agent_overview=True),
        tools=replace(profile.tools,agent_overview=True),instructions=profile.instructions +
        ' Automatic AX updates default to at most 1000 tokens. Browser actions accept ax_overview_tokens '
        'for the next automatic update only: prefer 0 when you will search a known target next, or 512 '
        'for orientation; larger budgets are for demonstrated need, not routine navigation. '
        'Use targeted ax_search and ax_read instead of repeatedly printing whole pages. '
        'Revisited identical pages may reference previously delivered node descriptions using reused_from. '
        'Only the accompanying current ref/bid is valid; never act on a historical bid. '
        'Reuse covers public AX equality, not hidden application state or proof an action succeeded.')
