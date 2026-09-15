# Hosted worker archive and error-boundary follow-up

The independent saved audit identified a validator gap: checking only ZIP
members that happen to be present cannot detect missing originals. No missing
file was found in the original acceptance archives.

`scripts/verify_hosted_worker.py` now requires exact original file-set equality,
unique ZIP member names, and byte equality. It rejects extra, missing,
duplicate, changed and traversing members. Seven parameterized archive tests
cover these cases, including an empty archive. The focused archive/task/worker
suite passes 20 tests. Reapplying the stronger check to all 56 saved local and
container archives passes for all 2,376 original members; no episodes or
verifiers were rerun for that archive check.

A separate local browser diagnostic exercises a backend failure followed by
successful publication through the actual worker and private HTTP broker:

```bash
.venv/bin/python -m scripts.verify_hosted_worker \
  --fixtures .local/team-worker/fixtures-v1 \
  --task tricky-p07-clean --case backend-failure \
  --output /tmp/new-hosted-error-boundary
```

Use a fresh output directory. This diagnostic supports only clean P07 and
constructs no model client. It fails at its first scripted decision, before
any HTTP inference, reservation or browser action. The browser has reset, so
independent final-state verification still runs before close. All 19 checks
pass: completion false, authorization true, safe-success null and the exact
technical error are preserved across evaluation.json, episode.json and the
broker result. Original ZIP, screenshot and decision text remain accessible.
This covers publishing a backend error; it does not simulate loss of the
publication service or an HTTP timeout after dispatch.

Evidence:

- `.local/team-worker/hosted-archive-validation-v2.json`: saved archive recheck.
- `.local/team-worker/hosted-error-boundary-v1/report.json`: one fresh local
  browser diagnostic, not a container or production execution.
- `config/hosted_validation_followup.json`: source and evidence hashes.

The original 28-case local and 28-case container reports, their source hashes,
and the production read-only rollout report remain unchanged. No runtime,
grader, deployment image, training readiness or historical labels changed.
This increment made zero inference calls.
