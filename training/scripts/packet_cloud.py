#!/usr/bin/env python3
"""Plan by default; paid execution requires an explicit --execute switch.

Keep this local controller alive until cleanup completes. No allocation retries.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser_training.packet_cloud import Client, bundle, choose_offer, parse_connection
from browser_training.vllm_speed import residency_plan


def credentials():
    from dotenv import dotenv_values
    # Parse as data, never source .env as shell code. Environment overrides file.
    values = dotenv_values(ROOT.parent / ".env")
    return {name: os.environ.get(name) or values.get(name) or ""
            for name in ("PACKET_API_KEY", "HF_TOKEN")}


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def interrupt(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


def ssh_options(target, port, output, password):
    options = ["-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
               "-o", "ServerAliveCountMax=2", "-o", "StrictHostKeyChecking=accept-new",
               "-o", f"UserKnownHostsFile={output / 'known_hosts'}",
               "-o", "NumberOfPasswordPrompts=1"]
    env = {**os.environ}
    if password:
        # SSH reads password from a private askpass pipe, never argv or a log.
        helper = output / "askpass"
        helper.write_text('#!/usr/bin/env python3\nimport os\nprint(os.environ["PACKET_SSH_PASSWORD"])\n')
        helper.chmod(0o700)
        env.update(SSH_ASKPASS=str(helper), SSH_ASKPASS_REQUIRE="force", DISPLAY=":0",
                   PACKET_SSH_PASSWORD=password)
    else:
        options += ["-o", "BatchMode=yes"]
    return (["ssh", *options, "-p", str(port), target],
            ["scp", *options, "-P", str(port)], env)


def run_instance(client, offer, args, output, secret):
    """Single allocation; collect partial artifacts then DELETE on every exit path."""
    instance_id = None
    connected = None
    started = time.monotonic()
    deadline = started + args.minutes * 60
    state = {"offer": offer, "name": args.name, "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "minutes_limit": args.minutes, "termination_confirmed": False}
    save(output / "allocation.json", state)
    try:
        # Matches the published CLI's Dynamic API. product_id is NOT a documented
        # request field: pool membership links the quote, not a binding invoice cap.
        response = client.request("/instances", "POST", {
            "name": args.name, "pool_id": offer["pool_id"], "vgpus": 1})
        instance_id = response.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise RuntimeError("Create returned no instance ID; check dashboard before any retry")
        state["instance_id"] = instance_id
        save(output / "allocation.json", state)
        print(f"Instance {instance_id} allocated; local deadline {args.minutes} minutes", flush=True)
        endpoint = "/instances/" + instance_id
        ready_deadline = min(deadline, time.monotonic() + 300)
        while time.monotonic() < ready_deadline:
            data = client.request(endpoint + "/connection")
            connection = data.get("connection") or {}
            if connection.get("ssh_command"):
                target, port = parse_connection(connection["ssh_command"])
                ssh, scp, env = ssh_options(target, port, output, connection.get("password"))
                check = subprocess.run([*ssh, "true"], env=env, capture_output=True, timeout=20)
                if check.returncode == 0:
                    connected = (ssh, scp, env, target)
                    break
            time.sleep(5)
        if connected is None:
            raise TimeoutError("No working SSH connection within five minutes")
        ssh, scp, env, target = connected
        subprocess.run([*ssh, "mkdir -p ~/packet-training"], env=env, check=True, timeout=20)
        subprocess.run([*scp, str(output / "upload.tar.gz"), target + ":packet-training/upload.tar.gz"],
                       env=env, check=True, timeout=min(60, max(1, deadline - time.monotonic())))
        # Reserve time for two short artifact transfers and API termination.
        remaining = int(deadline - time.monotonic()) - 90
        if remaining <= 0:
            raise TimeoutError("Insufficient time remaining for bootstrap and cleanup")
        remote = ("cd ~/packet-training && tar -xzf upload.tar.gz && "
                  f"timeout --signal=TERM --kill-after=10s {remaining}s "
                  f"bash scripts/packet_vllm_worker.sh {shlex.quote(args.preset)} {min(900, remaining)}")
        with (output / "worker.log").open("w") as log:
            run = subprocess.run([*ssh, remote], env=env, input=secret + "\n", text=True,
                                 stdout=log, stderr=subprocess.STDOUT,
                                 timeout=max(1, deadline - time.monotonic() - 90))
        state["worker_exit_code"] = run.returncode
        if run.returncode:
            raise RuntimeError(f"Remote worker exited {run.returncode}; inspect collected worker.log")
    finally:
        # Prevent a second ordinary Ctrl-C from interrupting deletion in progress.
        previous = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            if connected:
                ssh, scp, env, target = connected
                try:
                    subprocess.run([*ssh, "cd ~/packet-training && tar -czf results.tar.gz outputs/packet"],
                                   env=env, check=True, capture_output=True, timeout=15)
                    subprocess.run([*scp, target + ":packet-training/results.tar.gz", str(output / "results.tar.gz")],
                                   env=env, check=True, capture_output=True, timeout=15)
                except (OSError, subprocess.SubprocessError):
                    state["artifact_collection_failed"] = True
            if instance_id:
                try:
                    client.request("/instances/" + instance_id, "DELETE")
                    state["delete_accepted"] = True
                    # DELETE success is acceptance, not confirmation the bill stopped.
                    for _ in range(2):
                        instances = client.request("/instances").get("instances", [])
                        matching = [i for i in instances if i.get("id") == instance_id]
                        if not matching or matching[0].get("status") in (
                                "terminated", "deleted", "cancelled", "un_subscribed"):
                            state["termination_confirmed"] = True
                            break
                        time.sleep(3)
                except Exception:
                    state["cleanup_failed"] = True
                if not state["termination_confirmed"]:
                    print(f"CHECK PACKET DASHBOARD: termination unconfirmed for {instance_id}", file=sys.stderr)
            else:
                state["allocation_outcome_unknown"] = True
                print("Create outcome may be ambiguous: inspect dashboard; do not retry automatically", file=sys.stderr)
            state["controller_wall_seconds"] = time.monotonic() - started
            state["estimated_compute_usd"] = state["controller_wall_seconds"] / 3600 * offer["hourly_usd"]
            state["cost_note"] = "Advertised-rate estimate, excludes billing minimums/storage/fees; check dashboard invoice"
            save(output / "allocation.json", state)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    if not state["termination_confirmed"]:
        raise RuntimeError("Instance termination not confirmed; check Packet dashboard now")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["inspect", "plan", "run", "terminate"])
    p.add_argument("--execute", action="store_true", help="Explicitly allow a paid allocation")
    p.add_argument("--max-hourly", type=float, default=0.70)
    p.add_argument("--minutes", type=int, default=30, help="Whole attempt, including provisioning/install/download")
    p.add_argument("--pool", type=int)
    p.add_argument("--preset", choices=["baseline", "mtp"], default="baseline")
    p.add_argument("--name", default="qwen-fp8-speed-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()))
    p.add_argument("--output", type=Path)
    p.add_argument("--instance-id", help="Explicit target for manual recovery/termination")
    args = p.parse_args()
    if not 5 <= args.minutes <= 60 or not 0 < args.max_hourly <= 2:
        p.error("minutes must be 5..60 and max-hourly must be >0 and <=2")
    if args.action == "run" and not args.execute:
        p.error("Paid run needs --execute; use plan to review first")
    if args.action == "terminate" and (not args.instance_id or not re_id(args.instance_id)):
        p.error("terminate needs a valid --instance-id")
    secrets = credentials()
    client = Client(secrets["PACKET_API_KEY"])
    if args.action == "terminate":
        client.request("/instances/" + args.instance_id, "DELETE")
        print("Deletion accepted; confirm terminated status using inspect/dashboard")
        return
    options = client.request("/launch-options")
    wallet = client.request("/inventory/balance").get("wallet", {})
    financial = {k: wallet.get(k) for k in ("availableBalance", "availableBalanceFormatted", "currency")}
    if args.action == "inspect":
        print(json.dumps({"wallet": financial, "products": [{k: x.get(k) for k in (
            "id", "name", "pricePerHourCents", "vramGb", "poolIds", "totalAvailableGpus")}
            for x in options.get("products", [])], "pools": options.get("pools", []),
            "instances": [{k: x.get(k) for k in ("id", "name", "status")}
                          for x in client.request("/instances").get("instances", [])]}, indent=2))
        return
    offer = choose_offer(options, args.max_hourly, args.pool)
    estimated_cents = offer["hourly_usd"] * args.minutes / 60 * 100
    if args.action == "run" and (financial["currency"] != "usd"
                                 or (financial["availableBalance"] or 0) < estimated_cents):
        raise RuntimeError("USD wallet balance does not cover the quoted attempt")
    output = (args.output or ROOT / "outputs/packet" / args.name).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"offer": offer, "wallet": financial, "minutes_limit": args.minutes,
                "benchmark": residency_plan("envs/rl/.venv/bin/vllm", preset=args.preset),
                "estimated_compute_usd": offer["hourly_usd"] * args.minutes / 60,
                "pricing_caveat": "Quote only; API create accepts pool_id, not a binding product price cap",
                "files": bundle(ROOT, output / "upload.tar.gz")}
    try:
        manifest["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except subprocess.SubprocessError:
        manifest["git_commit"] = None
    save(output / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2), flush=True)
    if args.action == "run":
        signal.signal(signal.SIGTERM, interrupt)
        run_instance(client, offer, args, output, secrets["HF_TOKEN"])


def re_id(value):
    import re
    return bool(re.fullmatch(r"[a-zA-Z0-9_-]+", value))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
