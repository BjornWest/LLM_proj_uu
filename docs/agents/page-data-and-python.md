# Public page extraction and isolated Python

Implemented locally as `core-tools-v11-data`. No new paid-model evaluation or
production rollout is claimed. `standard_profile(data_tools=False)` retains the
previous tool set for controlled comparisons. Historical run configurations and
artifacts remain unchanged.

## Tool contract

`extract_page(ref, format, verbose=False)` resolves an existing public AX ref in
the fresh current capture. It saves the full semantic subtree, independently of
AX overview/presentation budgets and previously delivered-node suppression.
No live DOM evaluation, hidden state, account API, grader data or implicit page
navigation is used. Standard AX semantic filtering still applies; this is not
an export of every raw DOM node. Public page content is untrusted.

- `tree`: ordered nodes with full name/value/state, child refs and parent refs.
- `text`: JSON lines containing ref/role/name/value, preserving node boundaries.
- `table`: a selected accessible table/grid, with ordered cell-string rows,
  header rows, nullable columns, row/cell refs and full source nodes. Duplicate
  headers, blanks and uneven row lengths are preserved. Multiple header rows
  leave columns null. Nested tables or missing semantic boundaries fail
  explicitly; the agent can use tree/text instead. Merged cells are not expanded.

The result names an immutable episode-local dataset (`data1`, etc.), SHA256,
coverage and a small preview. Full data is stored in `dataset-data1.json`.
The agent must navigate pagination itself and explicitly choose which datasets
and records to combine. No numeric/date coercion, filtering or deduplication is
performed. `verbose` follows the AX convention: only extraction identity metadata
is optional; semantic state remains. Dataset extraction does not mark the whole
subtree as read in conversational AX history.

`run_python(code, datasets=["data1"])` exposes those exact datasets in a Python
`datasets` dictionary. The agent uses ordinary Python and standard-library
modules (`decimal`, `datetime`, `json`, `re`, `statistics`, etc.). Instructions
recommend checking types/headers/row lengths and explicitly parsing raw values.
Use `print` to return output. Python errors and tracebacks are ordinary tool
results; scripts are never automatically repaired or retried.

Scripts run in independent processes. Variables and /tmp files do not persist;
extracted datasets remain available for the episode. A script's modifications
to its in-memory dataset cannot change the stored snapshot. Helpers inherit the
tools but not dataset handles: own-browser helpers extract their own public data;
no-browser helpers may compute on literals supplied in their context.

## Runtime and resource limits

The optional `DockerPython` executor requires Docker CLI/daemon access and a
trusted local image. There is no unsandboxed fallback. Runtime resolves the
image to its immutable ID, records it, and uses `--pull=never`. This workstation
has a cached vanilla Python 3.11.8 image tagged `intent-browser-python:stdlib-v1`;
no image download was needed. Elsewhere, build explicitly:

```bash
docker build -f deploy/python/Dockerfile -t intent-browser-python:stdlib-v1 .
```

`HARNESS_PYTHON_IMAGE` can select a different trusted, locally installed image.
For frozen evaluations use an immutable ID/digest and retain its provisioning
provenance. The factory also accepts `data_config=DataConfig(...)` explicitly.
Do not mount the host Docker socket into an untrusted execution container.
Existing deployed workers have not been given Docker access or a new image by
this increment: a containerized worker needs a separately reviewed execution
service/interface before claiming this feature is operational there.

Default limits: 10 seconds (including container startup/output drain), 256 MiB
memory and swap combined, one CPU quota, 16 processes, 16 MiB temporary filesystem,
64 KiB per stdout/stderr stream. No network, host mounts, credentials, writable
root filesystem or extra capabilities; execution UID is 65534. Output overflow
terminates the invocation; timeout also removes the container. These are ordinary
container boundaries, not a claim of a formally secure hostile-code platform.

Datasets: at most 2 MiB each, 16 MiB total and 64 per episode. Exceeding a limit
fails with no partial dataset. Tool feedback is capped at 1,500 tokenizer tokens;
shortened previews/output are marked, while raw output up to the hard byte limit
is retained separately. These storage byte limits are not model context budgets.

## Evidence and validation

Each extraction/result is in `data-result-NNN.json`, each submitted script in
`python-NNN.py`; script results bind input dataset hashes, image ID, exit code,
wall time, stdout/stderr, output-limit status and errors. The normal native tool
request/response and policy-delivery ledger retain the actual model-facing data
result. Script output is an agent calculation, not privileged verifier evidence.

```bash
.venv/bin/python -m pytest -q tests/test_data_tools.py
.venv/bin/python scripts/verify_data_tools.py --output .local/review/data-tools-NEW
```

The verification script uses two fresh parallel BrowserGym processes and a mock
inference transport. It checks full extraction versus preview, exact decimals
and dates, an explicit failed-conversion/corrected-script sequence, private data
exclusion, fixed tool schemas, exact requests, dataset hashes, and grading before
close. Separate real containers check timeout, excess output, syntax errors,
missing packages, absent network/host files/secrets, read-only root and ephemeral
state. These tests establish plumbing and isolation boundaries, not Qwen ability.

## Two-task Qwen development rerun (2026-09-21)

User authorized exactly WA28 and WA50. Saved cohort:
`.local/data-tools-rerun-v1/`, with fresh source package/certificate, parallel
forum/shopping leases, immutable Python image ID, and six-provider routing that
excludes DekaLLM. Both actual providers were Chutes. This is local evidence, not
production rollout or a controlled provider/harness ablation.

WA50 voluntarily extracted the table twice (10 then 37 rows) and ran two Python
scripts, using Decimal/date filters and checking excluded orders. Its answer of
21 orders / 6560.69 matches independent arithmetic over the retained table and
the native reference. WA28 did not use the data tools; it used AX inspection and
a screenshot and returned reference-matching username/title/count. Neither hit
the output cap. Each recovered from one schema-invalid tool call before execution
(WA50 numeric select option; WA28 an over-limit AX result count).

**Both native grades remain failure:** both final answers omit the explicitly
requested system-level task_type/status/retrieved_data envelope. WA28 also returns
a single object rather than the goal's list. No answer repair/regrading occurred.
The original task wording is retained alongside the system envelope instruction;
WA50's goal says to return only order_count/amount. The current common viewer and
triage header uses pre-close unknown status; authoritative-evaluation.json and
native-evaluator-output.json contain the post-close failure. Do not report either
as passed based on the correct values.

WA50: 13 requests, 3196 generated tokens, final input 22694 tokens, $0.04967032.
WA28: 30 requests, 6191 generated tokens, final input 44656 tokens, $0.15472076.
Total actual reported cost $0.20439108; no unknown-cost attempts. Reported cache
fractions are only 8.7% and 21.9%, respectively. Saved request prefixes, tool
schemas, other request settings and per-episode session IDs stayed constant.
Thus removing DekaLLM did not resolve low reported cache reuse in this pair;
these observations do not isolate its cause.

`audit.json` verifies all 43 exact request/response/ledger matches and lifecycle
boundaries. `review.json` binds source artifacts and records data results,
independent table arithmetic, native assertions and request-prefix checks.
`review_saved.py` reproduces that read-only review (uses exclusive output).
Historical cohort and raw labels remain unchanged; no extra live rerun was made.
