# Raven native authoring and re-export

The package at [`design/raven/`](../../design/raven/) preserves the five native scene/metadata pairs consumed by the live exporter. They are the supported authoring starting points for this source import; older development scenes are not needed just to run the current demos.

## Native sources

All paths in this table are under [`design/raven/outputs/raven/`](../../design/raven/outputs/raven/).

| Saved Blender scene | Companion metadata | Exported rig / role |
| --- | --- | --- |
| [`raven-chat-perch-v26.blend`](../../design/raven/outputs/raven/raven-chat-perch-v26.blend) | `chat-perch-v26.json` | `perch26`: native petting and turning/hopping caw poses |
| [`raven-chat-idle-v29.blend`](../../design/raven/outputs/raven/raven-chat-idle-v29.blend) | `chat-idle-native-v29.json` | `idle29`: perch and idle poses |
| [`raven-chat-flight-v26.blend`](../../design/raven/outputs/raven/raven-chat-flight-v26.blend) | `chat-flight-v26.json` | `flight26`: takeoff, glide, right-facing glide, and dive/landing |
| [`raven-flight-modules-v30.blend`](../../design/raven/outputs/raven/raven-flight-modules-v30.blend) | `flight-modules-v30.json` | `flight30`: composable flight clips, headings, connectors, turns, wingbeats, and rolls |
| [`raven-chat-attention-v24.blend`](../../design/raven/outputs/raven/raven-chat-attention-v24.blend) | `chat-attention.json` | `attention24`: exact attention-grid head poses and blink layers |

Keep each scene and its metadata together. Metadata supplies clip ranges, native timings, projected pose/anchor information, and route semantics used by export and runtime. A `.blend` by itself is not the complete application animation contract.

The saved scenes are the canonical portable edit/extract sources. The package also retains 14 historical generator scripts as provenance; they are not a turnkey clean rebuild of every raster asset. Historical raster-cache paths are not included. The v29 seed/provenance records Blender 5.2.2 build `d13f752e3b9c`, Cycles, and six render threads; use that information when investigating native/raster differences rather than assuming any Blender version will reproduce identical pixels.

## Current export format

[`work/export_raven_live_v34.py`](../../design/raven/work/export_raven_live_v34.py) reads those saved scenes and evaluates visible mesh and curve objects at selected native frames. It writes:

- `outputs/raven/live-raven-v34.json`: rig hierarchy, mesh/array descriptors, sampled clips, cameras, anchors, colors, source hashes, and binary metadata.
- `outputs/raven/live-raven-v34.bin`: little-endian packed arrays for evaluated geometry and transforms.
- `work/live-raven-v34-extraction-report.json`: sampling counts, validation measurements, and before/after source hashes.

The exporter is designed to read the native sources without saving or modifying them. It verifies their hashes before and after extraction. It exports evaluated local vertex geometry and local position/quaternion/scale transforms; it does **not** transfer an editable armature or shape-key bank to the browser.

Coordinates are Blender Z-up. The native camera looks along local `-Z`, with local `+Y` up. Colors are linear scene RGB derived from native emission/base colors; the browser applies sRGB output without filmic tone mapping. Preserve the native camera/anchor convention when comparing Blender with the browser.

## Re-export

From `design/raven/`, with Blender installed and available as `blender`:

```sh
blender --background --python work/export_raven_live_v34.py -- --fps 15
```

Run authoring/export commands within the repository's resource-bounding workflow when required by its local instructions. The `--fps 15` option controls geometry evaluation density, **not browser playback speed**. The exporter also retains exact junction/contact samples, blink samples, rapid idle turns, and selected takeoff/landing frames. Attention export retains the complete exact grid. The runtime uses the native timeline and interpolates between stored evaluations at its chosen render refresh rate, including 60, 120, and 144 fps targets.

For a small extraction probe:

```sh
blender --background --python work/export_raven_live_v34.py -- --fps 15 --scout
```

Scout outputs go under `work/live-v34-scout/`, with a separate scout report. They omit most samples and must not replace the accepted production demo bank.

Re-exporting overwrites the live bank JSON/binary in the package. Preserve a known-good snapshot or work on a branch before running it. Inspect the extraction report, verify source hashes stayed unchanged, and check the resulting demos before accepting changes.

## Runtime metadata is a separate layer

The controller also loads these shipped files:

