# Full B06 caller after parser and ordered-counter corrections

The additive `scripts/modal_b06_full_episode.py` reuses the accepted B06
saved-answer registry, quote grader, extraction factories, canonical sidecar,
current trace viewer and durable completion Events. It never allocates a GPU.
The task, world, native reference and public request stay the same.

## Timing and limits

There is no `maximum_episode_seconds`, episode deadline CLI option, aggregate
SIGALRM or policy/grading reserve. `max_steps=None`, ISL 100000 and context
131072 remain; `retry_policy=None` means no automatic provider retries.
Argument-validation feedback uses the reviewed argument-recovery descendant.

Execution isolation/imports and counter admission have separate 180-second
watchdogs. Browser factory, reset, step and close each have a 180-second
thread watchdog. Browser expiry and operator SIGTERM/SIGINT record a failed
Events state and hard-exit124 from a separate thread, avoiding exceptions
inside Playwright's dispatcher. Emergency workers are allocated before browser startup, so thread exhaustion
during a stall cannot disable a signal stop. A five-second fallback stops a
stuck evidence writer. No network notification flush runs on this emergency path: its durable
SQLite outbox remains for later delivery. The bounded launcher kills local
browser descendants; Training owns stopping remote serving.

Model requests have separate 600-second watchdogs and HTTP timeouts. A caught
soft timeout still fails when its context exits. Timers disarm after each
operation, and an already armed outer episode alarm is rejected. None of these
bounds accumulates into an episode duration limit. Runtime preparation/export,
observation work outside env.step and native grading have no caller watchdog
or aggregate bound (apart from individual extractor requests). A stall there
can keep Events running until platform expiry; this is a qualification, not a
claim that every phase has a watchdog.

The remaining hard expiry is the **actual provider platform maximum**. The
live deployment binds `platform_lifetime` with `mode=episode-owned`,
`expiry_kind=provider-platform-maximum`, numeric start/expiry UTC and
`provider_max_seconds=86400`. Expiry must equal start plus that exact Modal
maximum. The reviewed spec fixes startup/request watchdogs at180/600 seconds.
The legacy `gpu_deadline_utc` is an alias for that expiry, not a new episode
cutoff. `deployment.deadline` and `deployment.qualification.deadline` must
also equal this expiry for the unchanged Bridge. Training's30-second cleanup
reserve is internal to its worker and must not shorten these alias fields.
The unchanged Bridge rejects a regressing wall clock; retain that qualification
on long WSL runs. The ordered counter receives only this platform lifetime.
Training shuts serving down when policy/grading terminate and owns platform
watchdogs and cleanup. Do not wrap this caller in an episode-wide `timeout`.

## Source and admission

Use the exact db706d65 ordered counter source. Its general ordered
modality/history/ISL qualification requirements are unchanged: a single-request
replay proof cannot qualify it. Preserve/reject old sorted-wire receipts.
Capability reuse needs its own reviewed evidence; don't manufacture probe rows
or run the synthetic 100k burn-in on each episode.

Training supplies a reviewed three-hash parser binding: original source,
patched source and patch fingerprint. A pinned live `parser_patch_receipt`
matches those hashes, is passed and binds the actual serving session. Its
pinned regression receipt is passed and repeats patched source/session.
Deployment qualification and count proof repeat `parser_patch_sha256`.

The five-field implementation `runtime_projection` binds counter source,
wire function, relay file, tokenize projection file and projection function.
Its compact sorted UTF-8 JSON SHA256 is an implementation fingerprint only;
all model-visible count/generation bytes retain insertion order. The proof
and live deployment must agree on `counter_projection_sha256`.

The serving identity's `source_commit=95e9ac98` is the historical B06 task
lineage required by the existing Bridge/factories. The separately pinned
isolation root, source manifest and reviewed execution commit must point to
the argument-recovery descendant. Do not present95 as the execution commit.
Only runner/native-tool source bindings need prospective recipe rebinding;
original recipe bytes remain immutable. Main/WIP modules are not fallbacks.

## Grade, viewer and notifications

An external automatic grade contract must be attached before dispatch. The
caller checks current viewer availability before policy dispatch, public prose/memories, isolated module origins and actual browser
startup. Extraction is a separate closed-policy session. Native, canonical and
current8878 HTTP projections must agree before Events marks success. A native
false verdict is a completed evaluation, whereas missing or mismatched grades
are infrastructure failures. Inconclusive requires explicit grade keys and a canonical reason without a
technical error; the derived grade must have verified binding. Missing keys
cannot stand in for null grades.

Claims are exclusive per pilot ID within the exact reviewed claims directory,
independent of output path. Do not change that directory to restart an existing
pilot; historical v2 IDs belong to their separately authorized scope. Events creates
one episode and one suite completion subscription. The caller publishes only
terminal evidence; there is no resident trace watcher. Emergency failure records keep their task verdict null. Notification delivery
failure after verified completion is recorded separately and preserves the
grade plus pending outbox; it does not turn a graded result into a task failure.
A signal after Events is already terminal creates an interruption note that
retains its verdict/evidence instead of a contradictory null failure. For a
recorded operator stop, signal the caller PID in the bounded receipt's
`entry.json`, not the launcher. Ctrl-C/SIGTERM to the launcher hard-kills its
scope before forwarding; SIGHUP is not handled here. Those paths require
manual recovery from saved evidence, never an automatic replay.

## Current release limits

CPU-only tests cover real operation alarms, parser/projection admission,
terminal grade checks and actual SQLite completion/duplicate protection. They
use synthetic proof records and mock model calls; two real Playwright stall
controls cover watchdog/SIGTERM emergency exits. Supply the pinned Events
helper path explicitly with `FULL_B06_EVENTS_HELPER` for local tests; no claim of actual
serving parity or runtime promotion follows from them. Existing-world
zero-provider browser/native/canonical/HTTP acceptance and fresh Training
serving/parity evidence remain necessary before allocation/dispatch.

Terminal verification uses the frozen `trace_grades.read_grade` reader to validate the recorded episode hashes. Its `binding_status` is computed in memory; raw grade sidecars do not store that field. The canonical grade, selected sidecar and HTTP trace identity must all belong to the returned trace.
