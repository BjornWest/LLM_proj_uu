"""Reusable pinned RL/vLLM Modal image; defining it performs no cloud work.

Call build_image only while assembling a local Modal app. Add application source
mounts afterwards: Modal disallows later build commands after deferred mounts.
This factory defines no app, volumes, model downloads or episode tooling.
"""
from pathlib import Path


def build_image(training_root=None):
    """Define the CUDA13/vLLM0.28 image from this tree's exact RL lockfile."""
    import modal

    if not modal.is_local():
        raise RuntimeError("Assemble the Modal image locally, not in a container")
    root = Path(training_root) if training_root is not None else Path(__file__).resolve().parents[1]
    for name in ("pyproject.toml", "uv.lock"):
        if not (root / "envs/rl" / name).is_file():
            raise FileNotFoundError(root / "envs/rl" / name)
    return (modal.Image.debian_slim(python_version="3.12")
        .apt_install("git", "libgomp1", "build-essential")
        .uv_pip_install("uv==0.10.8")
        .add_local_file(root / "envs/rl/pyproject.toml", "/opt/rl/pyproject.toml", copy=True)
        .add_local_file(root / "envs/rl/uv.lock", "/opt/rl/uv.lock", copy=True)
        .run_commands("uv python install 3.12.12",
            "cd /opt/rl && uv sync --locked --python 3.12.12 --default-index https://pypi.org/simple",
            "uv pip check --python /opt/rl/.venv/bin/python")
        .env({"HF_HOME": "/model-cache", "HF_HUB_CACHE": "/model-cache/hub",
              "HF_XET_HIGH_PERFORMANCE": "1", "PYTHONPATH": "/opt/training:/opt/training/scripts",
              "PYTHONUNBUFFERED": "1", "VLLM_NO_USAGE_STATS": "1",
              "VLLM_WORKER_MULTIPROC_METHOD": "spawn", "WANDB_MODE": "disabled",
              "TOKENIZERS_PARALLELISM": "false", "PYTHONDONTWRITEBYTECODE": "1"}))