- `live-actions-meta-v34.json`
- `live-idle-meta-v34.json`
- `live-flight-meta-v34.json`
- `live-attention-meta-v34.json`
- `patrol-path.json`

The geometry exporter does **not** regenerate those four live metadata files. The package includes [`work/build-live-metadata-v34.cjs`](../../design/raven/work/build-live-metadata-v34.cjs) and its exact source dependencies. From `design/raven/`, regenerate the shipped descriptions with:

```sh
node work/build-live-metadata-v34.cjs
```

This script strips atlas/pixel-packing fields while preserving native/semantic information from the following `outputs/raven/` inputs:

| Input | Derived live metadata |
| --- | --- |
| `chat-actions-v26.json` | `live-actions-meta-v34.json` |
| `chat-idle-v29.json` | `live-idle-meta-v34.json` |
| `flight-library-v30.json` | `live-flight-meta-v34.json` |
| `chat-attention-v26.json` | `live-attention-meta-v34.json` |

It also uses the included `chat-flight-director-v33.js` for its original/derived metadata equivalence check and writes `work/live-metadata-v34-report.json`. This is the historical validation dependency, while the current live pages use the v36 director.

Regenerating those files from the shipped inputs reproduces their descriptions; it does not discover intentional edits made to Blender scene timelines or rebuild updated native manifests automatically. Re-exporting unchanged scene geometry can reuse existing metadata. Changing clip lengths, names, frame ranges, headings, route endpoints, cameras, or anchor conventions requires coordinated changes to the relevant native metadata and its packed descriptions.

Do not assume that successful geometry extraction or re-stripping old metadata alone makes a new animation bank compatible with the controller or flight director. Treat the supplied metadata as part of the versioned snapshot. Any future metadata-generation changes should retain their full source dependency closure and meaningful compatibility checks.

## Procedural browser changes matter

The browser applies accepted behavior beyond the saved native clips:

- `RavenIdleGaze` chooses continuous random idle targets, smooths nearby cursor tracking, and holds the pose after the cursor leaves.
- `raven-live-v42.js` interpolates attention-grid geometry/transforms, supports extra raised-beak motion, and composes the native petting delta onto the current idle head pose.
- The renderer applies flight yaw/bank and aligns pose blends using screen anchors and compatible rigs.
- `ChatFlightDirector` chooses constrained routes, swerves, depth variation, and continuous return transitions. Farther paths shrink the Raven toward 80% scale.
- The full-page controller supplies screen placement, the direct upward ascent path, button contact, sound marks, and timing/state transitions. Helper Ravens share assets but have independent route clocks.

Consequently, the saved Blender scene alone may not reproduce every final browser pose or screen-space path. Compare the browser result as well as the native render before deciding a source edit is correct.

Several procedural paths identify nodes or meshes by names such as `Head` and the `Continuous breast, neck` prefix. Cross-rig blending checks matching node names, mesh names, parent relationships, vertex counts, and triangle topology. Renaming, reparenting, changing topology, or adding/removing mesh objects in only one compatible rig can break attention, petting, or transition blending. Coordinate such changes across relevant scenes and update runtime code deliberately.

## Validation after authoring

1. From the repository root, run `python3 design/raven/tools/verify_bundle.py` to check the file inventory/integrity and recorded bundle expectations. Review [`manifest.json`](../../design/raven/manifest.json) and [`validation.json`](../../design/raven/validation.json) rather than treating old reports as evidence for new bytes.
2. Check the native extraction report for failed topology/TRS/anchor assertions and source mutation. Spot-check clip endpoints, fast turns, blinking, takeoff contact/release, and landing contact.
3. Preview both the full-page v42 and extension-shaped v40 pages. Check idle tracking and petting from varied head poses, caw turns, takeoff-to-flight continuity, swerves/turns/rolls, immediate reply return, and resize behavior.
4. Check one and several Ravens at 60/120/144 render targets, hidden-tab resume, reduced-motion mode, clear/cancel, and conversation switching. Assess measured frame times and memory, not the configured target alone.
5. If metadata or package files intentionally change, update the inventory, provenance, and checksum records deliberately after review. The verifier checks the imported snapshot; it does not approve new bytes or refresh the manifest automatically. Keep the accepted prior version recoverable.

This export itself creates no commits and is not an integrated harness change. Later authoring or implementation commits must follow [`AGENTS.md`](../../AGENTS.md), including independent review from the other agent family before adoption handoff or dev/prod integration. A same-family subagent is not a substitute for that review.
