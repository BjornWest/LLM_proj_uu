# Shared trace library: local backend integration

Status: implemented for combined **local review**, not deployed. No production
store, worker, invitation, budget or trace visibility was changed. Frontend source
is UX candidate `96fbd40`; these backend additions are separate working changes.
The old `trace-library-plan.md` is historical; its Blob proposal is superseded by
PC SQLite plus local immutable objects. There is no Blob request path here.

## Data path

The Vercel invitation handler authenticates the viewer, derives the owner itself,
and calls the existing PC control origin with its server-only control credential.
It never forwards a browser-supplied owner or origin. The PC library authorizes
catalog, session and attachment reads for that owner. Worker credentials cannot
call these internal endpoints. Neither API exposes an import or filesystem route.

Public contract matches the frontend handoff:

- `GET /api/library/sessions?limit=25&cursor=...`: `{sessions,has_more,cursor}`.
  Limit 1–100, default 25. Stable ID-order pagination, not chronological ordering.
  Only compact SQLite catalog rows are read; no projections or assets.
- `GET /api/library/sessions/:id`: exact common projection content except an
  opaque library ID, authorized attachment URLs and additive `library_metadata`.
  Original session ID, manifest hash and metadata provenance remain recorded.
- `GET /api/library/sessions/:id/assets/:attachmentId`: streamed immutable bytes,
  single byte-range support (including suffix requests), private revalidation.
  Every conditional request still checks ownership. No public CDN caching.
- `/trace-viewer` and generated protected scripts/styles are packaged by the
  existing hash-pinned `prepareViewer` function and included in build provenance.

Control-side endpoints are POST `/internal/library/list`, `/session`, `/asset`;
these are read-only storage operations. Session and attachment responses stream
through the frontend, rather than embedding base64 in the catalog. Listings are
not polled in the background. Deep links currently cause the documented frontend
metadata-plus-frame duplicate projection read; ordinary opening fetches it once.

The index uses the existing SQLite database. `DAYLIGHT_LIBRARY_ROOT` selects
object storage, defaulting to `library` beside `DAYLIGHT_SQLITE_PATH`. In the
control container this is `/state/library` on the existing persistent volume.
The control Dockerfile includes the library module; the image has **not** been
rebuilt, restarted or deployed in this increment.

## Explicit publication

Reuse the existing `data/curation/export_replay.py` exporter and
`common_agent_util` projection. No new BrowserGym parser was introduced.
Publication accepts a completed **directory** in `browsergym-saved-replay-v1`
format, manifest schema 1, not executable uploaded HTML or a ZIP extraction API.

Before sharing, review the selected export for credentials and confidential
content. The publisher is not a sanitizer. A redacted derivative requires its own
provenance; original logs are not silently changed. There is no automatic import
of `runs/` or automatic publication into every teammate's account.

```bash
node deploy/daylight/publish-library.mjs \
  --bundle /absolute/path/to/reviewed-replay \
  --owner INVITATION_OWNER \
  --database /absolute/path/to/state.sqlite \
  --root /absolute/path/to/library \
  --metadata /absolute/path/to/publication-metadata.json \
  --reviewed-for-sharing
```

Metadata is optional. Explicit site/collection/kind/task/condition information is
kept separate from historical projection fields; absent values stay null. Outcomes
come directly from `manifest.raw_outcomes`, not supplied metadata or a new grader.
`metadata_source` defaults to `explicit local bundle publication`.

The importer verifies every manifest-listed file's exact hash/size, rejects
traversal/symlinks, and checks mapped attachments against those bytes. Limits are
64 MiB per file and 512 MiB total per import, stated as bytes, not token counts.
It stores original evidence and the manifest without serving imported HTML as app
code. Content-addressed objects deduplicate identical bytes across publications;
authenticated owner records control visibility independently of shared storage.

Objects are written completely before atomic index publication. Interrupted
imports leave no visible partial session and can be repeated without model/browser
actions. Identical owner+manifest+metadata imports are idempotent; changed exports
or metadata create distinct immutable IDs. Unreferenced partial objects are retained;
no retention or garbage collection runs. Existing trace ZIP endpoints are unchanged;
this increment does not add a new bundle-download endpoint.

## Local checks and review

```bash
npm --prefix deploy/daylight run build
npm --prefix deploy/daylight test
.venv/bin/python scripts/smoke_trace_library_backend.py
LIBRARY_PREVIEW_AUTOLOGIN=1 node deploy/daylight/tests/library-integration-server.mjs
```

The last command prints a localhost port. Open `/workspace/replays`. It explicitly
imports only two existing reviewed test bundles into a temporary database/object
store; no production records or budgets. Automatic sign-in is a loopback-only
review convenience. With that flag omitted, use the fixture invitation documented
in the test source. It cannot call a model or start a worker job.

Five backend tests cover publication idempotence, exact bytes/outcomes, dedup,
summary-only pagination, interruption/resume, bad hashes/paths/symlinks, invitation
and owner boundaries, worker-role rejection, conditional reads and ranged streams.
The combined browser smoke covers the real frontend → real invitation handler →
real PC HTTP service → isolated SQLite/object store → actual shared renderer.
It checks twelve recorded actions, lazy screenshot reads, failed/unknown outcomes,
foreign-owner rejection and no jobs/actions/model calls. This is saved replay;
it neither reruns an episode nor recomputes a verifier.

Automatic publication from worker completion, bulk historical import, external
upload credentials, Campus/manual trace adapters and production deployment remain
separate follow-ups. Existing renderers remain available for those trace types.
