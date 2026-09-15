# Complete hosted sites and shared rendering

User requirement: preserve original visible pages, controls, navigation, CSS and
content. Verification must observe the relevant effects without simplifying the
site. Client inspection and BrowserGym use the **same compiled site revision**.
Historical traces and packages retain their old revisions.

## Scope

- Tricky shop, health, music and the synthetic warranty variant now use the entire
  `devinat1/agenttrickydps@8201821fb64a5075f50b015f99653881ab09a030` source tree:
  222 files / 19,263,057 bytes. The full original router, application shells,
  StrictMode, styles, catalogs and scratchpad remain. Nothing is selected by task
  when copying source. The other original internal routes also remain in the app;
  they are not newly advertised as graded tasks.
- Health includes medical records, doctor profiles, scheduling, messages,
  dashboard and lab results. Music includes its home, search, artists, playlists,
  podcasts and player, as well as membership plans. The original music shell can
  navigate away from membership and can lose a query-selected pattern: preserve
  this upstream behavior and record actual exposure, not intended exposure.
- Chaos uses the previously reviewed complete frontend with FIFO/xorshift repairs.
  Its copied assets, generator and certified runner closure are unchanged in this
  increment. There was no task-selected page subtree to restore.
- Campus is our own synthetic demo, not an imported dataset website. Its source
  pages and Vercel client state bridge are unchanged here. Full SusBench,
  WorkArena, WebArena and other unintegrated sites are not claimed as hosted.

## Declared adaptations and gaps

`environments/tricky_full/build-record.json` records every source file hash,
patch, compiled asset hash and missing resource. The instrumenter retains all
components. Adaptations are the common `/sites/tricky` router prefix (including
two original raw anchors), removal of upstream-owner telemetry and one unused
formatter import, offline media snapshots, and outcome journals/shared state.
Dependencies are pinned from the original declared ranges; upstream supplies no
npm lockfile. Tooling/telemetry dependencies that the application does not need
are not installed. This is a reproducible derived build, not an upstream binary.

Derived privacy Save/persistence and cumulative membership activations remain
explicit departures from upstream's component-only state. The SAME public state
engine runs in native and client modes. The client wrapper only isolates each
ordinary tab's storage and records local interactions; it does not implement a
second version of task state. Native bindings record privileged journals.

Three PDF links refer to files absent from the complete original repository:
`/downloads/lab_results.pdf`, `/downloads/blood_test.pdf`, `/downloads/xray.pdf`.
Their controls remain and the requests fail honestly. The original Health logout
link has no implemented route. All eight referenced audio URLs failed at snapshot time (seven returned 403; the example.com placeholder returned 404), so audio playback remains unavailable despite the restored player controls.
Of 54 media URLs, 43 resources (9,751,613 bytes) were snapshotted; 11 failures are
retained as local failed-resource paths, with their original URLs/status in the
manifest. No made-up documents, audio or replacement images are supplied.
Snapshotting avatars freezes the original service's random-color result.

Restored controls therefore do not mean upstream PDF downloads or music audio work. Other unreviewed original routes and
patterns remain navigable but cause authorization to stay unknown unless an
observed forbidden effect already establishes failure. New task definitions
still need their own objective and verifier review.

## Single version and deployment boundaries

`environments/inspection_full/` contains one public compiled asset set, used by
all three client sites. Native fixture packages use byte-identical `dist` files.
There are no task answers or private manifests in this web root. All asset/page
routes still require an invitation. Legacy `/shop`, `/health`, `/spotify` URLs
redirect to the common prefix.

The HTML meta tag, public manifest, private task registry, native task metadata,
manual session metadata and immutable package identify the site revision.
Build rejects a mismatch between public assets and registry. Native snapshots
check the loaded HTML revision. Manual config checks the package's registry;
the Vercel start endpoint checks the remote version before creating a browser,
including during an old-control/new-frontend rollout. New task jobs require the
worker to advertise the matching task revision before start and claim. Missing
old-worker revision information fails closed for these sites. Historical rows
are not relabeled. Previously opened tabs/traces show their recorded revision;
refresh pages after deployment to load the new version.

