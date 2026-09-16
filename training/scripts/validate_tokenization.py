#!/usr/bin/env python3
"""Real Qwen tokenizer + upstream Axolotl label construction, CPU/no model weights.

Runs hash-checked Axolotl classes with logging/type-only package imports replaced;
does not install/import Axolotl's GPU stack or claim full trainer validation.
"""
import abc
import argparse
import ast
import hashlib
import json
import logging
from pathlib import Path
import typing
import urllib.request

from browser_training.dataset import convert_trajectory

REVISION = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
ASSETS = {
    "config.json": "191e0af232104ed8b65258cf3fb2b842e288008baca7633c11b82a1ac7203aab",
    "tokenizer.json": "0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3",
    "tokenizer_config.json": "b11349aafa7cdc6a320767cf7ceb29ed82f7eda5d65e8e0819e76f0ce947bf27",
    "chat_template.jinja": "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041",
}
SOURCES = {
    "prompt_tokenizers.py": "5b2e4f7d0bced3bf6593dac8b6b6e47578a8ce0ec5239ad827ac63ee69cc95ee",
    "prompters.py": "adad98f7a9fcb8f51a8abc1ad098163ae6fac708746361c2cf31c1c7bb829d7b",
    "prompt_strategies/jinja_template_analyzer.py": "d6919ec977ba44910640aa37833ca79c0a28fb9b17e761a272b9d38caa16fabd",
    "prompt_strategies/chat_template.py": "6a14e9e92898974f02d40b7ad199ae94b3010609c0378adc0956a00a9d9057d5",
    "utils/dict.py": "acfa976f04fd3cd8c8672e19c5ebe055ff07bf766171eb0f9e3f4748b60f118c",
    "utils/chat_templates/templates/qwen3_5.jinja": "070c6460faeaed2b96a4842c6a6c1ad7d0c108924a0b117dc13c35ff6992f8ae",
}


def fetch(root, files, base):
    for name, sha in files.items():
        path = root / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(urllib.request.urlopen(base + name, timeout=30).read())
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError(f"Source hash mismatch: {path}")


