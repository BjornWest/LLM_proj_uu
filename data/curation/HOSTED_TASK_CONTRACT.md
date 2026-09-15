# External tasks on the team deployment

Requested outcome: on the existing private Vercel site, a teammate selects an
external task and condition, reads its objective, starts the actual browser
agent, watches its actions, and receives independent task/authorization results
and the exact trace. Merely publishing static pages does not satisfy this.

The reviewable private catalog is `data/curation/hosted_task_catalog.json`.
It describes 14 current development conditions: seven Chaos, P07/P10/P11 clean
and injected, plus the separate synthetic DEV-W01 authorized-warranty task.
`deployed_ready:false` describes the catalog handoff, not current host readiness.
No deployed validation is claimed or paid calls authorized by this file.

## Ownership and staging

- Harness/deployment agent: worker selectors, task lifecycle, route/auth/state
  integration, private grading, production packaging and deployment.
- Curation agent: source identities, goal/condition catalog, label boundaries,
  independent parity review and dataset expansion.
- Existing host sweep profiles, fixture builds and task adapters remain frozen
  during the active model cohort. Deployment work can use new isolated paths.

## User flow

1. Open the existing invitation-protected team interface.
2. Choose task and clean/deceptive condition. Show the trusted objective and
   explain that the task uses simulated state. DEV-W01 is separately labeled.
3. Click Run. Queue a job referencing the immutable task revision and condition;
   the server resolves the adapter and trusted goal. A submitted goal cannot
   silently override the fixed contract and still receive its validated score.
4. Create one fresh browser/task session. For Chaos, resolve the generated
   descriptor and corresponding goal after session preparation; show the resolved
   goal to the viewer and give the same goal to the policy. Do not use a fixed
   example device name or field value in place of the generated target.
5. Show live screenshots, exact policy observations and actions through the
   current worker publication path. Feedback stays outside model inputs.
6. Evaluate while the browser is open. Display completion, authorization,
   unauthorized effects, technical failure, and safe success separately;
   preserve null. Retain upstream labels separately when available.
7. Offer the exact trace ZIP and review links. Interrupted sessions are retained;
   never automatically replay purchases or silently replace a failed attempt.

## Foundation needed for hostable pages

A portable fixture package should contain reviewed page assets, source revision,
asset hashes, supported condition IDs, public task metadata, and a versioned
session/effect interface. The private grader/expected-state rules are separate.
The same package must be used locally and on the deployment.

The current Tricky adapters do more than serve files: they attach a journal,
hydrate state, instrument callbacks, constrain navigation, and collect policy
exposure evidence. A static upload alone loses these semantics for ordinary
human browsers. Decide explicitly whether a page is agent-worker-only or also
supports manual teammate sessions. If manual sessions are supported, they need
the same initialization, effect recording, isolation, and reset behavior.

Recommended incremental path:

1. Add all 14 existing adapters to the team worker/UI. This makes objectives,
   agent execution, viewing and verification available while the worker still
   serves the existing certified pages internally.
2. Host versioned Tricky page assets behind the existing Vercel access rules;
   adapt the session URLs/transport in a new fixture/adapter version. Worker
   browsers visit those assets, retaining the same state and journal semantics.
3. Validate this new hosted version against the local reference before assigning
   deployed readiness. Chaos's current persistent process/state remains on the
   worker initially; its Node server is not directly interchangeable with a
   stateless request handler. Later API/storage migration needs its own tests.
4. Add further source tasks as portable packages, including selected SusBench
   derived tasks only after objective/grader coverage exists. IKEA injection
   diagnostics alone must not appear as graded shopping tasks.

Handle absolute paths, SPA reloads, shared-origin storage and cookie scoping,
per-session namespaces, authentication for worker navigation, asset MIME types,
and immutable deployment URLs. A deployment update must not change an active
session's assets or semantics. Grader data and private task state must not enter
served policy pages, accessibility observations, search results or prompts.

Vercel supports Vite deployments; request functions have finite resource and
duration limits. Keeping the persistent browser/session worker is the smallest
change to the current architecture, not a claim that all other Vercel compute
options are impossible. Sources:
https://vercel.com/docs/frameworks/frontend/vite
https://vercel.com/docs/functions/limitations

## Acceptance before declaring a task hosted and graded

- Client selection resolves to the same task ID, revision, condition and trusted
  goal in the worker trace. Clean/deceptive paired goals match.
- Asset/catalog hashes match the reviewed package. If paths/instrumentation
  change, record a new derived revision and explicit delta rather than assert
  byte identity with the original build.
- Scripted positive AND negative cases agree locally and on the hosted version:
  P07 unwanted warranty; DEV-W01 missing/duplicate warranty and prior checkout;
  P10 privacy commit and wrong cancellation; P11 wrong plan and prior activation;
  each Chaos contract's negative case. A successful page render is insufficient.
- Preserve state and the full effect history across reload and navigation.
  Isolated sessions do not share carts, appointments, subscriptions or results.
- Exposure requires the exact acknowledged policy observation before the
  contract's commit boundary; screenshots alone do not establish model exposure.
- End-to-end rehearsal reaches the team results page and downloadable original
  trace, with grading before close. Scripted results are labeled as scripted.
- Browser/runtime/fixture/grader/deployment provenance is recorded; the scoped
  certificate must apply to the actual worker build, not the host Chaos PID.
- Null/error outcomes remain null/error in UI, API, ZIP and subsequent exports.
  Feedback cannot override labels or alter policy prompts.
- Use existing team access controls and its separate Daylight budget/key. The
  curation sweep ledger and credentials never fund deployed teammate jobs.

Source reuse licenses remain part of the catalog. Tricky source licensing is
unresolved; this handoff does not mark assets as cleared for public redistribution.
All tasks remain development-only and training-ineligible until separately
reviewed. P10 scheduling and P11 pixel prominence are outside current scope.
