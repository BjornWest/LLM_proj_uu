# Development and evaluation releases

Bjorn requested Git-based development/evaluation separation on 2026-10-07.
Evaluation owns promotion; Product, Website, Harness and Inspect own their
implementation paths. An implementation commit is a candidate, not an accepted
runtime. Model dispatch still needs a finite episode authorization.

## Two environments

Development may keep changing. Implementation agents submit an exact base/commit,
owned changed paths, dependency and asset additions, tests and task/grader API.
Prefer an agent-owned branch/worktree. During migration, the temporary-index
candidate command below captures only explicitly named files from the shared
development directory, without modifying its index, HEAD or other dirty files.
Do not commit all changes, checkout/reset shared main, or relocate a running agent.

Evaluation runs a fixed commit in a detached worktree. A suite records that commit,
the readiness certificate, dependency/environment inventory, task/world/recipe
hashes, model configuration and limits. Keep outputs/traces/secrets outside the
worktree. Import project modules only from the evaluation worktree: installed
editable packages must not silently supply missing modules from development.

Historical archives remain evidence. The first address build imports the exact
1099 frozen source/data files and the two explicitly approved chat assets. Small
build metadata is additional. It is a runnable address-task slice after acceptance,
not an assertion that HEAD or every later task is integrated. Do not start new
unrelated implementation branches from the slice without declaring dependencies.
Its legacy `.local` source files are deliberately tracked because the old runtime
consumes them; traces, credentials and generated run artifacts are not added.

## Safe candidate commits

`scripts/evaluation_release.py snapshot` imports a pinned source specification
into a new Git commit/ref and detached worktree. It uses Git plumbing with a
temporary index and does not change shared main. Failed operations leave additive
evidence or an identifiable candidate; never reset main to recover them.

For a fix or feature, create a JSON list of owned repository-relative paths.
The base must be an exact prior release candidate commit, never mutable `main`.
Include every new required asset/module and test. A missing declared existing path
is an explicit deletion; a missing new path fails. Shell globs are not accepted.
Undeclared files, including existing chat assets, are inherited directly from the
base Git blobs; a partial source root only needs the owner's declared changes.

```bash
python3 scripts/run_bounded_job.py --memory-mib 2048 -- \
  python3 scripts/evaluation_release.py candidate \
  --repo /home/bjorn/code/LLM_proj_uu \
  --base EXACT_RELEASE_COMMIT \
  --source-root /home/bjorn/code/LLM_proj_uu \
  --paths /absolute/path/owned-paths.json \
  --ref refs/heads/dev/OWNER-FEATURE-UNIQUE \
  --worktree /home/bjorn/code/LLM_proj_uu-worktrees/OWNER-FEATURE-UNIQUE \
  --receipt /absolute/path/new-candidate-receipt.json
```

Use the bounded launcher and coordinate the shared two-job resource limit.
The command creates a parented feature commit. It also regenerates
`.evaluation-release.json` to describe the candidate; this metadata change is
expected. Commit identity/provenance does not itself certify feature behavior.
Tell Evaluation the exact commit/base, changed paths and dependency/test evidence.
Dependencies owned by another agent must be declared, not copied from its dirty
files. Evaluation alone integrates competing commits and publishes the active
release. Ordinary development branches may instead provide standard Git commits
with the same explicit base and ownership guarantees.

## Readiness before promotion

The release checker requires a clean tracked inventory, exact committed source
hashes and nonempty chat HTML/license. This prevents the known asset omission.
An import-only or constructor-only check cannot certify readiness.

For each task being released, Website/adapter owners execute a zero-provider smoke
from the actual detached worktree using the normal bounded launcher. Evidence must
cover isolated imports, browser reset, initial observation, actual public task and
memory/setup, captured return, once-only native automatic grading, HTTP viewer
projection and relevant positive/negative controls. A correctly graded negative
scripted answer is useful proof; the model need not run. Preserve failures and
qualifications. Do not invent effect authority or use a pass flag as an outcome
proof. External environments, installed dependencies, browser and tokenizer data
must be inventoried/pinned separately; Git does not freeze them.

The standardized evidence JSON has `schema: 1`, exact `commit` and `worktree`,
`model_requests: 0`, an `environment` path/hash record, and `cases`. Each case
contains a unique `task_id`, recipe and authority path/hash records, and `checks`.
Each named check below has `status: "pass"` and a pinned actual artifact. That
status means its stage passed, not that a deliberately wrong task answer succeeded.

```text
import_isolation, browser_reset, initial_observation, task_setup,
capture, automatic_grade, viewer_projection, positive_negative_controls
```

```bash
python3 scripts/evaluation_release.py certify \
  --worktree /absolute/evaluation-worktree \
  --evidence /absolute/task-smoke.json \
  --certificate /absolute/new-readiness-certificate.json
```

Evaluation reviews actual artifacts and produces a separate promotion approval
with `owner: "Evaluation"`, `status: "accepted"`, the exact `commit`, and the
certificate path/hash. Certification checks artifact bindings and stage coverage;
it cannot replace semantic review of the trusted stage proofs.

```bash
python3 scripts/evaluation_release.py promote \
  --worktree /absolute/evaluation-worktree \
  --certificate /absolute/readiness-certificate.json \
  --approval /absolute/promotion-approval.json \
  --registry /home/bjorn/code/LLM_proj_uu/.local/evaluation-releases/current.json \
  --label address-20261007-r1
```

This creates an immutable `eval/LABEL` tag and atomically updates the discovery
pointer. Existing suites retain their original commit/certificate; they never
follow that pointer during execution. A certificate/tag does not authorize a
model episode or imply support outside its listed tasks. Preserve authority source
closures and native/reference bindings when integrating fixes; a commit does not
bypass their acceptance requirements.

## Before each suite

Call `require_ready(worktree, certificate)` or the equivalent checker before
preparing model dispatch, and bind its exact output plus the promotion approval
into the suite plan. The function rechecks sources and proof/artifact hashes.
Changing dependencies/environment or the runtime code requires a new candidate
and smoke. Verify actual installed environment against the recorded inventory in
the task adapter; matching an inventory file alone does not verify current packages.

```bash
python3 scripts/evaluation_release.py check \
  --worktree /absolute/evaluation-worktree \
  --certificate /absolute/readiness-certificate.json
```

`check` without a certificate reports only source integrity and explicitly says
the candidate is not runtime ready. Every new episode must attach automatic grading
and verify viewer publication, or use an explicit recorded diagnostic escape.
Missing grading is an infrastructure failure, not a model task failure.

The first address migration still uses its reviewed frozen outer grading contract.
Harness's prospective `AutomaticGrading` implementation is a separate candidate
commit requiring integration tests; never overwrite old sources to adopt it.

## Resource and rollout boundaries

All heavy packaging/tests/browser/model/server work uses `run_bounded_job.py`.
At most two heavyweight jobs total. Browser smoke can run sequentially when an
observed PID/thread-limit dependency requires it; the retained address parallel
startup hit the job's 256-PID cap, so its next browser checks are serial. No automatic
episode retry, world regeneration or new model request is part of release migration.

This protocol eliminates dependency on mutable development files for accepted
releases and catches tested setup/grade failures before provider dispatch. It does
not promise that every unknown browser/hardware incompatibility can be impossible.
