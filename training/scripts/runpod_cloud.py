#!/usr/bin/env python3
"""Bounded Runpod benchmark using the same frozen worker and cleanup as Packet.

REST v2 create fields follow runpod-python/api/ctl_commands.py. REST v1
connection and deletion fields follow Runpod's published OpenAPI schema.
No API credential is uploaded. Only a per-attempt SSH public key is in pod env.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_training.packet_cloud import bundle
from browser_training.vllm_speed import residency_plan
from packet_cloud import interrupt, run_instance, save

GPU = "NVIDIA RTX PRO 6000 Blackwell Server Edition"
IMAGE = "runpod/base:1.4.0-cuda1300-ubuntu2404"


class Client:
    def __init__(self, key):
        if not key:
            raise ValueError("RUNPOD_API_KEY is missing")
        self.key = key
        self.create_body = None
        self.output = None
        self.offer = None

    def api(self, base, path, method="GET", body=None):
        req = Request(base + path, method=method,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={"Authorization": "Bearer " + self.key,
                               "User-Agent": "runpod-python", "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=20) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            # Retain the public diagnostic, never request headers or credentials.
            try:
                payload = json.loads(exc.read())
                detail = str(payload.get("detail") or payload.get("message") or payload.get("error") or "")
                detail = detail.replace(self.key, "[redacted]")[:1000]
            except (ValueError, AttributeError):
                detail = ""
            raise RuntimeError(f"Runpod {method} {path}: HTTP {exc.code} {detail}") from None

    def graphql(self, query):
        # GraphQL's documented query-key authentication. Never log this URL.
        req = Request("https://api.runpod.io/graphql?" + urlencode({"api_key": self.key}),
                      data=json.dumps({"query": query}).encode(),
                      headers={"Content-Type": "application/json", "User-Agent": "runpod-python"})
        try:
            with urlopen(req, timeout=20) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"Runpod GraphQL: HTTP {exc.code}") from None
        if result.get("errors"):
            raise RuntimeError("Runpod GraphQL rejected query")
        return result["data"]

    def request(self, path, method="GET", body=None):
        """Translate the small provider interface used by the shared lifecycle."""
        if path == "/instances" and method == "POST":
            pod = self.api("https://api.runpod.io", "/v2/pods", "POST", self.create_body)
            return {"instance_id": pod.get("id")}
        if path == "/instances":
            pods = self.api("https://rest.runpod.io/v1", "/pods")
            return {"instances": [{"id": p["id"], "status": p.get("desiredStatus", "").lower()}
                                  for p in pods]}
        pod_id = path.split("/")[2]
        if path.endswith("/connection"):
            pod = self.api("https://rest.runpod.io/v1", "/pods/" + pod_id + "?includeMachine=true")
            receipt = {k: pod.get(k) for k in ("id", "name", "desiredStatus", "costPerHr",
                                              "containerDiskInGb", "imageName", "gpuCount")}
            machine = pod.get("machine") or {}
            receipt["machine"] = {k: machine.get(k) for k in ("gpuTypeId", "dataCenterId",
                                                             "secureCloud", "currentPricePerGpu")}
            save(self.output / "assigned-pod.json", receipt)
            # Checked only after lifecycle has saved the ID, so failures DELETE it.
            rate = pod.get("costPerHr")
            if rate is not None and not 0 < float(rate) <= 2.14:
                raise RuntimeError("Assigned total hourly rate exceeds GPU+disk allowance")
            if machine.get("gpuTypeId") and machine["gpuTypeId"] != GPU:
                raise RuntimeError("Assigned GPU type differs from authorized RTX PRO 6000")
            if rate is not None:
                self.offer["hourly_usd"] = float(rate)
            ip = pod.get("publicIp")
            port = (pod.get("portMappings") or {}).get("22")
            if not ip or not port:
                return {"connection": {}}
            ipaddress.ip_address(ip)
            if not 1 <= int(port) <= 65535:
                raise ValueError("Invalid SSH port")
            return {"connection": {"ssh_command": f"ssh -p {port} root@{ip}"}}
        return self.api("https://rest.runpod.io/v1", "/pods/" + pod_id, method)


def choose_offer(data):
    """Live stock, not advertised catalog price; prefer authorized community."""
    for cloud, limit in (("COMMUNITY", 1.70), ("SECURE", 2.10)):
        rows = data[cloud]["gpuTypes"]
        price = (rows[0].get("lowestPrice") or {}) if rows else {}
        rate = price.get("uninterruptablePrice")
        if rate and 0 < rate <= limit and price.get("stockStatus") not in (None, "None", "OutOfStock"):
            return {"provider": "Runpod", "cloud": cloud, "gpu": GPU,
                    "hourly_usd": rate, "pool_id": 0, "stock": price["stockStatus"]}
    raise RuntimeError("No eligible Runpod RTX PRO 6000 stock at authorized rates")


def main():
    from dotenv import dotenv_values
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("inspect", "run", "manual", "terminate"))
    p.add_argument("--execute", action="store_true")
    p.add_argument("--minutes", type=int, default=30)
    p.add_argument("--cloud", choices=("auto", "COMMUNITY", "SECURE"), default="auto")
    p.add_argument("--instance-id")
    args = p.parse_args()
    if not 5 <= args.minutes <= 30:
        p.error("Whole-attempt limit must be 5..30 minutes")
    if args.action in ("run", "manual") and not args.execute:
        p.error("Paid run requires --execute")
    values = dotenv_values(ROOT.parent / ".env")
    client = Client(os.environ.get("RUNPOD_API_KEY") or values.get("RUNPOD_API_KEY"))
    if args.action == "terminate":
        if not args.instance_id or not args.instance_id.isalnum():
            p.error("terminate needs an alphanumeric --instance-id")
        client.request("/instances/" + args.instance_id, "DELETE")
        print("Deletion accepted; confirm using inspect/dashboard")
        return
    account = client.graphql('{ myself { clientBalance currentSpendPerHr pods { id name desiredStatus costPerHr } } }')["myself"]
    offers = {}
    for cloud in ("COMMUNITY", "SECURE"):
        offers[cloud] = client.graphql('{ gpuTypes(input:{id:' + json.dumps(GPU) +
            '}) { id lowestPrice(input:{gpuCount:1, secureCloud:' + str(cloud == "SECURE").lower() +
            '}) { uninterruptablePrice stockStatus } } }')
    print(json.dumps({"account": account, "offers": offers}, indent=2), flush=True)
    if args.action == "inspect":
        return
    offer = choose_offer(offers if args.cloud == "auto" else {
        c: offers[c] if c == args.cloud else {"gpuTypes": []} for c in offers})
    if account["clientBalance"] < 2.14 * args.minutes / 60:
        raise RuntimeError("Balance does not cover this bounded attempt")
    args.name = "qwen-residency-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    args.provider, args.preset = "Runpod", "baseline"
    args.manual = args.action == "manual"
    output = (ROOT / "outputs/runpod" / args.name).resolve()
    output.mkdir(parents=True, exist_ok=False)
    args.ssh_key = output / "ssh-key"
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(args.ssh_key)],
                   check=True, capture_output=True)
    client.create_body = {"name": args.name, "image": IMAGE, "cloud": offer["cloud"],
                          "startSsh": True, "disk": 120, "ports": ["22/tcp"],
                          "gpu": {"id": GPU, "count": 1, "minRamPerGpu": 128,
                                  "minVcpuCountPerGpu": 8,
                                  "allowedCudaVersions": ["13.0", "13.2", "13.3", "13.4"]},
                          "env": {"PUBLIC_KEY": args.ssh_key.with_suffix(".pub").read_text().strip()}}
    client.output, client.offer = output, offer
    manifest = {"offer": offer, "create": client.create_body, "minutes_limit": args.minutes,
                "mode": args.action,
                "balance_before": account["clientBalance"],
                "benchmark": residency_plan("envs/rl/.venv/bin/vllm"),
                "files": bundle(ROOT, output / "upload.tar.gz"),
                "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "storage": "120GB ephemeral container disk; deleted with pod"}
    save(output / "manifest.json", manifest)
    print(f"Selected {offer['cloud']} at ${offer['hourly_usd']}/hour GPU; output {output}", flush=True)
    signal.signal(signal.SIGTERM, interrupt)
    run_instance(client, offer, args, output, os.environ.get("HF_TOKEN") or values.get("HF_TOKEN") or "")
    print("Pod termination confirmed", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
