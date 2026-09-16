# Screenshot retention proposal (not implemented)

User requested a policy that favors informative and unique runs and avoids
duplicating screenshots. No existing artifacts may be deleted by this proposal.

## First step: exact deduplication without losing evidence

Store immutable image bytes by SHA-256 and reference them from episode manifests.
Identical files across observations, retries and runs can share one stored object.
Action equality, DOM equality or a similar-looking thumbnail does not establish
image equality: even the same click can affect different state. Perceptual hashes
can group candidates for review but must not silently substitute images.

Keep each episode's observation/action ordering and original screenshot pathname,
hash and capture time. Export must materialize its original paths and exact bytes
and preserve existing source/artifact hashes. Do not rewrite frozen trajectories
or call an incomplete export exact. Existing ZIPs and independent copies may still
duplicate image bytes; catalog/storage deduplication is not automatically ZIP
deduplication. Retain portable complete exports as explicitly pinned objects.

Before enabling deletion, implement reference tracking across live episodes,
frozen profiles, training manifests, exports, backups and pinned reviews. Garbage
collection only removes unreferenced objects after a dry-run and grace period.
It must not race an in-progress episode or export.

## Run selection: coverage, rarity and information

Keep a lightweight record for every run: goal, provenance, model/provider/settings,
actions, errors, costs, outcomes including nulls, and artifact availability.
Evaluation denominators and failure rates must not change when media is pruned.
Training selection is separate from storage selection.

Protect active work, report/demo examples, certified regressions, held-out
evaluation cohorts, explicit user pins and committed training datasets. Initially
retain all screenshots for a recent window (a proposed 30 days, adjustable to a
measured disk budget), then prioritize representative examples by:

- Site/task/condition and environment/grader version.
- Model/checkpoint/provider/prompt and observation modality.
- Outcome and distinct failure mechanism; technical errors stay separate.
- Initial state, action/state-transition sequence and distinct terminal effects.

Keep all newly discovered failure clusters and successes that establish new
coverage. If success is rare, successes deserve extra retention; if failure is
rare, failures deserve it. Repeated identical failures need not outweigh rare
successful strategies. Keep a small random sample within common clusters to
avoid over-selecting dramatic or easily categorized runs. Deduplication of media
does not establish that whole episodes are equivalent.

## Older repetitive media

After review, repetitive unpinned runs could retain initial/final screenshots and
frames around errors or commits while shedding intermediate frames. Mark every
removed frame explicitly as pruned, with its former hash and retention reason;
never present a neighboring image as the original. Such runs are unsuitable for
full visual-trajectory training unless the required images remain accessible.

The scheduler should combine a recent-time window with a disk budget, not rely on
age alone. Start with a storage inventory and reclaim estimate, exact-byte image
deduplication, then a reviewable retention dry-run. Approval to discuss a policy
does not authorize deleting the current evidence.
