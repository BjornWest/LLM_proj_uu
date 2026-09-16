# Committed artifact audit — 16 September 2026

Initial read-only audit of committed tree `585fa07bb7a0e812110e957ab87b854c0e57d860`.
User subsequently authorized the ordinary untracking cleanup documented below.
Concurrent working-tree changes and untracked work are excluded from the measurements.
This is a storage/retention review, not a credential audit.

## Authorized cleanup

88 generated files / 24,671,912 bytes removed from the tracked tree, with local
originals preserved. These are the six raw ledgers, three RNG corpora, ten runtime
locks and 69 legacy compiled website files identified below. Narrow ignore rules
prevent accidental re-addition. Historical website manifests, current
`inspection_full`, dependency locks, profiles and reports remain tracked.

Exact bytes were independently copied and checked under the ignored local
`.local/git-artifact-cleanup-v1/` archive. This is a same-machine backup, not remote
artifact storage. The prior committed copies also remain in ordinary Git history.
[Retention manifest](../../data/curation/git_artifact_retention_v1.json) records
the source commit, blob IDs, SHA256, sizes, and compact ledger accounting totals.
It contains no model requests/responses.

Deployment check: `node build.mjs` passed in an isolated copy of committed inputs
with **none** of the three legacy inspection directories present. The active
`inspection_full` assets were present and passed the build's hash checks. This
establishes local build compatibility, not a new Vercel deployment or model run.

To check local evidence, or restore missing files on another full clone:

```bash
python3 data/curation/restore_git_artifacts.py
python3 data/curation/restore_git_artifacts.py --restore-missing
```

The helper restores exact Git blobs only when absent, checks existing content,
and refuses differing content; it never overwrites a newer ledger. Runtime locks
are not restored. A shallow clone missing the old blobs needs the recorded
historical commit fetched first. Recovery restores historical evidence, not a new
spending allowance or permission to resume a frozen cohort. Restore the ledgers
before using historical audit/sweep scripts; do not initialize replacement budgets.
The helper can use `--destination /path/to/empty-directory` for a separate recovery
copy without touching the working tree.

## Findings

The committed tree contains 980 files / 62,795,516 bytes (62.80 MB, decimal).
Compiled website assets under `dist/` account for 47,794,288 bytes. Repeated
identical blobs share Git storage: unique blob sizes total 45,913,013 bytes before
compression. Removing duplicate paths saves checkout space, not an equivalent
amount of Git object storage.

| Priority | Paths | Finding and recommendation |
| --- | --- | --- |
| Clear local runtime output | `data/curation/routed-pilot-*/{budget,suite}.lock` | Ten tracked empty process-lock files. Ignore these narrowly and remove them from tracking in a coordinated cleanup. Preserve dependency lockfiles such as `uv.lock`, `package-lock.json`, and `requirements.lock.txt`. |
| Strong external-artifact candidate | `data/curation/sweeps/budget.json` and five `data/curation/routed-pilot-*/budget.json` files | Six ledgers total 4,027,600 bytes, with 302 embedded request/response pairs including prompt messages. These are raw trace data despite the accounting filename. Preserve exact original bytes in durable private artifact storage; keep compact accounting summaries, hashes and retrieval references in Git. Never reset reservations or replace an operational ledger with a summary. |
| Generated research output | `data/curation/chaos-repair-review/rng-{original,imul,xorshift32-v1}/variants.json` | Three generated 1,024-descriptor corpora total 1,066,114 bytes. Good candidates for external artifacts while keeping generator code, version/seed inputs, regression tests, summary counts and corpus hashes. Preserve historical bytes before changing paths. |
| Historical deploy assets; coordinate before removal | `environments/inspection_shop/`, `environments/inspection_health/`, `environments/inspection_music/` | 72 files / 19,609,133 bytes. Current deployment uses `inspection_full`; these are legacy reduced fixtures. They are candidates for a versioned historical package, not immediate deletion. Preserve their manifests and historical reproducibility, and check owner/package dependencies before removing tracking. |
| Keep available to builds | `environments/inspection_full/` | 109 files / 28,232,707 bytes. Current Vercel build directly reads these files, and `scripts/setup_tricky_full.py` restores offline media from this directory. A blanket `dist/` ignore/removal would break clean checkouts/builds. Moving these requires a pinned, hash-verified artifact acquisition/package step first. |

The seventh budget file, `calibration-chaos-v1/budget.json`, is a compact 6,071-byte
accounting record without embedded model request/response objects in this scan.
It does not have the same bulk-data problem.

## Keep in Git

- Task definitions, catalogs, source/license references, curated inventory and
  verifier/configuration inputs. A JSON/JSONL suffix does not make a file disposable.
- Small validation summaries, review conclusions, manifests and evidence hashes.
  These explain why an adapter or result is trusted.
- Dependency lockfiles, source templates, and intentionally small test fixtures.
- Frozen profile provenance. The five roughly 244–246 KB WorkArena profiles are
  mostly source hashes (the guided-v5 source map serializes to about 236 KB), not
  copied page traces. Future formats could share immutable manifests, but rewriting
  old hashed profiles is not warranted simply to save this amount of space.

No tracked observation text files, browser videos, ZIP trace bundles, model
checkpoints, database files or Python bytecode were found by path/extension checks
in this committed tree. The raw request payloads above were found by inspecting
JSON structure, not merely filenames. Large image files are website assets.

## Safe cleanup sequence

1. Put future run/export data in already ignored `runs/` or `.local/` locations;
   use durable private storage for artifacts that must survive the workstation.
2. Archive any existing authoritative evidence byte-for-byte, with verified
   hashes and a retrieval manifest. Update consumers deliberately; existing
   budget paths and historical hash checks are dependencies.
3. Add narrow ignore rules and remove the selected files from Git tracking while
   preserving local files. Adding `.gitignore` entries alone does not untrack
   committed files. Do not unlink live lock files while a process may hold them.
4. Coordinate deployment/fixture changes with their owner. Do not remove current
   website assets until a clean checkout can obtain the exact package and build.

Ordinary untracking does not erase old Git history or shrink existing historical
blobs. History rewriting is separate, disruptive work and is not proposed here.

## Inspection method

Used `git ls-tree -rlz HEAD` for committed sizes/object identities and
`git cat-file blob` to inspect committed JSON structures. Counted embedded
`model_request`, `model_response`, and `messages` objects without publishing their
contents. Checked deployment/build consumers in `deploy/daylight/build.mjs`,
`scripts/setup_tricky_full.py`, and `docs/agents/full-site-restoration.md`.
Tracked lock files do not currently match ignore rules with `git check-ignore
--no-index`; existing calibration/sweep ignore rules cover different paths.
