# Maps: original-task offline staging

This is **source-inspected scaffolding, not a runnable or validated benchmark**.
No Maps browser, website service, model or download was started for this work.
The cached pinned image was inspected in two read-only, network-none Python
containers with the normal entrypoint disabled; neither ran application services.
Root owns archive restoration, site startup and future browser preflight.

The ten original goals are retained in `contracts.json`:70 (postcode),248
(coordinates),377 (nearby restaurants),52 (walking time),84 (New York driving
time),363 (walking distance),16 (both walking/driving),36 (one-hour threshold),
151 (minimum service-route time),287 (Pittsburgh–Philadelphia driving time).
These cover ten source templates. Targets71/73 remain available as later
same-template postcode cases;137 adds place-inference work later. There are no
dark-pattern variants or rewritten goals here.

## Files and boundaries

- `contracts.json`: unchanged source prompts and rows, private original
  evaluators, public input slots, per-task capability/preflight requirements.
  `policy_input` contains only the original goal.
- `staging.py`: policy projection and artifact-bound preflight validation;
  an EpisodeTask-shaped adapter whose evaluation deliberately remains unknown.
  A top-level `ready` claim, missing evidence or changed evidence cannot satisfy
  the gate. A valid supplied preflight receipt still does **not** accept a task.
- `driver.py`: source-derived original controls and scripted driver scaffold.
  It stops with `RuntimeProofRequired` before emitting an answer or success.
  The caller must bind actual page/action/current-AX functions; no environment
  factory or live CLI is supplied. Selectors have not been browser-validated.
- `preflight-requirements.json`: explicit service, delivery, grading and negative
  case requirements. No derived task verifier is implemented yet.
- `source-findings.json`: concrete source-level dependencies and evidence paths.
- `test_staging.py`: nine offline boundary checks. Its temporary synthetic
  receipt tests only validation behavior; it is not a browser observation or
  usable readiness certificate.

Offline command:

```bash
PYTHONPATH=. .venv/bin/python -m unittest data.curation.expansion.webarena_maps.test_staging
```

## Dependencies that matter before browser execution

**Search is semantically read-only but uses POST.** The original `search.js`
loads geocoder result fragments and More results via POST. Copying the shopping
GET/HEAD-only route would break Maps. Confirm exact initialized local geocoder
paths and bodies before allowing those specific read operations; do not enable
arbitrary write endpoints.

**Search-result clicks can enter the missing object database.** Original result
links point to node/way/relation pages. Their click handler pans first and then
permits navigation. The previously confirmed description404 problem therefore
also affects paths reached from otherwise healthy geocoding. Task248 needs a
real accessible coordinate-display path. Hidden `data-lat`/`data-lon` attributes,
private Nominatim responses and expected answers must not be projected into the
agent's context to manufacture one. Task70 may obtain the postcode directly
from visible search-result address text, but that must be observed, not assumed.

**A query is not a rendered-map proof.** Search auto-pans to its first result;
individual result markers are added on mouseover and removed on mouseout.
Task377 needs an actual rendering/identity check. Core-tools-v3 has no hover, and
source inspection does not establish whether another original control path is
sufficient. Do not silently replace the original map with a simplified result
list or declare it impossible before browser preflight.

**Route modes need correct evidence.** All three original OSRM engines request
`route/v1/driving`. Distinguish `routed-car`, `routed-bike` and `routed-foot` plus
the actual selected engine, resolved endpoints and current successful response.
The engine ID is `fossgis_osrm_bike`, not `fossgis_osrm_bicycle`. Routing takes the
first geocoder result and replaces the textbox with its display name; verify
that identity and locality rather than assuming the original input was resolved
correctly. The geocoder viewbox can affect this selection.

**Preserve visible precision.** The UI rounds duration to minutes and displays
H:MM. HH:MM:SS answers derived from that display should have zero seconds, not
private raw API seconds. A displayed1:00 is ambiguous at a strict one-hour
threshold. Distance is rounded to meters below1km, one decimal km below10km,
and integer km above that. Keep raw route values private for consistency checks,
separate from the actual policy-visible evidence. The original frontend consumes
`routes[0]`; document the service's optimization before interpreting task151 as
an unrestricted global minimum over alternatives.

## Admission after infrastructure becomes available

Retain original image/data/config provenance and a fresh runtime profile. Confirm
local assets, geocoding, tiles and both required routing modes over Pittsburgh,
New York and Philadelphia. Run source-supported UI controls through the actual
harness and retain requests, decision AX, screenshots and task-specific outcomes.
Implement independent completion checks alongside the unchanged native grader;
run positive and wrong-answer/destination/mode/endpoint controls, plus stale-route
and service-failure cases. Infrastructure failure remains unknown/technical,
never semantic NOT_FOUND. Task253 and description369–373 remain held.

A native root visit is insufficient for route tasks. Authoritative route identity,
mode and current rendering must be checked separately. Broad authorization,
training eligibility and deployed readiness remain unestablished. Complete-site
fidelity and component licenses remain separate requirements; the task source's
license does not license every image asset.
