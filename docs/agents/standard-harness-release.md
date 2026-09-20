# Standard harness and Prislyktan release

Code `8bdcbde` is deployed to Vercel and the PC backend. The utility projection
is committed/published at `common_agent_util` `8ee71c5`. Existing named state
volumes and the Cloudflare URL are retained. No invitation or access scope changed.

## Implemented scope

- Normal CLI, local BrowserGym demo, live worker and shared-browser Ask use
  `core-tools-v10-agents`: native tools, incremental AX, retained reasoning,
  screenshots on request, up to eight sequential calls per response and bounded
  general-purpose helpers. Explicit historical/training profiles are unchanged.
- Helpers have separate conversations, model sessions and nested traces. Parent
  and children share call and spending limits. Inference transport is serialized;
  independent browser conversations are cooperatively scheduled on the browser
  thread. Child tool definitions inherit the parent except for spawning helpers.
- Own-browser helpers require an explicit environment factory. They work in the
  synthetic diagnostic and open-ended/rooms paths; derived browser-local journal
  and HAR tasks currently expose no-browser helpers only. Unsupported requests
  return a visible error; task state is not silently cloned or reset.
- Manual Ask runs the same core inside the existing human browser. Request,
  response, cost, retries and cancellation remain recorded. Ordinary RPC deadlines
  remain short; a response containing up to eight browser calls has a bounded
  five-minute RPC deadline. Browser action limits and interruption still apply.
- The authenticated worker viewer exposes separate helper conversations with
  family links. Archives include complete nested originals. Family cost totals
  include helper calls, without treating distinct sessions as provider switches.
- Prislyktan has six trusted tasks, generic manual browsing, shared Ask and a fast
  client-side design preview. Task/Ask execution uses the original four-origin
  server and ledger. The preview uses original assets with an explicit local
  storage shim, separate state and no grading. Preview content is invitation
  protected, manifest/hash allowlisted and cannot make network/API calls.

## Evidence

- Two live Qwen synthetic delegation episodes: six requests each, successful
  public-code lookup and final answer. Reported cost $0.00743652 + $0.0118935 =
  **$0.01933002**, no unknown charges, against one $0.25 authorization. Frozen
  profiles, traces and audits: `.local/preflight/subagent-qwen-v1` and `-v2`.
  This is an explicitly required-helper diagnostic, not a performance benchmark.
- 53 focused Python tests plus 40 subtests, 124 Node tests and 30 shared utility
  tests passed. Interactive browser checks cover fresh capture, retry boundaries,
  helper session/schema inheritance, late cancellation and stopping a batch.
- 37 selected scripted worker cases pass exact trace ZIP and outcome publication:
  all 14 existing contracts positive/negative, six Prislyktan positives, the two
  supported Prislyktan negatives and a technical-error/unknown-success case.
  `scripts/certify_standard_worker.py` checks exact coverage, artifact hashes and
  unchanged source closure. The certificate does not claim model competence.
- Fresh Chaos contract acceptance passed all 16 cases. Expanded current-profile
  checks cover eight Tricky adapter families, shopping native HAR grading,
  wishlist, contact/coupon, forum votes and posts. Representative container checks
  pass for native HAR/vote grading, Tricky outcomes and Prislyktan outcomes.
  Container shared-browser tests pass for music and repeated Prislyktan Ask.
- `scripts/check_standard_production.py` passed 48 read-only checks: exact
  committed assets, all 224 live task identities, protected preview asset hashes,
  manual/Ask availability, real page rendering, no browser errors, no writes or
  newly created jobs. Evidence: `.local/current-standard/production-v2`.

## Limitations and preserved failures

Legacy exposure/avoidance labels remain null under incremental policy delivery;
outcome checks remain active. Revalidating exposure and own-browser helper effects
requires further adapter evidence. Historical labels are retained separately.

The WebArena forum biography page returned the proxy's `Site response failed;
no replay` response at its 25-second upstream deadline in two scripted attempts.
Its subsequent reset initially failed; the dedicated clone/service was restored,
with no human session or shared research-site reset. Other forum and shopping
checks subsequently passed. Biography performance is **not fixed or certified by
this release**; the 203-task registry remains a development adoption based on
representative adapter checks, not per-task success. Raw failed attempts remain.

Other retained validation failures were test setup errors: an incorrect fixture
environment-variable name, a failure mock missing multimodal capability, and
attempted negative drivers for Prislyktan tasks that have no negative variant.
They were corrected/excluded explicitly, never relabeled as passing evidence.

Rollout initially failed because Docker Desktop rejected implicit propagation
on the new certificate bind. The final override uses an immutable directory and
explicit `rprivate`. Exact command/environment **names and non-secret paths** are
in `.local/current-standard/rollout-directory-mount.json`; recreate both control
and worker together because they share the control network namespace. Keep the
old package/image/certificate paths for rollback; do not overwrite them.
