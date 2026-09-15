# Independent FIFO v2 source and lifecycle review

**No blocking defect found in the tested event-ordering and remount paths.**
The supplied handoff named FIFO v1, but the working sources and available copied
build had already advanced to v2. This review records that newer identity;
the earlier v1 reports remain unchanged.

## Source/build match

Inspected `environments/chaos/stage-queue.mjs`,
`environments/chaos/stage-component-prefix.js.txt`, and
`scripts/setup_chaos_repair.py`. All three match the patch-source hashes recorded
in `.local/chaos-fifo-xor32-v2/dist/intent-repair.json`:

| Source | SHA256 |
| --- | --- |
| Queue | `18eb21af5fa82b80d8245afd5975302102a398d5b91df58c76248c610b557d9f` |
| React prefix | `40eb7bd2baca603f5845750cda4c93a4ac8d34148734f28ce2a3b1d380f2b72b` |
| Copy/patch script | `b17e8a140418fb2879213756894a8030a3c25f901f61b4ca5fc8c253352a9b22` |

The setup script rejects unexpected original CLI/frontend hashes and existing
output directories, copies the package into a new path, and uses cached
dependencies through a symlink. This review did not rebuild or download anything.
The live copied server was fingerprinted at `http://localhost:46053` before
browser testing. Original and candidate file hashes remained unchanged.

The queue captures event values immediately, dispatches one event at a time,
closes before invoking the terminal callback, and discards pending work after
closure. Callback failures have a separate diagnostic from transport failures.
React binds each queue to its session/challenge/mount nonce; cleanup closes that
queue and guards its later callbacks. V2 also adds those identifiers to retained
diagnostic getters, addressing the earlier v1 provenance concern.

## Independent execution

The existing independent queue-module acceptance script passes all **nine cases**
on the actual copied v2 module. Evidence:
`chaos-repair-review/queue-v2-unit.json`. The author's eight queue tests also pass,
including rejected async callbacks and preservation of the first close reason.

`check_chaos_overlapping_mounts.py` adds **three same-document React/session
overlap cases**, each using two fresh sessions on the copied server:

| Held old request | Adversarial sequence | Observed result |
| --- | --- | --- |
| Input response | Native fill/save; hold input response; navigate to new session; release old response | Old queued save discarded; zero old server clicks; new session unchanged, then completes once. |
| Terminal success response | Native double-click; hold first commit response; navigate to new session; release old success | Already dispatched old commit remains recorded; queued duplicate discarded; fresh idle page is not marked successful; its own commit then completes once. |
| Input transport failure | Native fill/save; hold input before abort; navigate to new session; abort old request | Old queued save discarded; zero old server clicks; fresh page is not sealed by the old error; its own commit then completes once. |

Each old queue retains its own context and `unmounted` close reason. New mount
nonces differ, new queue snapshots and page text are identical before/after old
completion, and native server interaction counts match the expected cases.
The new session is deliberately still idle when the old result arrives, so an
incorrect stale success/error callback cannot hide behind an already-completed
new page.

Evidence: `chaos-repair-review/overlapping-mounts-v2.json`, including original
response bodies, request payloads, both queues, raw per-session server events,
source hashes, and explicit privileged operations. No interaction API shortcuts
or model calls were used. Controlled responses are fetched once and fulfilled
unchanged; the failure case is explicitly aborted. SPA navigation uses test-only
history/popstate manipulation. These are lifecycle diagnostics, not policy
trajectories or independent benchmark-success labels; `safe_success` remains
null and training eligibility false.

## Remaining adversarial cases to consider

- **Delayed mount response:** hold session A's mount response, navigate to B and
  finish B's mount, then release A. Require B's nonce, goal, fields and queue to
  remain unchanged. Repeat with A's mount rejection. Current source has the
  relevant stale-effect guard, but the new tests above delay interactions after
  mounting, not mount requests themselves.
- **Challenge change within one session:** repeat the overlap test between two
  different challenge IDs. The effect depends on both session and challenge;
  current browser evidence changes session while keeping challenge ID fixed.
- **Mount failure diagnostics:** loading/mount-failure states have a null nonce
  and may have no queue. Consumers must require a non-null matching mount nonce
  before interpreting a snapshot as an active queue; `closed: false` alone is
  insufficient.

These are explicit coverage boundaries, not reproduced defects. The original
task descriptors/seeds, runtime profiles, historical graders and model outcomes
were not changed. P11 implementation remains owned by the harness agent's
delegated membership work; curation retains independent contract review.

```bash
node data/curation/test_chaos_queue_candidate.mjs CANDIDATE_QUEUE NEW_REPORT_JSON
.venv/bin/python data/curation/check_chaos_overlapping_mounts.py \
  --base-url CANDIDATE_ORIGIN --bundle CANDIDATE_CLI --report NEW_REPORT_JSON
```
