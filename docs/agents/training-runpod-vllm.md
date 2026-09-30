# Runpod: bounded Qwen FP8 inference benchmark

Prepared and attempted 2026-09-30. **Allocation, SSH, GPU arithmetic, dependency
installation, model download and FP8 weight loading have worked on SM120.
vLLM startup and its health endpoint now pass; generation and throughput
remain unverified.** All four allocated pods were deleted.

## Launch and limits

From the repository root, using the ignored `.env` containing `RUNPOD_API_KEY`
and optional `HF_TOKEN`:

```bash
training/.venv/bin/python training/scripts/runpod_cloud.py inspect

# First qualification: allocate and upload, then run stages manually over SSH.
# The independent controller stays alive to enforce deadline cleanup.
training/.venv/bin/python training/scripts/runpod_cloud.py manual --execute --minutes 23

# Paid execution only for an explicitly authorized attempt.
training/.venv/bin/python training/scripts/runpod_cloud.py run --execute --minutes 28

# Explicit secure-cloud fallback; no automatic creation retries.
training/.venv/bin/python training/scripts/runpod_cloud.py run \
  --execute --minutes 28 --cloud SECURE

# Recovery targets exactly one recorded pod.
training/.venv/bin/python training/scripts/runpod_cloud.py terminate --instance-id POD_ID
```

The helper prefers the full **RTX PRO 6000 Blackwell Server Edition, 96 GB** at
up to $1.70/hour community pricing, then up to $2.10/hour secure pricing, based
on live `lowestPrice` stock. It excludes Max-Q, workstation and MIG variants.
At inspection, rates were $1.69 and $2.09 respectively. Stock changed between
queries; catalog availability is not an allocation guarantee.

It creates one pod with Runpod's published `runpod/base:1.4.0-cuda1300-ubuntu2404`
image, at least 128 GB host RAM/eight vCPUs, a CUDA 13-compatible host and 120 GB
ephemeral disk. The assigned total pod rate must be at most $2.14/hour (allowing
small disk charges); an incompatible assignment fails after recording the ID,
so cleanup can delete it. An API quote is not a binding provider billing cap.

The same [Packet residency benchmark](training-packet-vllm.md) and frozen upload
are reused: 30K/1K long-context decode, 5K/1K high-concurrency decode, matched
prefill probes and a half-concurrency decode comparison. Model revision,
vLLM 0.28.0, official tokenizer, cold cache and phase accounting are unchanged.
Only the provider lifecycle and SSH identity differ. The worker's historical
`outputs/packet` directory remains inside the result archive; local receipts
live under ignored `training/outputs/runpod/`.

In `manual` mode no worker launches automatically. Read `connection.json` in the
printed local output directory for the SSH/scp argv and operator deadline. The
per-attempt private key stays in that ignored directory. Run the existing worker
with a third argument `setup`, `download`, or `benchmark`; the first two arguments
remain `baseline` and benchmark seconds. Pass a newline on SSH stdin for setup
and benchmark, or the selected HF token plus newline for download. Never pass
credentials as command-line arguments.

```bash
# These commands run on the pod in ~/packet-training, under an SSH timeout
# bounded by the operator deadline. Their stdout should be captured locally.
bash scripts/packet_vllm_worker.sh baseline 900 setup
bash scripts/packet_vllm_worker.sh baseline 900 download
bash scripts/packet_vllm_worker.sh baseline 900 benchmark
```

A failed SSH stage leaves the pod and model cache intact. Fix the failed file
in place, copy that correction back to the repository, record its new hash, and
rerun only the failed stage within the remaining allowance. Preserve failed
logs and partial results; do not repeat completed benchmark cohorts silently.
When finished, write `{"exit_code":0}` (success) or a nonzero exit code to the
local `manual-finished.json` file. The controller then collects artifacts and
deletes the pod. If no marker arrives it starts cleanup 90 seconds before the
whole-attempt deadline. Interrupting the controller also triggers cleanup.

Provisioning, dependency installation and model download count against the
whole-attempt deadline. Artifact collection reserves 90 seconds. The controller
uses the existing cleanup path: collect partial results, DELETE the exact pod,
then confirm absence/termination. Keep it running; SIGKILL, workstation failure
or API outages can still require manual deletion. No provider-side termination
timer was verified: installed runpodctl 2.14.0 lacks the `--terminate-after`
creation flag mentioned in the installed skill snapshot.

## Observed first attempt

* A community-cloud POST returned HTTP 400, with no pod created. The original
  diagnostic body was not retained, so the cause is **unestablished**. The
  request matched the subsequently inspected live v2 schema. Later API errors
  retain a sanitized public diagnostic.
