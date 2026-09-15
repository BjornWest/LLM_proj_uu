# Offline replay and website handoff

The new saved-run replay opens a finished BrowserGym trace in a browser without
running a model, contacting a website, repeating actions, or changing its grade.
It reuses `common_agent_util`'s BrowserGym projection and existing trace viewer.

Try these locally:

- [Privacy failure: cancelled the protected appointment](http://localhost:8876/replay-privacy-failure-v2/index.html)
- [Download privacy replay ZIP](http://localhost:8876/replay-privacy-failure-v2/replay.zip)
- [Malformed model output: preserved unknown outcome](http://localhost:8876/replay-format-error-v2/index.html)
- [Shopping recovery: corrected a duplicate after a blocked control](http://localhost:8876/replay-shopping-recovery-v1/index.html)

Download/extract a ZIP and open `index.html` directly. Network access is not
needed. Search, event filters, step navigation, screenshots, exact model
requests/responses, action results and separate privileged evaluation work.
Replay shows recorded sequence and states; it is not continuous video playback
or an editable branch into a new browser execution. Video files, when recorded,
are retained as downloadable attachments and in the originals.

## Three different offline activities

| Activity | What it does | Browser/model calls |
|---|---|---|
| Saved-run replay | Shows an existing run's observations, actions and outcomes. | Neither. |
| Verifier replay/audit | Recomputes/checks a grade from saved evidence under a pinned grader. | Neither. |
| Scripted browser reproduction | Executes explicit actions in a fresh browser to test an environment/control bug. | Browser calls, no model calls. |

`audit_sweep.py` handles saved inference/receipt consistency. Earlier reproduction
and validation scripts exercise the third category. The new exporter handles
the first. None should be presented as a new autonomous agent pass.

## Create another portable replay

```bash
.venv/bin/python data/curation/export_replay.py runs/EPISODE_ID \
  --output .local/review/my-new-replay
```

Only finished episodes are exported. A new output directory is required;
existing output, source symlinks, mismatched identity and oversized traces are
rejected. The default source-size cap is 64 MiB. There are no downloads.

Outputs:

- `index.html`: standalone existing viewer, with embedded projection/media and
  a local data bridge. Outbound connections are blocked by CSP.
- `session.json`: exact `common_agent_util.agent_trace.adapters.browsergym.project`
  result, retaining message order, timestamps, observations, model payloads,
  action/transition results, errors and separate privileged verifier messages.
- `assets.json`: attachment URL -> relative original path, MIME type, bytes, hash.
- `original/EPISODE_ID/`: original trace files, byte-for-byte, including journals
  and raw observations. No dropped or synthesized outcome labels.
- `manifest.json`: format version, episode identity, source/payload hashes,
  exporter/projection/viewer source provenance, read-only scope and raw outcome.
- `replay.zip`: the above portable package; its manifest does not hash itself or
  the enclosing ZIP. Recorded source files are checked again before export.

The original shopping-recovery package predates a placeholder-substitution
hardening: current exporter uses single-pass `Template.substitute`, so source
text containing ASSETS/SESSION cannot be mistaken for a template token. Its
manifest retains the original exporter hash; that package is not rewritten.
Current privacy and format-error packages use the tested final exporter.

## For the deployment and UI agents

The UI can consume `session.json` and `assets.json` directly and render within the
existing invitation-protected site. Avoid a second trace parser or separate
semantics for model input versus privileged verification. Resolve attachment
URLs through the current job/invitation access checks, rather than serving
originals from a public static path. Display the trace's recorded outcomes,
including null/error, with the exporter and source provenance available.

If implementing ZIP import, validate archive paths, sizes and manifest hashes;
never execute an uploaded `index.html` as trusted application code. The site's
own renderer can use structured projection data and render captured text as
text. Saved replay must not enqueue a worker job or consume a model budget.

Suggested UI entry: **Saved runs → open a run → choose step / inspect input,
action, screenshot and result → review separate evaluation → download original
trace**. Review feedback belongs to a separate record keyed by episode/step and
artifact hash, never a rewrite of the raw trace or its grade.

A website import/listing route is NOT implemented by this local handoff. The
portable data and working local viewer are ready for the deployment/UI agents.
The current team worker already publishes exact trace ZIPs; these can supply the
same projection without changing how an agent episode runs.

## Validation

Four unit tests cover exact originals/ZIP bytes and hashes, null preservation,
script-closing text, template-token text, existing/dangling output protection,
source symlinks, size caps, incomplete runs and identity mismatch.
Two real Chromium file-URL tests verify search, filters, step selection and
rendered screenshots with zero HTTP requests or browser JavaScript errors.
Evidence: `data/curation/offline_replay_validation_v2.json` plus the retained v1 checks.
The v2 viewer removes the misleading generic zero-decision counter and maps
“Browser actions only” to actual recorded tool events. A twelve-action trace
shows twelve actions; the parser-failure trace correctly shows none. Original
projection data remains unchanged; prior exports are preserved.
