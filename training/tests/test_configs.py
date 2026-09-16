import json
from pathlib import Path
import runpy
import subprocess
import sys
import tomllib
import yaml
import pytest
from browser_training.launch import parser, vllm_command

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("preset", ["baseline", "lora", "lora-mtp"])
def test_launch_presets(preset):
    command = vllm_command(parser().parse_args(["--preset", preset]))
    assert ("--enable-lora" in command) == (preset != "baseline")
    assert ("--speculative-config" in command) == (preset == "lora-mtp")
    assert command[command.index("--kv-cache-dtype") + 1] == "auto"
    assert command[command.index("--logprobs-mode") + 1] == "processed_logprobs"


def test_adapter_version_capacity():
    with pytest.raises(ValueError, match="max_loras"):
        vllm_command(parser().parse_args(["--max-loras", "2"]))


def test_sft_invariants():
    for path in (ROOT / "configs").glob("sft*.yml"):
        cfg = yaml.safe_load(path.read_text())
        assert cfg["base_model"].startswith(("Qwen/", "greghavens/"))
        assert cfg["adapter"] in ("lora", "qlora") and cfg["bf16"] is True
        assert cfg["peft_autocast_adapter_dtype"] is False
        assert cfg["lora_dropout"] == 0
        assert cfg["datasets"][0]["roles_to_train"] == ["assistant"]
        assert "lm_head" not in cfg["lora_target_modules"]
        assert not cfg.get("fp8", False)
        assert len(cfg["revision_of_model"]) == 40
        if "Qwen3.8" in cfg["base_model"]:
            assert cfg["chat_template"] == "tokenizer_default"
            assert cfg["chat_template_kwargs"] == {"enable_thinking": False, "preserve_thinking": True}


def test_rl_packing_and_real_run_gate():
    cfg = runpy.run_path(ROOT / "configs/rl_qwen38_27b_fp8_lora.py")["CONFIG"]
    assert cfg["token_budget"] == 0 and cfg["per_device_train_batch_size"] == 1
    result = subprocess.run([sys.executable, "scripts/run_async_grpo.py", "--config", "configs/rl_qwen38_27b_fp8_lora.py"],
                            cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 2 and "BLOCKED" in result.stderr


def test_all_lockfiles_are_present():
    for folder in [ROOT, *sorted((ROOT / "envs").iterdir())]:
        lock = tomllib.loads((folder / "uv.lock").read_text())
        assert lock["package"]


def test_safetensors_header_dtype(tmp_path):
    import struct
    check = runpy.run_path(ROOT / "scripts/check_adapter_dtypes.py")["check"]
    file = tmp_path / "adapter_model.safetensors"
    for dtype in ("BF16", "F32"):
        header = json.dumps({"model.lora_A.weight": {"dtype": dtype, "shape": [1], "data_offsets": [0, 2]}}).encode()
        file.write_bytes(struct.pack("<Q", len(header)) + header + b"\x00\x00")
        if dtype == "BF16":
            assert check(file)["dtype"] == "BF16"
        else:
            with pytest.raises(AssertionError):
                check(file)