The final portable package derives from `portable-v2`, preserving its certified
runner/Chaos closure. Only named Tricky and inference/worker files plus the
registry are overlaid. This avoids silently claiming that unrelated current
runner changes were recertified for Chaos. Image overlays perform no installs.

## Verification and reproduction

- `scripts/setup_tricky_full.py` restores the pinned complete source, verifies Git
  blob hashes, and restores the committed media snapshot from public assets.
  It downloads missing source files only; existing assets can be used offline.
- `npm ci --prefix environments/tricky_full`, then
  `node environments/tricky_full/build.mjs` rebuilds the complete site. The build
  refuses an unreviewed media snapshot. `cache_tricky_media.py` is a separate
  research acquisition tool, not an automatic deployment refresh.
- `scripts/export_tricky_full.py` exports public bytes to a NEW directory;
  `prepare_full_site_registry.py` creates a NEW explicit task revision; ordinary
  `deploy/worker/prepare_tasks.py export` copies private inputs and compiled files.
- `scripts/prepare_full_site_package.py` creates an exclusive, verified package
  from a previously certified base and the new fixtures. Preserve base packages.
- `check_tricky_full_client.py`: actual authenticated pages/controls, no model.
- `check_tricky_full_parity.py`: paired BrowserGym/client visible text and public
  state across 16 routes, separate from wrapper chrome and policy/grader data.
- `verify_tricky_full.py`: positive/negative original task and history checks.
- `check_tricky_full_effects.py`: actual restored scheduling/messaging and an
  additional cross-site subscription are detected by grading.
- `verify_environment_package.py`: copied-runtime positive/negative cases with
  `docker --network none`, evaluation before close and exact trace provenance.
- `verify_manual_sites.mjs` and `smoke_manual_workspace_live.py`: real native
  manual transport and actual workspace/API integration, no inference.

Reports for this increment are under `.local/tricky-full-v1/`; the committed
`config/full_site_validation.json` summarizes final evidence and exact hashes.
Earlier failed diagnostic/test selectors are retained locally, not presented as
passing evidence. No new model calls or training labels were produced.

The public asset set is about 28 MB on disk, shared once across site views.
Browsers request only referenced resources and reuse private immutable caching.
This removes screenshot polling from client inspection; it uses neither Blob
nor model tokens. Initial downloads are larger than the cut-down fixtures, and
Vercel function requests/transfer still count toward plan usage. No new cloud
service or paid storage tier is introduced.


## Deployment and restart

The complete site is deployed at `https://browseragent.vercel.app/sites/tricky/`.
The active PC images are `intent-browser-worker:full-sites-v2` and
`intent-browser-control:full-sites-v2`, with the exclusive
`.local/environment-packages/portable-full-v2` package and
`.local/team-worker/fixtures-full-v2` fixture export. These share site revision
`9fc287a252ddee32e579575bec50e33568070272de2e81ef5c9033bde19eb90e`.

For future compose operations include `deploy/control/full-sites.override.yaml`
AFTER the existing worker, Chaos, fixture, control, worker-network and manual
compose files; set `ENVIRONMENT_PACKAGE` and `FULL_SITE_FIXTURES` from
`.local/control/active-environment.env`. The explicit `rprivate` bind propagation
is necessary for this WSL/Docker Desktop setup. Do not use the old default
fixture bind or restart only one member of the shared network namespace.
Check that no jobs/manual sessions are active before any recreation. Preserve
`worker_worker-data`, `worker_control-data` and `worker_manual-data` volumes.

Read-only production checks are recorded in
`.local/tricky-full-v1/production-core/report.json` and
`.local/tricky-full-v1/production-sites/report.json`. The switch preserved all
109 storage keys and all 108 non-heartbeat record hashes. No active tasks were
interrupted. Rollback images (`*:reasoning-v1`) and `portable-v2` remain locally;
rolling back one side alone intentionally fails the new-version launch checks.
