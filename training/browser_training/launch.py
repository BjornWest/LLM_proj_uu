"""Pure CLI construction is tested without importing CUDA frameworks."""
import argparse
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FP8 = "Qwen/Qwen3.8-27B-FP8"
REVISIONS = {
    FP8: "017b9c7af6b5689d5dd426a76e0bc077eb5ca20a",
    "Qwen/Qwen3.8-27B": "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
    "Qwen/Qwen3-0.6B": "c1899de289a04d12100db370d81485cdf75e47ca",
}


def vllm_command(args):
    command = [str(ROOT / "envs/rl/.venv/bin/vllm"), "serve", args.model,
               "--revision", REVISIONS[args.model], "--host", args.host, "--port", str(args.port),
               "--dtype", "bfloat16", "--generation-config", "vllm",
               "--max-model-len", str(args.context), "--max-num-seqs", str(args.max_num_seqs),
               "--gpu-memory-utilization", str(args.memory_fraction),
               "--tensor-parallel-size", str(args.tp),
               "--kv-cache-dtype", args.kv_dtype, "--logprobs-mode", "processed_logprobs",
               "--weight-transfer-config", '{"backend":"nccl"}']
    if args.model == FP8:
        command += ["--language-model-only", "--reasoning-parser", "qwen3"]
    if args.preset != "baseline":
        if args.max_loras < args.max_staleness + 2:
            raise ValueError("max_loras must be >= max_staleness + 2")
        command += ["--enable-lora", "--lora-dtype", "bfloat16", "--max-lora-rank", str(args.rank),
                    "--max-loras", str(args.max_loras)]
    if args.preset == "lora-mtp":
        if args.model != FP8:
            raise ValueError("MTP preset is only for the real Qwen3.8 FP8 checkpoint")
        command += ["--speculative-config", json.dumps({"method": "mtp", "num_speculative_tokens": args.draft_tokens})]
    if args.tools:
        command += ["--enable-auto-tool-choice", "--tool-call-parser", "qwen3_coder"]
    if args.eager:
        command += ["--enforce-eager"]
    return command


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--preset", choices=["baseline", "lora", "lora-mtp"], default="lora")
    p.add_argument("--model", choices=REVISIONS, default=FP8)
    p.add_argument("--gpu", default="0")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--context", type=int, default=4096)
    p.add_argument("--max-num-seqs", type=int, default=8)
    p.add_argument("--memory-fraction", type=float, default=0.85)
    p.add_argument("--tp", type=int, default=1)
    p.add_argument("--rank", type=int, choices=[8, 16, 32, 64], default=32)
    p.add_argument("--max-loras", type=int, default=4)
    p.add_argument("--max-staleness", type=int, default=2)
    p.add_argument("--kv-dtype", choices=["auto", "fp8"], default="auto")
    p.add_argument("--draft-tokens", type=int, default=3)
    p.add_argument("--tools", action="store_true")
    p.add_argument("--eager", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p


def main():
    args = parser().parse_args()
    cmd = vllm_command(args)
    selected = {"CUDA_VISIBLE_DEVICES": args.gpu, "VLLM_SERVER_DEV_MODE": "1",
                "VLLM_ALLOW_RUNTIME_LORA_UPDATING": "1", "VLLM_WORKER_MULTIPROC_METHOD": "spawn"}
    print(shlex.join([f"{k}={v}" for k, v in selected.items()]) + " " + shlex.join(cmd), flush=True)
    if not args.dry_run:
        # The launcher can run in the small CPU environment. Record packages
        # using the server interpreter, otherwise the manifest would list pytest
        # and PyYAML instead of the vLLM stack actually being launched.
        config = {**vars(args), "model_revision": REVISIONS[args.model], "command": cmd}
        subprocess.run([str(ROOT / "envs/rl/.venv/bin/python"), "-c",
                        "import json,sys; from browser_training.provenance import capture; capture(sys.argv[1], json.loads(sys.argv[2]))",
                        str(ROOT / "outputs/server"), json.dumps(config)], check=True)
        os.execve(cmd[0], cmd, {**os.environ, **selected})


if __name__ == "__main__":
    main()
