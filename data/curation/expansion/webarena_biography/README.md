# Original WebArena 399, derived final-profile verification

This adopts the unchanged original goal, “Change my bio to \"I am a robot\" in the discussion forum,” on the complete cached WebArena Verified Reddit site. It does not repair or relabel the upstream evaluator. The original native grade and a separately attributed project-derived final-state grade are both retained.

The browser uses the copied `core-tools-v3` runtime, native calls through MockTransport, fresh browser sessions and a 48,000-character observation cap. Scripted drivers use privileged selectors but require every action BID to appear in the current delivered AX. This is site/grader validation, not model performance or training readiness.

## Isolation and outcomes

Only the separately owned `curation-webarena-biography-v1` container is created or reset: site `http://localhost:19099`, control `http://localhost:19098`. Its pinned cached image, ownership label and lack of mounts are checked. Existing Reddit ports 18999/9999 are never reset or used. A suite creates fresh image state, records its initial biography and restores that exact field before each case. Read-only warmup requests avoid mixing first-load compilation latency into action validation; all warming is recorded separately from policy decisions. No original site assets or core sources are changed.

Four cases exercise correct save, wrong save, correct-then-wrong overwrite, and deliberately missing privileged final-read evidence. The last is a verifier fault-injection case; it must yield unknown, even if the browser viewed correct text.

The adapter performs an independent authenticated profile GET during terminal evaluation, before browser close, without navigating the policy page or delivering grader content. It calls the read-only parent helper `biography_outcome.py`, comparing the final rendered biography after all captured writes. After close, a separate replay combines the original HAR with this explicitly distinguished privileged read. Browser HAR bytes and native results remain original. This proves only scoped final profile state, not a complete database ledger or every side effect; authorization and safe success remain unknown for a correct outcome.

## Reproduce offline

Use a fresh output path. The suite rejects existing output directories, uses cached images (`--pull never`), permits only its owned container reset, and bounds each native child to 240 seconds.

```bash
CURATION_FROZEN_RUNTIME="$PWD/.local/curation-expansion/frozen-runtime-v1" \
.venv/bin/python data/curation/expansion/webarena_biography/suite.py \
  --output .local/curation-expansion/webarena-biography-NEW

.venv/bin/python -m unittest data.curation.expansion.test_biography_outcome
```

Browser execution uses `.venv`; original upstream grading uses the existing `.local/webarena-verified/venv`. Every case fingerprints actual copied core files, task/driver/helper sources, dataset and installed upstream grader Python files before/after. Raw logs, evaluation, native messages, screenshots, HAR, privileged read and hashes are retained under the exclusive output directory.

The early v1 development positive saved the correct biography but had one cold-page 500ms native click timeout; it is retained and does not count as error-free acceptance. The v2 setup stopped before browser execution because `env-ctrl init` returned before PostgreSQL was ready. The later wrapper waits for the owned database before reading its baseline. Neither development issue is silently relabeled.

## Completed scripted acceptance

Current evidence: `.local/curation-expansion/webarena-biography-v4/report.json` and `validation-index.json`. All four cases pass with zero action errors and terminal evaluation before browser close. There are 32 mocked native requests and 28 actual browser targets verified against exact current delivered AX.

| Case | Original native score | Derived completion |
| --- | --- | --- |
| Correct saved biography | 1 | true |
| Wrong saved biography | 0 | false |
| Correct, then overwritten with wrong text | 1 | false |
| Independent final read deliberately omitted | 1 | null |

The accepted profile explicitly uses `slow_mo=0`. The v3 warmup-only attempt still hit a 500ms Save-click timeout at `slow_mo=100`; it is retained separately. Source before the timing change is saved at `.local/curation-expansion/webarena-biography-source-v3/`. This development adjustment does not fix or certify the general BrowserGym 500ms action timeout. Eight existing parent-helper offline tests pass. Broad authorization, teacher capability and training readiness remain unassessed.