* The explicitly authorized secure fallback created pod `c4ybv3ar9mtbl4` in
  `US-NE-1`, at $2.09/hour. Direct SSH with a per-attempt public key worked.
* The worker failed immediately at `pip install --user uv==0.10.8`. Container
  `PIP_BREAK_SYSTEM_PACKAGES` was not inherited by the SSH command, so the
  distro Python enforced PEP 668. No weights or inference were attempted.
* Deletion was confirmed after about 64 seconds. Account balance fell from
  $8.2133059373 to $8.1767361623: approximately **$0.03657**, with no active pods
  and zero hourly account spend afterward. This is an observed balance change,
  not a downloaded itemized invoice.
* Bootstrap now creates `.bootstrap` with `python3 -m venv`, installs pinned uv
  inside it and prepends that venv's binaries to PATH. Local execution verified
  uv 0.10.8; shell parsing and all 29 launcher/benchmark tests passed. The fixed
  bootstrap subsequently passed on the second and third rented pods.

Evidence is in `training/outputs/runpod/qwen-residency-20260930-164911/`:
`allocation.json`, `assigned-pod.json`, `manifest.json`, `worker.log` and
`results.tar.gz`. Archives are remote input: extract with a safe tar filter,
never blindly follow archive paths or symlinks. SSH private keys are ignored
local artifacts and are never in the upload allowlist.

## Second attempt and cache fix

The second pod (`e44ybky5kzo2ey`) completed setup, real BF16 backward and FP8 GEMM
on SM120, and downloaded the pinned model. Driver was 595.91.07; PyTorch was
2.13.0+cu130; available VRAM was 94.97 GiB. It stopped before starting vLLM:
Hub 1.31.0 checked the cached repository tree and found three files excluded by
the downloader (`README.md`, `LICENSE`, `.gitattributes`). The offline consumer
had requested the entire repository rather than the prepared subset.

`MODEL_CACHE_PATTERNS` now defines the same file subset for download and offline
lookup, including those repository metadata files. A CPU regression against the
locked Hub library reproduced the original failure, verified a complete local
snapshot passes, and verified actual missing weights still fail. No dummy
weights were loaded as a model. Both earlier pods were deleted. Combined
controller wall time was 354 seconds, with account balance declining from
$8.2133059373 to $8.0077687512 (about $0.20554). No vLLM throughput was measured.

The user subsequently requested manual SSH qualification: stay on one live pod
and repair script failures without reallocating. The new manual lifecycle was
validated against explicit finish and deadline expiry; all 32 focused CPU checks
passed before allocating `i33hcp3m6o4s3j` with a 23-minute limit. That pod was deleted at its deadline without successful serving or throughput.

## Manual qualification and compiler discovery

The third pod completed setup in 28 seconds and downloaded the pinned snapshot
in 34 seconds. Qwen FP8 weights loaded successfully (27.64 GiB, about three
seconds), but vLLM startup exposed two SSH environment failures:

1. FlashInfer JIT could not find `ninja`, although it was installed in the locked
   Python environment. The worker now prepends that environment's `bin` to PATH.
2. FlashInfer's availability check could not find `nvcc`, although CUDA 13 was
   installed at `/usr/local/cuda`. The worker now sets `CUDA_HOME` and prepends
   its `bin` directory. A live check then found NVCC 13.0 and reported
   `has_flashinfer() == True`.

The final path correction was checked on the live pod, but the operator deadline
expired before another model startup. No health check, generation, capacity
measurement or benchmark request completed. The worker now checks both compiler
executables and FlashInfer availability before downloading or reloading weights.
Failed startup logs remain preserved separately; no successful cohort was rerun.

All three pods were confirmed deleted. A later settled account check showed
$7.2512402013 versus the initial $8.2133059373: approximately **$0.9621** observed
balance decline, including any delayed billing. This is not an itemized invoice.
The account reported zero active pods and zero hourly spend before the next
explicitly authorized allocation. The requested extension arrived after deletion
and was not automatically treated as permission to rent a replacement.

| Capability | Evidence | Remaining check |
|---|---|---|
| Allocation, direct SSH, rate checks, deletion | Three paid attempts | New provider images may differ |
| BF16 backward and FP8 GEMM on SM120 | GPU preflight passed | Full model execution |
| Locked environment and model cache | Setup/download passed | Persistent volume not implemented |
| FP8 Qwen weight loading | 27.64 GiB observed | Generation/quality validation |
| Compiler discovery and startup | Fourth attempt reached HTTP 200 health | Actual generation |
| Benchmark phase separation | CPU replay of prior reference | New GPU throughput measurements |

Evidence for the third attempt is in ignored
`training/outputs/runpod/qwen-residency-20260930-171148/`. These directories
contain private SSH keys: do not serve them over HTTP or commit them.

