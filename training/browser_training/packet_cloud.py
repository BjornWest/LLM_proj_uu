"""Small Packet Dynamic client; credentials stay on the controlling workstation.

Endpoints/body follow packet-gpu-cli@1.1.1. No speculative storage API writes.
The advertised product price is an estimate, not an enforceable provider bill cap.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import tarfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API = "https://dash.packet.ai/api/v1"
UPLOAD_FILES = (
    "envs/rl/pyproject.toml", "envs/rl/uv.lock",
    "browser_training/__init__.py", "browser_training/launch.py",
    "browser_training/vllm_speed.py", "scripts/packet_vllm_worker.sh",
    "scripts/benchmark_vllm_native.py", "scripts/download_models.py",
    "scripts/verify_gpu.py",
)


class Client:
    def __init__(self, key: str):
        if not key:
            raise ValueError("PACKET_API_KEY is missing")
        self.key = key

    def request(self, endpoint: str, method: str = "GET", body=None):
        req = Request(API + endpoint, method=method,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={"Authorization": "Bearer " + self.key,
                               "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=20) as response:
                raw = response.read()
                result = json.loads(raw) if raw else {}
        except HTTPError as exc:
            # Provider error bodies may contain private account/connection fields.
            raise RuntimeError(f"Packet {method} {endpoint}: HTTP {exc.code}") from None
        if result.get("success") is False or result.get("error"):
            raise RuntimeError(f"Packet {method} {endpoint}: API rejected request")
        return result.get("data", result)


def choose_offer(options, max_hourly=0.70, pool_id=None):
    """Never match the $0 monthly SKU or treat pool.price_per_hour=0 as free."""
    products = [p for p in options.get("products", [])
                if "rtx pro 6000 blackwell" in p["name"].lower()
                and "dynamic" in p["name"].lower()
                and "monthly" not in p["name"].lower()
                and 0 < p.get("pricePerHourCents", 0) <= max_hourly * 100
                and p.get("vramGb", 0) >= 96]
    for product in sorted(products, key=lambda p: p["pricePerHourCents"]):
        for pool in options.get("pools", []):
            if (int(pool["id"]) in product["poolIds"]
                    and pool.get("available_gpus", 0) >= 1
                    and (pool_id is None or int(pool["id"]) == pool_id)):
                return {"product_id": product["id"], "product": product["name"],
                        "pool_id": int(pool["id"]), "region": pool.get("region"),
                        "hourly_usd": product["pricePerHourCents"] / 100,
                        "description": product.get("description"), "vgpus": 1}
    raise RuntimeError("No available hourly RTX PRO 6000 96GB offer within price limit")


def parse_connection(command: str):
    """Parse data, never execute the provider's SSH command as shell code."""
    tokens = shlex.split(command)
    if not tokens or tokens.pop(0) != "ssh":
        raise ValueError("Expected an SSH connection command")
    port, target = 22, None
    while tokens:
        token = tokens.pop(0)
        if token == "-p" and tokens:
            port = int(tokens.pop(0))
        elif re.fullmatch(r"[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+", token) and target is None:
            target = token
        else:
            raise ValueError("Unsupported SSH connection syntax")
    if not target or not 1 <= port <= 65535:
        raise ValueError("Invalid SSH connection")
    return target, port


def bundle(root: Path, destination: Path):
    hashes = {}
    with tarfile.open(destination, "w:gz") as archive:
        for relative in UPLOAD_FILES:
            path = root / relative
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Missing regular deployment file: {relative}")
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            archive.add(path, arcname=relative, recursive=False)
    return hashes
