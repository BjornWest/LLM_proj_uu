import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time


def capture(output, config):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout.strip()
    files = [p for folder in ("browser_training", "configs", "scripts") for p in (root / folder).rglob("*")
             if p.is_file() and "__pycache__" not in p.parts]
    report = {"timestamp": time.time(), "git_commit": commit, "git_dirty": bool(dirty),
              "python": sys.version, "config": config,
              "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
              "source_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    # Remote images install the environment separately (e.g. /opt/rl/.venv)
    # and mount only selected project sources. Discover actual files instead
    # of assuming a complete repository exists next to this module.
    environment_root = Path(sys.prefix).parent
    locks = {folder / name for folder in (root, environment_root)
             for name in ("pyproject.toml", "uv.lock")}
    for name in ("pyproject.toml", "uv.lock"):
        locks.update((root / "envs").glob("*/" + name))
    report["environment_file_sha256"] = {
        str(p.relative_to(root)) if p.is_relative_to(root) else str(p):
            hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(locks) if p.is_file()}
    # The flash-attn version does not identify compiled GPU targets. Record the
    # extension artifact as well, without importing or executing its CUDA code.
    report["kernel_artifacts"] = {}
    extension = importlib.util.find_spec("flash_attn_2_cuda")
    if extension and extension.origin:
        binary = Path(extension.origin)
        with binary.open("rb") as stream:
            report["kernel_artifacts"][binary.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    report["dataset_sha256"] = {}
    for dataset in config.get("datasets", []):
        path = Path(dataset["path"])
        if path.is_file():
            with path.open("rb") as stream:
                report["dataset_sha256"][str(path)] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = output / f"manifest-{time.time_ns()}.json"
    manifest.write_text(json.dumps(report, indent=2, default=str))
    return manifest