## Fourth attempt: startup passed, benchmark timed out

The user explicitly authorized a fresh ten-minute manual attempt. Community
allocation returned the retained diagnostic “There are no longer any instances
available with the requested specifications.” A read-only check confirmed no
pod was created before the authorized secure-cloud fallback.

Secure pod `ogz886870spime` used driver 580.173.02, CUDA 13.0, SM120 and
94.9705 GiB usable VRAM. Setup and compiler preflight passed in 80.6 seconds;
the pinned 81-file model snapshot downloaded in 29.3 seconds. FP8 weights used
27.64 GiB. The corrected paths let FlashInfer compile and initialize on SM120.
Cold engine initialization took 190.46 seconds, including 54.33 seconds of
Torch compilation, 49.28 seconds of initial profiling and subsequent FlashInfer
JIT/Qwen warmup/CUDA graph work. The full benchmark stage also includes imports
and API-server startup: `/health` returned **HTTP 200** at 17:53:31 UTC.

vLLM reported 56.47 GiB available for KV cache. The hybrid-aware probe calculated:

| Input / reserved output tokens | Full-context concurrency | Predicted reserved pool fraction |
|---|---:|---:|
| 30,000 / 1,000 | 51 | 99.49% |
| 5,000 / 1,000 | 168 | 99.75% |

These are **capacity calculations**, not observed active KV occupancy or measured
throughput. The deadline interrupted preparation of the 30K native dataset after
22 complete JSONL lines, before benchmark requests began. No generation result,
steady decode tokens/s, prefill tokens/s or `execution.json` was produced; outer
`timeout` ended the stage with exit code 124. The partial dataset is evidence of
interruption and must not be reused as a complete benchmark input.

The controller retrieved artifacts and confirmed deletion after 513.9 seconds
(about **$0.30** at the quoted rate, below the authorized $0.35 compute estimate).
An immediate account check reported no pods and zero hourly spend. Its balance
was $7.0384133596; balance deltas may lag usage and are not a final invoice.
Evidence is under ignored
`training/outputs/runpod/qwen-residency-20260930-174530/`, including the frozen
manifest, stage receipts, GPU samples and collected `server.log`.

The next run should prepare exact-token native prompts on CPU before allocation
and reuse model/compiler caches where practical. Allow a cold-start window plus
several minutes for the 51-request long-context cohort; ten minutes covering
provisioning, full dependency installation, download and cold compilation was
insufficient. Do not change to eager execution simply to fit the time budget:
that would measure a different configuration. Persistent-cache attachment and
precomputed-prompt upload are **next work**, not implemented capabilities.

## Storage

There were no existing account network volumes. This attempt used ephemeral
storage, which was removed with the pod, and did not create recurring storage
charges. For repeated runs, create a network volume in a data center with this
GPU, attach it **at pod creation**, and put `HF_HOME` on that mount. A pod's local
persistent disk is not equivalent to a network volume surviving pod deletion.
Network volumes constrain placement and bill while the GPU is absent; choose
the location and storage budget before adopting one. Current launch code does
not yet attach network volumes or promise cache persistence.

## Official agent setup

The user requested [Runpod's agent setup guide](https://docs.runpod.io/agent-setup.md).
Its noninteractive skills command installed **eight** current skills (the guide
describes an older six-skill bundle) in `~/.agents/skills`. The `runpod` marketplace
was registered with `codex plugin marketplace add`. `runpodctl 2.14.0` was installed
from the official GitHub release, its binary digest verified, and an authenticated
read-only `user` call succeeded. No API key was printed, sourced or uploaded.

**Pending user UI step:** open `/plugins`, select the Runpod marketplace, install
Runpod and reload if requested. Hosted MCP activation/OAuth was not performed or
claimed. The guide's fallback `codex mcp add --transport http ...` is incompatible
with this local CLI; its live help uses `codex mcp add runpod --url
https://mcp.getrunpod.io/`. Do that only if the activated plugin does not expose
its tools. The API-key launcher needs neither a plugin reload nor MCP OAuth.
The docs feedback MCP is not connected; documentation feedback has not been sent.

Sources: [live REST v2 schema](https://api.runpod.io/v2/openapi.json),
[published v1 schema](https://github.com/runpod/docs/blob/main/api-reference/openapi.json),
[official Python create/terminate source](https://github.com/runpod/runpod-python/blob/main/runpod/api/ctl_commands.py),
[official base-image source](https://github.com/runpod/containers/blob/main/official-templates/base/Dockerfile),
[CLI releases](https://github.com/runpod/runpodctl/releases),
[agent skills](https://github.com/runpod/runpod-plugins-official).
