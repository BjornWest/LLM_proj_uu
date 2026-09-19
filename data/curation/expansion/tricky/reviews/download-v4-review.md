# Download v4 transport review

DOWNLOAD-V4-REVIEW-01: **accepted transport amendment; no concrete mismatch found**. The live process and downloader sources were not changed, stopped or restarted. No network requests were made.

The amendment's source and plan hashes match. Removing exactly the documented session import/context/call, helper fingerprint field and version note recovers v3 byte-for-byte. `validate_range`, `file_sha` and `verify_completed` also match independently by AST.

Each executor worker owns its own persistent requests Session, scoped to one asset. The executor drains before the session context closes its clients. No shared session is used concurrently. Nonzero adapter retry totals are rejected; a range error propagates. Other already in-flight requests may finish during executor shutdown, as in v3; “no retry” does not mean instant cancellation of every worker.

The cookie jar is cleared before each top-level range call. An offline test using a real requests Session and in-memory adapter confirms cookies still propagate within a redirect chain, then disappear before the next independent range. Range, If-Range, identity encoding, streaming and timeout arguments are unchanged. No claim about measured DNS/TLS reduction or throughput follows from these offline tests.

The same manifest reserves **198,568,153,001 bytes** under a **200,000,000,000-byte** cap, leaving 1,431,846,999 bytes of plan headroom. This remains planned asset body bytes plus existing reservations, not measured wire traffic or a guarantee against crash-loss retransmission. Completed hashes, pinned original source totals, ETags, partial-prefix suffix resumes and whole-file expected identity checks remain unchanged. No reservation was reset or expanded by this amendment.

Validation: 21 offline tests passed—seven independent transport/safety tests plus 14 existing tests. Tests use temporary synthetic files and mocked/in-memory HTTP; an outbound connection tripwire is installed. The live ledger was not read, so its historical pre-start hash remains the amendment's assertion rather than an independently reconstructed snapshot.

Evidence: adjacent `download-v4-review.json` and executable `download-v4-review.py`. Reproduce with system `python3`, which has requests installed; the repository `.venv` currently does not:

```bash
python3 data/curation/expansion/tricky/reviews/download-v4-review.py
```

The executable refuses to overwrite the existing report; use a separately versioned review path for a future rerun. This review does not certify downloaded archive completion, service readiness or dataset tasks.
