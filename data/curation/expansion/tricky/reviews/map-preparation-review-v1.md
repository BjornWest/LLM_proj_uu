# Maps volume-preparation independent review

**Hold extraction until the ownership, output reservation and streamed-input provenance gaps are fixed. The active downloader can continue unchanged.**

This review used saved header evidence, local synthetic TARs and mocked Docker/process calls. No data was downloaded, no container/service/volume was created, and no running process was changed.

## Source completeness

All eight saved header-report hashes match. Their offsets form a gapless chain of 7,224 members. The complete PostgreSQL subtree contains 7,220 entries and ends exactly at byte **37,329,782,784**. Before that subtree there is one parent directory; after the cutoff only the declared flatnode parent/directory/cache entries occur. All source types are regular files or directories. The current plan's strip counts match every prefix depth; routing retains car, bike and foot. This validates selection boundaries, not payload hashes or runtime geocoding.

## Concrete findings

- **MAP-PREP-01 — execution_blocker**: Initial unused-name listing does not establish exclusive volume ownership. docker volume create is idempotent; no owner/token reinspection occurs before mount/extraction. A concurrently created existing volume is accepted and written. Claim transaction-scoped volume names and verify returned volume identity/unique ownership token immediately before every extraction; serialize cooperating executions with an owned lock. Reject an existing foreign volume regardless of a stale initial listing. Never delete partial/foreign volumes automatically.

- **MAP-PREP-02 — execution_blocker**: Exclusive report creation occurs only in finalization after volumes have been changed. A competing output writer causes extraction to run and then raises FileExistsError, losing the operation report. Reserve the report path exclusively before any mutation, retaining a durable in-progress record and updating the same reserved artifact through completion/failure. Keep existing report bytes untouched.

- **MAP-PREP-03 — provenance_blocker**: Archive is rehashed during preflight but reopened later. Offline replacement after verification sends changed bytes while the report still claims the old archive hash. Bind extraction to the verified file identity and hash the actual streamed bytes, rejecting changes and recording partial volumes. A post-stream mismatch must never become extracted_not_launched; exclude concurrent mutations through a cooperative lock or immutable input snapshot.

- **MAP-PREP-04 — validation_gap_current_plan_valid**: No duplicate volume or strip-components validation. A duplicate plan fails only after creating/extracting the first volume; a strip count that removes all paths is not rejected. Current v2 plan has unique names and correct strip counts. Validate unique names, safe source basenames and prefix/strip relationships before mutation, plus expected extracted file count/path coverage.

Ten offline tests pass in `test_map_preparation_v1.py`. Some deliberately reproduce unsafe acceptance; they should be inverted when validating a repaired implementation. Existing output/dangling-symlink rejection, TAR traversal/type checks and exact prefix boundaries behaved as intended. Duplicate plan entries do eventually fail on the second exclusive log file, after partial extraction; the evidence does not claim two completed extractions. No automatic deletion was found.

The script should also pass `--pull never` to its cached-image Docker runs. The current v2 plan itself has valid names and strip counts; no downloader or plan-prefix change is requested by these findings.
