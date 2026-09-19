# Shared execution bridge for the 203 expanded tasks

Status: interface inventory; not an execution certificate. This bridge is intended
for BOTH local suites and the website worker. The worker adds scheduling,
authentication and publication, not a second setup or grader implementation.
Historical bindings, profiles and traces remain unchanged. New execution requires
its own source/build validation. No model calls are part of integration acceptance.

## Private runtime context

`make_task(task_id, *, runtime_context, revision)` selects an allowlisted private
binding and returns a runner-compatible task. The context supplies a complete
Tricky fixture root; dedicated shopping/forum origins; scoped read-only state
callbacks; and an optional native HAR evaluator. None of these are policy input.
Only the original goal and its declared terminal-response instruction are sent to
the model. Local suites inject the same context as the worker.

Use one exclusive, freshly reset worker-owned WebArena clone per active job.
Never borrow manual-session clones or shared benchmark services. Backend owns
provisioning/reset/authentication, lifecycle attestation and container access.
Reset the COMPLETE application between general-agent jobs; historical scoped
SQL cleanup is only a scripted-test optimization, not adequate here. The worker
must not receive a Docker socket, arbitrary SQL or arbitrary host URL capability.
A failed reset/identity check blocks execution, and a failed cleanup quarantines
that clone. Binding revision and current runtime/build identities are separate.

## Required privileged operations

| Family | Tasks | Setup | Private evidence / phase |
| --- | ---: | --- | --- |
| Tricky authored and original | 100 | Exact complete fixture, fresh context; preserve contract-specific cart/saved-article seeds | Existing client snapshot, journal, final answer/form grading BEFORE close. No host database operation. |
| WebArena native read-only | 71 | Original start URL and fixture account, fresh context, GET/HEAD-only same-origin routing | Embedded HAR and exact terminal JSON; pinned `webarena-verified==1.2.3` evaluation AFTER context close/HAR flush. Runtime pre-close grade stays unknown. |
| Forum biography | 5 | Fresh canonical forum, benchmark account | Independent authenticated GET `/user/MarvelsGrantMan136`, observed request evidence, existing `biography_outcome.check_biography` BEFORE close. No SQL required. |
| Forum vote | 1 (407) | Fresh canonical forum, target initially neutral | `forum.vote_state(target_id)` before/after plus authenticated forum `/new` HTML BEFORE close. Includes both UI-ID and timestamp newest rows. |
| Forum post | 15 | Fresh canonical forum | `forum.submission_ids()` before setup and at initial capture; `forum.posts_since(baseline_ids)` after policy, plus authenticated read of each new post BEFORE close. |
| Shopping wishlist | 6 | Fresh canonical shop; ordinary authenticated account GET before original product/start URL | `shopping.wishlist_state()` initial/final plus authenticated `/wishlist/` and `/customer/account/` reads BEFORE close. |
| Shopping contact draft | 5 | Fresh context, GET/HEAD-only same-origin routing | Final visible contact-form fields plus blocked/request events BEFORE close. No SQL, no submission. |

Exact read-only query implementations to reuse:

- `data/curation/expansion/webarena_votes/common.py:db_state`: integer allowlisted
  target; returns `target`, `vote`, `ui_newest`, `timestamp_newest`. Preserve
  disagreement as unknown; do not substitute the source target for chronological
  intent. Only accepted task 407 is enabled.
- `data/curation/expansion/webarena_posts/common_v2.py:initial_ids/posts_new`:
  snapshot the FULL ID set, not max ID (preloaded rows and sequence disagree).
  `posts_since` returns rows with id, forum_id/name, user_id/username, title, body,
  url, timestamp, edited_at, visibility, moderated. Include all new writers/rows;
  no username filter that could hide unexpected writes. Baseline is lease-bound.
- `data/curation/expansion/webarena_wishlist/common.py:state`: fixture account
  `emma.lopez@gmail.com`, exact owner, wishlist, items and options projections.
  Keep quantity/options and ownership checks. Ordinary app GET establishes CSRF
  session; no token bypass or application modification.

Recommended host API is operation-name + lease identity + allowlisted task ID,
with the server storing the baseline. Never accept SQL strings, container names,
or caller-supplied baseline IDs as untrusted HTTP inputs. In-process trusted
local context may retain the baseline list. Return instance/reset identity with
reads so the bridge can reject cross-session evidence. Private fixture account
headers differ from production secrets: do not put lease/admin tokens into raw
browser HAR or exported traces. Keep control-plane authentication out of browser
request headers; use an isolated network or a host-mediated proxy that injects
credentials outside browser capture.

## Grading boundary

Pre-close adapters retain the existing Evaluation semantics, including partial
coverage and null authorization. The 71 native tasks instead capture exact final
response before close and declare `grading_phase="after_browser_close"` and provide
`finalize_after_close(trace_directory, summary) -> Evaluation` after the runner has
closed the context. Store a separate post-close result with timing and HAR hash;
never rewrite the earlier unknown runtime evaluation as if evaluated before close.
The suite and publisher both call
`intent_browser.task_finalization.finalize_task_run(task, trace_directory, summary)`
once, which records authoritative-evaluation.json and retains both. If recording/evaluator fails, publish technical failure
with an unknown grade. No fallback from missing evidence to declared success.

Mutation native-history scores are diagnostics only; current-state derived
checkers remain authoritative. No need to run these optional diagnostics to
launch a job. Post-close hook must finish before ZIP publication.

## Runtime adoption and acceptance

Old WebArena run scripts assert a historical copied runtime and fixed clone
names. Do not import those scripts into the current worker or mutate their module
globals. The new bridge uses their pure checkers and explicitly carries forward
setup/evidence collection under current source fingerprints. Tricky adapters can
reuse their checker/snapshot methods with portable setup; do not change old files.

Preserve per-task max_steps, observation cap 48000, native `core-tools-v3`
profile, exact terminal instruction and wait-before-fresh-observation ordering.
Worker request reservation must describe the actual native-tool request, not a
legacy text-only approximation. Backend owns that shared integration.

Validate all 203 IDs/goals/contracts statically. Scripted positive/negative
acceptance must cover each setup/grader family and every distinct seeded setup;
report coverage explicitly. A family smoke does not mean all 203 have been newly
executed. Keep scripted validation, model results and training readiness separate.

Current factory: `data.curation.worker_integration.tasks.make_task`. Context type:
`data.curation.worker_integration.context.RuntimeContext`. Credentials in optional
`browser_proxy` go only to BrowserContext and the private httpx GET helper. The latter shares
actual server-issued cookies with the browser, refuses foreign URLs and follows
no redirects. Playwright APIRequestContext CONNECT is deliberately avoided. Never
serialize the context.
