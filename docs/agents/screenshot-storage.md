# Exact-byte screenshot storage

Implemented for this workstation's primary trace stores. The agent runtime,
verifiers, frozen trajectories and published APIs are unchanged. There is **no
retention deletion or garbage collector**. At **20,000,000,000 bytes (20 GB)** the
monitor reports `review_required`; deciding what to prune is future work.

## What is deduplicated

`scripts/screenshot_storage.py` hashes PNG **file bytes** with SHA-256. Only
screenshots under completed `episode.json` markers, with marker and image older
than 60 seconds, are eligible. Active/incomplete traces remain untouched.
Identical bytes share a regular read-only hard link to a private object pool on
the same filesystem, separated by owner/group/read permissions. No visual
similarity or action-based substitution is used. Every existing image pathname
and byte remains available; existing artifact serving and exact-content ZIP
exports keep working. No symlink is introduced into a trace.

Existing ZIP files are never rewritten. Their embedded PNG compressed bytes
are monitored separately. SQLite's published base64 images/ZIP parts are not
deduplicated by this file-level maintenance tool; the entire control volume's
allocated file storage is included as a conservative upper bound. This is not
a content-addressed API migration.

Hard links share permissions and filesystem timestamps. Images become
read-only without widening their read permissions; their filesystem mtime is
that of the pooled object. Recorded capture times and all trace JSON remain
unchanged. Completed screenshots must be immutable: do not chmod/edit a shared
image in place. Create a separate derivative when editing a picture. Ordinary
copies/backups may materialize duplicates unless the copy tool preserves links.

## Running and monitoring

```bash
# Inventory only; no image/pool changes:
python3 scripts/maintain_screenshots.py
# Deduplicate closed screenshots and update the report:
python3 scripts/maintain_screenshots.py --apply
# An individual filesystem, useful on a future rollout instance:
python3 scripts/screenshot_storage.py runs --pool .local/screenshot-storage/objects --apply
python3 scripts/test_screenshot_storage.py
python3 scripts/test_maintain_screenshots.py
```

The aggregate wrapper currently inventories `runs/`, Docker `worker_manual-data`
and `worker_worker-data`. It counts control storage in `worker_control-data`.
Docker helpers use existing `intent-browser-worker:full-sites-v2`, UID 10001,
network disabled, no credentials, read-only root filesystem, and no browser/model
calls. They do not restart the running services. Missing volumes/images/Docker
produce an **incomplete** report; the helper will not create a missing volume or
pull an image. The named volumes/image are workstation configuration and must
be updated for another installation.

Reports:

- `.local/screenshot-storage/report.json`: current usage, hashes, per-scan
  reference counts, actual pool hardlink counts, errors and threshold status.
- `.local/review/screenshot-storage.html`: summary, served by the existing review
  server at http://localhost:8876/screenshot-storage.html . It is a snapshot;
  check its update timestamp.
- `.local/screenshot-storage/before-report.json`, `migration-validation.json`:
  initial inventory and exact file-set/byte checks for the first migration.

`references` counts matching paths within a scanned root. `pool_objects` records
actual `hardlink_references` excluding the pool's own link, including references
outside that root. Unreferenced objects are counted and retained. There is no
manual reference counter to become inconsistent after a crash. Hash uniqueness
is theoretical byte uniqueness; different filesystems/owners/permissions can
still need separate physical objects.

The budget uses **allocated unique image inode bytes**, existing ZIP image
compressed bytes, and the control-storage upper bound, not the larger sum of
all logical reference sizes. It excludes external machines/backups, `.local/`
diagnostic exports/cached fixtures, and non-PNG media. Those require explicit
additional scopes if they become primary stores. Deleting one of many references
normally saves no image bytes. Any eventual retention policy must measure
reclaimable objects and protect retained references, rather than prioritize
runs by their apparent logical size alone.

## Hourly local timer

The supplied user-systemd units target this workstation's
`~/code/LLM_proj_uu` checkout. Adjust `WorkingDirectory` elsewhere.

```bash
mkdir -p ~/.config/systemd/user
cp deploy/storage/intent-screenshot-maintenance.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now intent-screenshot-maintenance.timer
systemctl --user list-timers intent-screenshot-maintenance.timer
journalctl --user -u intent-screenshot-maintenance.service -n 10
# Stop future maintenance without removing evidence:
systemctl --user disable --now intent-screenshot-maintenance.timer
```

The timer runs hourly while the WSL user service manager is running; this is
not a Windows boot/WSL auto-start service. It logs `review_required` at the
threshold and writes the report. It does not send external notifications or
silently implement retention. Per-pool and aggregate locks prevent overlapping
maintenance. Per-file errors do not become a falsely healthy usage report.

Pool installation is exclusive and verifies exact bytes against existing
objects. Replacement checks source identity and bytes before atomic linking.
A crash can leave an extra pool object, but never requires deleting the original
first. Objects are never garbage-collected by this implementation.

## Initial validation, 2026-09-16

- 2,735 PNG paths across local runs, hosted manual sessions and hosted worker
  runs; allocated image storage fell from 207,859,712 to 54,075,392 bytes
  (153,784,320 bytes saved, 74%). Local runs alone had 2,634 paths/591 byte hashes;
  the largest shared image had 118 references.
- All 16,029 original files retained identical file sets and SHA-256 values,
  including non-image records and existing ZIPs. The object pools are separate
  additions and are excluded from this original-file-set comparison.
- Sixteen focused offline tests passed: exact sharing/non-sharing, unchanged ZIP
  content, active/recent exclusions, corruption, changed-source rejection,
  permission boundaries, symlinks, outside-scan references, no deletion,
  threshold/error reporting and offline Docker-helper configuration.
- The installed hourly service completed successfully; a second application
  linked zero additional files. HTML report returned HTTP 200. Initial monitored
  budget was about 84 MB including archive images and the control-storage upper
  bound, far below 20 GB. No model calls or service restarts were involved.