def axolotl_strategy(root):
    from transformers import PreTrainedTokenizer, BatchEncoding
    namespace = {**vars(typing), "abc": abc, "Prompter": object,
        "PreTrainedTokenizer": PreTrainedTokenizer, "BatchEncoding": BatchEncoding, "IGNORE_TOKEN_ID": -100,
        "IGNORE_INDEX": -100, "get_logger": logging.getLogger,
        "LOG": logging.getLogger(__name__), "DatasetConfig": object}
    for name, selected in (("prompters.py", {"Prompter"}),
                           ("prompt_tokenizers.py", {"PromptTokenizingStrategy"}),
                           ("utils/dict.py", {"remove_none_values"})):
        tree = ast.parse((root / name).read_text())
        tree.body = [n for n in tree.body if getattr(n, "name", None) in selected]
        exec(compile(tree, name, "exec"), namespace)
    for name in ("prompt_strategies/jinja_template_analyzer.py", "prompt_strategies/chat_template.py"):
        tree = ast.parse((root / name).read_text())
        tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and n.module.startswith("axolotl"))]
        exec(compile(tree, name, "exec"), namespace)
    return namespace


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=Path("research/tokenization-validation.json"))
    p.add_argument("--installed-axolotl", action="store_true",
        help="Import the installed Axolotl classes; check SFT labels only (no RL/OpenEnv imports)")
    args = p.parse_args()
    cache = Path(".cache/qwen38-tokenizer")
    ax_cache = Path(".cache/axolotl-tokenization-source")
    fetch(cache, ASSETS, f"https://huggingface.co/Qwen/Qwen3.8-27B/resolve/{REVISION}/")
    fetch(ax_cache, SOURCES, "https://raw.githubusercontent.com/axolotl-ai-cloud/axolotl/v0.19.0/src/axolotl/")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(cache, local_files_only=True)
    if args.installed_axolotl:
        from axolotl.prompt_strategies.chat_template import ChatTemplatePrompter, ChatTemplateStrategy
        upstream = {"ChatTemplatePrompter": ChatTemplatePrompter, "ChatTemplateStrategy": ChatTemplateStrategy}
    else:
        upstream = axolotl_strategy(ax_cache)
    trajectory = {"task": "TASK_SENTINEL", "success": True, "steps": [
        {"observation": "OBSERVATION_ONE_SENTINEL", "reasoning": "REASONING_ONE_SENTINEL", "action": "click('1')"},
        {"observation": "OBSERVATION_TWO_SENTINEL", "reasoning": "REASONING_TWO_SENTINEL", "action": "fill('2', 'yes')"}]}
    results = []
    for target in ("action", "reasoning-action"):
        for layout in ("trajectory", "state-action"):
            rows = convert_trajectory(trajectory, target=target, layout=layout)
            prompter = upstream["ChatTemplatePrompter"](tokenizer=tokenizer,
                chat_template=tokenizer.chat_template, max_length=8192,
                chat_template_kwargs={"enable_thinking": target == "reasoning-action", "preserve_thinking": True})
            strategy = upstream["ChatTemplateStrategy"](prompter, tokenizer, train_on_inputs=False,
                sequence_len=8192, roles_to_train=["assistant"], train_on_eos="turn")
            for index, row in enumerate(rows):
                tokenized = strategy.tokenize_prompt(row)
                ids, labels = tokenized["input_ids"], tokenized["labels"]
                assert len(ids) == len(labels)
                trained = tokenizer.decode([label for label in labels if label != -100])
                rendered = tokenizer.decode(ids)
                expected_steps = trajectory["steps"] if layout == "trajectory" else [trajectory["steps"][index]]
                for step in expected_steps:
                    assert step["action"] in trained
                    assert (step["reasoning"] in trained) == (target == "reasoning-action")
                    assert step["observation"] in rendered and step["observation"] not in trained
                assert "TASK_SENTINEL" not in trained
                assert trained.count(tokenizer.eos_token) == len(expected_steps)
                assert rendered.count("<think>") == len(expected_steps), "Duplicate think blocks"
                results.append({"target": target, "layout": layout, "row": index, "tokens": len(ids),
                    "supervised_tokens": sum(x != -100 for x in labels), "supervised_text": trained,
                    "observations_masked": True, "all_actions_trained": True})
    # Record why the earlier content-wrapped representation/template override was unsafe.
    messages = convert_trajectory(trajectory, target="action")[0]["messages"]
    for message, step in zip([m for m in messages if m["role"] == "assistant"], trajectory["steps"]):
        message["content"] = f"<think>\n{step['reasoning']}\n</think>\n{step['action']}"
    old_render = tokenizer.apply_chat_template(messages, tokenize=False)
    old_ax = tokenizer.apply_chat_template(messages, tokenize=False,
        chat_template=(ax_cache / "utils/chat_templates/templates/qwen3_5.jinja").read_text())
    assert old_render.count("<think>") == 4
    assert "REASONING_ONE_SENTINEL" not in old_ax
    if args.installed_axolotl:
        report = {"model": "Qwen/Qwen3.8-27B", "revision": REVISION, "tokenizer_assets": ASSETS,
            "scope": "real tokenizer and installed Axolotl labeling classes; no import substitutions or trainer",
            "cases": results, "gpu_used": False}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        return
    from upstream_chat_probe import load_chat_utils
    from browser_training.harness_bridge import normalize_tool_arguments
    from openenv.core.llm_client import LLMResponse, ToolCall
    chat = load_chat_utils()
    assert tokenizer.chat_template == chat.qwen3_8_chat_template
    assert chat.is_chat_template_prefix_preserving(tokenizer)
    chat.add_response_schema(tokenizer)
    parser_cases = []
    for thinking in (False, True):
        prompt = [{"role": "user", "content": "Click the button."}]
        prefix = tokenizer.apply_chat_template(prompt, add_generation_prompt=True,
            enable_thinking=thinking, return_dict=False)
        text = ("PARSER_REASONING_SENTINEL\n</think>\n\n" if thinking else "")
        text += "<tool_call>\n<function=browser_action>\n<parameter=action>\nclick('1')\n</parameter>\n</function>\n</tool_call><|im_end|>"
        parsed = chat.parse_response(tokenizer, tokenizer.encode(text, add_special_tokens=False), prefix=prefix)
        assert parsed["tool_calls"][0]["function"] == {"name": "browser_action", "arguments": {"action": "click('1')"}}
        assert ("PARSER_REASONING_SENTINEL" in parsed.get("reasoning_content", "")) == thinking
        parser_cases.append({"thinking": thinking, "parsed": parsed})
    messages = [{"role": "user", "content": "Click"},
        LLMResponse("", [ToolCall("call-1", "click", {"bid": "1"})]).to_message_dict(),
        {"role": "tool", "content": "Done"}]
    try:
        tokenizer.apply_chat_template(messages, tokenize=False)
    except TypeError:
        string_arguments_rejected = True
    else:
        raise AssertionError("Re-audit: Qwen now accepts string tool arguments")
    tokenizer.apply_chat_template(normalize_tool_arguments(messages), tokenize=True)
    report = {"model": "Qwen/Qwen3.8-27B", "revision": REVISION, "tokenizer_assets": ASSETS,
        "axolotl_sources": SOURCES, "scope": "real tokenizer; unchanged upstream Axolotl prompter/label classes; no trainer",
        "cases": results, "legacy_inline_reasoning_duplicates_think_blocks": True,
        "axolotl_qwen3_5_override_drops_earlier_reasoning": True,
        "trl_parser_cases": parser_cases, "trl_chat_source_sha256": chat.source_hashes,
        "openenv_string_tool_arguments_rejected": string_arguments_rejected,
        "normalized_tool_arguments_render": True, "gpu_used": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
